"""Healer — 开源版 (stub)"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
__all__ = []

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

__all__ = []
__all__ = []
__all__ = []
class HealthStatus:
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    FAILING = 'failing'

class CircuitBreaker:
    def __init__(self, *a, **kw):
        raise NotImplementedError("meshctx-core required (private repo)")

    def check(self):
        raise NotImplementedError("meshctx-core required (private repo)")


class HealerPlugin:
    state = 'active'
    async def on_load(self, kernel):
        raise NotImplementedError("meshctx-core required (private repo)")

    def generate_report(self):
        raise NotImplementedError("meshctx-core required (private repo)")


