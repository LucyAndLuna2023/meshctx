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
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
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
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class LimitConfig:
    """限流配置 — 定义一条路由的限流规则。"""
    key: str                          # 限流标识, e.g. "api:chat"
    max_requests: int                 # 窗口内最大请求数
    window_seconds: int               # 时间窗口 (秒)
    algorithm: str = "token_bucket"   # token_bucket | sliding_window
    burst_size: Optional[int] = None  # 突发容量 (仅 token_bucket, 默认 = max_requests)
    scope: str = "user_id"            # 维度: user_id | endpoint | ip | global
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LimitResult:
    """限流检查结果。"""
    allowed: bool
    remaining: int                    # 剩余请求数
    limit: int                        # 总限额
    reset_at: float                   # 窗口重置时间 (Unix timestamp)
    retry_after: float                # 建议重试等待秒数 (429 时)
    algorithm: str
    scope: str
    key: str
    current_count: int                # 当前窗口内计数


@dataclass
class RateLimiterStats:
    """限流器全局统计。"""
    total_checks: int = 0
    total_allowed: int = 0
    total_blocked: int = 0
    active_configs: int = 0
    blocked_by_scope: Dict[str, int] = field(default_factory=dict)
    blocked_by_key: Dict[str, int] = field(default_factory=dict)
    last_updated: float = 0.0


# ═══════════════════════════════════════════════════════════
# Token Bucket 实现
# ═══════════════════════════════════════════════════════════

class TokenBucket:
    """
    令牌桶 — 支持突发流量。

    以恒定速率填充令牌, 最大容量为 burst_size。
    每次请求消耗 1 个令牌。桶满时丢弃多余令牌。
    """

    def __init__(self, capacity: int, fill_rate: float):
        self.capacity = capacity           # 最大令牌数
        self.fill_rate = fill_rate         # 每秒填充令牌数
        self.tokens = float(capacity)      # 当前令牌数
        self.last_fill = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        """根据经过的时间填充令牌。"""
        now = time.monotonic()
        elapsed = now - self.last_fill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
        self.last_fill = now

    def consume(self, tokens: int = 1) -> bool:
        """尝试消耗 1 个令牌。返回 True 表示成功。"""
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_available(self) -> int:
        """获取当前可用令牌数 (近似)。"""
        with self.lock:
            self._refill()
            return int(self.tokens)

    def get_retry_after(self) -> float:
        """估算下一次令牌可用的时间 (秒)。"""
        with self.lock:
            if self.tokens >= 1:
                return 0.0
            # 需要等待 fill_rate 个令牌生成
            needed = 1.0 - self.tokens
            if self.fill_rate > 0:
                return needed / self.fill_rate
            return float("inf")


# ═══════════════════════════════════════════════════════════
# Sliding Window 实现
# ═══════════════════════════════════════════════════════════

