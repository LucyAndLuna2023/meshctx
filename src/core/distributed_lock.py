"""
meshctx Distributed Lock — 分布式锁
====================================

Redis SETNX + Lua 脚本分布式锁, 支持 Redlock 算法。

核心功能:
  1. Redis SETNX + Lua 脚本 — 原子获取与释放
  2. 锁续期 Watchdog — 自动续期长任务
  3. 锁粒度 — global / resource / key 三级
  4. 死锁检测 + 自动释放 — 基于 TTL 超时
  5. Redlock 算法 — 多 Redis 实例共识
  6. 本地回退 — 无 Redis 时使用线程锁

使用示例:
  lock_mgr = get_distributed_lock()
  lock = lock_mgr.acquire("resource:db:table_x", ttl=30)
  if lock:
      try:
          # 临界区代码
          do_critical_work()
      finally:
          lock_mgr.release(lock)
"""

import json
import logging
import os
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.distributed_lock")


# ═══════════════════════════════════════════════════════════
# Redis 可选导入
# ═══════════════════════════════════════════════════════════

_redis_available = False
_redis_module = None
try:
    import redis as _redis_module
    _redis_available = True
except ImportError:
    logger.info("redis not installed; using local lock fallback only")
    _redis_module = None


# ═══════════════════════════════════════════════════════════
# 枚举与数据结构
# ═══════════════════════════════════════════════════════════

class LockGranularity(Enum):
    """锁粒度。"""
    GLOBAL = "global"        # 全系统互斥
    RESOURCE = "resource"    # 资源级互斥 (e.g. "db")
    KEY = "key"              # 键级互斥 (e.g. "db:table:row123")


class LockState(Enum):
    """锁状态。"""
    ACQUIRED = auto()
    RELEASED = auto()
    EXPIRED = auto()
    STOLEN = auto()          # 被其他实例强制获取


@dataclass
class Lock:
    """分布式锁实例。"""
    resource: str                      # 锁资源标识
    token: str                         # 唯一持有者 token (UUID-like)
    acquired_at: float                 # 获取时间 (Unix timestamp)
    ttl: float                         # 锁的 TTL (秒)
    expires_at: float                  # 过期时间
    granularity: LockGranularity = LockGranularity.KEY
    state: LockState = LockState.ACQUIRED
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Watchdog
    _watchdog_active: bool = field(default=False, repr=False)
    _watchdog_thread: Optional[threading.Thread] = field(default=None, repr=False)


@dataclass
class LockStats:
    """锁统计信息。"""
    total_acquired: int = 0
    total_released: int = 0
    total_expired: int = 0
    total_failed: int = 0
    total_stolen: int = 0
    active_locks: int = 0
    deadlocks_detected: int = 0
    last_updated: float = 0.0


# ═══════════════════════════════════════════════════════════
# Lua 脚本 (原子操作)
# ═══════════════════════════════════════════════════════════

ACQUIRE_SCRIPT = """
-- 获取锁: SET resource token NX EX ttl
-- KEYS[1]: lock key
-- ARGV[1]: token
-- ARGV[2]: ttl (seconds)
local result = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
if result then
    return 1
else
    return 0
end
"""

RELEASE_SCRIPT = """
-- 释放锁: 验证 token, 仅在持有者释放时删除
-- KEYS[1]: lock key
-- ARGV[1]: token
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

RENEW_SCRIPT = """
-- 续期: 验证 token, 延长 TTL
-- KEYS[1]: lock key
-- ARGV[1]: token
-- ARGV[2]: new_ttl (seconds)
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
else
    return 0
end
"""

FORCE_RELEASE_SCRIPT = """
-- 强制释放: 无视 token (死锁恢复)
-- KEYS[1]: lock key
local val = redis.call('GET', KEYS[1])
local count = redis.call('DEL', KEYS[1])
return {val or '', count}
"""

DETECT_DEADLOCKS_SCRIPT = """
-- 死锁检测: 扫描所有 lock:* key, 返回 TTL <= threshold 的
-- KEYS[1]: scan pattern (e.g. "lock:*")
-- ARGV[1]: ttl_threshold (seconds)
local keys = redis.call('KEYS', 'lock:*')
local result = {}
for i, k in ipairs(keys) do
    local ttl = redis.call('TTL', k)
    if ttl >= 0 and ttl <= tonumber(ARGV[1]) then
        table.insert(result, {k, redis.call('GET', k), ttl})
    end
