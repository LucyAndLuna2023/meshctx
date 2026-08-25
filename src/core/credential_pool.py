"""
meshctx Credential Pool — 凭证管理与轮换
=========================================
管理多个API密钥池: 添加、获取、轮换、过期、加密存储。

存储:
  - 默认池文件: ~/.meshctx/credentials/pools.json (可用 $MESHCTX_CREDENTIALS_FILE 覆盖)
  - 加密: 优先 cryptography.fernet (密钥来自 $MESHCTX_CREDENTIAL_KEY 或本地密钥文件
    ~/.meshctx/credentials/.key, 0600 权限); cryptography 不可用时降级为
    base64 + 派生密钥混淆, 绝不将明文密钥落盘。

开源实现说明: 本文件为 meshctx 开源仓库中的真实实现 (取代原接口 stub)。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CREDENTIALS_FILE_ENV = "MESHCTX_CREDENTIALS_FILE"
CREDENTIAL_KEY_ENV = "MESHCTX_CREDENTIAL_KEY"

_STATUS_ACTIVE = 'active'
_STATUS_EXHAUSTED = 'exhausted'
_STATUS_REVOKED = 'revoked'


def _default_pool_file() -> str:
    env = os.environ.get(CREDENTIALS_FILE_ENV, "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.abspath(os.path.expanduser("~/.meshctx/credentials/pools.json"))


@dataclass
class PooledKey:
    """A single API key in a credential pool."""
    key: str = None
    provider: str = ''
    status: str = 'active'
    call_count: int = 0
    label: str = ''
    exhausted_reason: str = ''
    exhausted_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider,
            "status": self.status,
            "call_count": self.call_count,
            "label": self.label,
            "exhausted_reason": self.exhausted_reason,
            "exhausted_at": self.exhausted_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PooledKey':
        return cls(
            key=d.get("key"),
            provider=d.get("provider", ''),
            status=d.get("status", 'active'),
            call_count=int(d.get("call_count", 0)),
            label=d.get("label", ''),
            exhausted_reason=d.get("exhausted_reason", ''),
            exhausted_at=float(d.get("exhausted_at", 0.0) or 0.0),
        )


@dataclass
class PoolConfig:
    """Configuration for a credential pool."""
    provider: str = ''
    strategy: str = 'round_robin'
    keys: List[PooledKey] = field(default_factory=list)
    cooldown_seconds: int = 300
    _round_robin_index: int = field(default=0, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "strategy": self.strategy,
            "keys": [k.to_dict() for k in self.keys],
            "cooldown_seconds": self.cooldown_seconds,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PoolConfig':
        cfg = cls(
            provider=d.get("provider", ''),
            strategy=d.get("strategy", 'round_robin'),
            cooldown_seconds=int(d.get("cooldown_seconds", 300)),
        )
        for kd in d.get("keys", []):
            if isinstance(kd, dict):
                cfg.keys.append(PooledKey.from_dict(kd))
        return cfg


# ── 加密工具 ───────────────────────────────────────────────────────

def _crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _load_or_create_encryption_key() -> bytes:
    """获取加密密钥: 环境变量 > 本地密钥文件 (自动创建, 0600)"""
    env_key = os.environ.get(CREDENTIAL_KEY_ENV, "").strip()
    if env_key:
        try:
            return base64.urlsafe_b64decode(env_key.encode("ascii") + b"=" * (-len(env_key) % 4))
        except Exception:
            # 环境变量不是合法 base64 → 用 sha256 派生 (仍可用, 但非 Fernet 格式)
            return hashlib.sha256(env_key.encode("utf-8")).digest()

    key_path = Path(os.path.expanduser("~/.meshctx/credentials/.key"))
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.is_file():
            data = key_path.read_bytes()
            if len(data) >= 32:
                return data
        if _crypto_available():
            from cryptography.fernet import Fernet
            new_key = Fernet.generate_key()
        else:
            new_key = hashlib.sha256(
                f"meshctx-credential-pool-{os.path.expanduser('~')}-{time.time()}".encode("utf-8")
            ).digest()
        try:
            key_path.write_bytes(new_key)
            os.chmod(str(key_path), 0o600)
        except OSError:
            pass  # 写失败时仍使用内存密钥 (不落盘, 不影响本轮运行)
        return new_key
    except OSError:
        # 无法访问 home → 用进程级派生密钥
        return hashlib.sha256(
            f"meshctx-credential-pool-{os.path.expanduser('~')}-{os.getpid()}".encode("utf-8")
        ).digest()


class _Cipher:
    """统一加密接口: Fernet 优先, 降级 XOR+base64。"""

    def __init__(self, key: bytes):
        self._key = key
        self._fernet = None
        if not _crypto_available():
            return
        try:
            from cryptography.fernet import Fernet
            if len(key) == 44:
                # Fernet 密钥 (base64 文本形式)
                self._fernet = Fernet(key)
            elif len(key) == 32:
                # 原始 32 字节密钥 → base64 编码后构造 Fernet
                self._fernet = Fernet(base64.urlsafe_b64encode(key))
            else:
                k = hashlib.sha256(key).digest()
                self._fernet = Fernet(base64.urlsafe_b64encode(k))
        except Exception:
            # Fernet 构造失败 (如密钥无效) → 降级 XOR 混淆, 保持可用
            self._fernet = None

    def encrypt(self, data: bytes) -> bytes:
        if self._fernet is not None:
            return self._fernet.encrypt(data)
        return self._xor(data)

    def decrypt(self, data: bytes) -> bytes:
        if self._fernet is not None:
            from cryptography.fernet import InvalidToken
            try:
                return self._fernet.decrypt(data)
            except InvalidToken:
                # 可能是降级格式, 尝试 XOR
                try:
                    return self._xor(data)
                except Exception:
                    raise
        return self._xor(data)

    def _xor(self, data: bytes) -> bytes:
        """降级混淆: 派生密钥流 XOR + base64。非强加密, 仅避免明文落盘。"""
        stream = hashlib.sha256(self._key).digest()
        out = bytearray()
        for i, b in enumerate(data):
            out.append(b ^ stream[i % len(stream)])
            if (i + 1) % len(stream) == 0:
                stream = hashlib.sha256(stream + self._key).digest()
        return base64.b64encode(bytes(out))

    def _xor_decrypt(self, data: bytes) -> bytes:
        raw = base64.b64decode(data)
        stream = hashlib.sha256(self._key).digest()
        out = bytearray()
        for i, b in enumerate(raw):
            out.append(b ^ stream[i % len(stream)])
            if (i + 1) % len(stream) == 0:
                stream = hashlib.sha256(stream + self._key).digest()
        return bytes(out)


class CredentialPoolManager:
    """Manages multiple credential pools for different providers."""

    VALID_STRATEGIES = {'round_robin', 'least_used', 'random'}

    def __init__(self, pool_file: Optional[str] = None):
        self.pool_file = pool_file if pool_file is not None else _default_pool_file()
        self.pools: Dict[str, PoolConfig] = {}
        self._lock = threading.RLock()
        self._cipher = _Cipher(_load_or_create_encryption_key())
        self._load()

    # ── 查询 ────────────────────────────────────────────────
    def list_providers(self) -> List[str]:
        """List all provider names that have pools."""
        with self._lock:
            return list(self.pools.keys())

    def ensure_pool(self, provider: str) -> PoolConfig:
        """Get or create a pool for a provider."""
        with self._lock:
            if provider not in self.pools:
                self.pools[provider] = PoolConfig(provider=provider)
            return self.pools[provider]

    def set_strategy(self, provider: str, strategy: str) -> bool:
        """Set the key selection strategy for a provider's pool."""
        if strategy not in self.VALID_STRATEGIES:
            return False
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return False
            pool.strategy = strategy
            self._save()
            return True

    def add_key(self, provider: str, key: str, label: str = '') -> PooledKey:
        """Add a key to a provider's pool. Duplicate keys (same key value) are ignored."""
        with self._lock:
            pool = self.ensure_pool(provider)
            for existing in pool.keys:
                if existing.key == key:
                    return existing
            pk = PooledKey(key=key, provider=provider, label=label)
            pool.keys.append(pk)
            self._save()
            return pk

    def list_keys(self, provider: str) -> List[Dict[str, Any]]:
        """List all keys in a provider's pool as dicts."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return []
            return [k.to_dict() for k in pool.keys]

    def remove_key(self, provider: str, index: int) -> bool:
        """Remove a key by index from a provider's pool. Clears pool if last key."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return False
            if index < 0 or index >= len(pool.keys):
                return False
            pool.keys.pop(index)
            if not pool.keys:
                self.pools.pop(provider, None)
            self._save()
            return True

    def _get_active_keys(self, provider: str) -> List[PooledKey]:
        """Get active keys (not exhausted or recovered from cooldown)."""
        pool = self.pools.get(provider)
        if pool is None:
            return []
        now = time.time()
        active: List[PooledKey] = []
        for k in pool.keys:
            if k.status == _STATUS_ACTIVE:
                active.append(k)
            elif k.status == _STATUS_EXHAUSTED:
                cooldown = int(getattr(pool, "cooldown_seconds", 300) or 300)
                if k.exhausted_at and (now - k.exhausted_at) >= cooldown:
                    # 冷却结束 → 恢复 active
                    k.status = _STATUS_ACTIVE
                    k.exhausted_reason = ''
                    k.exhausted_at = 0.0
                    active.append(k)
        return active

    def get_key(self, provider: str) -> Optional[str]:
        """Get the next available key for a provider based on the pool strategy."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return None
            active = self._get_active_keys(provider)
            if not active:
                return None
            strategy = pool.strategy
            if strategy == 'round_robin':
                idx = int(getattr(pool, '_round_robin_index', 0) or 0)
                chosen = active[idx % len(active)]
                pool._round_robin_index = idx + 1
            elif strategy == 'least_used':
                chosen = min(active, key=lambda k: k.call_count)
            elif strategy == 'random':
                chosen = random.choice(active)
            else:
                chosen = active[0]
            chosen.call_count += 1
            self._save()
            return chosen.key

    def mark_exhausted(self, provider: str, key_value: str, reason: str = '') -> bool:
        """Mark a key as exhausted (e.g. rate limited)."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return False
            for k in pool.keys:
                if k.key == key_value:
                    k.status = _STATUS_EXHAUSTED
                    k.exhausted_reason = reason
                    k.exhausted_at = time.time()
                    self._save()
                    return True
            return False

    def mark_revoked(self, provider: str, key_value: str) -> bool:
        """Mark a key as revoked (permanently invalid)."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return False
            for k in pool.keys:
                if k.key == key_value:
                    k.status = _STATUS_REVOKED
                    k.exhausted_reason = 'revoked'
                    k.exhausted_at = time.time()
                    self._save()
                    return True
            return False

    def reset_key(self, provider: str, index: int) -> bool:
        """Reset a key's status back to active."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return False
            if index < 0 or index >= len(pool.keys):
                return False
            k = pool.keys[index]
            k.status = _STATUS_ACTIVE
            k.exhausted_reason = ''
            k.exhausted_at = 0.0
            self._save()
            return True

    def reset_provider(self, provider: str) -> int:
        """Reset all keys in a provider's pool to active. Returns count reset."""
        with self._lock:
            pool = self.pools.get(provider)
            if pool is None:
                return 0
            count = 0
            for k in pool.keys:
                if k.status != _STATUS_ACTIVE:
                    count += 1
                    k.status = _STATUS_ACTIVE
                    k.exhausted_reason = ''
                    k.exhausted_at = 0.0
            self._save()
            return count

    def clear_all(self):
        """Remove all pools and keys."""
        with self._lock:
            self.pools.clear()
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all pools."""
        with self._lock:
            total_keys = 0
            active = 0
            exhausted = 0
            revoked = 0
            total_calls = 0
            for pool in self.pools.values():
                total_keys += len(pool.keys)
                total_calls += sum(k.call_count for k in pool.keys)
                for k in pool.keys:
                    if k.status == _STATUS_ACTIVE:
                        active += 1
                    elif k.status == _STATUS_EXHAUSTED:
                        exhausted += 1
                    elif k.status == _STATUS_REVOKED:
                        revoked += 1
            return {
                "total_pools": len(self.pools),
                "total_keys": total_keys,
                "active_keys": active,
                "exhausted_keys": exhausted,
                "revoked_keys": revoked,
                "total_calls": total_calls,
                "pool_file": self.pool_file,
            }

    # ── 持久化 (加密) ───────────────────────────────────────
    def _save(self):
        """Save pools to disk (加密存储, 不落明文)."""
        data = {
            p.provider: p.to_dict()
            for p in self.pools.values()
        }
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            encrypted = self._cipher.encrypt(payload)
            pool_path = Path(self.pool_file)
            pool_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = pool_path.with_name(pool_path.name + ".tmp")
            tmp.write_bytes(encrypted)
            tmp.replace(pool_path)
        except OSError:
            # 无法写盘: 保持内存状态, 不抛 (后续 _save 重试)
            return

    def _load(self):
        """Load pools from disk."""
        pool_path = Path(self.pool_file)
        if not pool_path.is_file():
            return
        try:
            raw = pool_path.read_bytes()
        except OSError:
            return
        payload = None
        # 尝试解密
        try:
            payload = self._cipher.decrypt(raw)
        except Exception:
            payload = None
        if payload is None:
            # 兼容旧版明文 JSON: 读入后立即重写为加密格式
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            with self._lock:
                for provider, cfg_dict in data.items():
                    if isinstance(cfg_dict, dict):
                        cfg = PoolConfig.from_dict(cfg_dict)
                        cfg.provider = provider
                        self.pools[provider] = cfg
            self._save()  # 明文 → 立即加密重写
            return
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        with self._lock:
            for provider, cfg_dict in data.items():
                if isinstance(cfg_dict, dict):
                    cfg = PoolConfig.from_dict(cfg_dict)
                    cfg.provider = provider
                    self.pools[provider] = cfg


# ── 单例 ─────────────────────────────────────────────────────────
_pool_manager: Optional[CredentialPoolManager] = None
_pool_lock = threading.Lock()


def get_credential_pool() -> CredentialPoolManager:
    """Get or create the global CredentialPoolManager singleton."""
    global _pool_manager
    with _pool_lock:
        if _pool_manager is None:
            _pool_manager = CredentialPoolManager()
        return _pool_manager


def reset_credential_pool():
    """Reset the global CredentialPoolManager singleton."""
    global _pool_manager
    with _pool_lock:
        _pool_manager = None


__all__ = [
    "PooledKey", "PoolConfig", "CredentialPoolManager",
    "list_providers", "ensure_pool", "set_strategy", "add_key",
    "list_keys", "remove_key", "get_key", "mark_exhausted",
    "mark_revoked", "reset_key", "reset_provider", "clear_all",
    "get_stats", "get_credential_pool", "reset_credential_pool",
]
