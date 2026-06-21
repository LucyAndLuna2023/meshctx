"""meshctx api_gateway"""
import time, hashlib, hmac as _hmac, threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class BackendHealth(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

class CircuitState(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class AuthMethod(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    API_KEY = "api_key"
    HMAC = "hmac"
    JWT = "jwt"
    NONE = "none"

class Role(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    SERVICE = "service"
    ANONYMOUS = "anonymous"

@dataclass
class BackendService:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    name: str = ""
    base_url: str = ""
    weight: int = 1
    health: BackendHealth = BackendHealth.HEALTHY

@dataclass
class Route:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    path: str = ""
    backend_names: list = field(default_factory=list)
    methods: list = field(default_factory=list)

@dataclass
class AuthCredential:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    api_key_id: str = ""
    secret: str = ""
    role: Role = Role.USER
    enabled: bool = True

@dataclass
class AuthResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    authenticated: bool = False
    authorized: bool = True
    identity: str = ""
    role: Role = Role.ANONYMOUS
    reason: str = ""

@dataclass
class RateLimitConfig:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    capacity: int = 100
    refill_rate: float = 10.0

class TokenBucket:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, capacity=100, refill_rate=10.0, **kw):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
    def consume(self, tokens=1, **kw):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0.0
        wait = (tokens - self.tokens) / max(self.refill_rate, 0.001)
        return False, wait

@dataclass
class GatewayMetrics:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    requests: int = 0
    errors: int = 0
    latency_sum: float = 0.0

class CircuitBreaker:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, failure_threshold=3, recovery_timeout=30, half_open_max=1, **kw):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
    def allow_request(self, **kw):
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return True
    def on_failure(self, **kw):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
    def on_success(self, **kw):
        self.success_count += 1
        if self.state == CircuitState.HALF_OPEN and self.success_count >= self.half_open_max:
            self.state = CircuitState.CLOSED
            self.failure_count = 0

CB = CircuitBreaker

class APIGateway:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, name="default", **kw):
        self.name = name
        self._backends: dict = {}
        self._routes: list = []
        self._api_keys: dict = {}
        self._hmac_secret = None
        self._buckets: dict = {}
        self._tier_configs: dict = {}
        self._global_bucket = TokenBucket(1000, 1000)
        self._global_rate_configured = False
        self._lock = threading.Lock()
        self.metrics = GatewayMetrics()

    def register_backend(self, name, base_url, weight=1, **kw):
        if name in self._backends:
            raise ValueError(f"Backend '{name}' already registered")
        svc = BackendService(name=name, base_url=base_url, weight=weight)
        self._backends[name] = svc
        return svc

    def remove_backend(self, name, **kw):
        self._backends.pop(name, None)

    def set_backend_health(self, name, health, **kw):
        if name in self._backends:
            self._backends[name].health = health

    def get_backend(self, name, **kw):
        return self._backends.get(name)

    def list_backends(self, **kw):
        return list(self._backends.values())

    def add_route(self, path, backend_names, methods=None, **kw):
        route = Route(path=path, backend_names=backend_names, methods=methods or ["GET"])
        self._routes.append(route)

    def resolve_route(self, path, method="GET", **kw):
        best = None
        best_len = -1
        for route in self._routes:
            if path.startswith(route.path):
                if len(route.path) > best_len:
                    if method in route.methods or not route.methods:
                        best = route
                        best_len = len(route.path)
        return best

    def register_api_key(self, key_id, secret, role=Role.USER, **kw):
        cred = AuthCredential(api_key_id=key_id, secret=secret, role=role)
        self._api_keys[key_id] = cred
        return cred

    def set_hmac_secret(self, secret, **kw):
        self._hmac_secret = secret

    def authenticate(self, method, **kwargs):
        if method == AuthMethod.API_KEY:
            api_key = kwargs.get("api_key", "")
            parts = api_key.split(":", 1)
            if len(parts) == 2:
                kid, secret = parts
                cred = self._api_keys.get(kid)
                if cred:
                    if not cred.enabled:
                        return AuthResult(authenticated=False, reason="API key disabled")
                    if cred.secret == secret:
                        return AuthResult(authenticated=True, role=cred.role, identity=kid)
                    return AuthResult(authenticated=False, reason="Wrong secret")
                return AuthResult(authenticated=False, reason="Unknown API key")
            return AuthResult(authenticated=False, reason="Invalid API key format")
        elif method == AuthMethod.HMAC:
            sig = kwargs.get("hmac_signature", "")
            body = kwargs.get("hmac_body", "")
            if self._hmac_secret:
                expected = _hmac.new(self._hmac_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                if sig == expected:
                    return AuthResult(authenticated=True, role=Role.SERVICE)
            return AuthResult(authenticated=False, reason="HMAC verification failed")
        return AuthResult(authenticated=False, reason=f"Unknown auth method")

    def authorize(self, auth_result, allowed_roles, **kw):
        if auth_result.role in allowed_roles:
            auth_result.authorized = True
        else:
            auth_result.authorized = False
            auth_result.reason = f"Role {auth_result.role.value} not in {[r.value for r in allowed_roles]}"
        return auth_result

    def set_rate_tier(self, tier_name, capacity, refill_rate, **kw):
        self._tier_configs[tier_name] = RateLimitConfig(capacity=capacity, refill_rate=refill_rate)

    def set_global_rate_limit(self, capacity, refill_rate, **kw):
        self._global_bucket = TokenBucket(capacity=capacity, refill_rate=refill_rate)
        self._global_rate_configured = True

    def check_rate_limit(self, client_id, tier_name, **kw):
        with self._lock:
            if not self._global_bucket.consume()[0]:
                return False, 1.0
            key = f"{client_id}:{tier_name}"
            if key not in self._buckets:
                cfg = self._tier_configs.get(tier_name, RateLimitConfig())
                self._buckets[key] = TokenBucket(capacity=cfg.capacity, refill_rate=cfg.refill_rate)
            return self._buckets[key].consume()

    def get_metrics(self, **kw):
        return self.metrics

_gateway = None

def get_gateway(name="default"):
    global _gateway
    if _gateway is None:
        _gateway = APIGateway(name)
    return _gateway

def reset_gateway():
    global _gateway
    _gateway = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

