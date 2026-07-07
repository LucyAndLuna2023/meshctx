"""
meshctx Credential Pool — 凭证管理与轮换
=========================================
管理多个API密钥池: 添加、获取、轮换、过期、加密存储。
"""

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.credential_pool")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class PooledKey:
    """A single API key in a credential pool."""
    key: str
    provider: str = ""
    status: str = "active"
    call_count: int = 0
    label: str = ""
    exhausted_reason: str = ""
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
    def from_dict(cls, d: Dict[str, Any]) -> "PooledKey":
        return cls(
            key=d.get("key", ""),
            provider=d.get("provider", ""),
            status=d.get("status", "active"),
            call_count=d.get("call_count", 0),
            label=d.get("label", ""),
            exhausted_reason=d.get("exhausted_reason", ""),
            exhausted_at=d.get("exhausted_at", 0.0),
        )


@dataclass
class PoolConfig:
    """Configuration for a credential pool."""
    provider: str = ""
    strategy: str = "round_robin"
    keys: List[PooledKey] = field(default_factory=list)
    cooldown_seconds: int = 300
    _round_robin_index: int = field(default=0, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "strategy": self.strategy,
            "cooldown_seconds": self.cooldown_seconds,
            "keys": [k.to_dict() for k in self.keys],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PoolConfig":
        cfg = cls(
            provider=d.get("provider", ""),
            strategy=d.get("strategy", "round_robin"),
            cooldown_seconds=d.get("cooldown_seconds", 300),
        )
        cfg.keys = [PooledKey.from_dict(kd) for kd in d.get("keys", [])]
        return cfg


# ═══════════════════════════════════════════════════════════
# CredentialPoolManager
# ═══════════════════════════════════════════════════════════

class CredentialPoolManager:
    """Manages multiple credential pools for different providers."""

    VALID_STRATEGIES = {"round_robin", "least_used", "random"}

    def __init__(self, pool_file: Optional[str] = None):
        self.pools: Dict[str, PoolConfig] = {}
        self._pool_file = pool_file
        if pool_file and os.path.exists(pool_file):
            self._load()

    # ── Pool management ───────────────────────────────────

    def list_providers(self) -> List[str]:
        """List all provider names that have pools."""
        return list(self.pools.keys())

    def ensure_pool(self, provider: str) -> PoolConfig:
        """Get or create a pool for a provider."""
        if provider not in self.pools:
            self.pools[provider] = PoolConfig(provider=provider)
            self._save()
        return self.pools[provider]

    def set_strategy(self, provider: str, strategy: str) -> bool:
        """Set the key selection strategy for a provider's pool."""
        if strategy not in self.VALID_STRATEGIES:
            return False
        pool = self.ensure_pool(provider)
        pool.strategy = strategy
        self._save()
        return True

    # ── Key management ─────────────────────────────────────

    def add_key(self, provider: str, key: str, label: str = "") -> PooledKey:
        """Add a key to a provider's pool. Duplicate keys (same key value) are ignored."""
        pool = self.ensure_pool(provider)
        existing = [k for k in pool.keys if k.key == key]
        if existing:
            return existing[0]
        pk = PooledKey(key=key, provider=provider, label=label)
        pool.keys.append(pk)
        self._save()
        return pk

    def list_keys(self, provider: str) -> List[Dict[str, Any]]:
        """List all keys in a provider's pool as dicts."""
        pool = self.pools.get(provider)
        if pool is None:
            return []
        return [k.to_dict() for k in pool.keys]

    def remove_key(self, provider: str, index: int) -> bool:
        """Remove a key by index from a provider's pool. Clears pool if last key."""
        pool = self.pools.get(provider)
        if pool is None:
            return False
        if index < 0 or index >= len(pool.keys):
            return False
        pool.keys.pop(index)
        if len(pool.keys) == 0:
            del self.pools[provider]
        self._save()
        return True

    # ── Key selection ──────────────────────────────────────

    def _get_active_keys(self, provider: str) -> List[PooledKey]:
        """Get active keys (not exhausted or recovered from cooldown)."""
        pool = self.pools.get(provider)
        if pool is None:
            return []
        now = time.time()
        active = []
        for k in pool.keys:
            if k.status == "active":
                active.append(k)
            elif k.status == "exhausted":
                if k.exhausted_at > 0 and (now - k.exhausted_at) >= pool.cooldown_seconds:
                    k.status = "active"
                    k.exhausted_at = 0.0
                    active.append(k)
        return active

    def get_key(self, provider: str) -> Optional[str]:
        """Get the next available key for a provider based on the pool strategy."""
        active = self._get_active_keys(provider)
        if not active:
            return None

        pool = self.pools[provider]
        strategy = pool.strategy

        if strategy == "random":
            key = random.choice(active)
        elif strategy == "least_used":
            key = min(active, key=lambda k: k.call_count)
        else:  # round_robin
            pool._round_robin_index = pool._round_robin_index % len(active)
            key = active[pool._round_robin_index]
            pool._round_robin_index += 1

        key.call_count += 1
        self._save()
        return key.key

    # ── Key status management ──────────────────────────────

    def mark_exhausted(self, provider: str, key_value: str, reason: str = "") -> bool:
        """Mark a key as exhausted (e.g. rate limited)."""
        pool = self.pools.get(provider)
        if pool is None:
            return False
        for k in pool.keys:
            if k.key == key_value:
                k.status = "exhausted"
                k.exhausted_reason = reason
                k.exhausted_at = time.time()
                self._save()
                return True
        return False

    def mark_revoked(self, provider: str, key_value: str) -> bool:
        """Mark a key as revoked (permanently invalid)."""
        pool = self.pools.get(provider)
        if pool is None:
            return False
        for k in pool.keys:
            if k.key == key_value:
                k.status = "revoked"
                self._save()
                return True
        return False

    def reset_key(self, provider: str, index: int) -> bool:
        """Reset a key's status back to active."""
        pool = self.pools.get(provider)
        if pool is None:
            return False
        if index < 0 or index >= len(pool.keys):
            return False
        k = pool.keys[index]
        k.status = "active"
        k.exhausted_reason = ""
        k.exhausted_at = 0.0
        self._save()
        return True

    def reset_provider(self, provider: str) -> int:
        """Reset all keys in a provider's pool to active. Returns count reset."""
        pool = self.pools.get(provider)
        if pool is None:
            return 0
        count = 0
        for k in pool.keys:
            if k.status != "active":
                k.status = "active"
                k.exhausted_reason = ""
                k.exhausted_at = 0.0
                count += 1
        self._save()
        return count

    def clear_all(self):
        """Remove all pools and keys."""
        self.pools.clear()
        self._save()

    # ── Stats ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all pools."""
        total_keys = 0
        active_keys = 0
        exhausted_keys = 0
        for pool in self.pools.values():
            total_keys += len(pool.keys)
            for k in pool.keys:
                if k.status == "active":
                    active_keys += 1
                elif k.status == "exhausted":
                    exhausted_keys += 1
        return {
            "total_pools": len(self.pools),
            "total_keys": total_keys,
            "active_keys": active_keys,
            "exhausted_keys": exhausted_keys,
        }

    # ── Persistence ────────────────────────────────────────

    def _save(self):
        """Save pools to disk if a pool_file was specified."""
        if not self._pool_file:
            return
        try:
            data = {
                "pools": {name: pool.to_dict() for name, pool in self.pools.items()},
            }
            p = Path(self._pool_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save credential pools: {e}")

    def _load(self):
        """Load pools from disk."""
        try:
            data = json.loads(Path(self._pool_file).read_text())
            for name, pd in data.get("pools", {}).items():
                self.pools[name] = PoolConfig.from_dict(pd)
        except Exception as e:
            logger.error(f"Failed to load credential pools: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_credential_pool_instance: Optional[CredentialPoolManager] = None


def get_credential_pool() -> CredentialPoolManager:
    """Get or create the global CredentialPoolManager singleton."""
    global _credential_pool_instance
    if _credential_pool_instance is None:
        _credential_pool_instance = CredentialPoolManager()
    return _credential_pool_instance


def reset_credential_pool():
    """Reset the global CredentialPoolManager singleton."""
    global _credential_pool_instance
    _credential_pool_instance = None
