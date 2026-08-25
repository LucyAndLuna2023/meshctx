"""Approval Engine — 安全审批引擎 (开源真实实现)

三级模式: manual(必须审批) / smart(智能判断) / off(跳过审批)。

- ApprovalEngine.check: 按危险命令模式库评估风险等级, 决定是否需审批
- request_decision / request: 审批请求队列 + 通过/拒绝/超时, 支持 callable 审批器
- approve_request / reject_request: 外部解析挂起中的审批请求
- 检测覆盖: rm -rf /、dd 写盘、mkfs、fork 炸弹、chmod -R 777 /、
  git reset --hard、git push --force、DROP TABLE、关机重启、管道到 shell 等

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.approval")


class RiskLevel(str, Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'

    def __str__(self):
        return self.value


class ApprovalMode(str, Enum):
    MANUAL = 'manual'
    SMART = 'smart'
    OFF = 'off'

    def __str__(self):
        return self.value


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


# (正则, 风险等级, 原因) — 命中任一模式即标记该风险
DANGEROUS_PATTERNS: List[tuple] = [
    (re.compile(r"rm\s+-rf?\s+/\b"), RiskLevel.CRITICAL, "删除根目录 (rm -rf /)"),
    (re.compile(r"\brm\s+-rf\b"), RiskLevel.HIGH, "递归强制删除 (rm -rf)"),
    (re.compile(r"\bdd\s+if=.*\sof=/dev/"), RiskLevel.CRITICAL, "dd 写入块设备"),
    (re.compile(r"\bmkfs\.\w+"), RiskLevel.CRITICAL, "格式化磁盘分区"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;:"), RiskLevel.CRITICAL, "Fork 炸弹"),
    (re.compile(r"chmod\s+-R\s+777\s+/"), RiskLevel.CRITICAL, "递归开放根目录权限"),
    (re.compile(r"\bchmod\s+-R\s+777\b"), RiskLevel.HIGH, "递归开放目录权限"),
    (re.compile(r"git\s+reset\s+--hard"), RiskLevel.HIGH, "git reset --hard 丢弃提交"),
    (re.compile(r"git\s+push\s+--force"), RiskLevel.HIGH, "git force push 覆盖远端提交"),
    (re.compile(r"\bDROP\s+TABLE\b"), RiskLevel.CRITICAL, "删除数据库表 (DROP TABLE)"),
    (re.compile(r"\b(shutdown|poweroff|reboot|halt)\b"), RiskLevel.HIGH, "关机/重启系统"),
    (re.compile(r"\|\s*(ba|z)?sh\b"), RiskLevel.CRITICAL, "管道执行到 shell"),
    (re.compile(r">\s*/dev/sd"), RiskLevel.CRITICAL, "直接写入磁盘设备"),
    (re.compile(r"\bsudo\b"), RiskLevel.MEDIUM, "sudo 提权命令"),
    (re.compile(r"\bmv\s+[^\s]+\s+/"), RiskLevel.MEDIUM, "移动文件到根目录"),
]


@dataclass
class ApprovalResult:
    """审批检查结果"""
    requires_approval: bool = True
    reason: str = ''
    risk_level: RiskLevel = None
    yolo_override: bool = False
    action: str = 'prompt'

    def __post_init__(self):
        if self.risk_level is None:
            self.risk_level = RiskLevel.LOW
        if not self.action:
            self.action = 'prompt'


@dataclass
class ApprovalDecision:
    """一次审批请求的决定记录。"""
    request_id: str = ''
    command: str = ''
    reason: str = ''
    status: str = 'pending'       # pending / approved / rejected / timeout / suggest
    risk_level: RiskLevel = None
    decided_at: float = None
    auto: bool = False            # 是否自动放行 (安全命令, 2026-08-25 审计补)
    action: str = ''              # approve / deny / suggest / timeout (交互审批器契约)

    def __post_init__(self):
        if self.risk_level is None:
            self.risk_level = RiskLevel.MEDIUM
        if not self.request_id:
            self.request_id = uuid.uuid4().hex

    @property
    def approved(self) -> bool:
        return self.status == 'approved'


class ApprovalEngine:
    """安全审批引擎"""

    def __init__(self, mode: str = 'smart', yolo: bool = False,
                 timeout: float = 30.0, approver: Optional[Callable] = None):
        self.mode: ApprovalMode = self._coerce_mode(mode)
        self.yolo: bool = bool(yolo)
        self.timeout: float = max(0.0, float(timeout))
        self._approver: Optional[Callable] = approver
        self._pending: Dict[str, ApprovalDecision] = {}
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = {
            "checks": 0, "approved": 0, "rejected": 0, "timeout": 0,
        }
        # suggest 模式结果记录 (2026-08-25 004meshctx 审计补齐)
        self.last_suggestion: str = ""
        self.last_decision: str = ""

    @staticmethod
    def _coerce_mode(mode) -> ApprovalMode:
        if isinstance(mode, ApprovalMode):
            return mode
        try:
            return ApprovalMode(str(mode).strip().lower())
        except ValueError:
            raise ValueError(
                f"无效审批模式: {mode!r} (可选: manual / smart / off)"
            ) from None

    # ── 模式 ──────────────────────────────────────────────

    def set_mode(self, mode: str):
        """切换审批模式：manual / smart / off"""
        self.mode = self._coerce_mode(mode)
        return self.mode

    def register_approver(self, approver: Callable):
        """注册 callable 审批器: approver(decision) → True/False/None。

        True 或 'approve' → 批准; False 或 'reject' → 拒绝; None → 超时拒绝。
        """
        self._approver = approver

    # ── 风险评估 ──────────────────────────────────────────

    def _assess(self, command: str, context: Optional[dict] = None) -> ApprovalResult:
        risk = RiskLevel.LOW
        reason = ""
        for pattern, level, msg in DANGEROUS_PATTERNS:
            if pattern.search(command):
                if _RISK_ORDER[level] > _RISK_ORDER[risk]:
                    risk = level
                    reason = msg
        # 上下文附加信号: context.risk_override 可强制抬高/降低风险
        ctx = context or {}
        override = ctx.get("risk_override")
        if override is not None:
            try:
                override_level = RiskLevel(str(override).strip().lower())
                if _RISK_ORDER[override_level] > _RISK_ORDER[risk]:
                    risk = override_level
                    reason = f"上下文风险覆盖: {override}"
            except ValueError:
                logger.debug("忽略无效 risk_override: %r", override)
        if reason == "":
            reason = "命令评估为低风险"
        return ApprovalResult(
            requires_approval=False,
            reason=reason,
            risk_level=risk,
            action='allow',
        )

    def check(self, command: str, context: Optional[dict] = None) -> ApprovalResult:
        """检查命令是否需要审批"""
        if not command or not isinstance(command, str):
            command = str(command or "")
        result = self._assess(command, context)
        risk = result.risk_level
        with self._lock:
            self._stats["checks"] = self._stats.get("checks", 0) + 1

        if self.mode == ApprovalMode.OFF:
            result.requires_approval = False
            result.action = 'allow'
            result.reason = f"off 模式跳过审批: {result.reason}"
            return result
        if self.yolo:
            result.requires_approval = False
            result.yolo_override = True
            result.action = 'allow'
            result.reason = f"YOLO 覆盖: {result.reason}"
            return result

        if self.mode == ApprovalMode.MANUAL:
            needs = _RISK_ORDER[risk] >= _RISK_ORDER[RiskLevel.MEDIUM]
        else:  # smart
            needs = _RISK_ORDER[risk] >= _RISK_ORDER[RiskLevel.HIGH]

        result.requires_approval = needs
        result.action = 'block' if risk == RiskLevel.CRITICAL else ('prompt' if needs else 'allow')
        if not needs:
            result.reason = f"自动放行: {result.reason}"
        return result

    # ── 审批请求 ──────────────────────────────────────────

    def _enqueue(self, command: str, reason: str = '') -> ApprovalDecision:
        result = self._assess(command, {})
        decision = ApprovalDecision(
            command=command,
            reason=reason or result.reason,
            risk_level=result.risk_level,
        )
        with self._lock:
            self._pending[decision.request_id] = decision
        return decision

    def approve_request(self, request_id: str) -> bool:
        """通过挂起的审批请求。"""
        with self._lock:
            decision = self._pending.get(request_id)
            if decision is None or decision.status != 'pending':
                return False
            decision.status = 'approved'
            decision.decided_at = time.time()
            self._stats["approved"] = self._stats.get("approved", 0) + 1
        return True

    def reject_request(self, request_id: str) -> bool:
        """拒绝挂起的审批请求。"""
        with self._lock:
            decision = self._pending.get(request_id)
            if decision is None or decision.status != 'pending':
                return False
            decision.status = 'rejected'
            decision.decided_at = time.time()
            self._stats["rejected"] = self._stats.get("rejected", 0) + 1
        return True

    def _interactive_prompt(self, decision: ApprovalDecision) -> str:
        try:
            answer = input(
                f"[审批] 命令: {decision.command}\n"
                f"       原因: {decision.reason} (风险: {decision.risk_level})\n"
                f"       批准? [y=批准 / n=拒绝 / 其他=超时拒绝]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "timeout"
        if answer in ("y", "yes", "approve"):
            return "approved"
        if answer in ("n", "no", "reject"):
            return "rejected"
        return "timeout"

    def request_decision(self, command: str, reason: str = '') -> ApprovalDecision:
        """请求用户审批 (同步/CLI 交互式三选一)。

        解析顺序: 安全命令自动放行 → callable 审批器 → 交互式 CLI → 审批队列等待
        (外部调用 approve_request/reject_request, 超时自动拒绝)。

        2026-08-25 004meshctx 审计修复: smart/manual 模式下低风险命令
        (_assess 判定 requires_approval=False) 直接 auto-approve, 不再进等待队列。
        """
        result = self.check(command, {})
        if not result.requires_approval:
            decision = self._enqueue(command, reason or result.reason)
            self.approve_request(decision.request_id)
            decision.auto = True
            return decision

        decision = self._enqueue(command, reason or result.reason)
        approver = self._approver
        if approver is None:
            # 默认走 interactive_approval.ask_approval (三选一 TUI/非TTY降级)
            try:
                from src.core.interactive_approval import ask_approval as _ask
            except Exception:  # noqa: BLE001
                _ask = None
            if _ask is not None:
                try:
                    answer = _ask(command=command, risk=str(decision.risk_level.value),
                                  reason=decision.reason)
                except Exception as e:  # noqa: BLE001
                    logger.warning("ask_approval 异常, 按拒绝处理: %s", e)
                    answer = None
                if answer is not None and hasattr(answer, "action"):
                    action = getattr(answer, "action", "deny")
                    if action == "approve":
                        self.approve_request(decision.request_id)
                    elif action == "suggest":
                        decision.status = "suggest"
                        decision.action = "suggest"
                        decision.decided_at = time.time()
                        self.last_suggestion = getattr(answer, "suggest_text", "") or ""
                        self.last_decision = "suggest"
                    else:
                        self.reject_request(decision.request_id)
                        self.last_decision = action
                    return decision
                # ask_approval 不可用或返回异常 → 落到下面队列等待
        if callable(approver):
            try:
                answer = approver(decision)
            except Exception as e:  # noqa: BLE001
                logger.warning("审批器异常, 按拒绝处理: %s", e)
                answer = False
            # 支持交互式 ApprovalDecision 对象 (action: approve/deny/suggest/timeout)
            if hasattr(answer, "action"):
                action = getattr(answer, "action", "deny")
                if action == "approve":
                    self.approve_request(decision.request_id)
                elif action == "suggest":
                    decision.status = "suggest"
                    decision.action = "suggest"
                    decision.decided_at = time.time()
                    self.last_suggestion = getattr(answer, "suggest_text", "") or ""
                    self.last_decision = "suggest"
                else:
                    self.reject_request(decision.request_id)
                    self.last_decision = action
            elif answer is True or answer in ("approve", "approved"):
                self.approve_request(decision.request_id)
            elif answer is False or answer in ("reject", "denied", "rejected"):
                self.reject_request(decision.request_id)
            else:
                decision.status = "timeout"
                decision.decided_at = time.time()
                with self._lock:
                    self._stats["timeout"] = self._stats.get("timeout", 0) + 1
            return decision

        interactive = False
        try:
            interactive = sys.stdin is not None and sys.stdin.isatty()
        except Exception:  # noqa: BLE001
            interactive = False
        if interactive:
            outcome = self._interactive_prompt(decision)
            if outcome == "approved":
                self.approve_request(decision.request_id)
            elif outcome == "rejected":
                self.reject_request(decision.request_id)
            else:
                decision.status = "timeout"
                decision.decided_at = time.time()
                with self._lock:
                    self._stats["timeout"] = self._stats.get("timeout", 0) + 1
            return decision

        # 非交互: 等待外部通过 approve_request / reject_request 解析
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            with self._lock:
                if decision.status != 'pending':
                    return decision
            time.sleep(0.05)
        if decision.status == 'pending':
            decision.status = "timeout"
            decision.decided_at = time.time()
            with self._lock:
                self._stats["timeout"] = self._stats.get("timeout", 0) + 1
        return decision

    def request(self, command: str, reason: str = '') -> bool:
        """请求用户审批 (同步/CLI 模式)。返回是否批准。"""
        return self.request_decision(command, reason).approved

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict:
        """返回审批统计"""
        with self._lock:
            return {
                "mode": self.mode.value,
                "yolo": self.yolo,
                "checks": self._stats.get("checks", 0),
                "approved": self._stats.get("approved", 0),
                "rejected": self._stats.get("rejected", 0),
                "timeout": self._stats.get("timeout", 0),
                "pending": sum(1 for d in self._pending.values() if d.status == 'pending'),
            }


# ── 模块级便捷函数 (与 stub 的 __all__ 保持一致) ──────────

_default_engine: Optional[ApprovalEngine] = None
_engine_lock = threading.Lock()


def _get_engine() -> ApprovalEngine:
    global _default_engine
    with _engine_lock:
        if _default_engine is None:
            _default_engine = ApprovalEngine()
        return _default_engine


def set_mode(mode: str):
    return _get_engine().set_mode(mode)


def check(command: str, context: Optional[dict] = None) -> ApprovalResult:
    return _get_engine().check(command, context)


def request_decision(command: str, reason: str = '') -> ApprovalDecision:
    return _get_engine().request_decision(command, reason)


def request(command: str, reason: str = '') -> bool:
    return _get_engine().request(command, reason)


def stats() -> dict:
    return _get_engine().stats()


__all__ = ["RiskLevel", "ApprovalMode", "ApprovalResult", "ApprovalEngine", "set_mode", "check", "request_decision", "request", "stats"]
