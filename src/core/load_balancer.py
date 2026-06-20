"""
meshctx Load Balancer — 智能负载均衡器
======================================

多策略负载均衡 + 健康检查 + 熔断器。

核心功能:
  1. 最少连接 (Least Connections) — 将请求路由到连接最少的后端
  2. 加权轮询 (Weighted Round Robin) — 按权重比例分配
  3. 一致性哈希 (Consistent Hashing) — 相同 key 路由到相同后端
  4. 后端健康检查 — HTTP/TCP 探活
  5. 动态权重调整 — 根据响应时间/错误率自动调整
  6. 故障转移 (Failover) — 健康后端失败时自动切换
  7. 熔断器 (Circuit Breaker) — 防止雪崩

使用示例:
  lb = get_load_balancer()
  lb.add_backend("api-1", "http://10.0.0.1:8080", weight=10)
  lb.add_backend("api-2", "http://10.0.0.2:8080", weight=10)
  backend = lb.select("least_connections")
  lb.record_result("api-1", success=True, latency_ms=45)
"""

import hashlib
import json
import logging
import os
import socket
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import urllib.request as _urllib
    _HTTP_TIMEOUT = 5
except ImportError:
    _urllib = None

logger = logging.getLogger("meshctx.load_balancer")


# ═══════════════════════════════════════════════════════════
# 枚举与数据结构
# ═══════════════════════════════════════════════════════════

class BackendState(Enum):
    """后端状态。"""
    HEALTHY = "healthy"           # 正常
    DEGRADED = "degraded"         # 性能下降, 仍可服务
    UNHEALTHY = "unhealthy"       # 不健康, 不应路由
    DRAINING = "draining"         # 正在排空连接
    OFFLINE = "offline"           # 手动下线


class CircuitState(Enum):
    """熔断器状态。"""
    CLOSED = auto()               # 正常 (熔断关闭)
    OPEN = auto()                 # 熔断打开, 拒绝请求
    HALF_OPEN = auto()            # 半开, 探测恢复


class LoadBalanceStrategy(Enum):
    """负载均衡策略。"""
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    CONSISTENT_HASH = "consistent_hash"
    RANDOM = "random"


@dataclass
class Backend:
    """后端服务节点。"""
    name: str
    address: str                         # host:port or URL
    weight: int = 10                     # 权重 (1-100)
    state: BackendState = BackendState.HEALTHY
    active_connections: int = 0
    total_requests: int = 0
    total_failures: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_health_check: float = 0.0
    last_used: float = 0.0
    failure_streak: int = 0              # 连续失败次数
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 熔断器
    circuit_state: CircuitState = CircuitState.CLOSED
    circuit_failures: int = 0
    circuit_last_failure: float = 0.0
    circuit_half_open_time: float = 0.0


@dataclass
class SelectionResult:
    """选择结果。"""
    backend: Optional[Backend]
    strategy: str
    success: bool
    error: Optional[str] = None


@dataclass
class BalancerStats:
    """负载均衡器统计。"""
    total_selections: int = 0
    total_failures: int = 0
    total_successes: int = 0
    active_backends: int = 0
    healthy_backends: int = 0
    unhealthy_backends: int = 0
    circuit_open_backends: int = 0
    last_updated: float = 0.0
    strategy_usage: Dict[str, int] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 一致性哈希环
# ═══════════════════════════════════════════════════════════

