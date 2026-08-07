"""meshctx crypto — encryption and key management"""
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
def _patched_safe_load(stream):
    raise NotImplementedError("meshctx-core required (private repo)")

def get_crypto(*args, **kwargs):
    """Stub function"""
    raise NotImplementedError("meshctx-core required (private repo)")

def _get_fernet():
    """获取或生成 Fernet 密钥（基于机器标识）"""
    raise NotImplementedError("meshctx-core required (private repo)")

def encrypt_key(key: str) -> str:
    """Fernet 对称加密 API Key"""
    raise NotImplementedError("meshctx-core required (private repo)")

def decrypt_key(key: str) -> str:
    """Fernet 对称解密 API Key"""
    raise NotImplementedError("meshctx-core required (private repo)")

def is_encrypted(key: str) -> bool:
    raise NotImplementedError("meshctx-core required (private repo)")

