"""meshctx Action Gate — 行动门禁 (开源真实实现, v3.115.16)

按 TOOL_PRINCIPLE_MAP 检查动作是否合规:
- ActionGate.protect: 注册受保护动作 (rule 回调 / require_approval 静态判定)
- ActionGate.can_execute: 评估动作是否允许执行, 记录事件与统计
- list_protected / get_stats / get_recent_events: 查询接口

原则: 安全 (safety) / 隐私 (privacy) / 知情同意 (consent) /
数据完整性 (data_integrity) / 透明可审计 (transparency)。

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("meshctx.action_gate")


class GateLevel(str, Enum):
    """门控级别"""
    ALLOW = 'allow'       # 直接放行
    APPROVE = 'approve'   # 需审批
    BLOCK = 'block'       # 直接拦截

    def __str__(self):
        return self.value


# 原则定义 (principle_id → 说明)
PRINCIPLES: Dict[str, str] = {
    "principle_safety": "安全优先: 禁止可能导致系统/数据损坏的动作",
    "principle_privacy": "隐私保护: 禁止未授权访问或泄露敏感数据",
    "principle_consent": "知情同意: 影响外部系统的动作需用户确认",
    "principle_data_integrity": "数据完整性: 禁止破坏性数据操作",
    "principle_transparency": "透明可审计: 高风险动作必须留痕",
}

# 工具 → 涉及原则映射 (main.py /api/brain/gate-stats 直接读取)
TOOL_PRINCIPLE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "run_cmd": [
        {"principle_id": "principle_safety", "gate": GateLevel.APPROVE},
        {"principle_id": "principle_transparency", "gate": GateLevel.APPROVE},
    ],
    "terminal": [
        {"principle_id": "principle_safety", "gate": GateLevel.APPROVE},
        {"principle_id": "principle_transparency", "gate": GateLevel.APPROVE},
    ],
    "remote_exec": [
        {"principle_id": "principle_safety", "gate": GateLevel.APPROVE},
        {"principle_id": "principle_consent", "gate": GateLevel.APPROVE},
    ],
    "write_file": [
        {"principle_id": "principle_data_integrity", "gate": GateLevel.APPROVE},
    ],
    "delete_file": [
        {"principle_id": "principle_data_integrity", "gate": GateLevel.APPROVE},
        {"principle_id": "principle_safety", "gate": GateLevel.APPROVE},
    ],
    "browser_navigate": [
        {"principle_id": "principle_privacy", "gate": GateLevel.APPROVE},
    ],
    "git_push": [
        {"principle_id": "principle_data_integrity", "gate": GateLevel.APPROVE},
    ],
    "install_package": [
        {"principle_id": "principle_safety", "gate": GateLevel.APPROVE},
    ],
    "send_message": [
        {"principle_id": "principle_consent", "gate": GateLevel.APPROVE},
    ],
    "modify_config": [
        {"principle_id": "principle_data_integrity", "gate": GateLevel.APPROVE},
    ],
    "read_secrets": [
        {"principle_id": "principle_privacy", "gate": GateLevel.BLOCK},
    ],
}


class ActionGate:
    """Gate sensitive actions behind approval checks."""

    def __init__(self):
        self._protected: Dict[str, dict] = {}
        self._events: Deque[dict] = deque(maxlen=100)
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = {
            "protected": 0, "allowed": 0, "denied": 0, "evaluations": 0,
        }

    # ── 注册 ──────────────────────────────────────────────

    def protect(self, action: str, rule: Callable[[Dict], bool] = None,
                require_approval: bool = True):
        """注册受保护动作。

        Args:
            action: 动作名 (如 "run_cmd" / "delete_file")。
            rule: 可选回调 rule(context_dict) -> bool; 提供时以回调为准。
            require_approval: 无 rule 时, True 表示默认需审批 (can_execute=False),
                               False 表示默认放行。
        """
        if not action or not isinstance(action, str):
            raise ValueError("action 必须是非空字符串")
        if rule is not None and not callable(rule) and not isinstance(rule, bool):
            raise TypeError("rule 必须是 callable 或 bool")
        with self._lock:
            self._protected[action] = {
                "rule": rule,
                "require_approval": bool(require_approval),
            }
            self._stats["protected"] = len(self._protected)
        return action

    # ── 评估 ──────────────────────────────────────────────

    def _decide(self, action: str, context: dict) -> bool:
        entry = self._protected.get(action)
        if entry is None:
            return True  # 未受保护 → 放行
        rule = entry.get("rule")
        if rule is not None:
            if callable(rule):
                try:
                    return bool(rule(context or {}))
                except Exception as e:  # noqa: BLE001
                    logger.warning("动作 %s 规则回调异常, 按拒绝处理: %s", action, e)
                    return False
            return bool(rule)  # bool 静态规则
        return not entry.get("require_approval", True)

    def can_execute(self, action: str, context: dict = None) -> bool:
        """评估动作是否允许执行。"""
        ctx = context or {}
        allowed = self._decide(action, ctx)
        with self._lock:
            self._stats["evaluations"] = self._stats.get("evaluations", 0) + 1
            if allowed:
                self._stats["allowed"] = self._stats.get("allowed", 0) + 1
            else:
                self._stats["denied"] = self._stats.get("denied", 0) + 1
            self._events.append({
                "time": time.time(),
                "action": action,
                "allowed": allowed,
                "context_keys": sorted(k for k in (ctx.keys() if isinstance(ctx, dict) else [])),
            })
        return allowed

    # ── 查询 ──────────────────────────────────────────────

    def list_protected(self) -> list:
        with self._lock:
            return sorted(self._protected.keys())

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def get_recent_events(self, limit: int = 10) -> list:
        with self._lock:
            return [dict(e) for e in list(self._events)[-int(limit):]]

    def reset(self):
        with self._lock:
            self._events.clear()
            self._stats = {"protected": len(self._protected), "allowed": 0,
                           "denied": 0, "evaluations": 0}


# ── 全局单例 ───────────────────────────────────────────────

_gate: Optional[ActionGate] = None
_gate_lock = threading.Lock()


def get_action_gate() -> ActionGate:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = ActionGate()
        return _gate


def get_gate() -> ActionGate:
    """别名 (main.py /api/brain/gate-stats 使用 get_gate)。"""
    return get_action_gate()


# ── 模块级便捷函数 (与 stub 的 __all__ 保持一致) ──────────

def protect(action: str, rule: Callable[[Dict], bool] = None, require_approval: bool = True):
    return get_action_gate().protect(action, rule=rule, require_approval=require_approval)


def can_execute(action: str, context: dict = None) -> bool:
    return get_action_gate().can_execute(action, context)


def list_protected() -> list:
    return get_action_gate().list_protected()


__all__ = ["ActionGate", "protect", "can_execute", "list_protected", "get_action_gate"]
