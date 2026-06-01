"""
meshctx v3.90 — Rate Limiter Middleware (令牌桶限流)

Token bucket algorithm with IP/API Key tiered rate limiting.
Returns 429 + Retry-After header when limits exceeded.
Includes real-time statistics dashboard.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Any
from enum import Enum


class RateLimitTier(Enum):
    """Rate limit tiers for different client levels"""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ADMIN = "admin"


# Default tier configurations: (capacity, refill_rate_per_second)
DEFAULT_TIER_CONFIGS = {
    RateLimitTier.FREE: (60, 1.0),       # 60 burst, 1 req/s sustained
    RateLimitTier.BASIC: (300, 5.0),     # 300 burst, 5 req/s
    RateLimitTier.PREMIUM: (1000, 20.0),  # 1000 burst, 20 req/s
    RateLimitTier.ADMIN: (5000, 100.0),  # 5000 burst, 100 req/s
}


@dataclass
class TokenBucket:
    """Single token bucket for one client"""
    capacity: float
    refill_rate: float
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)
    requests_allowed: int = 0
    requests_denied: int = 0
    last_denied_time: float = 0.0

    def __post_init__(self):
        self.tokens = self.capacity

    def refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> Tuple[bool, float]:
        """Try to consume tokens. Returns (allowed, retry_after_seconds)"""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            self.requests_allowed += 1
            return True, 0.0
        else:
            self.requests_denied += 1
            self.last_denied_time = time.monotonic()
            needed = tokens - self.tokens
            retry_after = needed / max(self.refill_rate, 0.001)
            return False, retry_after

    def stats(self) -> Dict[str, Any]:
        """Return bucket statistics"""
        self.refill()
        return {
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
            "tokens_available": round(self.tokens, 2),
            "requests_allowed": self.requests_allowed,
            "requests_denied": self.requests_denied,
        }


@dataclass
class RateLimitResult:
    """Result of a rate limit check"""
    allowed: bool
    retry_after: float  # seconds
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    message: str = ""

    @property
    def is_limited(self) -> bool:
        return not self.allowed


class RateLimiter:
    """
    v3.90 Rate Limiter — Token bucket algorithm with tiered rate limiting.

    Supports IP-based and API Key-based rate limiting with configurable tiers.
    Provides real-time statistics dashboard.
    """

    def __init__(
        self,
        tier_configs: Optional[Dict[RateLimitTier, Tuple[int, float]]] = None,
    ):
        self.tier_configs = tier_configs or dict(DEFAULT_TIER_CONFIGS)
        self._lock = threading.RLock()
        self._buckets: Dict[str, TokenBucket] = {}
        self._api_key_tiers: Dict[str, RateLimitTier] = {}
        self._total_allowed = 0
        self._total_denied = 0
        self._start_time = time.monotonic()

    # ── Configuration ────────────────────────────────────────────

    def set_tier_config(
        self, tier: RateLimitTier, capacity: int, refill_rate: float
    ) -> None:
        """Configure or override a rate limit tier"""
        self.tier_configs[tier] = (capacity, refill_rate)

    def register_api_key(self, api_key: str, tier: RateLimitTier) -> None:
        """Register an API key with a specific tier"""
        self._api_key_tiers[api_key] = tier

    def set_ip_tier(self, ip: str, tier: RateLimitTier) -> None:
        """Assign a specific tier to an IP"""
        with self._lock:
            self._api_key_tiers[f"ip:{ip}"] = tier

    # ── Core Logic ───────────────────────────────────────────────

    def _get_or_create_bucket(self, key: str, tier: RateLimitTier) -> TokenBucket:
        """Get existing bucket or create a new one for the key"""
        if key not in self._buckets:
            capacity, refill_rate = self.tier_configs.get(
                tier, self.tier_configs[RateLimitTier.FREE]
            )
            self._buckets[key] = TokenBucket(
                capacity=float(capacity), refill_rate=float(refill_rate)
            )
        return self._buckets[key]

    def _resolve_tier(
        self, ip: str, api_key: Optional[str] = None
    ) -> Tuple[RateLimitTier, str]:
        """Resolve the tier and bucket key for a request"""
        if api_key and api_key in self._api_key_tiers:
            tier = self._api_key_tiers[api_key]
            return tier, f"apikey:{api_key}"
        # Check for IP-specific tier
        ip_key = f"ip:{ip}"
        if ip_key in self._api_key_tiers:
            tier = self._api_key_tiers[ip_key]
            return tier, ip_key
        # Default: IP-based with FREE tier
        return RateLimitTier.FREE, f"ip:{ip}"

    def check(
        self, ip: str, api_key: Optional[str] = None, cost: float = 1.0
    ) -> RateLimitResult:
        """
        Check if a request is rate-limited.

        Args:
            ip: Client IP address
            api_key: Optional API key for tiered limiting
            cost: Token cost of this request (default 1.0)

        Returns:
            RateLimitResult with allowed status and headers
        """
        tier, bucket_key = self._resolve_tier(ip, api_key)

        with self._lock:
            bucket = self._get_or_create_bucket(bucket_key, tier)
            allowed, retry_after = bucket.consume(cost)

            if allowed:
                self._total_allowed += 1
                return RateLimitResult(
                    allowed=True,
                    retry_after=0.0,
                    headers={
                        "X-RateLimit-Limit": str(int(bucket.capacity)),
                        "X-RateLimit-Remaining": str(int(bucket.tokens)),
                        "X-RateLimit-Tier": tier.value,
                    },
                )
            else:
                self._total_denied += 1
                retry_after_int = int(retry_after) + 1
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry_after,
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after_int),
                        "X-RateLimit-Limit": str(int(bucket.capacity)),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Tier": tier.value,
                    },
                    message=(
                        f"Rate limit exceeded (tier: {tier.value}). "
                        f"Retry after {retry_after_int}s"
                    ),
                )

    def is_allowed(self, ip: str, api_key: Optional[str] = None) -> bool:
        """Simple boolean check: is this request allowed?"""
        return self.check(ip, api_key).allowed

    # ── Statistics Dashboard ─────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Get overall rate limiter statistics"""
        uptime = time.monotonic() - self._start_time
        with self._lock:
            total = self._total_allowed + self._total_denied
            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": total,
                "total_allowed": self._total_allowed,
                "total_denied": self._total_denied,
                "deny_rate": (
                    f"{self._total_denied / max(total, 1) * 100:.1f}%"
                ),
                "avg_rps": round(total / max(uptime, 0.001), 2),
                "active_clients": len(self._buckets),
            }

    def client_stats(self, bucket_key: Optional[str] = None) -> Dict[str, Any]:
        """Get per-client statistics. If no key specified, returns all."""
        with self._lock:
            if bucket_key:
                if bucket_key in self._buckets:
                    return {bucket_key: self._buckets[bucket_key].stats()}
                return {}
            return {k: v.stats() for k, v in self._buckets.items()}

    def dashboard(self) -> Dict[str, Any]:
        """Full real-time statistics dashboard"""
        with self._lock:
            return {
                "overview": self.stats(),
                "clients": self.client_stats(),
                "tiers": {
                    tier.value: {
                        "capacity": cap,
                        "refill_rate": rate,
                    }
                    for tier, (cap, rate) in self.tier_configs.items()
                },
                "api_key_count": len(self._api_key_tiers),
            }

    # ── Maintenance ──────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all buckets and counters"""
        with self._lock:
            self._buckets.clear()
            self._total_allowed = 0
            self._total_denied = 0
            self._start_time = time.monotonic()

    def cleanup_stale(self, max_age_seconds: float = 3600.0) -> int:
        """Remove stale buckets inactive for more than max_age_seconds"""
        now = time.monotonic()
        removed = 0
        with self._lock:
            stale_keys = [
                k
                for k, b in self._buckets.items()
                if now - b.last_refill > max_age_seconds
            ]
            for k in stale_keys:
                del self._buckets[k]
                removed += 1
        return removed


# ── Singleton ────────────────────────────────────────────────────

_rate_limiter: Optional[RateLimiter] = None
_lock_singleton = threading.Lock()


def get_rate_limiter(
    tier_configs: Optional[Dict[RateLimitTier, Tuple[int, float]]] = None,
) -> RateLimiter:
    """Get or create the global RateLimiter singleton"""
    global _rate_limiter
    if _rate_limiter is None:
        with _lock_singleton:
            if _rate_limiter is None:
                _rate_limiter = RateLimiter(tier_configs=tier_configs)
    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global RateLimiter singleton"""
    global _rate_limiter
    with _lock_singleton:
        _rate_limiter = None
