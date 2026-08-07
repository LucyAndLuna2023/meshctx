"""Session Resume — 开源版 (stub)"""
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
class SessionState:
    """Represents a stored session state."""
    def __init__(self, id, profile, messages):
        raise NotImplementedError("meshctx-core required (private repo)")


class SessionResumeEngine:
    """Engine for saving and resuming sessions using file-based storage."""
    def __init__(self, storage):
        raise NotImplementedError("meshctx-core required (private repo)")

    def _session_path(self, session_id):
        raise NotImplementedError("meshctx-core required (private repo)")

    def save(self, session_id, data):
        """Save session data to disk."""
        raise NotImplementedError("meshctx-core required (private repo)")

    def resume(self, session_id):
        """Resume a session. Returns session data dict or None if not found."""
        raise NotImplementedError("meshctx-core required (private repo)")

    def list_recent(self, limit):
        """List up to `limit` most recently modified sessions."""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_stats(self):
        """Return statistics about stored sessions."""
        raise NotImplementedError("meshctx-core required (private repo)")


class _SessionResume:
    def resume(self, *a, **kw):
        raise NotImplementedError("meshctx-core required (private repo)")

    def stats(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    def detect_previous_session(self, **kw):
        """检测是否存在上次会话存档"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def restore(self, session_id, **kw):
        """恢复指定会话"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def apply_to_kernel(self, kernel, **kw):
        """将会话上下文注入内核"""
        raise NotImplementedError("meshctx-core required (private repo)")


def get_session_resume():
    raise NotImplementedError("meshctx-core required (private repo)")

