"""Crypto — 开源版 (降级)"""
import base64, hashlib

def encrypt_key(key: str, password: str = None) -> str:
    """开源版: 简单混淆，非安全加密"""
    return base64.b64encode(key.encode()).decode()

def decrypt_key(encrypted: str, password: str = None) -> str:
    """开源版: 解混淆"""
    try:
        return base64.b64decode(encrypted.encode()).decode()
    except:
        return encrypted