class SlidingWindow:
    """
    滑动窗口 — 精确计数。

    记录每个请求的时间戳, 窗口滑动时自动清理过期记录。
    使用 deque 实现 O(1) 清理, 内存占用与请求数成正比。
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []   # deque-like with list for simplicity
        self.lock = threading.Lock()

    def _clean(self, now: float):
        """清除窗口外的过期时间戳。"""
        cutoff = now - self.window_seconds
        # Find first index >= cutoff
        idx = 0
        for i, ts in enumerate(self.timestamps):
            if ts >= cutoff:
                idx = i
                break
        else:
            idx = len(self.timestamps)
        self.timestamps = self.timestamps[idx:]

    def add(self) -> bool:
        """记录一次请求。返回 True 表示在限制内。"""
        now = time.monotonic()
        with self.lock:
            self._clean(now)
            if len(self.timestamps) >= self.max_requests:
                return False
            self.timestamps.append(now)
            return True

    def count(self) -> int:
        """返回当前窗口内的请求数。"""
        now = time.monotonic()
        with self.lock:
            self._clean(now)
            return len(self.timestamps)

    def get_retry_after(self) -> float:
        """估算窗口何时能接受新请求。"""
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

class RedisRateLimiterBackend:
    """
    Redis 分布式限流后端。

    使用 INCR + EXPIRE 实现滑动窗口计数。
    支持多进程/多实例共享限流状态。
    """

    SLIDING_WINDOW_SCRIPT = """
    local key = KEYS[1]
    local window = tonumber(ARGV[1])
    local limit = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])

    -- 移除窗口外的成员
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

    -- 统计当前窗口内请求数
    local current = redis.call('ZCARD', key)

    if current >= limit then
        -- 返回最早的成员剩余时间
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local retry_after = 0
        if #oldest > 0 then
            retry_after = window - (now - tonumber(oldest[2]))
            if retry_after < 0 then retry_after = 0 end
        end
        return {0, current, retry_after}
    end

    -- 添加当前请求
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

    -- 获取上次填充时间
    local last_fill = tonumber(redis.call('HGET', key, 'last_fill') or now)
    local tokens = tonumber(redis.call('HGET', key, 'tokens') or capacity)

    -- 填充令牌
    local elapsed = now - last_fill
    tokens = math.min(capacity, tokens + elapsed * fill_rate)

    if tokens >= 1 then
        tokens = tokens - 1
        redis.call('HMSET', key, 'tokens', tokens, 'last_fill', now)
        redis.call('EXPIRE', key, math.ceil(capacity / fill_rate) + 10)
        return {1, math.floor(tokens)}
    end

    -- 计算重试时间
    local retry = 0
    if fill_rate > 0 then
        retry = math.ceil((1 - tokens) / fill_rate)
    end
    return {0, 0, retry}
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._client: Any = None
        if _redis_available and _redis_module:
            try:
                self._client = _redis_module.from_url(redis_url, decode_responses=True)
                self._client.ping()
                self._sliding_script_sha = self._client.script_load(
                    self.SLIDING_WINDOW_SCRIPT
                )
                self._token_bucket_script_sha = self._client.script_load(
                    self.TOKEN_BUCKET_SCRIPT
                )
                logger.info(f"Redis rate limiter backend connected: {redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, falling back to in-memory")
                self._client = None
        else:
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def sliding_window_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> Tuple[bool, int, float]:
        """Redis 滑动窗口检查。返回 (allowed, current_count, retry_after)。"""
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
        """Redis 令牌桶检查。返回 (allowed, remaining, retry_after)。"""
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
    """
    分布式速率限制器 — 双算法、多维度。

    支持:
      - Token Bucket: 允许突发, 适合 API Gateway 场景
      - Sliding Window: 精确计数, 适合严格的速率限制
      - 多维度: 按 user_id / endpoint / IP / global 限流
      - Redis 分布式后端 (可选, 回退到内存)

    维度组合:
      scope='user_id' → key_prefix: "user:<user_id>:<route>"
      scope='ip'      → key_prefix: "ip:<ip>:<route>"
      scope='endpoint'→ key_prefix: "endpoint:<route>"
      scope='global'  → key_prefix: "global:<route>"
    """

    def __init__(self, redis_url: Optional[str] = None):
        # 配置存储
        self._configs: Dict[str, LimitConfig] = {}
        self._config_lock = threading.Lock()

        # 内存后端 — Token Bucket 实例
        self._buckets: Dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()

        # 内存后端 — Sliding Window 实例
        self._windows: Dict[str, SlidingWindow] = {}
        self._windows_lock = threading.Lock()

        # Redis 后端
        self._redis_backend: Optional[RedisRateLimiterBackend] = None
        if redis_url:
            self._redis_backend = RedisRateLimiterBackend(redis_url)
        elif os.environ.get("MESHCTX_REDIS_URL"):
            self._redis_backend = RedisRateLimiterBackend(
                os.environ["MESHCTX_REDIS_URL"]
            )

        # 统计
        self._stats = RateLimiterStats()
        self._stats_lock = threading.Lock()

        # 清理线程 — 定期清理过期桶和窗口
        self._cleanup_interval = 300  # 5 分钟
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="rate-limiter-cleanup"
        )
        self._cleanup_thread.start()

        # 持久化路径 (可选)
        self._persist_path = Path(
            os.environ.get(
                "MESHCTX_RATE_LIMITER_PERSIST",
                str(Path.home() / ".meshctx" / "rate_limiter_configs.json"),
            )
        )
        self._load_configs()

        logger.info(
            f"RateLimiter initialized: {len(self._configs)} configs, "
            f"redis={'connected' if self.redis_available else 'unavailable'}"
        )

    # ── 属性 ──────────────────────────────────────────

    @property
    def redis_available(self) -> bool:
        return self._redis_backend is not None and self._redis_backend.available

    # ── 配置管理 ──────────────────────────────────────

    def configure_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
        algorithm: str = "token_bucket",
        burst_size: Optional[int] = None,
        scope: str = "user_id",
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LimitConfig:
        """
        配置一条限流规则。

        Args:
            key: 限流标识 (e.g. "api:chat", "api:search")
            max_requests: 窗口内最大请求数
            window_seconds: 时间窗口 (秒)
            algorithm: "token_bucket" 或 "sliding_window"
            burst_size: 突发容量 (仅 token_bucket)
            scope: 维度 ("user_id" | "endpoint" | "ip" | "global")
            enabled: 是否启用
            metadata: 附加元数据

        Returns:
            LimitConfig: 创建的配置对象
        """
        if algorithm not in ("token_bucket", "sliding_window"):
            raise ValueError(f"Unknown algorithm: {algorithm}, use 'token_bucket' or 'sliding_window'")

        if scope not in ("user_id", "endpoint", "ip", "global"):
            raise ValueError(f"Unknown scope: {scope}, use 'user_id'/'endpoint'/'ip'/'global'")

        if burst_size is None:
            burst_size = max_requests

        config = LimitConfig(
            key=key,
            max_requests=max_requests,
            window_seconds=window_seconds,
            algorithm=algorithm,
            burst_size=burst_size,
            scope=scope,
            enabled=enabled,
            metadata=metadata or {},
        )

        with self._config_lock:
            self._configs[key] = config

        self._save_configs()
        logger.info(f"Configured limit: {key} ({algorithm}, {max_requests}/{window_seconds}s, scope={scope})")
        return config

    def get_config(self, key: str) -> Optional[LimitConfig]:
        """获取限流配置。"""
        with self._config_lock:
            return self._configs.get(key)

    def list_configs(self) -> List[LimitConfig]:
        """列出所有限流配置。"""
        with self._config_lock:
            return list(self._configs.values())

    def remove_config(self, key: str) -> bool:
        """移除一条限流配置。"""
        with self._config_lock:
            if key in self._configs:
                del self._configs[key]
                self._save_configs()
                # 清理关联的桶/窗口
                with self._buckets_lock:
                    self._buckets.pop(key, None)
                with self._windows_lock:
                    self._windows.pop(key, None)
                logger.info(f"Removed limit config: {key}")
                return True
        return False

    # ── 限流检查 ──────────────────────────────────────

    def check(
        self,
        key: str,
        user_id: Optional[str] = None,
        ip: Optional[str] = None,
        consume: bool = True,
    ) -> Tuple[bool, LimitResult]:
        """
        检查请求是否被允许。

        Args:
            key: 限流标识 (与 configure_limit 中的 key 对应)
            user_id: 用户 ID (scope=user_id 时需要)
            ip: 客户端 IP (scope=ip 时需要)
            consume: 是否消耗配额 (False = 仅查询)

        Returns:
            (allowed, LimitResult): 是否允许及详细信息
        """
        config = self.get_config(key)
        if config is None:
            # 无配置 → 自动创建宽松默认配置
            config = self.configure_limit(
                key=key,
                max_requests=1000,
                window_seconds=60,
                algorithm="token_bucket",
                scope="global",
            )
            logger.info(f"Auto-created default limit config for: {key}")

        if not config.enabled:
            return True, LimitResult(
                allowed=True,
                remaining=config.max_requests,
                limit=config.max_requests,
                reset_at=time.time() + config.window_seconds,
                retry_after=0,
                algorithm=config.algorithm,
                scope=config.scope,
                key=key,
                current_count=0,
            )

        # 构建维度 key
        scope_key = self._build_scope_key(config, user_id, ip)

        # 统计
        with self._stats_lock:
            self._stats.total_checks += 1
            self._stats.last_updated = time.time()

        # 执行检查
        if config.algorithm == "token_bucket":
            allowed, remaining, current, retry = self._check_token_bucket(
                config, scope_key, consume
            )
        else:
            allowed, remaining, current, retry = self._check_sliding_window(
                config, scope_key, consume
            )

        # 更新统计
        with self._stats_lock:
            if allowed:
                self._stats.total_allowed += 1
            else:
                self._stats.total_blocked += 1
                self._stats.blocked_by_scope[config.scope] = (
                    self._stats.blocked_by_scope.get(config.scope, 0) + 1
                )
                self._stats.blocked_by_key[key] = (
                    self._stats.blocked_by_key.get(key, 0) + 1
                )

        return allowed, LimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=config.max_requests,
            reset_at=time.time() + config.window_seconds,
            retry_after=retry,
            algorithm=config.algorithm,
            scope=config.scope,
            key=key,
            current_count=current,
        )

    def check_multi(
        self,
        keys: List[str],
        user_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> List[Tuple[bool, LimitResult]]:
        """
        同时检查多条限流规则。所有规则都通过才允许。

        Args:
            keys: 多个限流标识
            user_id: 用户 ID
            ip: 客户端 IP

        Returns:
            每条的 (allowed, result) 列表
        """
        results = []
        for key in keys:
            results.append(self.check(key, user_id=user_id, ip=ip))
        return results

    def _build_scope_key(self, config: LimitConfig, user_id: Optional[str], ip: Optional[str]) -> str:
        """根据 scope 构建实际的限流 key。"""
        if config.scope == "user_id":
            uid = user_id or "anonymous"
            return f"user:{uid}:{config.key}"
        elif config.scope == "ip":
            client_ip = ip or "0.0.0.0"
            return f"ip:{client_ip}:{config.key}"
        elif config.scope == "endpoint":
            return f"endpoint:{config.key}"
        else:  # global
            return f"global:{config.key}"

    def _check_token_bucket(
        self, config: LimitConfig, scope_key: str, consume: bool
    ) -> Tuple[bool, int, int, float]:
        """令牌桶检查 (Redis 优先, 回退内存)。"""
        fill_rate = config.max_requests / config.window_seconds

        # 尝试 Redis
        if self.redis_available and self._redis_backend:
            try:
                allowed, remaining, retry = self._redis_backend.token_bucket_check(
                    f"meshctx:rate:tb:{scope_key}",
                    config.burst_size or config.max_requests,
                    fill_rate,
                )
                current = (config.burst_size or config.max_requests) - remaining
                return allowed, remaining, current, retry
            except Exception as e:
                logger.warning(f"Redis token bucket check failed: {e}, falling back to memory")

        # 内存回退
        with self._buckets_lock:
            if scope_key not in self._buckets:
                self._buckets[scope_key] = TokenBucket(
                    capacity=config.burst_size or config.max_requests,
                    fill_rate=fill_rate,
                )
            bucket = self._buckets[scope_key]

        if not consume:
            return True, bucket.get_available(), 0, 0.0

        allowed = bucket.consume(1)
        remaining = bucket.get_available()
        current = (config.burst_size or config.max_requests) - remaining
        retry = bucket.get_retry_after() if not allowed else 0.0
        return allowed, remaining, current, retry

    def _check_sliding_window(
        self, config: LimitConfig, scope_key: str, consume: bool
    ) -> Tuple[bool, int, int, float]:
        """滑动窗口检查 (Redis 优先, 回退内存)。"""
        # 尝试 Redis
        if self.redis_available and self._redis_backend:
            try:
                allowed, current, retry = self._redis_backend.sliding_window_check(
                    f"meshctx:rate:sw:{scope_key}",
                    config.max_requests,
                    config.window_seconds,
                )
                remaining = max(0, config.max_requests - current)
                return allowed, remaining, current, retry
            except Exception as e:
                logger.warning(f"Redis sliding window check failed: {e}, falling back to memory")

        # 内存回退
        with self._windows_lock:
            if scope_key not in self._windows:
                self._windows[scope_key] = SlidingWindow(
                    max_requests=config.max_requests,
                    window_seconds=config.window_seconds,
                )
            window = self._windows[scope_key]

        if not consume:
            current = window.count()
            return True, config.max_requests - current, current, 0.0

        allowed = window.add()
        current = window.count()
        remaining = config.max_requests - current
        retry = window.get_retry_after() if not allowed else 0.0
        return allowed, remaining, current, retry

    # ── 突发流量保护 ──────────────────────────────────

    def enable_burst_protection(self, key: str, burst_multiplier: float = 2.0) -> LimitConfig:
        """
        为限流规则启用突发保护。

        将算法设为 token_bucket, burst_size = max_requests * burst_multiplier。
        """
        config = self.get_config(key)
        if config is None:
            raise ValueError(f"No config found for key: {key}")

        return self.configure_limit(
            key=key,
            max_requests=config.max_requests,
            window_seconds=config.window_seconds,
            algorithm="token_bucket",
            burst_size=int(config.max_requests * burst_multiplier),
            scope=config.scope,
            enabled=config.enabled,
            metadata={**config.metadata, "burst_enabled": True, "burst_multiplier": burst_multiplier},
        )

    # ── 429 响应生成 ──────────────────────────────────

    def build_429_response(self, result: LimitResult) -> Dict[str, Any]:
        """
        构建 429 Too Many Requests 响应体。

        Args:
            result: check() 返回的 LimitResult

        Returns:
            包含 retry_after, limit 等字段的 dict
        """
        return {
            "error": "rate_limit_exceeded",
            "message": f"Too many requests for {result.key}",
            "retry_after": round(result.retry_after, 1),
            "retry_after_seconds": int(result.retry_after),
            "limit": result.limit,
            "remaining": 0,
            "reset_at": result.reset_at,
            "algorithm": result.algorithm,
            "scope": result.scope,
        }

    def get_retry_after_header(self, result: LimitResult) -> str:
        """生成 Retry-After HTTP header 值。"""
        if result.retry_after <= 0:
            return str(max(1, int(result.reset_at - time.time())))
        return str(int(result.retry_after) + 1)

    # ── 状态与统计 ────────────────────────────────────

    def get_stats(self) -> RateLimiterStats:
        """获取限流统计。"""
        with self._stats_lock:
            with self._config_lock:
                self._stats.active_configs = len(self._configs)
            return self._stats

    def get_status(self, key: Optional[str] = None) -> Dict[str, Any]:
        """
        获取限流状态 — 对应 /api/rate_limiter/status 端点。

        Args:
            key: 可选, 查询特定 key 的状态

        Returns:
            包含配置、当前计数、剩余配额的 dict
        """
        stats = self.get_stats()
        result: Dict[str, Any] = {
            "summary": {
                "total_checks": stats.total_checks,
                "total_allowed": stats.total_allowed,
                "total_blocked": stats.total_blocked,
                "block_rate": (
                    stats.total_blocked / max(1, stats.total_checks)
                ),
                "active_configs": stats.active_configs,
                "redis_available": self.redis_available,
                "last_updated": stats.last_updated,
            },
            "configs": {},
        }

        configs = [self.get_config(key)] if key else self.list_configs()
        for cfg in configs:
            if cfg is None:
                continue
            # 检查一次当前状态 (不消耗)
            _, status_result = self.check(cfg.key, consume=False)
            result["configs"][cfg.key] = {
                "algorithm": cfg.algorithm,
                "scope": cfg.scope,
                "max_requests": cfg.max_requests,
                "window_seconds": cfg.window_seconds,
                "enabled": cfg.enabled,
                "current_count": status_result.current_count,
                "remaining": status_result.remaining,
                "reset_at": status_result.reset_at,
            }

        return result

    def reset(self, key: Optional[str] = None):
        """重置限流状态。"""
        if key:
            with self._buckets_lock:
                # 清理所有匹配 scope_key 的桶
                to_remove = [k for k in self._buckets if key in k]
                for k in to_remove:
                    del self._buckets[k]
            with self._windows_lock:
                to_remove = [k for k in self._windows if key in k]
                for k in to_remove:
                    del self._windows[k]
            logger.info(f"Reset rate limiter state for key: {key}")
        else:
            with self._buckets_lock:
                self._buckets.clear()
            with self._windows_lock:
                self._windows.clear()
            logger.info("Reset all rate limiter state")

    # ── 持久化 ────────────────────────────────────────

    def _load_configs(self):
        """从磁盘加载持久化的限流配置。"""
        try:
            if self._persist_path.exists():
                data = json.loads(self._persist_path.read_text())
                with self._config_lock:
                    for item in data:
                        cfg = LimitConfig(**item)
                        self._configs[cfg.key] = cfg
                logger.info(f"Loaded {len(data)} rate limiter configs from {self._persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load rate limiter configs: {e}")

    def _save_configs(self):
        """持久化限流配置到磁盘。"""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_lock:
                data = [
                    {
                        "key": c.key,
                        "max_requests": c.max_requests,
                        "window_seconds": c.window_seconds,
                        "algorithm": c.algorithm,
                        "burst_size": c.burst_size,
                        "scope": c.scope,
                        "enabled": c.enabled,
                        "metadata": c.metadata,
                    }
                    for c in self._configs.values()
                ]
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save rate limiter configs: {e}")

    def _cleanup_loop(self):
        """后台清理线程 — 定期清理不活跃的桶和窗口。"""
        while True:
            time.sleep(self._cleanup_interval)
            try:
                now = time.monotonic()
                max_idle = 600  # 10 分钟无活动则清理

                with self._buckets_lock:
                    stale = []
                    for k, bucket in self._buckets.items():
                        if now - bucket.last_fill > max_idle:
                            stale.append(k)
                    for k in stale:
                        del self._buckets[k]

                with self._windows_lock:
                    stale = []
                    for k, window in self._windows.items():
                        if window.timestamps:
                            if now - window.timestamps[-1] > max_idle:
                                stale.append(k)
                        else:
                            stale.append(k)
                    for k in stale:
                        del self._windows[k]

                if stale:
                    logger.debug(f"Cleaned up {len(stale)} stale rate limiter states")
            except Exception as e:
                logger.error(f"Rate limiter cleanup error: {e}")


# ═══════════════════════════════════════════════════════════
# 单例与工厂
# ═══════════════════════════════════════════════════════════

_rate_limiter_instance: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter(redis_url: Optional[str] = None) -> RateLimiter:
    """
    获取全局 RateLimiter 单例 (auto-create)。

    Args:
        redis_url: Redis 连接 URL (仅首次创建时使用)

    Returns:
        RateLimiter 实例
    """
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        with _rate_limiter_lock:
            if _rate_limiter_instance is None:
                _rate_limiter_instance = RateLimiter(redis_url=redis_url)
    return _rate_limiter_instance


def is_rate_limited(key: str, user_id: Optional[str] = None, ip: Optional[str] = None) -> bool:
    """
    快速检查是否被限流 (便捷函数)。

    Returns:
        True 表示被限流 (请求不应发送)
    """
    limiter = get_rate_limiter()
    allowed, _ = limiter.check(key, user_id=user_id, ip=ip)
    return not allowed
