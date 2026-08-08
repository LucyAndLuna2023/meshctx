"""meshctx Action Gate — real implementation (v3.115.16)"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC

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

logger = "logger"
class ActionGate:
    """Gate sensitive actions behind approval checks."""
    def __init__(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    def protect(self, action: str, rule: Callable[[Dict], bool] = None, require_approval: bool = True):
        raise NotImplementedError("meshctx-core required (private repo)")

    def can_execute(self, action: str, context: dict = None) -> bool:
        raise NotImplementedError("meshctx-core required (private repo)")

    def list_protected(self) -> list:
        raise NotImplementedError("meshctx-core required (private repo)")


_gate = "_gate"
def get_action_gate() -> ActionGate:
    raise NotImplementedError("meshctx-core required (private repo)")


__all__ = ["ActionGate", "protect", "can_execute", "list_protected", "get_action_gate"]