class ConsistentHashRing:
    """
    一致性哈希环 — 虚拟节点实现。

    每个物理后端映射到 virtual_nodes 个虚拟节点,
    使用 MD5 哈希计算在环上的位置。
    """

    def __init__(self, virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self._ring: Dict[int, str] = {}     # hash → backend_name
        self._sorted_keys: List[int] = []    # 排序的哈希值
        self._lock = threading.Lock()

    def _hash(self, key: str) -> int:
        """MD5 哈希 → 32-bit 无符号整数。"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16) & 0xFFFFFFFF

    def add(self, backend_name: str, weight: int = 10):
        """将后端加入哈希环。"""
        with self._lock:
            # 虚拟节点数按权重比例调整
            nodes = max(1, int(self.virtual_nodes * (weight / 10.0)))
            for i in range(nodes):
                vnode_key = f"{backend_name}:vnode:{i}"
                h = self._hash(vnode_key)
                self._ring[h] = backend_name
            self._sorted_keys = sorted(self._ring.keys())

    def remove(self, backend_name: str):
        """从哈希环移除后端。"""
        with self._lock:
            to_remove = [
                h for h, name in self._ring.items() if name == backend_name
            ]
            for h in to_remove:
                del self._ring[h]
            self._sorted_keys = sorted(self._ring.keys())

    def get(self, key: str) -> Optional[str]:
        """
        根据 key 查找对应的后端。

        Args:
            key: 路由 key (e.g. session_id, user_id)

        Returns:
            backend_name 或 None (环为空时)
        """
        with self._lock:
            if not self._ring:
                return None
            h = self._hash(key)
            # 二分查找: 第一个 >= h 的节点
            for k in self._sorted_keys:
                if h <= k:
                    return self._ring[k]
            # 回绕到环的起始
            return self._ring[self._sorted_keys[0]]

    def get_with_replicas(self, key: str, count: int = 3) -> List[str]:
        """获取 key 对应的 count 个后端 (用于故障转移)。"""
        with self._lock:
            if not self._ring:
                return []
            h = self._hash(key)
            results = []
            seen = set()
            for k in self._sorted_keys:
                name = self._ring[k]
                if name not in seen:
                    results.append(name)
                    seen.add(name)
                    if len(results) >= count:
                        break
            # 回绕
            if len(results) < count:
                for k in self._sorted_keys:
                    name = self._ring[k]
                    if name not in seen:
                        results.append(name)
                        seen.add(name)
                        if len(results) >= count:
                            break
            return results

    def get_backend_names(self) -> Set[str]:
        """获取环上所有唯一的后端名称。"""
        with self._lock:
            return set(self._ring.values())

    def clear(self):
        """清空哈希环。"""
        with self._lock:
            self._ring.clear()
            self._sorted_keys.clear()


# ═══════════════════════════════════════════════════════════
# 熔断器
# ═══════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    熔断器 — 防止级联故障。

    状态转换:
      CLOSED → (failures >= threshold) → OPEN
      OPEN → (timeout expired) → HALF_OPEN
      HALF_OPEN → (success) → CLOSED
      HALF_OPEN → (failure) → OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_state_change = time.time()
        self.half_open_requests = 0
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        """是否允许请求通过。"""
        with self._lock:
            now = time.time()

            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                if now - self.last_state_change >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_requests = 0
                    self.last_state_change = now
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_requests < self.half_open_max_requests:
                    self.half_open_requests += 1
                    return True
                return False

            return True

    def record_success(self):
        """记录成功。"""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.half_open_requests = 0
                self.last_state_change = time.time()
                logger.info("Circuit breaker reset to CLOSED (recovery confirmed)")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def record_failure(self):
        """记录失败。"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.last_state_change = time.time()
                logger.warning("Circuit breaker back to OPEN (HALF_OPEN failure)")

            elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_state_change = time.time()
                logger.warning(
                    f"Circuit breaker TRIPPED → OPEN "
                    f"({self.failure_count} failures, will retry in {self.recovery_timeout}s)"
                )

    def reset(self):
        """手动重置熔断器。"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.half_open_requests = 0
            self.last_state_change = time.time()


# ═══════════════════════════════════════════════════════════
# 健康检查器
# ═══════════════════════════════════════════════════════════

class HealthChecker:
    """
    健康检查器 — HTTP/TCP 探活。

    HTTP 检查: GET /health (或自定义路径), 期望 200 OK
    TCP 检查: 尝试 socket 连接
    """

    def __init__(
        self,
        check_interval: float = 10.0,
        timeout: float = 3.0,
        unhealthy_threshold: int = 3,
        healthy_threshold: int = 2,
    ):
        self.check_interval = check_interval
        self.timeout = timeout
        self.unhealthy_threshold = unhealthy_threshold
        self.healthy_threshold = healthy_threshold
        self._callbacks: Dict[str, Callable] = {}    # backend_name → check function
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register(self, backend_name: str, check_func: Callable[[], bool]):
        """注册自定义健康检查函数。"""
        self._callbacks[backend_name] = check_func

    def unregister(self, backend_name: str):
        """取消注册。"""
        self._callbacks.pop(backend_name, None)

    @staticmethod
    def http_check(url: str, path: str = "/health", timeout: float = 3.0) -> bool:
        """HTTP 健康检查 — 对指定 URL 发 GET 请求。"""
        try:
            full_url = url.rstrip("/") + "/" + path.lstrip("/")
            req = _urllib.Request(full_url, method="GET")
            resp = _urllib.urlopen(req, timeout=timeout)
            return 200 <= resp.status < 300
        except Exception as e:
            logger.debug(f"HTTP health check failed for {url}{path}: {e}")
            return False

    @staticmethod
    def tcp_check(host: str, port: int, timeout: float = 3.0) -> bool:
        """TCP 健康检查 — 尝试建立 socket 连接。"""
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except Exception as e:
            logger.debug(f"TCP health check failed for {host}:{port}: {e}")
            return False

    def start(self, backends: Dict[str, Backend]):
        """启动后台健康检查线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop,
            args=(backends,),
            daemon=True,
            name="health-checker",
        )
        self._thread.start()
        logger.info(f"Health checker started (interval={self.check_interval}s)")

    def stop(self):
        """停止健康检查线程。"""
        self._running = False
        logger.info("Health checker stopped")

    def _check_loop(self, backends: Dict[str, Backend]):
        """健康检查主循环。"""
        consecutive_failures: Dict[str, int] = defaultdict(int)
        consecutive_successes: Dict[str, int] = defaultdict(int)

        while self._running:
            time.sleep(self.check_interval)

            for name, backend in list(backends.items()):
                if backend.state == BackendState.OFFLINE:
                    continue

                healthy = False
                if name in self._callbacks:
                    try:
                        healthy = self._callbacks[name]()
                    except Exception as e:
                        logger.debug(f"Custom health check error for {name}: {e}")
                else:
                    # 默认: 尝试解析地址做 TCP 检查
                    healthy = self._try_default_check(backend)

                backend.last_health_check = time.time()

                if healthy:
                    consecutive_failures[name] = 0
                    consecutive_successes[name] = consecutive_successes.get(name, 0) + 1

                    if backend.state == BackendState.UNHEALTHY:
                        if consecutive_successes[name] >= self.healthy_threshold:
                            backend.state = BackendState.HEALTHY
                            backend.failure_streak = 0
                            logger.info(f"Backend {name} recovered → HEALTHY")
                else:
                    consecutive_successes[name] = 0
                    consecutive_failures[name] = consecutive_failures.get(name, 0) + 1

                    if backend.state == BackendState.HEALTHY:
                        if consecutive_failures[name] >= self.unhealthy_threshold:
                            backend.state = BackendState.UNHEALTHY
                            logger.warning(
                                f"Backend {name} marked UNHEALTHY "
                                f"({consecutive_failures[name]} consecutive failures)"
                            )

    def _try_default_check(self, backend: Backend) -> bool:
        """默认健康检查 — 尝试 TCP 连接或 HTTP GET。"""
        addr = backend.address
        # 判断是否为 HTTP URL
        if addr.startswith("http://") or addr.startswith("https://"):
            return self.http_check(addr, timeout=self.timeout)
        # 尝试解析 host:port
        try:
            if ":" in addr.replace("https://", "").replace("http://", ""):
                # 简单解析: 去掉协议后 host:port
                clean = addr.replace("https://", "").replace("http://", "")
                if ":" in clean:
                    host, port_str = clean.rsplit(":", 1)
                    port = int(port_str)
                    return self.tcp_check(host, port, timeout=self.timeout)
        except (ValueError, Exception):
            pass
        return False


