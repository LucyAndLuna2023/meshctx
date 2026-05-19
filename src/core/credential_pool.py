"""
MeshCtx Credential Pool — Multi-Key Rotation
=============================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Provides credential pooling with automatic key rotation across multiple
API keys per provider. Supports round-robin, least-used, and random
rotation strategies with automatic exhaustion detection.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import json
import os
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

# ── Data Model ──────────────────────────────────────────────


@dataclass
class PooledKey:
    """A single API key in a credential pool."""
    key: str
    provider: str
    label: str = ""
    status: str = "active"  # active, exhausted, rate_limited, revoked
    call_count: int = 0
    last_used: float = 0.0
    last_error: str = ""
    exhausted_at: float = 0.0
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "PooledKey":
        return cls(**{k: d.get(k, v.default if v.default is not v.default else "")
                       for k, v in cls.__dataclass_fields__.items()
                       if k in d or v.default is not v.default})


@dataclass
class PoolConfig:
    """Configuration for a provider's credential pool."""
    provider: str
    strategy: str = "round_robin"  # round_robin, least_used, random
    max_retries: int = 3
    cooldown_seconds: int = 300  # 5 min before retrying exhausted key
    keys: List[PooledKey] = field(default_factory=list)
    _round_robin_idx: int = field(default=0, repr=False)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["keys"] = [k.to_dict() for k in self.keys]
        d.pop("_round_robin_idx", None)
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "PoolConfig":
        keys = [PooledKey.from_dict(k) for k in d.pop("keys", [])]
        return cls(**d, keys=keys)


# ── Pool Manager ────────────────────────────────────────────


