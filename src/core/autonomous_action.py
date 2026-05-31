"""
meshctx v3.49 — Autonomous Action Engine (自主行动引擎)

闭环: SubconsciousObserver(Nudge生成) → ActionEngine(决策+执行)
解决: Agent不只会看，还会自己动手

安全三层:
  L1: 自动执行 (低风险: git status, pip list, 代码格式化)
  L2: 建议执行 (中风险: pip install, git commit, 测试运行) 
  L3: 需审批 (高风险: git push, 删除文件, 系统配置变更)

与SubconsciousObserver联动: 收到Nudge → 评估风险 → 执行/建议/拒绝
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.autonomous_action")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class RiskLevel(Enum):
    """操作风险等级"""
    SAFE = 0       # 无风险: 只读操作, 格式化
    LOW = 1        # 低风险: 测试运行,  lint
    MEDIUM = 2     # 中风险: pip install, git commit
    HIGH = 3       # 高风险: git push, 配置变更
    CRITICAL = 4   # 致命: 删除数据, 系统命令


class ActionStatus(Enum):
    """执行状态"""
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass
class Action:
    """可执行行动"""
    id: str = field(default_factory=lambda: f"act-{int(time.time()*1000)}")
    name: str = ""
    description: str = ""
    command: str = ""                    # shell命令
    risk_level: RiskLevel = RiskLevel.LOW
    status: ActionStatus = ActionStatus.PENDING
    timeout: int = 30
    working_dir: str = ""
    requires_approval: bool = False
    max_retries: int = 1
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    executed_at: float = 0
    output: str = ""
    error: str = ""
    exit_code: int = -1
    
    @property
    def is_safe(self) -> bool:
        return self.risk_level == RiskLevel.SAFE
    
    @property
    def needs_approval(self) -> bool:
        return self.requires_approval or self.risk_level.value >= RiskLevel.MEDIUM.value
    
    def to_summary(self) -> str:
        emoji = {RiskLevel.SAFE: "🟢", RiskLevel.LOW: "🟡", RiskLevel.MEDIUM: "🟠",
                 RiskLevel.HIGH: "🔴", RiskLevel.CRITICAL: "💀"}.get(self.risk_level, "")
        status_icon = {ActionStatus.SUCCESS: "✅", ActionStatus.FAILED: "❌",
                       ActionStatus.PENDING: "⏳", ActionStatus.REJECTED: "🚫"}.get(self.status, "")
        return f"{emoji}{status_icon} {self.name}: {self.description[:60]}"


# ═══════════════════════════════════════════════════════════
# Action Registry — 已知安全操作
# ═══════════════════════════════════════════════════════════

SAFE_ACTIONS = {
    # 只读操作
    "git_status": Action(
        name="git status", description="Check repository status",
        command="git status --short", risk_level=RiskLevel.SAFE, timeout=10,
    ),
    "git_log": Action(
        name="git log", description="Check recent commits",
        command="git log --oneline -5", risk_level=RiskLevel.SAFE, timeout=10,
    ),
    "git_diff": Action(
        name="git diff", description="Check uncommitted changes",
        command="git diff --stat", risk_level=RiskLevel.SAFE, timeout=10,
    ),
    "pip_list": Action(
        name="pip list", description="List installed packages",
        command="pip list --format=columns 2>/dev/null | head -20", risk_level=RiskLevel.SAFE, timeout=15,
    ),
    "disk_usage": Action(
        name="disk usage", description="Check disk space",
        command="df -h / | tail -1", risk_level=RiskLevel.SAFE, timeout=5,
    ),
    "memory_usage": Action(
        name="memory usage", description="Check memory",
        command="free -h | head -2", risk_level=RiskLevel.SAFE, timeout=5,
    ),
    "test_count": Action(
        name="test count", description="Count passing tests",
        command="python -m pytest --co -q 2>/dev/null | tail -1", risk_level=RiskLevel.SAFE, timeout=30,
    ),
    # 低风险操作
    "run_tests": Action(
        name="run tests", description="Run full test suite",
        command="python -m pytest tests/ --ignore=tests/ui --ignore=tests/archived -q 2>&1 | tail -5",
        risk_level=RiskLevel.LOW, timeout=120,
    ),
    "lint_check": Action(
        name="lint check", description="Run linter on changed files",
        command="python -m ruff check src/ --quiet 2>/dev/null | head -20 || echo 'ruff not installed'",
        risk_level=RiskLevel.LOW, timeout=30,
    ),
    "check_outdated": Action(
        name="check outdated", description="Check outdated packages",
        command="pip list --outdated --format=columns 2>/dev/null | head -15",
        risk_level=RiskLevel.SAFE, timeout=15,
    ),
    # 中风险操作(需审批)
    "git_add": Action(
        name="git add", description="Stage all changes",
        command="git add -A", risk_level=RiskLevel.MEDIUM, timeout=10,
        requires_approval=True,
    ),
    "git_commit": Action(
        name="git commit", description="Commit with message", 
        command="git commit -m 'auto: autonomous action engine commit'",
        risk_level=RiskLevel.MEDIUM, timeout=10, requires_approval=True,
    ),
    "pip_upgrade": Action(
        name="pip upgrade", description="Upgrade all packages",
        command="pip install --upgrade pip setuptools wheel 2>&1 | tail -5",
        risk_level=RiskLevel.MEDIUM, timeout=60, requires_approval=True,
    ),
    # 高风险操作(必须审批)
    "git_push": Action(
        name="git push", description="Push to remote",
        command="git push", risk_level=RiskLevel.HIGH, timeout=30,
        requires_approval=True,
    ),
    "system_restart": Action(
        name="system restart", description="Restart meshctx service",
        command="sudo systemctl restart meshctx 2>&1",
        risk_level=RiskLevel.CRITICAL, timeout=10, requires_approval=True,
    ),
}


# ═══════════════════════════════════════════════════════════
# Action Engine Core
# ═══════════════════════════════════════════════════════════

class ActionEngine:
    """
    自主行动引擎
    
    输入: Nudge(来自SubconsciousObserver) 或 规则触发
    处理: 风险分级 → 审批判断 → 执行 → 记录
    输出: 执行结果+统计
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._actions: Dict[str, Action] = dict(SAFE_ACTIONS)
        self._history: deque = deque(maxlen=200)
        self._auto_approve_safe: bool = self.config.get("auto_approve_safe", True)
        self._max_concurrent: int = self.config.get("max_concurrent", 3)
        self._execution_log: List[Dict] = []
        
        # 安全黑名单 — 永远不自动执行的模式
        self._blacklist_patterns = [
            "rm -rf", "DROP TABLE", "DELETE FROM", "format",
            "shutdown", "reboot", "chmod 777", "> /dev/sda",
            "eval(", "__import__", "exec(", "subprocess",
        ]
        
        # Nudge→Action映射规则
        self._nudge_rules = [
            # (nudge_title_pattern, action_name, is_auto)
            ("test", "run_tests", True),
            ("outdated", "check_outdated", True),
            ("git", "git_status", True),
            ("error", "run_tests", False),  # 错误时先跑测试但需确认
            ("deploy", "git_status", True),
            ("commit", "git_diff", True),
            ("disk", "disk_usage", True),
            ("memory", "memory_usage", True),
        ]
        
        logger.info(f"ActionEngine initialized ({len(self._actions)} registered actions)")

    def register_action(self, action: Action):
        """注册自定义行动"""
        self._actions[action.id] = action
        logger.info(f"Registered action: {action.name}")

    def evaluate_risk(self, command: str) -> RiskLevel:
        """评估命令风险"""
        cmd_lower = command.lower()
        
        # 检查黑名单
        for pattern in self._blacklist_patterns:
            if pattern.lower() in cmd_lower:
                return RiskLevel.CRITICAL
        
        # 高风险模式
        high_risk = ["git push", "sudo", "chmod", "chown", "rm ", "mv ",
                      "systemctl", "service ", "kill", "pkill"]
        for p in high_risk:
            if p in cmd_lower:
                return RiskLevel.HIGH
        
        # 中风险
        med_risk = ["pip install", "pip uninstall", "git commit", "git merge",
                     "npm install", "cargo install"]
        for p in med_risk:
            if p in cmd_lower:
                return RiskLevel.MEDIUM
        
        # 低风险
        low_risk = ["pytest", "python -m pytest", "pip list", "npm test",
                     "cargo test", "ruff", "black", "isort"]
        for p in low_risk:
            if p in cmd_lower:
                return RiskLevel.LOW
        
        # 只读操作安全
        safe_indicators = ["git status", "git log", "git diff", "git branch", "--help", "--version", " -h ", " -V ", "which ",
                            "type ", "echo ", "cat ", "head ", "tail ", "ls ",
                            "grep ", "wc ", "find ", "stat ", "df ", "free ", "pip list"]
        for p in safe_indicators:
            if p in cmd_lower:
                return RiskLevel.SAFE
        
        return RiskLevel.MEDIUM  # 默认中等风险

    async def execute(self, action: Action) -> Action:
        """执行行动"""
        if action.status == ActionStatus.REJECTED:
            return action
        
        action.status = ActionStatus.EXECUTING
        action.executed_at = time.time()
        
        try:
            # 在线程池中运行(避免阻塞事件循环)
            loop = asyncio.get_event_loop()
            
            def _run():
                proc = subprocess.run(
                    action.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=action.timeout,
                    cwd=action.working_dir or os.getcwd(),
                )
                return proc
            
            proc = await loop.run_in_executor(None, _run)
            
            action.output = (proc.stdout or "")[:2000]
            action.error = (proc.stderr or "")[:1000]
            action.exit_code = proc.returncode
            
            if proc.returncode == 0:
                action.status = ActionStatus.SUCCESS
                logger.info(f"Action SUCCESS: {action.name} (exit={proc.returncode})")
            else:
                action.status = ActionStatus.FAILED
                logger.warning(f"Action FAILED: {action.name} (exit={proc.returncode}, stderr={action.error[:100]})")
                
        except subprocess.TimeoutExpired:
            action.status = ActionStatus.FAILED
            action.error = f"TIMEOUT after {action.timeout}s"
            action.exit_code = -1
            logger.error(f"Action TIMEOUT: {action.name}")
            
        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error = str(e)[:500]
            action.exit_code = -2
            logger.error(f"Action ERROR: {action.name}: {e}")
        
        # 记录历史
        self._history.append(action)
        self._execution_log.append({
            "id": action.id,
            "name": action.name,
            "status": action.status.value,
            "risk": action.risk_level.value,
            "exit_code": action.exit_code,
            "time": action.executed_at,
        })
        
        return action

    def should_auto_approve(self, action: Action) -> bool:
        """判断是否可以自动批准"""
        if not self._auto_approve_safe:
            return False
        if action.requires_approval:
            return False
        if action.risk_level.value >= RiskLevel.MEDIUM.value:
            return False
        return True

    def map_nudge_to_actions(self, nudge) -> List[Action]:
        """将Nudge映射为可执行行动"""
        actions = []
        nudge_title = nudge.title.lower() if hasattr(nudge, 'title') else str(nudge).lower()
        
        for pattern, action_name, is_auto in self._nudge_rules:
            if pattern in nudge_title and action_name in self._actions:
                action = self._actions[action_name]
                cloned = Action(
                    id=f"{action.id}-{int(time.time())}",
                    name=action.name,
                    description=f"Triggered by nudge: {nudge.title if hasattr(nudge,'title') else ''}",
                    command=action.command,
                    risk_level=action.risk_level,
                    requires_approval=not is_auto,
                    timeout=action.timeout,
                    working_dir=action.working_dir,
                )
                actions.append(cloned)
        
        return actions

    def get_pending_approvals(self) -> List[Action]:
        """获取待审批行动"""
        return [a for a in self._history 
                if a.status == ActionStatus.PENDING and a.needs_approval]

    def approve(self, action_id: str) -> Optional[Action]:
        """批准行动"""
        for a in self._history:
            if a.id == action_id:
                a.status = ActionStatus.APPROVED
                return a
        return None

    def reject(self, action_id: str, reason: str = "") -> Optional[Action]:
        """拒绝行动"""
        # Search in reverse to find most recent first
        for a in reversed(list(self._history)):
            if a.id == action_id:
                a.status = ActionStatus.REJECTED
                a.error = reason
                return a
        return None

    async def execute_batch(self, actions: List[Action], auto_approve: bool = True) -> List[Action]:
        """批量执行行动"""
        results = []
        pending = []
        
        for action in actions:
            if auto_approve and self.should_auto_approve(action):
                action.status = ActionStatus.APPROVED
                pending.append(action)
            elif action.is_safe:
                pending.append(action)
            else:
                action.status = ActionStatus.PENDING
                results.append(action)
        
        # 并发执行已批准的行动
        tasks = [self.execute(a) for a in pending[:self._max_concurrent]]
        if tasks:
            executed = await asyncio.gather(*tasks)
            results.extend(executed)
        
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        total = len(self._execution_log)
        success = sum(1 for e in self._execution_log if e["status"] == "success")
        failed = sum(1 for e in self._execution_log if e["status"] == "failed")
        
        risk_dist = {}
        for e in self._execution_log:
            risk = e["risk"]
            risk_dist[f"risk_{risk}"] = risk_dist.get(f"risk_{risk}", 0) + 1
        
        return {
            "total_actions": total,
            "success": success,
            "failed": failed,
            "success_rate": f"{success/total*100:.1f}%" if total > 0 else "N/A",
            "risk_distribution": risk_dist,
            "pending_approvals": len(self.get_pending_approvals()),
            "registered_actions": len(self._actions),
            "auto_approve_enabled": self._auto_approve_safe,
            "last_executions": [
                {"name": e["name"], "status": e["status"], "time": e["time"]}
                for e in self._execution_log[-5:]
            ],
        }


