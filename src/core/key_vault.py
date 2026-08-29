#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Key Vault — 客户大模型 API Key 加密存储 (2026-08-28)

现状: API Key 明文存 ~/.meshctx/.env / config.yaml (任何可读该目录的进程可见)。
本模块: AES-256-GCM 加密 at rest, 运行时解密 at use。

设计:
- 主密钥: 机器指纹(hostname+MAC) + MESHCTX_MASTER_KEY(可选用户密钥) → PBKDF2-HMAC-SHA256 → AES-256
- 加密: AES-256-GCM (随机 nonce + 认证 tag, 防篡改)
- 存储: ~/.meshctx/key_vault.json  {provider: {ct, nonce, tag, created}}
- 兼容: 明文 .env 读取保留 (未迁移的 key 仍可用, 新保存的 key 加密)

依赖: cryptography (已装)
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("meshctx.keyvault")

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    _CRYPTO = True
except ImportError:
    _CRYPTO = False
    logger.warning("cryptography 未安装 — Key Vault 加密不可用, 回退明文存储")

VAULT_PATH = Path.home() / ".meshctx" / "key_vault.json"
_DEFAULT_SALT = b"meshctx-keyvault-v1"   # 旧格式兼容 (无随机 salt 时)
_ITERS = 200_000


def _machine_fingerprint() -> bytes:
    """机器指纹: hostname + 首个 MAC + 用户名 (派生主密钥用, 不存储)。"""
    parts = [socket.gethostname() or "unknown"]
    try:
        import uuid as _uuid
        mac = _uuid.getnode()
        parts.append(str(mac))
    except Exception:
        pass
    parts.append(os.environ.get("USER", os.environ.get("USERNAME", "user")))
    return "|".join(parts).encode()


def _master_key(salt: bytes = None) -> bytes:
    """主密钥: 机器指纹/用户密钥 + 随机 salt → PBKDF2-HMAC-SHA256 → 32 字节。
    002meshctx 建议1: 随机 salt (vault 落盘), 防固定盐离线暴力。"""
    user_secret = os.environ.get("MESHCTX_MASTER_KEY", "").encode() or _machine_fingerprint()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt or _DEFAULT_SALT, iterations=_ITERS)
    return kdf.derive(user_secret)


def _random_salt() -> bytes:
    return os.urandom(16)


def _key_available() -> bool:
    return _CRYPTO


class KeyVault:
    """加密存储: provider/name → 加密的 secret。线程安全。"""

    def __init__(self, path: str = ""):
        self._lock = threading.Lock()
        self._path = Path(path or VAULT_PATH)
        self._salt: bytes = b""
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                # 002meshctx 建议1: 随机 salt 落盘 (旧 vault 无 salt → 默认兼容)
                if data.get("salt"):
                    self._salt = base64.b64decode(data["salt"])
                # 002codex P1: 旧格式(26ddcdd) 是平铺 {name:{...}} — 无 'entries' 键时整个 dict 视为 entries
                self._data = data.get("entries", {}) if "entries" in data else data
        except Exception as e:
            logger.warning(f"KeyVault 加载失败: {e}")

    def _save(self):
        """原子写 (tmp + os.replace, 002meshctx 建议4: 防崩溃损坏)。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._salt:
                self._salt = _random_salt()
            payload = {"salt": base64.b64encode(self._salt).decode(),
                       "entries": self._data}
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            try:  # P3: tmp 先 chmod (防 replace 前 0644 窗口)
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            os.replace(tmp, self._path)
        except Exception as e:
            logger.warning(f"KeyVault 保存失败: {e}")

    def encrypt(self, name: str, secret: str) -> bool:
        """加密存储一个 secret。返回是否成功。"""
        if not _key_available():
            return False  # 无 cryptography → 调用方回退明文
        try:
            if not self._salt:
                self._salt = _random_salt()
            key = _master_key(self._salt)
            nonce = os.urandom(12)
            ct = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), b"meshctx-keyvault")
            with self._lock:
                self._data[name] = {
                    "ct": base64.b64encode(ct).decode(),
                    "nonce": base64.b64encode(nonce).decode(),
                    "created": time.time(),
                }
                self._save()
            return True
        except Exception as e:
            logger.error(f"KeyVault 加密失败 {name}: {e}")
            return False

    def decrypt(self, name: str) -> Optional[str]:
        """解密读取 secret。不存在/解密失败返回 None。"""
        if not _key_available():
            return None
        with self._lock:
            entry = self._data.get(name)
        if not entry:
            return None
        try:
            key = _master_key(self._salt or _DEFAULT_SALT)
            ct = base64.b64decode(entry["ct"])
            nonce = base64.b64decode(entry["nonce"])
            plain = AESGCM(key).decrypt(nonce, ct, b"meshctx-keyvault")
            return plain.decode("utf-8")
        except Exception as e:
            logger.error(f"KeyVault 解密失败 {name}: {e}")
            return None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._data

    def names(self) -> list:
        with self._lock:
            return list(self._data.keys())

    def remove(self, name: str) -> bool:
        with self._lock:
            if name in self._data:
                del self._data[name]
                self._save()
                return True
        return False


_default: Optional[KeyVault] = None


def get_vault() -> KeyVault:
    global _default
    if _default is None:
        _default = KeyVault()
    return _default


def reset_vault(path: str = "") -> KeyVault:
    global _default
    _default = KeyVault(path=path)
    return _default


def encrypt_secret(name: str, secret: str) -> bool:
    """加密保存 (优先 vault; cryptography 不可用返回 False)。"""
    if not secret:
        return False
    vault = get_vault()
    if vault.encrypt(name, secret):
        return True
    # 回退: 无 cryptography → 写 .env (明文, 保持兼容)
    try:
        env_path = Path.home() / ".meshctx" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        key_line = f"{name}={secret}"
        new_lines = [ln for ln in lines if not ln.startswith(f"{name}=")]
        new_lines.append(key_line)
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def get_secret(name: str) -> Optional[str]:
    """读取 secret: vault 优先 → .env 明文兼容。"""
    vault = get_vault()
    dec = vault.decrypt(name)
    if dec is not None:
        return dec
    # .env 兼容 (旧明文 key 迁移前仍可用)
    try:
        env_path = Path.home() / ".meshctx" / ".env"
        if env_path.exists():
            for ln in env_path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln.startswith(name + "="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def vault_status() -> Dict[str, Any]:
    """状态: 加密可用性 + 已存条目。"""
    vault = get_vault()
    return {"crypto_available": _key_available(),
            "master_key_source": "MESHCTX_MASTER_KEY" if os.environ.get("MESHCTX_MASTER_KEY") else "machine-fingerprint",
            "encrypted_entries": vault.names(),
            "vault_path": str(vault._path),
            "recommendation": "建议设置 MESHCTX_MASTER_KEY 环境变量增强主密钥 (可选)"}
