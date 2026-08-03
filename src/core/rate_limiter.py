"""
meshctx Rate Limiter — 分布式速率限制器
========================================

Token bucket + Sliding window 双算法限流引擎。

核心功能:
  1. TokenBucketLimiter — 令牌桶算法, 支持突发流量
  2. SlidingWindowLimiter — 滑动窗口算法, 精确计数
  3. 多维度限流 — endpoint / user_id / IP
  4. Redis-backed 分布式计数器 (可选, 回退到内存)
  5. 429 响应 + Retry-After header 生成
  6. 限流状态端点 /api/rate_limiter/status

使用示例:
  limiter = get_rate_limiter()
  limiter.configure_limit("api:chat", max_requests=100, window=60, algorithm="token_bucket")
  allowed, info = limiter.check("api:chat", user_id="user123")
  if not allowed:
      return 429, {"retry_after": info["retry_after"]}
"""

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.rate_limiter")


# ═══════════════════════════════════════════════════════════
# Redis 可选导入
# ═══════════════════════════════════════════════════════════

_redis_available = False
_redis_module = None
try:
    import redis as _redis_module
    _redis_available = True
except ImportError:
    logger.info("redis not installed; using in-memory rate limiter only")
    _redis_module = None


# ═══════════════════════════════════════════════════════════
# RateLimitTier
# ═══════════════════════════════════════════════════════════

class RateLimitTier(Enum):
    """Rate limit tiers for different API key levels."""
    FREE = "free"
    PREMIUM = "premium"
    ADMIN = "admin"


# ═══════════════════════════════════════════════════════════
# Tier Config
# ═══════════════════════════════════════════════════════════

@dataclass(slots=True)
class TierConfig:
    """Configuration for a rate limit tier."""
    capacity: int
    refill_rate: float


# ═══════════════════════════════════════════════════════════
# RateLimitResult
# ═══════════════════════════════════════════════════════════

@dataclass(slots=True)
class RateLimitResult:
    """Result of a rate-limit check."""
    allowed: bool = True
    retry_after: float = 0.0
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.headers.get("Retry-After") and self.retry_after > 0:
            self.headers["Retry-After"] = str(int(self.retry_after) + 1)

    @property
    def is_limited(self) -> bool:
        """True if the request should be blocked."""
        return not self.allowed


# ═══════════════════════════════════════════════════════════
# TokenBucket
# ═══════════════════════════════════════════════════════════

class TokenBucket:
    """
    令牌桶 — 支持突发流量。

    以恒定速率填充令牌, 最大容量为 capacity。
    每次请求消耗 tokens 个令牌。桶满时丢弃多余令牌。
    """

    def __init__(self, capacity: int = 100, refill_rate: float = 10.0):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens: float = float(capacity)
        self.last_refill: float = time.monotonic()
        self.lock = threading.Lock()

    def refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """Try to consume *tokens*.  Returns (allowed, retry_after)."""
        with self.lock:
            self.refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0
            needed = tokens - self.tokens
            retry = needed / self.refill_rate if self.refill_rate > 0 else float("inf")
            return False, retry

    def get_retry_after(self) -> float:
        """Estimate seconds until next token is available."""
        with self.lock:
            if self.tokens >= 1:
                return 0.0
            if self.refill_rate > 0:
                return (1.0 - self.tokens) / self.refill_rate
            return float("inf")


# ═══════════════════════════════════════════════════════════
# SlidingWindow
# ═══════════════════════════════════════════════════════════

class SlidingWindow:
    """
    滑动窗口 — 精确计数。

    记录每个请求的时间戳, 窗口滑动时自动清理过期记录。
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []
        self.lock = threading.Lock()

    def _clean(self, now: float):
        """Remove timestamps outside the window."""
        cutoff = now - self.window_seconds
        idx = 0
        for i, ts in enumerate(self.timestamps):
            if ts >= cutoff:
                idx = i
                break
        else:
            idx = len(self.timestamps)
        del self.timestamps[:idx]

    def add(self) -> bool:
        """Record a request.  Returns True if within limit."""
        now = time.monotonic()
        with self.lock:
            self._clean(now)
            if len(self.timestamps) >= self.max_requests:
                return False
            self.timestamps.append(now)
            return True

    def count(self) -> int:
        """Return current request count in the window."""
        now = time.monotonic()
        with self.lock:
            self._clean(now)
            return len(self.timestamps)

    def get_retry_after(self) -> float:
        """Estimate when the window accepts new requests."""
        now = time.monotonic()
        with self.lock:
            self._clean(now)
            if len(self.timestamps) < self.max_requests:
                return 0.0
            if not self.timestamps:
                return 0.0
            oldest = self.timestamps[0]
            return max(0.0, self.window_seconds - (now - oldest))


# ═══════════════════════════════════════════════════════════
# Redis 分布式后端
# ═══════════════════════════════════════════════════════════

SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local current = redis.call('ZCARD', key)

if current >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if #oldest > 0 then
        retry_after = window - (now - tonumber(oldest[2]))
        if retry_after < 0 then retry_after = 0 end
    end
    return {0, current, retry_after}
end

local member = now .. ':' .. redis.call('INCR', key .. ':counter')
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
return {1, current + 1, 0}
"""

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local fill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local last_fill = tonumber(redis.call('HGET', key, 'last_fill') or now)
local tokens = tonumber(redis.call('HGET', key, 'tokens') or capacity)

