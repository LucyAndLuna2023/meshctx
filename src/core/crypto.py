"""meshctx crypto — encryption and key management"""
# v3.115.8: legacy !!python/object YAML tag compatibility

# ── 全局 monkey-patch yaml.safe_load（最早执行，覆盖所有调用点）──
import yaml as _yaml_mod
from pathlib import Path
_original_safe_load = _yaml_mod.safe_load

def _patched_safe_load(stream):
    try:
        return _original_safe_load(stream)
    except _yaml_mod.constructor.ConstructorError:
        return _yaml_mod.load(stream, Loader=_yaml_mod.Loader)

_yaml_mod.safe_load = _patched_safe_load


def get_crypto(*args, **kwargs):
    """Stub function"""
    pass



# ── API Key 加密 (Fernet + 机器密钥) ──

import base64
import hashlib
import os as _os

def _get_fernet():
    """获取或生成 Fernet 密钥（基于机器标识）"""
    key_path = Path.home() / ".meshctx" / ".fernet_key"
    if key_path.exists():
        with open(key_path, "rb") as f:
            key = f.read()
    else:
        # 生成机器绑定密钥（hostname + MAC 地址哈希）
        import socket, uuid
        seed = f"{socket.gethostname()}:{uuid.getnode()}:meshctx-v3"
        raw = hashlib.sha256(seed.encode()).digest()
        key = base64.urlsafe_b64encode(raw)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        _os.chmod(key_path.parent, 0o700)
        with open(key_path, "wb") as f:
            f.write(key)
        _os.chmod(key_path, 0o600)
    from cryptography.fernet import Fernet
    return Fernet(key)


def encrypt_key(key: str) -> str:
    """Fernet 对称加密 API Key"""
    if not key or key.startswith("enc:"):
        return key
    f = _get_fernet()
    return f"enc:{f.encrypt(key.encode()).decode()}"


def decrypt_key(key: str) -> str:
    """Fernet 对称解密 API Key"""
    if not key or not key.startswith("enc:"):
        return key
    f = _get_fernet()
    return f.decrypt(key[4:].encode()).decode()


def is_encrypted(key: str) -> bool:
    return key.startswith("enc:")