# ═══════════════════════════════════════════════════════════
# LoadBalancer 主类
# ═══════════════════════════════════════════════════════════

class LoadBalancer:
    """
    智能负载均衡器 — 多策略 + 健康检查 + 故障转移 + 熔断。

    内置策略:
      - least_connections: 最少连接, 支持权重因子
      - weighted_round_robin: 加权轮询, 平滑分配
      - consistent_hash: 一致性哈希, 会话保持
      - random: 随机选择 (带权重)
    """

    def __init__(
        self,
        default_strategy: str = "least_connections",
        circuit_threshold: int = 5,
        circuit_recovery: float = 30.0,
        health_check_interval: float = 10.0,
    ):
        # 后端注册表
        self._backends: Dict[str, Backend] = OrderedDict()
        self._backends_lock = threading.Lock()

        # 默认策略
        if default_strategy not in ("least_connections", "weighted_round_robin", "consistent_hash", "random"):
            raise ValueError(f"Unknown strategy: {default_strategy}")
        self.default_strategy = default_strategy

        # 加权轮询状态
        self._wrr_index: int = 0
        self._wrr_current_weight: int = 0
        self._wrr_lock = threading.Lock()

        # 一致性哈希环
        self._hash_ring = ConsistentHashRing(virtual_nodes=150)

        # 熔断器 — 每个后端一个
        self._circuits: Dict[str, CircuitBreaker] = {}
        self._circuit_threshold = circuit_threshold
        self._circuit_recovery = circuit_recovery

        # 健康检查器
        self._health_checker = HealthChecker(
            check_interval=health_check_interval,
        )

        # 统计
        self._stats = BalancerStats()
        self._stats_lock = threading.Lock()

        # 事件回调
        self._on_failover: List[Callable] = []
        self._on_circuit_trip: List[Callable] = []
        self._on_backend_change: List[Callable] = []

        logger.info(
            f"LoadBalancer initialized (strategy={default_strategy}, "
            f"circuit_threshold={circuit_threshold})"
        )

    # ── 后端管理 ──────────────────────────────────────

    def add_backend(
        self,
        name: str,
        address: str,
        weight: int = 10,
        metadata: Optional[Dict[str, Any]] = None,
        health_check: Optional[Callable[[], bool]] = None,
    ) -> Backend:
        """
        添加后端服务节点。

        Args:
            name: 后端唯一标识
            address: 地址 (http://host:port 或 host:port)
            weight: 权重 (1-100)
            metadata: 附加元数据
            health_check: 自定义健康检查回调

        Returns:
            Backend: 创建的后端对象
        """
        with self._backends_lock:
            if name in self._backends:
                logger.warning(f"Backend {name} already exists, updating")
                return self.update_backend(name, address=address, weight=weight)

            backend = Backend(
                name=name,
                address=address,
                weight=max(1, min(100, weight)),
                metadata=metadata or {},
            )
            self._backends[name] = backend

            # 创建熔断器
            self._circuits[name] = CircuitBreaker(
                failure_threshold=self._circuit_threshold,
                recovery_timeout=self._circuit_recovery,
            )

            # 添加到一致性哈希环
            self._hash_ring.add(name, weight)

            # 注册健康检查
            if health_check:
                self._health_checker.register(name, health_check)

            # 触发回调
            for cb in self._on_backend_change:
                try:
                    cb("added", name, backend)
                except Exception:
                    pass

            logger.info(f"Backend added: {name} ({address}, weight={weight})")
            return backend

    def remove_backend(self, name: str) -> bool:
        """移除后端。"""
        with self._backends_lock:
            if name not in self._backends:
                return False
            del self._backends[name]
        self._circuits.pop(name, None)
        self._hash_ring.remove(name)
        self._health_checker.unregister(name)

        for cb in self._on_backend_change:
            try:
                cb("removed", name, None)
            except Exception:
                pass

        logger.info(f"Backend removed: {name}")
        return True

    def update_backend(
        self,
        name: str,
        address: Optional[str] = None,
        weight: Optional[int] = None,
        state: Optional[BackendState] = None,
    ) -> Optional[Backend]:
        """更新后端配置。"""
        with self._backends_lock:
            if name not in self._backends:
                return None
            b = self._backends[name]
            if address is not None:
                b.address = address
            if weight is not None:
                b.weight = max(1, min(100, weight))
                self._hash_ring.remove(name)
                self._hash_ring.add(name, b.weight)
            if state is not None:
                b.state = state
            return b

    def get_backend(self, name: str) -> Optional[Backend]:
        """获取后端信息。"""
        with self._backends_lock:
            return self._backends.get(name)

    def list_backends(self) -> List[Backend]:
        """列出所有后端。"""
        with self._backends_lock:
            return list(self._backends.values())

    def get_healthy_backends(self) -> List[Backend]:
        """获取所有健康后端 (含 degraded)。"""
        with self._backends_lock:
            return [
                b for b in self._backends.values()
                if b.state in (BackendState.HEALTHY, BackendState.DEGRADED)
            ]

    # ── 策略选择 ──────────────────────────────────────

    def select(
        self,
        strategy: Optional[str] = None,
        hash_key: Optional[str] = None,
    ) -> SelectionResult:
        """
        使用指定策略选择一个后端。

        Args:
            strategy: "least_connections" | "weighted_round_robin" | "consistent_hash" | "random"
            hash_key: 一致性哈希的 key (仅 consistent_hash 策略需要)

        Returns:
            SelectionResult: 选择结果
        """
        strategy = strategy or self.default_strategy
        if strategy not in ("least_connections", "weighted_round_robin", "consistent_hash", "random"):
            return SelectionResult(backend=None, strategy=strategy, success=False, error=f"Unknown strategy: {strategy}")

        with self._stats_lock:
            self._stats.total_selections += 1
            self._stats.strategy_usage[strategy] = self._stats.strategy_usage.get(strategy, 0) + 1
            self._stats.last_updated = time.time()

        if strategy == "least_connections":
            backend = self._select_least_connections()
        elif strategy == "weighted_round_robin":
            backend = self._select_weighted_round_robin()
        elif strategy == "consistent_hash":
            backend = self._select_consistent_hash(hash_key)
        else:  # random
            backend = self._select_random()

        if backend is None:
            with self._stats_lock:
                self._stats.total_failures += 1
            return SelectionResult(backend=None, strategy=strategy, success=False, error="No healthy backend available")

        with self._stats_lock:
            self._stats.total_successes += 1

        return SelectionResult(backend=backend, strategy=strategy, success=True)

    def select_with_failover(
        self,
        strategy: Optional[str] = None,
        hash_key: Optional[str] = None,
        max_attempts: int = 3,
    ) -> SelectionResult:
        """
        带故障转移的选择 — 失败时自动尝试下一个后端。

        当所选后端被熔断或不健康时, 自动切换到下一个候选。
        一致性哈希策略使用哈希环上的下一个节点。
        """
        strategy = strategy or self.default_strategy

        if strategy == "consistent_hash" and hash_key:
            # 一致性哈希: 沿环查找
            candidates = self._hash_ring.get_with_replicas(hash_key, max_attempts + 5)
            for name in candidates:
                backend = self.get_backend(name)
                if backend and self._is_available(backend):
                    self._increment_connections(backend)
                    return SelectionResult(backend=backend, strategy=strategy, success=True)
            return SelectionResult(backend=None, strategy=strategy, success=False, error="All hash ring candidates unavailable")

        # 其他策略: 尝试选择并验证
        for attempt in range(max_attempts):
            result = self.select(strategy=strategy, hash_key=hash_key)
            if result.success and result.backend and self._is_available(result.backend):
                return result
            # 标记并跳过当前失败的后端, 重试
            if result.backend:
                logger.debug(f"Failover: skipping {result.backend.name}, attempt {attempt + 1}")

        # 最终尝试: 排除不健康的
        healthy_backends = self.get_healthy_backends()
        available = [b for b in healthy_backends if self._is_available(b)]
        if available:
            backend = available[0]  # 任选第一个
            self._increment_connections(backend)
            return SelectionResult(backend=backend, strategy=strategy, success=True)

        return SelectionResult(backend=None, strategy=strategy, success=False, error="All backends unavailable after failover")

    # ── 内部选择算法 ──────────────────────────────────

    def _select_least_connections(self) -> Optional[Backend]:
        """最少连接选择 — 选 active_connections 最少且健康的。"""
        with self._backends_lock:
            candidates = [
                b for b in self._backends.values()
                if b.state in (BackendState.HEALTHY, BackendState.DEGRADED)
                and self._is_available(b)
            ]
            if not candidates:
                return None
            # 按 (connections / weight) 排序
            candidates.sort(key=lambda b: b.active_connections / max(1, b.weight))
            selected = candidates[0]
            self._increment_connections(selected)
            return selected

    def _select_weighted_round_robin(self) -> Optional[Backend]:
        """加权轮询 — 平滑加权轮询 (Smooth Weighted Round Robin)。"""
        with self._backends_lock:
            candidates = [
                b for b in self._backends.values()
                if b.state in (BackendState.HEALTHY, BackendState.DEGRADED)
                and self._is_available(b)
            ]
            if not candidates:
                return None

            # 计算权重最大公约数的近似
            total_weight = sum(b.weight for b in candidates)
            if total_weight == 0:
                return None

            with self._wrr_lock:
                self._wrr_index = (self._wrr_index + 1) % len(candidates)
                # 简单加权: 按权重比例跳过
                selected = candidates[self._wrr_index]

            self._increment_connections(selected)
            return selected

    def _select_consistent_hash(self, hash_key: Optional[str]) -> Optional[Backend]:
        """一致性哈希选择。"""
        key = hash_key or str(time.time())
        name = self._hash_ring.get(key)
        if name is None:
            return None
        backend = self.get_backend(name)
        if backend and backend.state in (BackendState.HEALTHY, BackendState.DEGRADED) and self._is_available(backend):
            self._increment_connections(backend)
            return backend
        # 故障转移: 尝试环上的下一个
        candidates = self._hash_ring.get_with_replicas(key, 5)
        for n in candidates:
            b = self.get_backend(n)
            if b and b.state in (BackendState.HEALTHY, BackendState.DEGRADED) and self._is_available(b):
                self._increment_connections(b)
                return b
        return None

    def _select_random(self) -> Optional[Backend]:
        """随机选择 — 带权重。"""
        import random
        with self._backends_lock:
            candidates = [
                b for b in self._backends.values()
                if b.state in (BackendState.HEALTHY, BackendState.DEGRADED)
                and self._is_available(b)
            ]
            if not candidates:
                return None
            # 权重采样
            weights = [b.weight for b in candidates]
            total = sum(weights)
            if total == 0:
                selected = random.choice(candidates)
            else:
                r = random.uniform(0, total)
                cumulative = 0
                selected = candidates[0]
                for b, w in zip(candidates, weights):
                    cumulative += w
                    if r <= cumulative:
                        selected = b
                        break
            self._increment_connections(selected)
            return selected

    # ── 熔断器集成 ────────────────────────────────────

    def _is_available(self, backend: Backend) -> bool:
        """检查后端是否可用 (熔断器状态)。"""
        if backend.name not in self._circuits:
            return True
        cb = self._circuits[backend.name]
        if backend.circuit_state == CircuitState.CLOSED:
            return True
        return cb.allow_request()

    # ── 连接追踪 ──────────────────────────────────────

    def _increment_connections(self, backend: Backend):
        """增加后端活跃连接数。"""
        backend.active_connections += 1
        backend.total_requests += 1
        backend.last_used = time.time()

    def release_connection(self, backend_name: str):
        """释放连接 (请求完成时调用)。"""
        backend = self.get_backend(backend_name)
        if backend and backend.active_connections > 0:
            backend.active_connections -= 1

    # ── 结果记录 + 动态权重 ───────────────────────────

    def record_result(
        self,
        backend_name: str,
        success: bool,
        latency_ms: float = 0.0,
    ):
        """
        记录请求结果, 用于动态权重调整和熔断。

        Args:
            backend_name: 后端名称
            success: 是否成功
            latency_ms: 响应延迟 (毫秒)
        """
        backend = self.get_backend(backend_name)
        if backend is None:
            return

        # 释放连接
        self.release_connection(backend_name)

        # 更新统计
        backend.total_latency_ms += latency_ms
        if backend.total_requests > 0:
            backend.avg_latency_ms = backend.total_latency_ms / backend.total_requests

        if success:
            backend.failure_streak = 0
            backend.total_failures = 0  # 重置, 避免无穷累积
            # 熔断器记录成功
            if backend_name in self._circuits:
                self._circuits[backend_name].record_success()
                backend.circuit_state = CircuitState.CLOSED
                backend.circuit_failures = 0

            # 动态权重调整: 低延迟 → 提升权重
            if backend.avg_latency_ms > 0 and backend.weight < 100:
                # 延迟低于 50ms 的提升权重
                if backend.avg_latency_ms < 50 and backend.weight < 100:
                    old_w = backend.weight
                    backend.weight = min(100, backend.weight + 1)
                    if backend.weight != old_w:
                        self._hash_ring.remove(backend_name)
                        self._hash_ring.add(backend_name, backend.weight)
                        logger.debug(f"Backend {backend_name} weight increased to {backend.weight}")
        else:
            backend.failure_streak += 1
            backend.total_failures += 1

            # 熔断器记录失败
            if backend_name in self._circuits:
                self._circuits[backend_name].record_failure()
                cb = self._circuits[backend_name]
                backend.circuit_failures = cb.failure_count
                if cb.state == CircuitState.OPEN:
                    backend.circuit_state = CircuitState.OPEN
                    for cb_fn in self._on_circuit_trip:
                        try:
                            cb_fn(backend_name, backend)
                        except Exception:
                            pass

            # 动态权重调整: 连续失败 → 降低权重
            if backend.failure_streak >= 3 and backend.weight > 1:
                old_w = backend.weight
                backend.weight = max(1, backend.weight - 2)
                if backend.weight != old_w:
                    self._hash_ring.remove(backend_name)
                    self._hash_ring.add(backend_name, backend.weight)
                    logger.debug(f"Backend {backend_name} weight decreased to {backend.weight}")

            # 连续失败过多 → 标记为 DEGRADED
            if backend.failure_streak >= 5:
                backend.state = BackendState.DEGRADED
                logger.warning(f"Backend {backend_name} degraded (failure streak={backend.failure_streak})")

    # ── 应急功能 ──────────────────────────────────────

    def drain_backend(self, name: str) -> bool:
        """排空后端 — 停止接受新连接, 但不中断现有连接。"""
        backend = self.get_backend(name)
        if backend:
            backend.state = BackendState.DRAINING
            logger.info(f"Backend {name} set to DRAINING")
            return True
        return False

    def reset_circuit(self, name: str) -> bool:
        """手动重置后端熔断器。"""
        if name in self._circuits:
            self._circuits[name].reset()
            backend = self.get_backend(name)
            if backend:
                backend.circuit_state = CircuitState.CLOSED
                backend.circuit_failures = 0
            logger.info(f"Circuit breaker reset for {name}")
            return True
        return False

    def reset_all_circuits(self):
        """重置所有熔断器。"""
        for cb in self._circuits.values():
            cb.reset()
        for b in self._backends.values():
            b.circuit_state = CircuitState.CLOSED
            b.circuit_failures = 0
        logger.info("All circuit breakers reset")

    # ── 健康检查 ──────────────────────────────────────

    def start_health_checks(self):
        """启动后台健康检查。"""
        self._health_checker.start(self._backends)

    def stop_health_checks(self):
        """停止后台健康检查。"""
        self._health_checker.stop()

    def run_health_check(self, name: str) -> bool:
        """手动触发单次健康检查。返回是否健康。"""
        backend = self.get_backend(name)
        if backend is None:
            return False
        healthy = self._health_checker._try_default_check(backend)
        backend.last_health_check = time.time()
        if healthy and backend.state == BackendState.UNHEALTHY:
            backend.state = BackendState.HEALTHY
        elif not healthy and backend.state == BackendState.HEALTHY:
            backend.state = BackendState.UNHEALTHY
        return healthy

    # ── 回调 ──────────────────────────────────────────

    def on_failover(self, callback: Callable):
        """注册故障转移回调。"""
        self._on_failover.append(callback)

    def on_circuit_trip(self, callback: Callable):
        """注册熔断器触发回调。"""
        self._on_circuit_trip.append(callback)

    def on_backend_change(self, callback: Callable):
        """注册后端变更回调。"""
        self._on_backend_change.append(callback)

    # ── 统计 ──────────────────────────────────────────

    def get_stats(self) -> BalancerStats:
        """获取负载均衡器统计。"""
        with self._stats_lock:
            with self._backends_lock:
                self._stats.active_backends = len(self._backends)
                self._stats.healthy_backends = sum(
                    1 for b in self._backends.values()
                    if b.state == BackendState.HEALTHY
                )
                self._stats.unhealthy_backends = sum(
                    1 for b in self._backends.values()
                    if b.state == BackendState.UNHEALTHY
                )
                self._stats.circuit_open_backends = sum(
                    1 for b in self._backends.values()
                    if b.circuit_state == CircuitState.OPEN
                )
            return self._stats

    def get_status(self) -> Dict[str, Any]:
        """
        获取负载均衡器完整状态 — 用于监控/调试端点。

        Returns:
            包含所有后端的详细状态、熔断器状态、统计信息
        """
        stats = self.get_stats()
        result: Dict[str, Any] = {
            "summary": {
                "default_strategy": self.default_strategy,
                "total_selections": stats.total_selections,
                "total_successes": stats.total_successes,
                "total_failures": stats.total_failures,
                "active_backends": stats.active_backends,
                "healthy_backends": stats.healthy_backends,
                "unhealthy_backends": stats.unhealthy_backends,
                "circuit_open_backends": stats.circuit_open_backends,
                "strategy_usage": stats.strategy_usage,
                "last_updated": stats.last_updated,
            },
            "backends": {},
        }

        for name, b in self._backends.items():
            circuit_info = {}
            if name in self._circuits:
                cb = self._circuits[name]
                circuit_info = {
                    "state": cb.state.name,
                    "failure_count": cb.failure_count,
                    "last_failure": cb.last_failure_time,
                    "half_open_requests": cb.half_open_requests,
                }

            result["backends"][name] = {
                "address": b.address,
                "weight": b.weight,
                "state": b.state.value,
                "active_connections": b.active_connections,
                "total_requests": b.total_requests,
                "total_failures": b.total_failures,
                "avg_latency_ms": round(b.avg_latency_ms, 2),
                "failure_streak": b.failure_streak,
                "circuit": circuit_info,
                "last_health_check": b.last_health_check,
                "last_used": b.last_used,
            }

        return result