# ═══════════════════════════════════════════════════════════
# Subconscious → Action 桥接
# ═══════════════════════════════════════════════════════════

async def subconscious_to_action_cycle(
    observer=None,
    engine: Optional[ActionEngine] = None,
    auto_approve: bool = True,
) -> Dict[str, Any]:
    """
    完整的 观察→决策→行动 自主循环
    
    1. SubconsciousObserver生成Nudge
    2. ActionEngine映射为Action
    3. 风险分级+自动审批
    4. 执行
    5. 返回统计
    """
    if engine is None:
        engine = ActionEngine()
    
    # 获取Nudge
    nudges = []
    if observer:
        try:
            nudges = await observer.cycle()
        except Exception as e:
            logger.error(f"Observer cycle failed: {e}")
    
    # 映射为Action
    all_actions = []
    for nudge in nudges:
        actions = engine.map_nudge_to_actions(nudge)
        all_actions.extend(actions)
    
    # 去重
    seen_commands = set()
    unique_actions = []
    for a in all_actions:
        if a.command not in seen_commands:
            seen_commands.add(a.command)
            unique_actions.append(a)
    
    # 执行
    results = await engine.execute_batch(unique_actions, auto_approve=auto_approve)
    
    # 统计
    executed = sum(1 for r in results if r.status in (ActionStatus.SUCCESS, ActionStatus.FAILED))
    success = sum(1 for r in results if r.status == ActionStatus.SUCCESS)
    
    return {
        "nudges_received": len(nudges),
        "actions_generated": len(unique_actions),
        "actions_executed": executed,
        "actions_succeeded": success,
        "pending_approval": len([r for r in results if r.status == ActionStatus.PENDING]),
        "results": [r.to_summary() for r in results],
    }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_engine: Optional[ActionEngine] = None


def get_action_engine(config: Optional[Dict] = None) -> ActionEngine:
    global _engine
    if _engine is None:
        _engine = ActionEngine(config)
    return _engine
