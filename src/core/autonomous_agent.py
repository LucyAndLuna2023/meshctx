"""v3.115.20: 自主Agent占位模块 — meshctx-core 未安装时提供桩实现。"""
import logging
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class AutonomousAgent:
    """占位Agent — meshctx-core未安装，Agent不可用。"""
    def __init__(self):
        self.running = False
        self.status = "stopped"
        self.config: Dict[str, Any] = {}
        self._cycle_count: int = 0
        self._last_observe: float = 0.0
    async def start(self):
        logger.warning("AutonomousAgent 需要 meshctx-core，当前为桩模式")
        self.running = False
        self.status = "error: meshctx-core not installed"
    async def stop(self):
        self.running = False
        self.status = "stopped"
    async def observe_now(self) -> Optional[Dict[str, Any]]:
        """占位观察 — 从不返回有效观察。"""
        self._last_observe = time.time()
        self._cycle_count += 1
        return None

_agent = None

def get_autonomous_agent() -> AutonomousAgent:
    global _agent
    if _agent is None:
        _agent = AutonomousAgent()
    return _agent