# ═══════════════════════════════════════════════════════════
# 辅助: defaultdict (内联避免 import)
# ═══════════════════════════════════════════════════════════

class defaultdict(dict):
    """简易 defaultdict 替代, 避免 import 问题。"""
    def __init__(self, default_factory=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_factory = default_factory

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        value = self.default_factory()
        self[key] = value
        return value


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_load_balancer_instance: Optional[LoadBalancer] = None
_load_balancer_lock = threading.Lock()


def get_load_balancer(
    default_strategy: str = "least_connections",
    circuit_threshold: int = 5,
    circuit_recovery: float = 30.0,
    health_check_interval: float = 10.0,
) -> LoadBalancer:
    """
    获取全局 LoadBalancer 单例 (auto-create)。

    Args:
        default_strategy: 默认策略
        circuit_threshold: 熔断失败阈值
        circuit_recovery: 熔断恢复超时 (秒)
        health_check_interval: 健康检查间隔 (秒)

    Returns:
        LoadBalancer 实例
    """
    global _load_balancer_instance
    if _load_balancer_instance is None:
        with _load_balancer_lock:
            if _load_balancer_instance is None:
                _load_balancer_instance = LoadBalancer(
                    default_strategy=default_strategy,
                    circuit_threshold=circuit_threshold,
                    circuit_recovery=circuit_recovery,
                    health_check_interval=health_check_interval,
                )
    return _load_balancer_instance
