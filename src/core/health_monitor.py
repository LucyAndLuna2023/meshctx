"""meshctx health_monitor — real implementation"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field

class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")
    def __repr__(self):
        return f"<meshctx stub {self._name}>"

def __getattr__(name):
    return _MeshCtxStubProxy(name)

@dataclass
class ModuleCheck:
    module: str = None
    status: str = None
    latency_ms: float = None
    error: str = ''

class RealtimeHealthMonitor:
    """Real-time health monitor for meshctx modules."""
    def __init__(self, check_interval: int = 60, history_size: int = 100):
        raise NotImplementedError("meshctx-core required (private repo)")

    async def check_module(self, module_name: str) -> ModuleCheck:
        """Check health of a single module."""
        raise NotImplementedError("meshctx-core required (private repo)")

    async def check_all(self) -> Dict[str, Any]:
        """Check all modules and return health summary."""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_summary(self) -> Dict[str, Any]:
        """Return health summary."""
        raise NotImplementedError("meshctx-core required (private repo)")

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to health events."""
        raise NotImplementedError("meshctx-core required (private repo)")


def get_health_monitor() -> RealtimeHealthMonitor:
    """Return the global singleton health monitor."""
    raise NotImplementedError("meshctx-core required (private repo)")


__all__ = ["ModuleCheck", "RealtimeHealthMonitor", "check_module", "check_all", "get_summary", "subscribe", "get_health_monitor"]