end
return result
"""


# ═══════════════════════════════════════════════════════════
# Redlock 算法实现
# ═══════════════════════════════════════════════════════════

class RedlockManager:
    """
    Redlock 算法 — 多 Redis 实例分布式锁。

    算法:
      1. 获取当前时间 (T1)
      2. 依次向 N 个 Redis 实例尝试获取锁 (SET NX EX)
      3. 计算经过时间 (T2 - T1)
      4. 如果获取了多数实例 (N/2 + 1) 且经过时间 < TTL:
         锁获取成功
      5. 否则: 释放已获取的实例

    引用: https://redis.io/topics/distlock
    """

    def __init__(self, redis_urls: List[str], quorum: Optional[int] = None):
        """
        Args:
            redis_urls: Redis 实例 URL 列表
            quorum: 法定人数 (默认 N/2 + 1)
        """
        self._clients: List[Any] = []
        self._urls = redis_urls
        self._quorum = quorum or (len(redis_urls) // 2 + 1)

        for url in redis_urls:
            try:
                client = _redis_module.from_url(url, socket_timeout=2, socket_connect_timeout=2)
                client.ping()
                self._clients.append(client)
                logger.info(f"Redlock: connected to {url}")
            except Exception as e:
                logger.warning(f"Redlock: failed to connect to {url}: {e}")

    @property
    def available(self) -> bool:
        """Redlock 是否可用 (至少 quorum 个实例在线)。"""
        return len(self._clients) >= self._quorum

    def acquire(self, resource: str, token: str, ttl: float) -> bool:
        """
        尝试获取 Redlock。

        Args:
            resource: 锁资源标识
            token: 持有者唯一 token
            ttl: 锁的 TTL (秒)

        Returns:
            True if acquired
        """
        if not self.available:
            logger.warning("Redlock not available: insufficient online instances")
            return False

        start = time.time()
        acquired_count = 0

        for client in self._clients:
            try:
                result = client.set(resource, token, nx=True, ex=int(ttl))
                if result:
                    acquired_count += 1
            except Exception as e:
                logger.debug(f"Redlock acquire error on {client}: {e}")

        elapsed = time.time() - start

        # 检查: 多数 + 时间有效
        if acquired_count >= self._quorum and elapsed < ttl:
            logger.debug(f"Redlock acquired on {acquired_count}/{len(self._clients)} instances (elapsed={elapsed:.2f}s)")
            return True

        # 失败: 释放已获取的
        self.release(resource, token)
        logger.debug(f"Redlock acquire failed: {acquired_count}/{self._quorum} required")
        return False

    def release(self, resource: str, token: str) -> bool:
        """释放 Redlock (在所有实例上)。"""
        success_count = 0
        for client in self._clients:
            try:
                # Lua 脚本: 验证 token 后删除
                script = _redis_module.register_script(RELEASE_SCRIPT)
                result = script(keys=[resource], args=[token], client=client)
                if result:
                    success_count += 1
            except Exception as e:
                logger.debug(f"Redlock release error: {e}")
        return success_count > 0

    def renew(self, resource: str, token: str, new_ttl: float) -> bool:
        """续期 Redlock (在所有实例上)。"""
        success_count = 0
        for client in self._clients:
            try:
                script = _redis_module.register_script(RENEW_SCRIPT)
                result = script(keys=[resource], args=[token, int(new_ttl)], client=client)
                if result:
                    success_count += 1
            except Exception as e:
                logger.debug(f"Redlock renew error: {e}")
        return success_count >= self._quorum


# ═══════════════════════════════════════════════════════════
# 本地锁回退
# ═══════════════════════════════════════════════════════════

class LocalLockBackend:
    """本地线程锁回退 — 使用 threading.Lock。"""

    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._owners: Dict[str, str] = {}
        self._lock = threading.Lock()

    def acquire(self, resource: str, token: str, ttl: float, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """获取本地锁。"""
        with self._lock:
            if resource not in self._locks:
                self._locks[resource] = threading.Lock()

        lock = self._locks[resource]
        acquired = lock.acquire(blocking=blocking, timeout=timeout or ttl)
        if acquired:
            self._owners[resource] = token
        return acquired

    def release(self, resource: str, token: str) -> bool:
        """释放本地锁。"""
        with self._lock:
            if resource not in self._locks:
                return False
            if self._owners.get(resource) != token:
                return False
            del self._owners[resource]
            try:
                self._locks[resource].release()
                return True
            except RuntimeError:
                # 未持有锁
                return False

    def renew(self, resource: str, token: str) -> bool:
        """续期 — 本地锁总是持有直到 release。无需操作。"""
        return self._owners.get(resource) == token


# ═══════════════════════════════════════════════════════════
# DistributedLockManager 主类
# ═══════════════════════════════════════════════════════════

class DistributedLockManager:
    """
    分布式锁管理器 — SETNX + Lua + Redlock + Watchdog。

    核心设计:
      - Redis 优先: 使用 SETNX + Lua 保证原子性
      - Redlock: 多 Redis 实例共识, 防止单点故障
      - Watchdog: 自动续期, 防止长任务锁过期
      - 本地回退: Redis 不可用时使用 threading.Lock
      - 死锁检测: 扫描 TTL 即将过期的锁
      - 锁粒度: global / resource / key
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redlock_urls: Optional[List[str]] = None,
        default_ttl: float = 30.0,
        watchdog_interval: float = 10.0,
    ):
        self.default_ttl = default_ttl
        self.watchdog_interval = watchdog_interval

        # Redis client
        self._redis: Any = None

        if redis_url:
            try:
                self._redis = _redis_module.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
                self._redis.ping()
                logger.info(f"DistributedLock: connected to Redis at {redis_url}")
            except Exception as e:
                logger.warning(f"DistributedLock: Redis connection failed: {e}")

        # Redlock
        self._redlock: Optional[RedlockManager] = None
        if redlock_urls and _redis_module:
            self._redlock = RedlockManager(redlock_urls)

        # 本地回退
        self._local_backend = LocalLockBackend()

        # 活跃锁注册表
        self._active_locks: Dict[str, Lock] = {}
        self._active_locks_lock = threading.Lock()

        # 统计
        self._stats = LockStats()

        # Lua 脚本注册
        self._acquire_script: Any = None
        self._release_script: Any = None
        self._renew_script: Any = None
        self._force_release_script: Any = None
        self._detect_deadlocks_script: Any = None
        self._register_scripts()

        logger.info(
            f"DistributedLockManager initialized: "
            f"redis={'connected' if self._redis else 'unavailable'}, "
            f"redlock={'enabled' if self._redlock else 'disabled'}"
        )

    @property
    def available(self) -> bool:
        """分布式锁是否可用。"""
        return self._redis is not None or self._redlock is not None

    # ── Lua 脚本注册 ──────────────────────────────────

    def _register_scripts(self):
        """向 Redis 注册 Lua 脚本。"""
        if self._redis and _redis_module:
            try:
                self._acquire_script = self._redis.register_script(ACQUIRE_SCRIPT)
                self._release_script = self._redis.register_script(RELEASE_SCRIPT)
                self._renew_script = self._redis.register_script(RENEW_SCRIPT)
                self._force_release_script = self._redis.register_script(FORCE_RELEASE_SCRIPT)
                self._detect_deadlocks_script = self._redis.register_script(DETECT_DEADLOCKS_SCRIPT)
                logger.debug("Lua scripts registered")
            except Exception as e:
                logger.warning(f"Failed to register Lua scripts: {e}")

    # ── 锁 key 构建 ───────────────────────────────────

    @staticmethod
    def build_lock_key(
        resource: str,
        granularity: LockGranularity = LockGranularity.KEY,
    ) -> str:
        """
        根据粒度和资源构建锁 key。

        granularity=GLOBAL  → "lock:global"
        granularity=RESOURCE → "lock:resource:<resource>"
        granularity=KEY    → "lock:key:<resource>"
        """
        if granularity == LockGranularity.GLOBAL:
            return "lock:global"
        elif granularity == LockGranularity.RESOURCE:
            return f"lock:resource:{resource}"
        else:
            return f"lock:key:{resource}"

    # ── 锁获取 ────────────────────────────────────────

    def acquire(
        self,
        resource: str,
        ttl: Optional[float] = None,
        granularity: LockGranularity = LockGranularity.KEY,
        blocking: bool = True,
        timeout: Optional[float] = None,
        enable_watchdog: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Lock]:
        """
        获取分布式锁。

        Args:
            resource: 锁资源标识 (e.g. "db:users:123")
            ttl: 锁的 TTL (秒), 默认 30
            granularity: 锁粒度
            blocking: True=阻塞等待, False=立即返回
            timeout: 阻塞超时 (秒), None=无限等待
            enable_watchdog: 是否启用自动续期
            metadata: 锁附加信息

        Returns:
            Lock 对象或 None (获取失败)
        """
        ttl = ttl or self.default_ttl
        token = self._generate_token()
        lock_key = self.build_lock_key(resource, granularity)

        deadline = time.time() + (timeout or ttl) if blocking else time.time()

        while True:
            acquired = self._try_acquire(lock_key, token, ttl)

            if acquired:
                lock = Lock(
                    resource=resource,
                    token=token,
                    acquired_at=time.time(),
                    ttl=ttl,
                    expires_at=time.time() + ttl,
                    granularity=granularity,
                    metadata=metadata or {},
                )

                with self._active_locks_lock:
                    self._active_locks[token] = lock
                    self._stats.total_acquired += 1
                    self._stats.active_locks = len(self._active_locks)
                    self._stats.last_updated = time.time()

                if enable_watchdog:
                    self._start_watchdog(lock, lock_key)

                logger.debug(f"Lock acquired: {lock_key} (ttl={ttl}s)")
                return lock

            if not blocking or (timeout is not None and time.time() >= deadline):
                self._stats.total_failed += 1
                self._stats.last_updated = time.time()
                logger.debug(f"Lock failed: {lock_key}")
                return None

            # 轮询等待
            time.sleep(0.05)

    def _try_acquire(self, lock_key: str, token: str, ttl: float) -> bool:
        """尝试获取锁 (Redis 优先 → Redlock → 本地)。"""
        # 1) Redlock
        if self._redlock and self._redlock.available:
            return self._redlock.acquire(lock_key, token, ttl)

        # 2) Redis
        if self._redis and self._acquire_script:
            try:
                result = self._acquire_script(keys=[lock_key], args=[token, int(ttl)])
                return bool(result)
            except Exception as e:
                logger.warning(f"Redis acquire error: {e}")
                # 回退到本地
                return self._local_backend.acquire(lock_key, token, ttl)

        # 3) 本地回退
        return self._local_backend.acquire(lock_key, token, ttl)

    # ── 锁释放 ────────────────────────────────────────

    def release(self, lock: Lock) -> bool:
        """
        释放分布式锁。

        Args:
            lock: acquire() 返回的 Lock 对象

        Returns:
            True if released
        """
        lock_key = self.build_lock_key(lock.resource, lock.granularity)

        # 停止 watchdog
        self._stop_watchdog(lock)

        released = self._try_release(lock_key, lock.token)

        with self._active_locks_lock:
            self._active_locks.pop(lock.token, None)
            if released:
                lock.state = LockState.RELEASED
                self._stats.total_released += 1
            else:
                lock.state = LockState.STOLEN
                self._stats.total_stolen += 1
            self._stats.active_locks = len(self._active_locks)
            self._stats.last_updated = time.time()

        logger.debug(f"Lock {'released' if released else 'stolen'}: {lock_key}")
        return released

    def release_resource(self, resource: str, granularity: LockGranularity = LockGranularity.KEY) -> bool:
        """根据资源标识释放锁 (便捷方法)。"""
        lock_key = self.build_lock_key(resource, granularity)
        # 查找对应的活跃 lock
        with self._active_locks_lock:
            for token, lock in list(self._active_locks.items()):
                if self.build_lock_key(lock.resource, lock.granularity) == lock_key:
                    return self.release(lock)
        # 直接强制释放
        return self._try_force_release(lock_key)

    def _try_release(self, lock_key: str, token: str) -> bool:
        """尝试释放锁。"""
        # 1) Redlock
        if self._redlock and self._redlock.available:
            return self._redlock.release(lock_key, token)

        # 2) Redis
        if self._redis and self._release_script:
            try:
                result = self._release_script(keys=[lock_key], args=[token])
                return bool(result)
            except Exception as e:
                logger.warning(f"Redis release error: {e}")
                return self._local_backend.release(lock_key, token)

        # 3) 本地回退
        return self._local_backend.release(lock_key, token)

    def _try_force_release(self, lock_key: str) -> bool:
        """强制释放锁 (死锁恢复)。"""
        if self._redis and self._force_release_script:
            try:
                result = self._force_release_script(keys=[lock_key])
                return bool(result[1])
            except Exception as e:
                logger.warning(f"Force release error: {e}")
        # 本地方案: 清除
        return self._local_backend.release(lock_key, "__force__")

    # ── 锁续期 (Watchdog) ─────────────────────────────

    def _start_watchdog(self, lock: Lock, lock_key: str):
        """启动 watchdog 线程, 自动续期。"""
        if lock._watchdog_active:
            return

        lock._watchdog_active = True

        def _watchdog_loop():
            """每隔 watchdog_interval 续期一次。"""
            renew_at = ttl * 0.6  # TTL 的 60% 时续期
            while lock._watchdog_active and lock.state == LockState.ACQUIRED:
                time.sleep(renew_at)

                if not lock._watchdog_active:
                    break

                renewed = self._try_renew(lock_key, lock.token, lock.ttl)
                if renewed:
                    lock.expires_at = time.time() + lock.ttl
                    logger.debug(f"Watchdog renewed: {lock_key} (+{lock.ttl}s)")
                else:
                    logger.warning(f"Watchdog renew failed: {lock_key} — lock may be stolen")
                    lock.state = LockState.STOLEN
                    self._stats.total_stolen += 1
                    break

        lock._watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            daemon=True,
            name=f"lock-watchdog-{lock.resource}",
        )
        lock._watchdog_thread.start()

    def _stop_watchdog(self, lock: Lock):
        """停止 watchdog 线程。"""
        lock._watchdog_active = False
        if lock._watchdog_thread and lock._watchdog_thread.is_alive():
            lock._watchdog_thread.join(timeout=1.0)

    def _try_renew(self, lock_key: str, token: str, ttl: float) -> bool:
        """尝试续期。"""
        # 1) Redlock
        if self._redlock and self._redlock.available:
            return self._redlock.renew(lock_key, token, ttl)

        # 2) Redis
        if self._redis and self._renew_script:
            try:
                result = self._renew_script(keys=[lock_key], args=[token, int(ttl)])
                return bool(result)
            except Exception as e:
                logger.warning(f"Redis renew error: {e}")
                return self._local_backend.renew(lock_key, token)

        # 3) 本地回退
        return self._local_backend.renew(lock_key, token)

    def renew(self, lock: Lock, new_ttl: Optional[float] = None) -> bool:
        """手动续期。"""
        lock_key = self.build_lock_key(lock.resource, lock.granularity)
        ttl_to_use = new_ttl or lock.ttl
        renewed = self._try_renew(lock_key, lock.token, ttl_to_use)
        if renewed:
            lock.expires_at = time.time() + ttl_to_use
        return renewed

    # ── 死锁检测 ──────────────────────────────────────

    def detect_deadlocks(self, ttl_threshold: float = 5.0) -> List[Dict[str, Any]]:
        """
        检测即将过期的锁 (潜在死锁)。

        扫描所有 lock:* key, 返回 TTL <= threshold 的锁。

        Args:
            ttl_threshold: TTL 阈值 (秒), 低于此值的锁认为是潜在死锁

        Returns:
            潜在死锁列表: [{"key": ..., "token": ..., "ttl": ...}, ...]
        """
        deadlocks = []

        if self._redis and self._detect_deadlocks_script:
            try:
                results = self._detect_deadlocks_script(args=[int(ttl_threshold)])
                for item in results:
                    deadlocks.append({
                        "key": item[0].decode() if isinstance(item[0], bytes) else item[0],
                        "token": item[1].decode() if isinstance(item[1], bytes) else item[1],
                        "ttl": int(item[2]),
                    })
            except Exception as e:
                logger.warning(f"Deadlock detection failed: {e}")

        # 同时检查本地活跃锁
        now = time.time()
        with self._active_locks_lock:
            for token, lock in self._active_locks.items():
                if lock.state == LockState.ACQUIRED:
                    remaining = lock.expires_at - now
                    if 0 <= remaining <= ttl_threshold:
                        deadlocks.append({
                            "key": self.build_lock_key(lock.resource, lock.granularity),
                            "token": token,
                            "ttl": round(remaining, 1),
                            "local": True,
                        })

        if deadlocks:
            self._stats.deadlocks_detected += len(deadlocks)
            logger.warning(f"Deadlocks detected: {len(deadlocks)}")

        return deadlocks

    def recover_deadlocks(self, ttl_threshold: float = 5.0) -> int:
        """
        自动恢复死锁 — 强制释放 TTL 即将过期的锁。

        Returns:
            恢复的锁数量
        """
        deadlocks = self.detect_deadlocks(ttl_threshold)
        recovered = 0
        for dl in deadlocks:
            lock_key = dl["key"]
            if self._try_force_release(lock_key):
                recovered += 1
                logger.info(f"Deadlock recovered: {lock_key} (ttl={dl['ttl']}s)")
        return recovered

    # ── Context Manager 支持 ──────────────────────────

    @contextmanager
    def lock(
        self,
        resource: str,
        ttl: Optional[float] = None,
        granularity: LockGranularity = LockGranularity.KEY,
        enable_watchdog: bool = True,
    ):
        """
        Context manager 风格的锁使用。

        Usage:
            with lock_mgr.lock("resource:db:table"):
                do_critical_work()
        """
        acquired = self.acquire(
            resource=resource,
            ttl=ttl,
            granularity=granularity,
            blocking=True,
            enable_watchdog=enable_watchdog,
        )
        if acquired is None:
            raise TimeoutError(f"Failed to acquire lock for: {resource}")
        try:
            yield acquired
        finally:
            self.release(acquired)

    # ── 查询 ──────────────────────────────────────────

    def is_locked(self, resource: str, granularity: LockGranularity = LockGranularity.KEY) -> bool:
        """检查资源是否被锁定。"""
        lock_key = self.build_lock_key(resource, granularity)

        # Redis
        if self._redis:
            try:
                return self._redis.exists(lock_key) > 0
            except Exception:
                pass

        # 本地
        with self._active_locks_lock:
            for lock in self._active_locks.values():
                if self.build_lock_key(lock.resource, lock.granularity) == lock_key:
                    return lock.state == LockState.ACQUIRED
        return False

    def get_lock_info(self, resource: str, granularity: LockGranularity = LockGranularity.KEY) -> Optional[Dict[str, Any]]:
        """获取锁的详细信息。"""
        lock_key = self.build_lock_key(resource, granularity)

        if self._redis:
            try:
                val = self._redis.get(lock_key)
                ttl_val = self._redis.ttl(lock_key)
                if val:
                    return {
                        "key": lock_key,
                        "token": val.decode() if isinstance(val, bytes) else val,
                        "ttl": int(ttl_val),
                        "backend": "redis",
                    }
            except Exception:
                pass

        # 本地
        with self._active_locks_lock:
            for lock in self._active_locks.values():
                if self.build_lock_key(lock.resource, lock.granularity) == lock_key:
                    return {
                        "key": lock_key,
                        "token": lock.token,
                        "ttl": round(lock.expires_at - time.time(), 1),
                        "backend": "local",
                        "acquired_at": lock.acquired_at,
                        "metadata": lock.metadata,
                    }
        return None

    def list_active_locks(self) -> List[Dict[str, Any]]:
        """列出所有活跃锁。"""
        with self._active_locks_lock:
            return [
                {
                    "resource": lock.resource,
                    "token": lock.token[:16] + "...",
                    "granularity": lock.granularity.value,
                    "state": lock.state.name,
                    "ttl": lock.ttl,
                    "acquired_at": lock.acquired_at,
                    "expires_at": lock.expires_at,
                    "watchdog_active": lock._watchdog_active,
                }
                for lock in self._active_locks.values()
            ]

    # ── 统计 ──────────────────────────────────────────

    def get_stats(self) -> LockStats:
        """获取锁统计信息。"""
        with self._active_locks_lock:
            self._stats.active_locks = len(self._active_locks)
            self._stats.last_updated = time.time()
            return self._stats

    def reset_stats(self):
        """重置统计信息。"""
        self._stats = LockStats()

    # ── 工具 ──────────────────────────────────────────

    @staticmethod
    def _generate_token() -> str:
        """生成唯一 token。"""
        return secrets.token_hex(32)


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_distributed_lock_instance: Optional[DistributedLockManager] = None
_distributed_lock_lock = threading.Lock()


def get_distributed_lock(
    redis_url: Optional[str] = None,
    redlock_urls: Optional[List[str]] = None,
    default_ttl: float = 30.0,
) -> DistributedLockManager:
    """
    获取全局 DistributedLockManager 单例 (auto-create)。

    Args:
        redis_url: Redis 连接 URL
        redlock_urls: Redlock 多实例 URL 列表
        default_ttl: 默认锁 TTL (秒)

    Returns:
        DistributedLockManager 实例
    """
    global _distributed_lock_instance
    if _distributed_lock_instance is None:
        with _distributed_lock_lock:
            if _distributed_lock_instance is None:
                _distributed_lock_instance = DistributedLockManager(
                    redis_url=redis_url,
                    redlock_urls=redlock_urls,
                    default_ttl=default_ttl,
                )
    return _distributed_lock_instance
