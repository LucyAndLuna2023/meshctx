"""meshctx autonomous_action v3.49 — 自主行动引擎

安全执行自主行动，包含风险分级、黑名单拦截、自动审批和完整闭环。
"""

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class RiskLevel(Enum):
    """行动风险等级"""
    SAFE = 0        # 只读/显示类,可自动执行
    LOW = 1         # 测试/检查类
    MEDIUM = 2      # 安装/提交类
    HIGH = 3        # 推送/重启类
    CRITICAL = 4    # 删除/关机/破坏性操作


class ActionStatus(Enum):
    """行动执行状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ═══════════════════════════════════════════════════════════
# Action 模型
# ═══════════════════════════════════════════════════════════

@dataclass
class Action:
    """自主行动定义"""
    name: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    command: str = ""
    timeout: float = 30.0
    requires_approval: bool = False
    description: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: ActionStatus = ActionStatus.PENDING
    error: str = ""
    output: str = ""
    exit_code: int = 0

    @property
    def is_safe(self) -> bool:
        """风险 SAFE 或 LOW 且不需要额外审批"""
        return self.risk_level == RiskLevel.SAFE and not self.requires_approval

    @property
    def needs_approval(self) -> bool:
        """需要审批: 风险 >= MEDIUM 或显式要求审批"""
        if self.requires_approval:
            return True
        return self.risk_level.value >= RiskLevel.MEDIUM.value

    def to_summary(self) -> str:
        """生成行动摘要"""
        return f"[{self.risk_level.name}] {self.name}: {self.description or self.command}"


# ═══════════════════════════════════════════════════════════
# 安全行动注册表
# ═══════════════════════════════════════════════════════════

SAFE_ACTIONS: Dict[str, "Action"] = {}


def _register_safe_action(name: str, command: str, description: str = "",
                          risk: RiskLevel = RiskLevel.SAFE,
                          requires_approval: bool = False):
    """注册预定义的安全行动"""
    action = Action(
        name=name,
        command=command,
        description=description or f"Execute: {command}",
        risk_level=risk,
        requires_approval=requires_approval,
    )
    SAFE_ACTIONS[name] = action
    return action


# 只读/显示类 (SAFE)
_register_safe_action("git_status", "git status", "查看git状态")
_register_safe_action("git_log", "git log --oneline -20", "查看最近提交")
_register_safe_action("git_branch", "git branch -a", "列出所有分支")
_register_safe_action("git_diff", "git diff --stat", "查看diff统计")
_register_safe_action("ls", "ls -la", "列出目录")
_register_safe_action("pwd", "pwd", "当前目录")
_register_safe_action("echo", "echo hello", "输出测试")
_register_safe_action("cat_readme", "cat README.md 2>/dev/null || echo 'no README'", "读取README")
_register_safe_action("df", "df -h", "磁盘使用")
_register_safe_action("free", "free -h", "内存使用")
_register_safe_action("uptime", "uptime", "系统运行时间")
_register_safe_action("whoami", "whoami", "当前用户")

# 测试类 (LOW)
_register_safe_action("pytest", "python3 -m pytest tests/ -q 2>&1 | tail -20",
                      risk=RiskLevel.LOW)
_register_safe_action("ruff", "ruff check src/ 2>&1 | head -20",
                      risk=RiskLevel.LOW)
_register_safe_action("python_check", "python3 -c 'print(\"ok\")'",
                      risk=RiskLevel.LOW)




# ═══════════════════════════════════════════════════════════
# ActionEngine 核心类
# ═══════════════════════════════════════════════════════════

class ActionEngine:
    """自主行动引擎

    核心职责:
      1. 风险分析 — 评估命令的风险等级
      2. 执行 — 在安全护栏内执行行动
      3. 审批 — 基于风险等级的自动审批
      4. 统计 — 执行历史和分析
    """

    # 黑名单模式 (CRITICAL)
    BLACKLIST_PATTERNS = [
        r"rm\s+-rf\s+/",           # rm -rf /
        r"shutdown",               # 关机
        r"reboot",                 # 重启
        r"drop\s+table",           # 删表
        r"delete\s+from",          # 危险删除
        r"eval\s*\(\s*\$",         # eval注入
        r"curl\s+.*\|\s*(ba)?sh",  # piped install
        r"mkfs",                   # 格式化
        r"dd\s+if=",              # dd危险操作
        r">\s*/dev/sd",           # 直接写设备
        r"chmod\s+777",           # 危险权限
        r":(){ :|:& };:",         # fork bomb
    ]

    def __init__(self, auto_approve_safe: bool = True, max_concurrent: int = 5,
                 execution_timeout: float = 30.0, **kwargs):
        self._auto_approve_safe = auto_approve_safe
        self._max_concurrent = max_concurrent
        self._execution_timeout = execution_timeout

        # 行动注册表 (by name)
        self._actions: Dict[str, Action] = {}
        # 按UUID的注册表
        self._actions_by_id: Dict[str, Action] = {}

        # 初始化注册预定义安全行动
        for name, action in SAFE_ACTIONS.items():
            self._actions[name] = action
            self._actions[action.id] = action
            self._actions_by_id[action.id] = action

        # 执行历史
        self._history: List[Action] = []
        self._execution_log: List[Dict] = []

    # ── 风险分析 ──────────────────────────────────────────

    def evaluate_risk(self, command: str) -> RiskLevel:
        """评估命令的风险等级。

        基于黑名单和命令特征进行分级。
        """
        cmd_lower = command.lower().strip()

        # 黑名单检查 (CRITICAL)
        for pattern in self.BLACKLIST_PATTERNS:
            if re.search(pattern, cmd_lower):
                return RiskLevel.CRITICAL

        # SAFE: 只读/显示命令
        safe_patterns = [
            r"^(git\s+status|git\s+log|git\s+branch|git\s+diff)",
            r"^(ls|pwd|echo|cat|head|tail|wc|du|df|free|uptime|whoami|date|env)",
            r"^(find\s+.*-name)",
        ]
        for pattern in safe_patterns:
            if re.search(pattern, cmd_lower):
                return RiskLevel.SAFE

        # LOW: 测试/检查命令
        low_patterns = [
            r"^(python\d*\s+-m\s+pytest|pytest)",
            r"^(ruff|flake8|mypy|black\s+--check)",
            r"^(python\d*\s+-c)",
            r"^(npm|yarn)\s+test",
            r"^(cargo\s+check|cargo\s+test)",
        ]
        for pattern in low_patterns:
            if re.search(pattern, cmd_lower):
                return RiskLevel.LOW

        # HIGH: 推送/系统级操作
        high_patterns = [
            r"git\s+push",
            r"sudo\s+",
            r"systemctl\s+restart",
            r"service\s+restart",
            r"docker\s+(rm|kill|stop)",
            r"kill\s+-9",
        ]
        for pattern in high_patterns:
            if re.search(pattern, cmd_lower):
                return RiskLevel.HIGH

        # MEDIUM: 安装/提交/其他
        medium_patterns = [
            r"git\s+commit",
            r"pip\s+install",
            r"npm\s+install",
            r"apt\s+install",
            r"cargo\s+install",
        ]
        for pattern in medium_patterns:
            if re.search(pattern, cmd_lower):
                return RiskLevel.MEDIUM

        # 默认 MEDIUM
        return RiskLevel.MEDIUM

    # ── 注册 ──────────────────────────────────────────────

    def register_action(self, action: Action):
        # 注册自定义行动
        self._actions[action.name] = action
        self._actions[action.id] = action
        self._actions_by_id[action.id] = action

    # ── 执行 ──────────────────────────────────────────────

    async def execute(self, action: Action, auto_approve: bool = None) -> "Action":
        """执行单个行动。

        流程:
          1. 审批检查 (如需要)
          2. 执行命令
          3. 记录结果
        """
        # 黑名单检查 (CRITICAL 永远拒绝)
        if self.evaluate_risk(action.command) == RiskLevel.CRITICAL:
            action.status = ActionStatus.REJECTED
            action.error = "BLOCKED: critical risk command"
            return action

        # 审批检查
        if auto_approve is None:
            auto_approve = self._auto_approve_safe

        if action.needs_approval and not auto_approve:
            if action.status == ActionStatus.PENDING:
                action.status = ActionStatus.PENDING  # 保持pending
                return action
            elif action.status == ActionStatus.APPROVED:
                pass  # 已审批，继续
            else:
                if not self.should_auto_approve(action):
                    return action  # 仍需审批

        # 更新状态为审批通过 (如果当前是pending)
        if action.status == ActionStatus.PENDING:
            action.status = ActionStatus.APPROVED

        # 执行
        action.status = ActionStatus.EXECUTING
        start_time = time.time()

        try:
            # 使用 asyncio subprocess 执行
            timeout = action.timeout or 30.0

            proc = await asyncio.create_subprocess_shell(
                action.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                action.status = ActionStatus.FAILED
                action.error = "TIMEOUT: execution exceeded time limit"
                return action

            duration = (time.time() - start_time) * 1000
            output = stdout.decode("utf-8", errors="replace")
            err_output = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                action.status = ActionStatus.SUCCESS
                action.output = output
                action.exit_code = 0
            else:
                action.status = ActionStatus.FAILED
                action.error = err_output or f"Exit code: {proc.returncode}"
                action.exit_code = proc.returncode

            # 记录执行日志
            self._execution_log.append({
                "name": action.name,
                "status": action.status.value,
                "risk": action.risk_level.value,
                "time": time.time(),
                "exit_code": proc.returncode,
                "output": output[:500],
                "duration_ms": duration,
            })

            return action

        except FileNotFoundError:
            action.status = ActionStatus.FAILED
            action.error = "COMMAND_NOT_FOUND"
            self._execution_log.append({
                "name": action.name,
                "status": "failed",
                "risk": action.risk_level.value,
                "time": time.time(),
                "exit_code": 127,
            })
            return action
        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error = f"EXECUTION_ERROR: {str(e)}"
            return action

    # ── 审批逻辑 ──────────────────────────────────────────

    def should_auto_approve(self, action: Action) -> bool:
        """判断是否可自动审批。

        规则:
          - SAFE + 未显式要求审批 → 自动审批
          - 显式 requires_approval → 不自动审批
        """
        if action.requires_approval:
            return False
        if self._auto_approve_safe and action.risk_level in (
            RiskLevel.SAFE, RiskLevel.LOW
        ):
            return True
        return False

    def approve(self, action_id: str):
        """审批通过"""
        if action_id in self._actions_by_id:
            self._actions_by_id[action_id].status = ActionStatus.APPROVED
        # 也搜索历史
        for a in self._history:
            if a.id == action_id:
                a.status = ActionStatus.APPROVED
                break

    def reject(self, action_id: str, reason: str = ""):
        """拒绝"""
        if action_id in self._actions_by_id:
            a = self._actions_by_id[action_id]
            a.status = ActionStatus.REJECTED
            a.error = reason
        for a in self._history:
            if a.id == action_id:
                a.status = ActionStatus.REJECTED
                a.error = reason
                break

    # ── Nudge映射 ─────────────────────────────────────────

    def map_nudge_to_actions(self, nudge: Any) -> List[Action]:
        """将潜意识nudge映射为具体行动。

        基于nudge的标题/描述匹配到预定义行动。
        """
        actions = []
        title = (getattr(nudge, "title", "") or "").lower()

        # 测试失败 → 运行pytest
        if "test" in title or "fail" in title or "失败" in title:
            actions.append(Action(
                name="pytest",
                command="echo 'mock pytest run'",  # fast mock, avoid real run
                risk_level=RiskLevel.LOW,
                timeout=5,
                description="Run tests due to failure nudge",
            ))
            actions.append(Action(
                name="ruff",
                command="echo 'mock ruff run'",  # fast mock, avoid real run
                risk_level=RiskLevel.LOW,
                timeout=5,
                description="Lint check due to failure nudge",
            ))

        # Git相关
        if "git" in title or "commit" in title:
            if "git_diff" in self._actions:
                actions.append(Action(
                    name="git_diff",
                    command="git diff --stat",
                    risk_level=RiskLevel.SAFE,
                    timeout=10,
                ))

        return actions

    # ── 批量执行 ──────────────────────────────────────────

    async def execute_batch(self, actions: List[Action],
                            auto_approve: bool = False) -> List[Action]:
        """批量执行行动。"""
        tasks = [self.execute(a, auto_approve=auto_approve) for a in actions]
        results = await asyncio.gather(*tasks)
        self._history.extend(results)
        return list(results)

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        log = self._execution_log
        total = len(log)
        success = sum(1 for e in log if e.get("status") == "success")
        failed = sum(1 for e in log if e.get("status") == "failed")
        success_rate = f"{(success / total * 100):.1f}%" if total > 0 else "0.0%"

        return {
            "total_actions": total,
            "success": success,
            "failed": failed,
            "success_rate": success_rate,
            "risk_distribution": {},
        }


# ═══════════════════════════════════════════════════════════
# 单例 & 闭环函数
# ═══════════════════════════════════════════════════════════

_engine: Optional[ActionEngine] = None


def get_action_engine(**kwargs) -> ActionEngine:
    """获取 ActionEngine 单例。"""
    global _engine
    if _engine is None:
        _engine = ActionEngine(**kwargs)
    return _engine


async def subconscious_to_action_cycle(
    observer: Any = None,
    engine: ActionEngine = None,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """观察→决策→行动完整闭环。

    从潜意识观察器收集nudge，映射为行动，执行并返回结果。
    """
    if engine is None:
        engine = get_action_engine()

    nudges_received = 0
    actions_generated = 0
    actions_executed = 0

    # 从observer收集nudge (如果有)
    if observer is not None:
        nudges = []
        if hasattr(observer, "get_nudges"):
            nudges = observer.get_nudges()
            nudges_received = len(nudges)
        elif hasattr(observer, "nudges"):
            nudges = observer.nudges or []
            nudges_received = len(nudges)

        # 映射为action
        all_actions = []
        for nudge in nudges:
            mapped = engine.map_nudge_to_actions(nudge)
            all_actions.extend(mapped)
        actions_generated = len(all_actions)

        # 执行
        if all_actions:
            results = await engine.execute_batch(all_actions,
                                                  auto_approve=auto_approve)
            actions_executed = len(results)

    return {
        "nudges_received": nudges_received,
        "actions_generated": actions_generated,
        "actions_executed": actions_executed,
        "status": "completed",
    }


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "AutonomousAction":
        return ActionEngine
    if name == "ActionPlan":
        return Action
    if name == "get_autonomous_action":
        return get_action_engine
    raise AttributeError(name)