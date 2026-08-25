"""meshctx crypto — 加解密与密钥管理 (开源真实实现)

- encrypt_key: 对称加密 API Key → "enc:<base64>"
- decrypt_key: 解密 "enc:" (Fernet/XOR) 与 "b64:" (纯 base64 兼容旧格式)
- is_encrypted: 判断是否密文 (enc:/b64: 前缀)

密钥来源 (优先级): 环境变量 MESHCTX_CRYPTO_KEY → ~/.meshctx/key 文件
(不存在则自动生成) → 机器标识 (hostname+user) 派生。

加密后端: cryptography.fernet 可用时优先 (requirements.txt 已声明);
不可用时降级为 hashlib 派生密钥 + XOR + base64 (纯 stdlib)。

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("meshctx.crypto")

_KEY_FILE = Path.home() / ".meshctx" / "key"
_ENC_PREFIX = "enc:"
_B64_PREFIX = "b64:"

_crypto_lock = threading.RLock()
_fernet = None
_fallback_key: Optional[bytes] = None
_fallback_used = False


# ═══════════════════════════════════════════════════════════
# 密钥管理
# ═══════════════════════════════════════════════════════════

def _machine_secret() -> bytes:
    """机器标识派生密钥 (hostname + user)。"""
    parts = []
    try:
        parts.append(socket.gethostname() or "")
    except Exception:  # noqa: BLE001
        parts.append("")
    parts.append(os.environ.get("USER") or os.environ.get("USERNAME") or "meshctx")
    parts.append(str(Path.home()))
    return ("|".join(parts)).encode("utf-8", errors="replace")


def _load_or_create_key_file() -> bytes:
    """读取 ~/.meshctx/key; 不存在则生成 32 字节随机密钥并落盘 (0600)。"""
    try:
        if _KEY_FILE.exists():
            data = _KEY_FILE.read_bytes()
            if data:
                return data
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = os.urandom(32)
        _KEY_FILE.write_bytes(data)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except Exception:  # noqa: BLE001 — Windows 无 chmod 语义
            pass
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning("密钥文件不可用 (%s), 回退机器标识派生密钥: %s", _KEY_FILE, e)
        return _machine_secret()


def _secret_key() -> bytes:
    env_key = os.environ.get("MESHCTX_CRYPTO_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8", errors="replace")
    return _load_or_create_key_file()


def _fernet_key() -> bytes:
    """Fernet 要求 32 字节 urlsafe base64 密钥 — 由 secret 的 SHA256 派生。"""
    return base64.urlsafe_b64encode(hashlib.sha256(_secret_key()).digest())


def _get_fernet():
    """获取或生成 Fernet (基于机器标识/环境变量/key 文件)。"""
    global _fernet
    with _crypto_lock:
        if _fernet is None:
            try:
                from cryptography.fernet import Fernet
                _fernet = Fernet(_fernet_key())
                global _fallback_used
                _fallback_used = False
            except Exception as e:  # noqa: BLE001
                logger.warning("cryptography 不可用, 降级 hashlib+XOR 加密: %s", e)
                _fernet = None
        return _fernet


# ═══════════════════════════════════════════════════════════
# XOR 降级加密 (纯 stdlib, 密码学强度低于 Fernet, 仅作离线兜底)
# ═══════════════════════════════════════════════════════════

def _xor_derive(data: bytes, secret: bytes, iv: bytes) -> bytes:
    key = hashlib.sha256(secret + iv).digest()
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i % len(key)]
    return bytes(out)


def _fallback_encrypt(plain: bytes) -> bytes:
    global _fallback_key
    with _crypto_lock:
        if _fallback_key is None:
            _fallback_key = _secret_key()
        secret = _fallback_key
    iv = os.urandom(16)
    return iv + _xor_derive(plain, secret, iv)


def _fallback_decrypt(token: bytes) -> bytes:
    global _fallback_key
    with _crypto_lock:
        if _fallback_key is None:
            _fallback_key = _secret_key()
        secret = _fallback_key
    if len(token) < 16:
        raise ValueError("密文长度不足")
    iv, body = token[:16], token[16:]
    return _xor_derive(body, secret, iv)


# ═══════════════════════════════════════════════════════════
# 对外 API
# ═══════════════════════════════════════════════════════════

def encrypt_key(key: str) -> str:
    """对称加密 API Key, 返回 "enc:<base64>" 密文。"""
    if key is None:
        raise ValueError("key 不能为 None")
    plain = str(key).encode("utf-8", errors="replace")
    fernet = _get_fernet()
    if fernet is not None:
        token = fernet.encrypt(plain)
        return _ENC_PREFIX + token.decode("ascii")
    token = _fallback_encrypt(plain)
    return _ENC_PREFIX + base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_key(key: str) -> str:
    """对称解密 API Key (支持 enc:/b64: 前缀; 明文原样返回)。"""
    if key is None:
        raise ValueError("key 不能为 None")
    value = str(key)
    if value.startswith(_ENC_PREFIX):
        payload = value[len(_ENC_PREFIX):]
        fernet = _get_fernet()
        if fernet is not None:
            try:
                # Fernet.decrypt 接收 base64 字符串 (内部自行解码)
                return fernet.decrypt(payload.encode("ascii")).decode("utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                logger.debug("Fernet 解密失败, 尝试 XOR 降级: %s", e)
        raw = base64.urlsafe_b64decode(payload.encode("ascii") + b"=" * (-len(payload) % 4))
        return _fallback_decrypt(raw).decode("utf-8", errors="replace")
    if value.startswith(_B64_PREFIX):
        # 兼容旧格式: b64: 为纯 base64 明文
        payload = value[len(_B64_PREFIX):]
        raw = base64.b64decode(payload.encode("ascii") + b"=" * (-len(payload) % 4))
        return raw.decode("utf-8", errors="replace")
    return value  # 明文


def is_encrypted(key: str) -> bool:
    if key is None:
        return False
    value = str(key)
    return value.startswith(_ENC_PREFIX) or value.startswith(_B64_PREFIX)


def _patched_safe_load(stream):
    """yaml.safe_load 包装: 加载后递归解密所有 enc:/b64: 字符串值。

    供 yaml 加载配置时自动解密 API Key 使用 (无调用方时安全 no-op)。
    """
    try:
        import yaml
        data = yaml.safe_load(stream)
    except Exception:  # noqa: BLE001
        raise
    return _decrypt_walk(data)


def _decrypt_walk(node):
    if isinstance(node, dict):
        return {k: _decrypt_walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_decrypt_walk(v) for v in node]
    if isinstance(node, str) and is_encrypted(node):
        try:
            return decrypt_key(node)
        except Exception as e:  # noqa: BLE001
            logger.debug("配置值解密失败, 原样保留: %s", e)
            return node
    return node


# ═══════════════════════════════════════════════════════════
# get_crypto 门面 (与 stub 的 __all__ 保持一致)
# ═══════════════════════════════════════════════════════════

class CryptoManager:
    """加解密门面对象。"""

    def __init__(self):
        pass

    def encrypt(self, key: str) -> str:
        return encrypt_key(key)

    def decrypt(self, key: str) -> str:
        return decrypt_key(key)

    def is_encrypted(self, key: str) -> bool:
        return is_encrypted(key)

    def get_fernet(self):
        return _get_fernet()


_crypto_manager: Optional[CryptoManager] = None


def get_crypto(*args, **kwargs) -> CryptoManager:
    """获取全局加解密门面 (单例)。"""
    global _crypto_manager
    with _crypto_lock:
        if _crypto_manager is None:
            _crypto_manager = CryptoManager()
        return _crypto_manager


__all__ = ["get_crypto", "encrypt_key", "decrypt_key", "is_encrypted"]
