"""
meshctx Heartbeat — 心跳监控
对标: OpenClaw heartbeat
"""
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
def heartbeat_start(name: str, interval_seconds: int = 60, on_miss: Callable = None, max_misses: int = 3) -> dict:
    """启动心跳监控"""
    raise NotImplementedError("meshctx-core required (private repo)")

def heartbeat_ping(name: str) -> dict:
    """发送心跳 (重置计时器)"""
    raise NotImplementedError("meshctx-core required (private repo)")

def heartbeat_status(name: str = None) -> dict:
    """查看心跳状态"""
    raise NotImplementedError("meshctx-core required (private repo)")

def heartbeat_stop(name: str) -> dict:
    """停止心跳监控"""
    raise NotImplementedError("meshctx-core required (private repo)")