class CredentialPoolManager:
    """Manages multi-key credential pools with automatic rotation.

    Usage:
        pool = get_credential_pool()
        key = pool.get_key("deepseek")
        # ... make API call ...
        if rate_limited:
            pool.mark_exhausted("deepseek", key, "429 Too Many Requests")
            key = pool.get_key("deepseek")  # auto-rotates
    """

    _instance: Optional["CredentialPoolManager"] = None
    _lock: Lock = Lock()

    def __init__(self, pool_file: str = ""):
        self.pool_file = Path(pool_file) if pool_file else self._default_pool_path()
        self.pools: Dict[str, PoolConfig] = {}
        self._load()

    @staticmethod
    def _default_pool_path() -> Path:
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        return home / "credential_pools.json"

    # ── Persistence ─────────────────────────────────────

    def _load(self):
        """Load pools from JSON file."""
        if self.pool_file.exists():
            try:
                data = json.loads(self.pool_file.read_text())
                for prov, cfg in data.get("pools", {}).items():
                    self.pools[prov] = PoolConfig.from_dict(cfg)
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self):
        """Save pools to JSON file (atomic write)."""
        self.pool_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.pool_file.with_suffix(".tmp")
        data = {
            "version": 1,
            "updated_at": time.time(),
            "pools": {prov: cfg.to_dict() for prov, cfg in self.pools.items()},
        }
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(self.pool_file)

    # ── Pool Management ─────────────────────────────────

    def ensure_pool(self, provider: str, strategy: str = "round_robin") -> PoolConfig:
        """Get or create a pool for a provider."""
        if provider not in self.pools:
            self.pools[provider] = PoolConfig(provider=provider, strategy=strategy)
            self._save()
        return self.pools[provider]

    def add_key(self, provider: str, key: str, label: str = "") -> PooledKey:
        """Add an API key to the provider's pool."""
        with self._lock:
            pool = self.ensure_pool(provider)
            # Don't add duplicate keys
            for existing in pool.keys:
                if existing.key == key:
                    return existing
            pk = PooledKey(key=key, provider=provider, label=label)
            pool.keys.append(pk)
            self._save()
            return pk

    def remove_key(self, provider: str, index: int) -> bool:
        """Remove a key by index from the pool."""
        with self._lock:
            pool = self.pools.get(provider)
            if not pool or index < 0 or index >= len(pool.keys):
                return False
            pool.keys.pop(index)
            if not pool.keys:
                del self.pools[provider]
            self._save()
            return True

    def list_keys(self, provider: str = "") -> List[Dict]:
        """List all keys, optionally filtered by provider."""
        result = []
        providers = [provider] if provider and provider in self.pools else list(self.pools.keys())
        for prov in providers:
            pool = self.pools.get(prov)
            if pool:
                for i, k in enumerate(pool.keys):
                    d = k.to_dict()
                    d["index"] = i
                    d["strategy"] = pool.strategy
                    result.append(d)
        return result

    def list_providers(self) -> List[str]:
        """List all providers with pools."""
        return list(self.pools.keys())

    # ── Key Rotation ─────────────────────────────────────

    def get_key(self, provider: str) -> Optional[str]:
        """Get the next available key using the configured strategy.

        Automatically skips exhausted keys that are still in cooldown.
        Returns None if no keys are available.
        """
        with self._lock:
            pool = self.pools.get(provider)
            if not pool or not pool.keys:
                return None

            # Collect available keys
            now = time.time()
            available = [
                (i, k) for i, k in enumerate(pool.keys)
                if k.status == "active" or
                   (k.status in ("exhausted", "rate_limited") and
                    now - k.exhausted_at > pool.cooldown_seconds)
            ]

            if not available:
                # All keys exhausted — try resetting the oldest exhausted
                oldest = min(pool.keys, key=lambda k: k.exhausted_at)
                if now - oldest.exhausted_at > pool.cooldown_seconds * 2:
                    oldest.status = "active"
                    oldest.exhausted_at = 0
                    self._save()
                    return self.get_key(provider)
                return None

            # Apply strategy
            if pool.strategy == "random":
                idx, chosen = random.choice(available)
            elif pool.strategy == "least_used":
                idx, chosen = min(available, key=lambda x: x[1].call_count)
            else:  # round_robin (default)
                # Find next round-robin index that's available
                start = pool._round_robin_idx % len(pool.keys)
                for offset in range(len(pool.keys)):
                    candidate_idx = (start + offset) % len(pool.keys)
                    for ai, ak in available:
                        if ai == candidate_idx:
                            idx, chosen = ai, ak
                            pool._round_robin_idx = (candidate_idx + 1) % len(pool.keys)
                            break
                    else:
                        continue
                    break
                else:
                    return None  # No available key found

            # Record usage
            chosen.call_count += 1
            chosen.last_used = now
            # Auto-reactivate if cooldown expired
            if chosen.status in ("exhausted", "rate_limited") and \
               now - chosen.exhausted_at > pool.cooldown_seconds:
                chosen.status = "active"
            self._save()
            return chosen.key

    def mark_exhausted(self, provider: str, key: str, error: str = "",
                       status: str = "exhausted") -> bool:
        """Mark a key as exhausted/rate-limited so it gets rotated out."""
        with self._lock:
            pool = self.pools.get(provider)
            if not pool:
                return False
            for k in pool.keys:
                if k.key == key:
                    k.status = status
                    k.exhausted_at = time.time()
                    k.last_error = error
                    self._save()
                    return True
            return False

    def mark_revoked(self, provider: str, key: str) -> bool:
        """Mark a key as revoked (permanently unusable)."""
        return self.mark_exhausted(provider, key, "revoked", "revoked")

    def reset_key(self, provider: str, index: int) -> bool:
        """Reset a key back to active status."""
        with self._lock:
            pool = self.pools.get(provider)
            if not pool or index < 0 or index >= len(pool.keys):
                return False
            pool.keys[index].status = "active"
            pool.keys[index].exhausted_at = 0
            pool.keys[index].last_error = ""
            self._save()
            return True

    def reset_provider(self, provider: str) -> int:
        """Reset all keys for a provider. Returns count of reset keys."""
        with self._lock:
            pool = self.pools.get(provider)
            if not pool:
                return 0
            count = 0
            for k in pool.keys:
                if k.status != "active":
                    k.status = "active"
                    k.exhausted_at = 0
                    k.last_error = ""
                    count += 1
            if count:
                self._save()
            return count

    def set_strategy(self, provider: str, strategy: str) -> bool:
        """Set the rotation strategy for a provider's pool."""
        valid = {"round_robin", "least_used", "random"}
        if strategy not in valid:
            return False
        pool = self.ensure_pool(provider)
        pool.strategy = strategy
        self._save()
        return True

    def get_stats(self, provider: str = "") -> Dict:
        """Get pool statistics."""
        pools_to_check = [provider] if provider else list(self.pools.keys())
        stats = {
            "total_pools": len(self.pools),
            "total_keys": 0,
            "active_keys": 0,
            "exhausted_keys": 0,
            "per_provider": {},
        }
        for prov in pools_to_check:
            pool = self.pools.get(prov)
            if not pool:
                continue
            ps = {"total": len(pool.keys), "active": 0, "exhausted": 0,
                  "rate_limited": 0, "revoked": 0, "strategy": pool.strategy}
            for k in pool.keys:
                stats["total_keys"] += 1
                if k.status == "active":
                    stats["active_keys"] += 1
                    ps["active"] += 1
                elif k.status == "exhausted":
                    stats["exhausted_keys"] += 1
                    ps["exhausted"] += 1
                elif k.status == "rate_limited":
                    ps["rate_limited"] += 1
                elif k.status == "revoked":
                    ps["revoked"] += 1
            stats["per_provider"][prov] = ps
        return stats

    def clear_all(self):
        """Remove all pools."""
        with self._lock:
            self.pools.clear()
            self._save()


# ── Singleton ───────────────────────────────────────────────

_global_pool: Optional[CredentialPoolManager] = None


def get_credential_pool() -> CredentialPoolManager:
    """Get or create the global credential pool manager."""
    global _global_pool
    if _global_pool is None:
        _global_pool = CredentialPoolManager()
    return _global_pool


def reset_credential_pool():
    """Reset the singleton (for testing)."""
    global _global_pool
    _global_pool = None
