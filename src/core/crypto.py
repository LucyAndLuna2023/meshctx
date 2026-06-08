"""
meshctx v1.8 — API Key 加密存储
跨平台: Windows/Linux/macOS 统一 Fernet 加密
"""
import os
import base64
import hashlib
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False


def _derive_key() -> bytes:
    """从机器特征派生加密密钥 (hostname+username+固定盐)"""
    hostname = os.uname().nodename if hasattr(os, 'uname') else os.environ.get('COMPUTERNAME', 'localhost')
    username = os.environ.get('USER', os.environ.get('USERNAME', 'meshctx'))
    seed = f"{hostname}:{username}:meshctx-v1.8-salt"
    key = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(key)


def encrypt_key(plaintext: str) -> str:
    """加密API Key"""
    if not plaintext:
        return plaintext
    if _HAS_FERNET:
        f = Fernet(_derive_key())
        encrypted = f.encrypt(plaintext.encode())
        return "enc:" + base64.urlsafe_b64encode(encrypted).decode()
    else:
        # Fallback: base64 (obfuscation only)
        return "b64:" + base64.b64encode(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """解密API Key — 支持多层b64编码"""
    if not ciphertext:
        return ciphertext
    result = ciphertext
    # 递归解码b64，最多5层
    for _ in range(5):
        if result.startswith("b64:"):
            try:
                result = base64.b64decode(result[4:]).decode()
            except Exception:
                break
        else:
            break
    # enc: 格式只解一次
    if result.startswith("enc:") and _HAS_FERNET:
        try:
            f = Fernet(_derive_key())
            encrypted = base64.urlsafe_b64decode(result[4:])
            return f.decrypt(encrypted).decode()
        except Exception:
            pass
    return result


def is_encrypted(value: str) -> bool:
    """检查值是否已加密"""
    return value.startswith("enc:") or value.startswith("b64:")