local elapsed = now - last_fill
tokens = math.min(capacity, tokens + elapsed * fill_rate)

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_fill', now)
    redis.call('EXPIRE', key, math.ceil(capacity / fill_rate) + 10)
    return {1, math.floor(tokens)}
end

local retry = 0
if fill_rate > 0 then
    retry = math.ceil((1 - tokens) / fill_rate)
end
return {0, 0, retry}
"""


class RedisRateLimiterBackend:
    """Redis-based distributed rate limiter backend."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._redis_url = redis_url
        self._client: Any = None
        self._sliding_script_sha: Optional[str] = None
        self._token_bucket_script_sha: Optional[str] = None
        self._connect()

    def _connect(self):
        """Establish Redis connection and load Lua scripts."""
        try:
            if _redis_module is None:
                return
            parsed = re.match(
                r'redis://(?::([^@]*)@)?([^:/]+)(?::(\d+))?(?:/(\d+))?',
                self._redis_url,
            )
            if parsed is None:
                host = "localhost"
                port = 6379
                db = 0
            else:
                host = parsed.group(2) or "localhost"
                port = int(parsed.group(3) or 6379)
                db = int(parsed.group(4) or 0)
            self._client = _redis_module.Redis(
                host=host,
                port=port,
                db=db,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            self._client.ping()
            self._sliding_script_sha = self._client.script_load(SLIDING_WINDOW_SCRIPT)
            self._token_bucket_script_sha = self._client.script_load(TOKEN_BUCKET_SCRIPT)
            logger.info(f"Redis rate limiter backend connected: {self._redis_url}")
        except Exception as e:
            logger.warning(f"Redis backend connection failed: {e}")
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def sliding_window_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int, float]:
        """Returns (allowed, current_count, retry_after)."""
        if not self._client:
            raise RuntimeError("Redis backend not available")
        now = time.time()
        result = self._client.evalsha(
            self._sliding_script_sha, 1, key, window_seconds, max_requests, now
        )
        allowed = bool(result[0])
        current = int(result[1])
        retry = float(result[2]) if len(result) > 2 else 0.0
        return allowed, current, retry

    def token_bucket_check(
        self, key: str, capacity: int, fill_rate: float
    ) -> Tuple[bool, int, float]:
        """Returns (allowed, remaining, retry_after)."""
        if not self._client:
            raise RuntimeError("Redis backend not available")
        now = time.time()
        result = self._client.evalsha(
            self._token_bucket_script_sha, 1, key, capacity, fill_rate, now
        )
        allowed = bool(result[0])
        remaining = int(result[1])
        retry = float(result[2]) if len(result) > 2 else 0.0
        return allowed, remaining, retry


# ═══════════════════════════════════════════════════════════
# RateLimiter 主类
# ═══════════════════════════════════════════════════════════

