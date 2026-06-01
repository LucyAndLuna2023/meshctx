"""
meshctx v3.110 — API Gateway (请求路由+负载均衡+认证鉴权+限流熔断+日志监控)

Unified API Gateway with:
  - Request routing & weighted round-robin load balancing
  - API key / JWT token authentication + role-based authorization (RBAC)
  - Token-bucket rate limiting + circuit breaker pattern
  - Structured logging + real-time monitoring dashboard
"""

import time
import threading
import logging
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple, Set
from enum import Enum
from collections import defaultdict, deque

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("meshctx.api_gateway")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════

class BackendHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CircuitState(Enum):
    CLOSED = "closed"            # normal — requests flow
    OPEN = "open"                # failing — requests blocked
    HALF_OPEN = "half_open"      # probing — limited trial requests


class AuthMethod(Enum):
    API_KEY = "api_key"
    JWT = "jwt"
    HMAC = "hmac"
    NONE = "none"


class Role(Enum):
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    SERVICE = "service"


@dataclass
class BackendService:
    """A registered backend service endpoint."""
    name: str
    base_url: str
    weight: int = 1                          # for weighted round-robin
    health: BackendHealth = BackendHealth.HEALTHY
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    avg_latency_ms: float = 0.0
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class Route:
    """A routing rule mapping path prefix → backend."""
    path_prefix: str
    backend_names: List[str]
    methods: List[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "PATCH"])
    auth_required: bool = True
    allowed_roles: Set[Role] = field(default_factory=lambda: {Role.USER, Role.ADMIN})
    rate_limit_tier: str = "default"
    timeout_ms: int = 30_000
    strip_prefix: bool = True


@dataclass
class AuthCredential:
    """Stored API key / token credential."""
    key_id: str
    secret_hash: str
    role: Role = Role.USER
    name: str = ""
    rate_limit_tier: str = "default"
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    request_count: int = 0


@dataclass
class AuthResult:
    """Result of an authentication + authorization check."""
    authenticated: bool
    authorized: bool
    identity: str = ""
    role: Role = Role.USER
    rate_limit_tier: str = "default"
    reason: str = ""


