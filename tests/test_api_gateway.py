"""v3.110 API Gateway tests"""
import time
import pytest
from src.core.api_gateway import (
    APIGateway,
    BackendService,
    BackendHealth,
    Route,
    CircuitBreaker,
    CircuitState,
    CircuitBreaker as CB,
    AuthCredential,
    AuthResult,
    AuthMethod,
    Role,
    TokenBucket,
    RateLimitConfig,
    GatewayMetrics,
    get_gateway,
    reset_gateway,
)


class TestBackendRegistration:
    """注册 + 移除后端服务"""

    def test_register_backend(self):
        gw = APIGateway("test")
        svc = gw.register_backend("api-v1", "http://localhost:8001", weight=3)
        assert svc.name == "api-v1"
        assert svc.base_url == "http://localhost:8001"
        assert svc.weight == 3
        assert len(gw.list_backends()) == 1

    def test_register_duplicate_raises(self):
        gw = APIGateway("test")
        gw.register_backend("api", "http://localhost:8001")
        with pytest.raises(ValueError, match="already registered"):
            gw.register_backend("api", "http://localhost:8002")

    def test_remove_backend(self):
        gw = APIGateway("test")
        gw.register_backend("api", "http://localhost:8001")
        gw.remove_backend("api")
        assert len(gw.list_backends()) == 0

    def test_set_backend_health(self):
        gw = APIGateway("test")
        gw.register_backend("api", "http://localhost:8001")
        gw.set_backend_health("api", BackendHealth.UNHEALTHY)
        assert gw.get_backend("api").health == BackendHealth.UNHEALTHY