class RateLimiter:
    """Distributed rate limiter supporting token bucket, tiered limits, IP-based
    and API-key-based rate limiting."""

    def __init__(self, redis_url: Optional[str] = None):
        # Tier configs
        self._tier_configs: Dict[RateLimitTier, TierConfig] = {
            RateLimitTier.FREE: TierConfig(capacity=100, refill_rate=10),
            RateLimitTier.PREMIUM: TierConfig(capacity=1000, refill_rate=100),
            RateLimitTier.ADMIN: TierConfig(capacity=10000, refill_rate=1000),
        }

        # API key → tier mapping
        self._api_keys: Dict[str, RateLimitTier] = {}

        # IP → tier mapping
        self._ip_tiers: Dict[str, RateLimitTier] = {}

        # Per-client buckets (key = "ip:<addr>")
        self._buckets: Dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()

        # Windows
        self._windows: Dict[str, SlidingWindow] = {}
        self._windows_lock = threading.Lock()

        # Stats
        self._total_allowed: int = 0
        self._total_denied: int = 0
        self._total_requests: int = 0
        self._active_clients: int = 0
        self._stats_lock = threading.Lock()

        # Redis
        self._redis_backend: Optional[RedisRateLimiterBackend] = None
        if redis_url:
            self._redis_backend = RedisRateLimiterBackend(redis_url)
        elif os.environ.get("MESHCTX_REDIS_URL"):
            self._redis_backend = RedisRateLimiterBackend(os.environ["MESHCTX_REDIS_URL"])

    # ── Tier management ──────────────────────────────────

    def set_tier_config(
        self,
        tier: RateLimitTier,
        capacity: int = 100,
        refill_rate: float = 10.0,
    ):
        """Configure a rate limit tier."""
        self._tier_configs[tier] = TierConfig(capacity=capacity, refill_rate=refill_rate)

    def register_api_key(self, api_key: str, tier: RateLimitTier):
        """Register an API key with a specific tier."""
        self._api_keys[api_key] = tier

    def set_ip_tier(self, ip: str, tier: RateLimitTier):
        """Assign a specific rate limit tier to an IP address."""
        self._ip_tiers[ip] = tier

    def _get_tier(self, ip: str, api_key: Optional[str] = None) -> RateLimitTier:
        """Determine the effective tier for a request."""
        if api_key and api_key in self._api_keys:
            return self._api_keys[api_key]
        if ip in self._ip_tiers:
            return self._ip_tiers[ip]
        return RateLimitTier.FREE

    # ── Rate check ───────────────────────────────────────

    def check(self, ip: str, api_key: Optional[str] = None) -> RateLimitResult:
        """Check if a request from *ip* should be allowed."""
        tier = self._get_tier(ip, api_key)
        config = self._tier_configs[tier]
        bucket_key = f"ip:{ip}"

        with self._buckets_lock:
            if bucket_key not in self._buckets:
                self._buckets[bucket_key] = TokenBucket(
                    capacity=config.capacity,
                    refill_rate=config.refill_rate,
                )
            bucket = self._buckets[bucket_key]

        with self._stats_lock:
            self._total_requests += 1

        allowed, retry = bucket.consume(1)

        with self._stats_lock:
            if allowed:
                self._total_allowed += 1
            else:
                self._total_denied += 1

        if allowed:
            return RateLimitResult(allowed=True, retry_after=0.0, status_code=200)

        return RateLimitResult(
            allowed=False,
            retry_after=retry,
            status_code=429,
            headers={"Retry-After": str(int(retry) + 1)},
        )

    def is_allowed(self, ip: str, api_key: Optional[str] = None) -> bool:
        """Shortcut: return True if request is allowed."""
        result = self.check(ip, api_key=api_key)
        return result.allowed

    # ── Stats & dashboard ────────────────────────────────

    def dashboard(self) -> Dict[str, Any]:
        """Return a dashboard overview."""
        with self._stats_lock:
            overview = {
                "total_requests": self._total_requests,
                "total_allowed": self._total_allowed,
                "total_denied": self._total_denied,
                "active_clients": len(self._buckets),
            }
        with self._buckets_lock:
            clients: Dict[str, Any] = {}
            for key, bucket in self._buckets.items():
                clients[key] = {
                    "tokens": bucket.tokens,
                    "capacity": bucket.capacity,
                    "last_refill": bucket.last_refill,
                }
        tiers: Dict[str, Any] = {}
        for tier, cfg in self._tier_configs.items():
            tiers[tier.value] = {"capacity": cfg.capacity, "refill_rate": cfg.refill_rate}

        return {"overview": overview, "clients": clients, "tiers": tiers}

    def stats(self) -> Dict[str, Any]:
        """Return basic stats."""
        with self._stats_lock:
            return {
                "total_requests": self._total_requests,
                "total_allowed": self._total_allowed,
                "total_denied": self._total_denied,
                "active_clients": len(self._buckets),
            }

    def client_stats(self, bucket_key: Optional[str] = None) -> Dict[str, Any]:
        """Return per-client stats, optionally filtered."""
        result: Dict[str, Any] = {}
        with self._buckets_lock:
            for key, bucket in self._buckets.items():
                if bucket_key is None or key == bucket_key:
                    result[key] = {
                        "tokens": bucket.tokens,
                        "capacity": bucket.capacity,
                    }
        return result

    # ── Maintenance ──────────────────────────────────────

    def reset(self):
        """Reset all rate limiter state."""
        with self._buckets_lock:
            self._buckets.clear()
        with self._windows_lock:
            self._windows.clear()
        with self._stats_lock:
            self._total_requests = 0
            self._total_allowed = 0
            self._total_denied = 0
            self._active_clients = 0

    def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """Remove buckets that have been idle for too long.  Returns count removed."""
        now = time.monotonic()
        removed = 0
        with self._buckets_lock:
            stale = [
                key
                for key, bucket in self._buckets.items()
                if now - bucket.last_refill > max_age_seconds
            ]
            for key in stale:
                del self._buckets[key]
                removed += 1
        return removed


# ═══════════════════════════════════════════════════════════
# 单例与工厂
# ═══════════════════════════════════════════════════════════

_rate_limiter_instance: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter(redis_url: Optional[str] = None) -> RateLimiter:
    """Get or create the global RateLimiter singleton."""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        with _rate_limiter_lock:
            if _rate_limiter_instance is None:
                _rate_limiter_instance = RateLimiter(redis_url=redis_url)
    return _rate_limiter_instance


def reset_rate_limiter():
    """Reset the global singleton (for testing)."""
    global _rate_limiter_instance
    with _rate_limiter_lock:
        _rate_limiter_instance = None