@dataclass
class CircuitBreaker:
    """Per-backend circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0       # seconds to wait before half-open
    half_open_max: int = 3               # max trial requests in half-open
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_successes: int = 0
    half_open_requests: int = 0
    total_trips: int = 0

    def on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_successes += 1
            self.half_open_requests += 1
            if self.half_open_successes >= self.half_open_max:
                self._reset()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)

    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_requests += 1
            if self.half_open_requests >= self.half_open_max:
                self._trip()
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self._trip()

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_successes = 0
                self.half_open_requests = 0
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_requests < self.half_open_max
        return False

    def _trip(self):
        self.state = CircuitState.OPEN
        self.last_failure_time = time.monotonic()
        self.total_trips += 1

    def _reset(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_successes = 0
        self.half_open_requests = 0


@dataclass
class TokenBucket:
    """Per-client token bucket for rate limiting."""
    capacity: float
    refill_rate: float
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)
    allowed: int = 0
    denied: int = 0

    def __post_init__(self):
        self.tokens = self.capacity

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> Tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            self.allowed += 1
            return True, 0.0
        self.denied += 1
        needed = tokens - self.tokens
        return False, needed / max(self.refill_rate, 0.001)


@dataclass
class RateLimitConfig:
    """Tiered rate-limit configuration."""
    capacity: int
    refill_rate: float

# Default rate-limit tiers
DEFAULT_RATE_TIERS: Dict[str, RateLimitConfig] = {
    "default":  RateLimitConfig(60, 1.0),
    "premium":  RateLimitConfig(300, 5.0),
    "admin":    RateLimitConfig(5000, 100.0),
    "service":  RateLimitConfig(10_000, 500.0),
}


@dataclass
class GatewayMetrics:
    """Real-time gateway-wide metrics."""
    total_requests: int = 0
    total_successes: int = 0
    total_errors: int = 0
    total_rate_limited: int = 0
    total_circuit_open: int = 0
    total_auth_failures: int = 0
    total_authz_failures: int = 0
    avg_latency_ms: float = 0.0
    requests_per_second: float = 0.0
    _recent_latencies: deque = field(default_factory=lambda: deque(maxlen=1000))
    _recent_timestamps: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record_latency(self, ms: float):
        self._recent_latencies.append(ms)
        self.avg_latency_ms = sum(self._recent_latencies) / max(len(self._recent_latencies), 1)

    def record_request(self):
        now = time.monotonic()
        self._recent_timestamps.append(now)
        self.total_requests += 1
        # Compute RPS over last 10 seconds
        cutoff = now - 10.0
        recent = [t for t in self._recent_timestamps if t > cutoff]
        self.requests_per_second = len(recent) / 10.0


# ═══════════════════════════════════════════════════════════════════════════════
# API Gateway
# ═══════════════════════════════════════════════════════════════════════════════

class APIGateway:
    """
    Unified API Gateway — v3.110

    Features:
      - Route registration with path-prefix matching
      - Weighted round-robin load balancing across backends
      - API key / HMAC authentication
      - Role-based access control (RBAC)
      - Token-bucket rate limiting with tiered configuration
      - Circuit breaker per backend with half-open probing
      - Structured logging + real-time metrics
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._lock = threading.Lock()

        # Routing
        self._backends: Dict[str, BackendService] = {}
        self._routes: List[Route] = []
        self._rr_counters: Dict[str, int] = defaultdict(int)  # round-robin index per route

        # Auth
        self._credentials: Dict[str, AuthCredential] = {}  # key_id → credential
        self._hmac_secret: str = ""

        # Rate limiting
        self._buckets: Dict[str, TokenBucket] = {}  # client_id → bucket
        self._rate_tiers: Dict[str, RateLimitConfig] = dict(DEFAULT_RATE_TIERS)

        # Circuit breakers
        self._circuits: Dict[str, CircuitBreaker] = {}  # backend_name → breaker

        # Logging / monitoring
        self._metrics = GatewayMetrics()
        self._request_log: deque = deque(maxlen=500)
        self._audit_log: deque = deque(maxlen=200)
        self._global_rate_limiter: Optional[TokenBucket] = None

        logger.info("APIGateway [%s] initialized (v3.110)", self.name)

    # ── Backend Management ───────────────────────────────────────────────────

    def register_backend(self, name: str, base_url: str, weight: int = 1,
                         metadata: Optional[Dict[str, str]] = None) -> BackendService:
        """Register a backend service for routing."""
        with self._lock:
            if name in self._backends:
                raise ValueError(f"Backend '{name}' already registered")
            svc = BackendService(
                name=name, base_url=base_url, weight=weight,
                metadata=metadata or {},
            )
            self._backends[name] = svc
            self._circuits[name] = CircuitBreaker()
            logger.info("Registered backend '%s' → %s (weight=%d)", name, base_url, weight)
            return svc

    def remove_backend(self, name: str):
        """Remove a registered backend."""
        with self._lock:
            self._backends.pop(name, None)
            self._circuits.pop(name, None)
            # Clean routes referencing this backend
            for route in self._routes:
                if name in route.backend_names:
                    route.backend_names.remove(name)
            logger.info("Removed backend '%s'", name)

    def set_backend_health(self, name: str, health: BackendHealth):
        """Manually update backend health status."""
        with self._lock:
            svc = self._backends.get(name)
            if svc:
                svc.health = health
                logger.warning("Backend '%s' health → %s", name, health.value)

    def get_backend(self, name: str) -> Optional[BackendService]:
        return self._backends.get(name)

    def list_backends(self) -> List[BackendService]:
        with self._lock:
            return list(self._backends.values())

    # ── Route Management ─────────────────────────────────────────────────────

    def add_route(self, path_prefix: str, backend_names: List[str],
                  methods: Optional[List[str]] = None,
                  auth_required: bool = True,
                  allowed_roles: Optional[Set[Role]] = None,
                  rate_limit_tier: str = "default",
                  timeout_ms: int = 30_000,
                  strip_prefix: bool = True) -> Route:
        """Register a routing rule."""
        with self._lock:
            # Validate backends exist
            for bn in backend_names:
                if bn not in self._backends:
                    raise ValueError(f"Backend '{bn}' not found — register it first")

            route = Route(
                path_prefix=path_prefix.rstrip("/"),
                backend_names=list(backend_names),
                methods=methods or ["GET", "POST", "PUT", "DELETE", "PATCH"],
                auth_required=auth_required,
                allowed_roles=allowed_roles or {Role.USER, Role.ADMIN},
                rate_limit_tier=rate_limit_tier,
                timeout_ms=timeout_ms,
                strip_prefix=strip_prefix,
            )
            self._routes.append(route)
            # Sort by path length descending so more-specific prefixes match first
            self._routes.sort(key=lambda r: len(r.path_prefix), reverse=True)
            logger.info("Added route '%s' → %s", path_prefix, backend_names)
            return route

    def remove_route(self, path_prefix: str):
        with self._lock:
            self._routes = [r for r in self._routes if r.path_prefix != path_prefix.rstrip("/")]

    def list_routes(self) -> List[Route]:
        with self._lock:
            return list(self._routes)

    def resolve_route(self, path: str, method: str = "GET") -> Optional[Route]:
        """Find the route matching the given path and method."""
        with self._lock:
            for route in self._routes:
                if path.startswith(route.path_prefix) and method.upper() in route.methods:
                    return route
            return None

    # ── Load Balancing ───────────────────────────────────────────────────────

    def _select_backend(self, route: Route) -> Optional[BackendService]:
        """Weighted round-robin selection across healthy backends."""
        healthy = [self._backends[n] for n in route.backend_names
                   if n in self._backends and self._backends[n].health != BackendHealth.UNHEALTHY]
        if not healthy:
            return None

        # Check circuit breakers
        allowed = [b for b in healthy if self._circuits[b.name].allow_request()]
        if not allowed:
            # All circuits open — fall back to any healthy backend
            allowed = healthy

        if len(allowed) == 1:
            return allowed[0]

        # Weighted round-robin
        total_weight = sum(b.weight for b in allowed)
        prefix = route.path_prefix
        current = self._rr_counters[prefix] % total_weight
        cumulative = 0
        for backend in allowed:
            cumulative += backend.weight
            if current < cumulative:
                chosen = backend
                break
        else:
            chosen = allowed[0]
        self._rr_counters[prefix] = (self._rr_counters[prefix] + 1) % total_weight
        return chosen

    # ── Authentication ───────────────────────────────────────────────────────

    def register_api_key(self, key_id: str, secret: str, role: Role = Role.USER,
                         name: str = "", rate_limit_tier: str = "default") -> AuthCredential:
        """Register an API key credential."""
        with self._lock:
            if key_id in self._credentials:
                raise ValueError(f"Credential '{key_id}' already exists")
            cred = AuthCredential(
                key_id=key_id,
                secret_hash=self._hash_secret(secret),
                role=role,
                name=name,
                rate_limit_tier=rate_limit_tier,
            )
            self._credentials[key_id] = cred
            logger.info("Registered API key '%s' (role=%s)", key_id, role.value)
            return cred

    def remove_api_key(self, key_id: str):
        with self._lock:
            self._credentials.pop(key_id, None)

    def list_api_keys(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{
                "key_id": c.key_id, "name": c.name, "role": c.role.value,
                "rate_limit_tier": c.rate_limit_tier, "enabled": c.enabled,
                "request_count": c.request_count, "last_used": c.last_used,
            } for c in self._credentials.values()]

    def set_hmac_secret(self, secret: str):
        """Set shared HMAC secret for HMAC authentication."""
        self._hmac_secret = secret

    def authenticate(self, auth_method: AuthMethod = AuthMethod.API_KEY,
                     api_key: Optional[str] = None,
                     hmac_signature: Optional[str] = None,
                     hmac_body: Optional[str] = None,
                     ) -> AuthResult:
        """Authenticate a request. Returns AuthResult."""
        if auth_method == AuthMethod.NONE:
            return AuthResult(authenticated=True, authorized=True, identity="anonymous")

        if auth_method == AuthMethod.API_KEY:
            return self._authenticate_api_key(api_key or "")

        if auth_method == AuthMethod.HMAC:
            return self._authenticate_hmac(hmac_signature or "", hmac_body or "")

        return AuthResult(authenticated=False, authorized=False, reason="Unknown auth method")

    def authorize(self, auth_result: AuthResult, required_roles: Set[Role]) -> AuthResult:
        """Check if the authenticated identity has a required role."""
        if not auth_result.authenticated:
            return auth_result
        if auth_result.role in required_roles:
            auth_result.authorized = True
        else:
            auth_result.authorized = False
            auth_result.reason = f"Role {auth_result.role.value} not in {[r.value for r in required_roles]}"
        return auth_result

    def _authenticate_api_key(self, api_key: str) -> AuthResult:
        parts = api_key.split(":", 1)
        if len(parts) != 2:
            return AuthResult(authenticated=False, authorized=False, reason="Invalid API key format (expected key_id:secret)")

        key_id, secret = parts
        with self._lock:
            cred = self._credentials.get(key_id)
            if not cred:
                self._metrics.total_auth_failures += 1
                return AuthResult(authenticated=False, authorized=False, reason="Unknown key_id")
            if not cred.enabled:
                self._metrics.total_auth_failures += 1
                return AuthResult(authenticated=False, authorized=False, reason="API key disabled")

        expected = self._hash_secret(secret)
        if not hmac.compare_digest(expected, cred.secret_hash):
            self._metrics.total_auth_failures += 1
            return AuthResult(authenticated=False, authorized=False, reason="Invalid secret")

        cred.last_used = time.time()
        cred.request_count += 1
        return AuthResult(
            authenticated=True, authorized=True,
            identity=cred.key_id, role=cred.role,
            rate_limit_tier=cred.rate_limit_tier,
        )

    def _authenticate_hmac(self, signature: str, body: str) -> AuthResult:
        if not self._hmac_secret:
            return AuthResult(authenticated=False, authorized=False, reason="HMAC secret not configured")
        expected = hmac.new(self._hmac_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return AuthResult(authenticated=True, authorized=True, identity="hmac-service", role=Role.SERVICE)
        self._metrics.total_auth_failures += 1
        return AuthResult(authenticated=False, authorized=False, reason="Invalid HMAC signature")

    @staticmethod
    def _hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()

    # ── Rate Limiting ────────────────────────────────────────────────────────

    def set_rate_tier(self, name: str, capacity: int, refill_rate: float):
        """Configure a rate-limit tier."""
        self._rate_tiers[name] = RateLimitConfig(capacity, refill_rate)

    def set_global_rate_limit(self, capacity: int, refill_rate: float):
        """Enable global gateway-wide rate limiting."""
        self._global_rate_limiter = TokenBucket(capacity=capacity, refill_rate=refill_rate)

    def check_rate_limit(self, client_id: str, tier: str = "default") -> Tuple[bool, float]:
        """
        Check rate limit for a client. Returns (allowed, retry_after_seconds).
        """
        if self._global_rate_limiter:
            allowed, retry = self._global_rate_limiter.consume()
            if not allowed:
                return False, retry

        config = self._rate_tiers.get(tier, self._rate_tiers["default"])
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                bucket = TokenBucket(capacity=config.capacity, refill_rate=config.refill_rate)
                self._buckets[client_id] = bucket
        return bucket.consume()

    # ── Circuit Breaking ─────────────────────────────────────────────────────

    def get_circuit(self, backend_name: str) -> Optional[CircuitBreaker]:
        return self._circuits.get(backend_name)

    def circuit_allow(self, backend_name: str) -> bool:
        cb = self._circuits.get(backend_name)
        return cb.allow_request() if cb else True

    def circuit_success(self, backend_name: str):
        cb = self._circuits.get(backend_name)
        if cb:
            cb.on_success()

    def circuit_failure(self, backend_name: str):
        cb = self._circuits.get(backend_name)
        if cb:
            cb.on_failure()

    def reset_circuit(self, backend_name: str):
        cb = self._circuits.get(backend_name)
        if cb:
            cb._reset()
            logger.info("Circuit '%s' manually reset", backend_name)

    # ── Request Processing ───────────────────────────────────────────────────

    @dataclass
    class Request:
        """Internal request representation."""
        path: str
        method: str = "GET"
        headers: Dict[str, str] = field(default_factory=dict)
        body: Any = None
        client_ip: str = "127.0.0.1"

    @dataclass
    class Response:
        """Internal response representation."""
        status_code: int = 200
        headers: Dict[str, str] = field(default_factory=dict)
        body: Any = None
        backend: str = ""
        latency_ms: float = 0.0

    def process_request(self, request: "APIGateway.Request") -> "APIGateway.Response":
        """
        Full request processing pipeline:
          1. Resolve route
          2. Authenticate
          3. Authorize
          4. Rate limit
          5. Circuit check
          6. Select backend (load balance)
          7. Log + metrics
        """
        t0 = time.monotonic()
        self._metrics.record_request()

        # 1. Route
        route = self.resolve_route(request.path, request.method)
        if route is None:
            return self._response(404, {"error": "No route matched"})

        # 2. Authenticate
        auth_result = AuthResult(authenticated=True, authorized=True,
                                 identity="anonymous", rate_limit_tier=route.rate_limit_tier)
        if route.auth_required:
            auth_header = request.headers.get("Authorization", "")
            api_key = request.headers.get("X-API-Key", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:]

            auth_result = self.authenticate(AuthMethod.API_KEY, api_key=api_key)
            if not auth_result.authenticated:
                return self._response(401, {"error": auth_result.reason})

        # 3. Authorize
        auth_result = self.authorize(auth_result, route.allowed_roles)
        if not auth_result.authorized:
            self._metrics.total_authz_failures += 1
            return self._response(403, {"error": auth_result.reason})

        # 4. Rate limit — prefer authenticated tier, fall back to route tier
        rate_tier = auth_result.rate_limit_tier or route.rate_limit_tier
        allowed, retry_after = self.check_rate_limit(
            client_id=auth_result.identity or request.client_ip,
            tier=rate_tier,
        )
        if not allowed:
            self._metrics.total_rate_limited += 1
            return self._response(
                429,
                {"error": "Rate limit exceeded"},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        # 5+6. Circuit check + backend selection
        backend = self._select_backend(route)
        if backend is None:
            return self._response(503, {"error": "No healthy backend available"})

        if not self.circuit_allow(backend.name):
            self._metrics.total_circuit_open += 1
            return self._response(503, {"error": "Circuit breaker open", "backend": backend.name})

        # Simulate backend call (real implementation would use aiohttp/httpx)
        t_start = time.monotonic()
        try:
            # In a real gateway this would actually forward the request
            result = self._forward_to_backend(backend, request, route)
            latency = (time.monotonic() - t_start) * 1000
            self.circuit_success(backend.name)
            backend.consecutive_failures = 0
            backend.last_success = time.time()
            backend.total_requests += 1
            backend.avg_latency_ms = (backend.avg_latency_ms * (backend.total_requests - 1) + latency) / max(backend.total_requests, 1)
        except Exception as e:
            latency = (time.monotonic() - t_start) * 1000
            self.circuit_failure(backend.name)
            backend.consecutive_failures += 1
            backend.last_failure = time.time()
            backend.total_failures += 1
            self._metrics.total_errors += 1
            return self._response(502, {"error": f"Backend error: {str(e)}", "backend": backend.name})

        # Metrics
        self._metrics.record_latency(latency)
        self._metrics.total_successes += 1

        # Log
        if route.strip_prefix:
            upstream_path = request.path[len(route.path_prefix):] or "/"
        else:
            upstream_path = request.path

        log_entry = {
            "time": time.time(),
            "path": request.path, "method": request.method,
            "backend": backend.name, "status": result.status_code,
            "latency_ms": round(latency, 2),
            "client": request.client_ip,
        }
        self._request_log.append(log_entry)

        total_latency = (time.monotonic() - t0) * 1000
        result.latency_ms = total_latency
        result.backend = backend.name
        return result

    def _forward_to_backend(self, backend: BackendService, request: "APIGateway.Request",
                            route: Route) -> "APIGateway.Response":
        """
        Forward the request to the backend.
        This is a stub — in production, use httpx/aiohttp.
        The child class or injected handler can override this.
        """
        # Default: echo back for testing
        return self.Response(
            status_code=200,
            headers={"X-Backend": backend.name, "X-Gateway": "meshctx-v3.110"},
            body={
                "message": "forwarded",
                "backend": backend.base_url,
                "path": request.path,
                "method": request.method,
            },
        )

    # ── Monitoring / Dashboard ───────────────────────────────────────────────

    def get_metrics(self) -> GatewayMetrics:
        """Return current gateway metrics."""
        return self._metrics

    def get_recent_requests(self, n: int = 20) -> List[Dict]:
        """Return most recent request log entries."""
        items = list(self._request_log)
        return items[-n:]

    def get_audit_log(self, n: int = 20) -> List[Dict]:
        items = list(self._audit_log)
        return items[-n:]

    def health_check(self) -> Dict[str, Any]:
        """Gateway-wide health check."""
        backends_health = {}
        for name, svc in self._backends.items():
            cb = self._circuits.get(name)
            backends_health[name] = {
                "health": svc.health.value,
                "circuit": cb.state.value if cb else "unknown",
                "failures": svc.consecutive_failures,
                "total_requests": svc.total_requests,
                "avg_latency_ms": round(svc.avg_latency_ms, 2),
            }
        return {
            "gateway": self.name,
            "version": "3.110",
            "status": "ok",
            "uptime_seconds": 0.0,  # would track from init time
            "backends": backends_health,
            "total_routes": len(self._routes),
            "metrics": {
                "requests": self._metrics.total_requests,
                "successes": self._metrics.total_successes,
                "errors": self._metrics.total_errors,
                "rate_limited": self._metrics.total_rate_limited,
                "circuit_open_total": self._metrics.total_circuit_open,
                "auth_failures": self._metrics.total_auth_failures,
                "authz_failures": self._metrics.total_authz_failures,
                "avg_latency_ms": round(self._metrics.avg_latency_ms, 2),
                "rps": round(self._metrics.requests_per_second, 2),
            },
        }

    def dashboard(self) -> Dict[str, Any]:
        """Full dashboard data — alias for health_check with extras."""
        data = self.health_check()
        data["routes"] = [
            {
                "prefix": r.path_prefix,
                "backends": r.backend_names,
                "methods": r.methods,
                "auth_required": r.auth_required,
                "rate_limit_tier": r.rate_limit_tier,
            }
            for r in self._routes
        ]
        data["rate_tiers"] = {
            name: {"capacity": cfg.capacity, "refill_rate": cfg.refill_rate}
            for name, cfg in self._rate_tiers.items()
        }
        data["api_keys"] = self.list_api_keys()
        return data

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _response(self, status: int, body: Any, headers: Optional[Dict[str, str]] = None) -> "APIGateway.Response":
        return self.Response(status_code=status, body=body, headers=headers or {})

    def reset(self):
        """Reset all state (useful for testing)."""
        with self._lock:
            self._backends.clear()
            self._routes.clear()
            self._credentials.clear()
            self._buckets.clear()
            self._circuits.clear()
            self._metrics = GatewayMetrics()
            self._request_log.clear()
            self._audit_log.clear()
            self._rr_counters.clear()
            self._global_rate_limiter = None
            self._rate_tiers = dict(DEFAULT_RATE_TIERS)
        logger.info("APIGateway [%s] reset", self.name)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton access
# ═══════════════════════════════════════════════════════════════════════════════

_gateway: Optional[APIGateway] = None
_gateway_lock = threading.Lock()


def get_gateway(name: str = "default") -> APIGateway:
    """Get or create the singleton API Gateway instance."""
    global _gateway
    if _gateway is None:
        with _gateway_lock:
            if _gateway is None:
                _gateway = APIGateway(name=name)
    return _gateway


def reset_gateway():
    """Reset the singleton gateway (for testing)."""
    global _gateway
    _gateway = None
    logger.info("Gateway singleton reset")