class TestRouting:
    """路由解析 + 负载均衡"""

    def test_add_route_and_resolve(self):
        gw = APIGateway("test")
        gw.register_backend("users", "http://users:8001")
        gw.register_backend("orders", "http://orders:8002")
        gw.add_route("/api/users", ["users"], methods=["GET", "POST"])
        gw.add_route("/api/orders", ["orders"])

        r = gw.resolve_route("/api/users/123", "GET")
        assert r is not None
        assert r.backend_names == ["users"]

        r2 = gw.resolve_route("/api/orders/99", "POST")
        assert r2 is not None
        assert r2.backend_names == ["orders"]

    def test_resolve_unknown_path_returns_none(self):
        gw = APIGateway("test")
        assert gw.resolve_route("/nonexistent") is None

    def test_method_not_matched(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api/data", ["svc"], methods=["GET"])
        # POST not in allowed methods
        assert gw.resolve_route("/api/data", "POST") is None
        # GET is
        assert gw.resolve_route("/api/data", "GET") is not None

    def test_longest_prefix_matched_first(self):
        gw = APIGateway("test")
        gw.register_backend("general", "http://general:80")
        gw.register_backend("admin", "http://admin:80")
        gw.add_route("/api", ["general"])
        gw.add_route("/api/admin", ["admin"])
        r = gw.resolve_route("/api/admin/users", "GET")
        assert r.backend_names == ["admin"]


class TestAuth:
    """认证 + 鉴权"""

    def test_api_key_auth_success(self):
        gw = APIGateway("test")
        gw.register_api_key("k1", "secret123", role=Role.ADMIN)
        result = gw.authenticate(AuthMethod.API_KEY, api_key="k1:secret123")
        assert result.authenticated is True
        assert result.role == Role.ADMIN

    def test_api_key_auth_bad_secret(self):
        gw = APIGateway("test")
        gw.register_api_key("k1", "secret123")
        result = gw.authenticate(AuthMethod.API_KEY, api_key="k1:wrong")
        assert result.authenticated is False

    def test_api_key_auth_disabled(self):
        gw = APIGateway("test")
        cred = gw.register_api_key("k1", "secret123")
        cred.enabled = False
        result = gw.authenticate(AuthMethod.API_KEY, api_key="k1:secret123")
        assert result.authenticated is False
        assert "disabled" in result.reason.lower()

    def test_api_key_auth_unknown_id(self):
        gw = APIGateway("test")
        result = gw.authenticate(AuthMethod.API_KEY, api_key="unknown:key")
        assert result.authenticated is False

    def test_role_authorization(self):
        gw = APIGateway("test")
        auth_ok = AuthResult(authenticated=True, authorized=True,
                             identity="u1", role=Role.READONLY)
        r = gw.authorize(auth_ok, {Role.USER, Role.ADMIN})
        assert r.authorized is False

        r2 = gw.authorize(auth_ok, {Role.READONLY, Role.USER})
        assert r2.authorized is True

    def test_hmac_auth(self):
        gw = APIGateway("test")
        gw.set_hmac_secret("shared-key")
        import hmac as _hmac, hashlib
        body = '{"action":"test"}'
        sig = _hmac.new(b"shared-key", body.encode(), hashlib.sha256).hexdigest()
        result = gw.authenticate(AuthMethod.HMAC, hmac_signature=sig, hmac_body=body)
        assert result.authenticated is True
        assert result.role == Role.SERVICE


class TestRateLimiting:
    """限流"""

    def test_rate_limit_allows_under_limit(self):
        gw = APIGateway("test")
        gw.set_rate_tier("test-tier", capacity=5, refill_rate=100)
        for i in range(5):
            allowed, retry = gw.check_rate_limit("client-1", "test-tier")
            assert allowed is True, f"request {i} should be allowed"
            assert retry == 0.0

    def test_rate_limit_blocks_after_exhaustion(self):
        gw = APIGateway("test")
        gw.set_rate_tier("test-tier", capacity=3, refill_rate=0.001)
        for _ in range(3):
            assert gw.check_rate_limit("client-2", "test-tier")[0] is True
        allowed, retry = gw.check_rate_limit("client-2", "test-tier")
        assert allowed is False
        assert retry > 0

    def test_global_rate_limit(self):
        gw = APIGateway("test")
        gw.set_global_rate_limit(2, 0.001)
        gw.set_rate_tier("test-tier", 100, 100)
        assert gw.check_rate_limit("a", "test-tier")[0] is True
        assert gw.check_rate_limit("b", "test-tier")[0] is True
        # 3rd global request blocked even though per-client has tokens
        assert gw.check_rate_limit("c", "test-tier")[0] is False


class TestCircuitBreaker:
    """熔断器"""

    def test_initial_state_closed(self):
        cb = CB(failure_threshold=3, recovery_timeout=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_trips_after_threshold(self):
        cb = CB(failure_threshold=2, recovery_timeout=30)
        cb.on_failure()
        assert cb.state == CircuitState.CLOSED
        cb.on_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_and_recovery(self):
        cb = CB(failure_threshold=1, recovery_timeout=0.01, half_open_max=2)
        cb.on_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        # Now should allow half-open probe
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN
        cb.on_success()
        cb.on_success()
        # After half_open_max successes, reset to CLOSED
        assert cb.state == CircuitState.CLOSED

    def test_half_open_fails_back_to_open(self):
        cb = CB(failure_threshold=1, recovery_timeout=0.01, half_open_max=2)
        cb.on_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        cb.allow_request()
        cb.on_failure()
        cb.on_failure()  # second failure in half-open
        assert cb.state == CircuitState.OPEN

    def test_reset_circuit(self):
        cb = CB(failure_threshold=1, recovery_timeout=60)
        cb.on_failure()
        assert cb.state == CircuitState.OPEN
        cb._reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestTokenBucket:
    """令牌桶基础行为"""

    def test_initial_tokens_at_capacity(self):
        tb = TokenBucket(capacity=100, refill_rate=10)
        assert tb.tokens == 100

    def test_consume_reduces_tokens(self):
        tb = TokenBucket(capacity=50, refill_rate=10)
        ok, retry = tb.consume(10)
        assert ok is True
        assert retry == 0.0
        assert tb.tokens == 40

    def test_tokens_never_exceed_capacity(self):
        tb = TokenBucket(capacity=10, refill_rate=100)
        tb.tokens = 5
        tb.last_refill = time.monotonic() - 10
        tb._refill()
        assert tb.tokens == 10


class TestFullPipeline:
    """端到端请求处理流水线"""

    def test_full_request_success(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api", ["svc"], auth_required=False)
        req = APIGateway.Request(path="/api/users", method="GET")
        resp = gw.process_request(req)
        assert resp.status_code == 200
        assert resp.backend == "svc"

    def test_request_blocked_by_auth(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/secure", ["svc"], auth_required=True)
        req = APIGateway.Request(path="/secure/data")
        resp = gw.process_request(req)
        assert resp.status_code == 401

    def test_request_blocked_by_rate_limit(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api", ["svc"], auth_required=False, rate_limit_tier="test")
        gw.set_rate_tier("test", capacity=1, refill_rate=0.001)
        # First request OK
        req1 = APIGateway.Request(path="/api/test", method="GET")
        r1 = gw.process_request(req1)
        assert r1.status_code == 200
        # Second blocked
        req2 = APIGateway.Request(path="/api/test2", method="GET")
        r2 = gw.process_request(req2)
        assert r2.status_code == 429

    def test_request_fails_when_backend_down(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api", ["svc"], auth_required=False)
        # Mark all backends unhealthy
        gw.set_backend_health("svc", BackendHealth.UNHEALTHY)
        req = APIGateway.Request(path="/api/data")
        resp = gw.process_request(req)
        assert resp.status_code == 503

    def test_authorization_blocks_wrong_role(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/admin", ["svc"], auth_required=True,
                     allowed_roles={Role.ADMIN})
        gw.register_api_key("user1", "pass1", role=Role.USER)
        req = APIGateway.Request(
            path="/admin/data",
            headers={"X-API-Key": "user1:pass1"},
        )
        resp = gw.process_request(req)
        assert resp.status_code == 403


class TestMonitoring:
    """监控 + 仪表盘"""

    def test_metrics_after_requests(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api", ["svc"], auth_required=False)
        for _ in range(5):
            gw.process_request(APIGateway.Request(path="/api/test"))
        m = gw.get_metrics()
        assert m.total_requests == 5
        assert m.total_successes == 5

    def test_dashboard_includes_routes_and_backends(self):
        gw = APIGateway("test")
        gw.register_backend("api", "http://api:8000")
        gw.add_route("/v1", ["api"])
        dash = gw.dashboard()
        assert dash["status"] == "ok"
        assert len(dash["routes"]) == 1
        assert "api" in dash["backends"]

    def test_recent_requests_log(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        gw.add_route("/api", ["svc"], auth_required=False)
        for i in range(3):
            gw.process_request(APIGateway.Request(path=f"/api/item/{i}"))
        log = gw.get_recent_requests(10)
        assert len(log) == 3
        assert log[0]["path"] == "/api/item/0"

    def test_health_check_returns_circuit_state(self):
        gw = APIGateway("test")
        gw.register_backend("svc", "http://svc:8000")
        hc = gw.health_check()
        assert hc["gateway"] == "test"
        assert hc["backends"]["svc"]["circuit"] == "closed"


class TestSingleton:
    """单例访问"""

    def test_get_gateway_returns_same_instance(self):
        reset_gateway()
        g1 = get_gateway("main")
        g2 = get_gateway("main")
        assert g1 is g2

    def test_reset_gateway(self):
        reset_gateway()
        g1 = get_gateway()
        reset_gateway()
        g2 = get_gateway()
        assert g1 is not g2
