"""v2.90 Proxy Manager — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def proxy(tmp_path):
    from src.core.proxy import ProxyManager
    return ProxyManager(config_path=tmp_path / "proxy_config.json")


class TestBackendManagement:
    def test_get_backends(self, proxy):
        backends = proxy.get_backends()
        assert len(backends) == 3
        assert all("host" in b and "port" in b for b in backends)

    def test_add_backend(self, proxy):
        backend = proxy.add_backend("10.0.0.1", 9090, weight=1.5)
        assert backend["host"] == "10.0.0.1"
        assert backend["port"] == 9090
        assert backend["weight"] == 1.5
        assert backend["healthy"] is True
        assert len(proxy.get_backends()) == 4

    def test_remove_backend(self, proxy):
        assert proxy.remove_backend("127.0.0.1", 8083) is True
        assert proxy.remove_backend("10.0.0.99", 9999) is False

    def test_get_healthy_backends(self, proxy):
        healthy = proxy.get_healthy_backends()
        assert len(healthy) == 2
        for b in healthy:
            assert b["healthy"] is True
            assert b["port"] != 8083


class TestHealthCheck:
    def test_health_check(self, proxy):
        result = proxy.health_check()
        assert result["total"] == 3
        assert result["healthy"] == 2
        assert result["unhealthy"] == 1
        assert result["status"] == "DEGRADED"

    def test_mark_unhealthy(self, proxy):
        assert proxy.mark_unhealthy("127.0.0.1", 8081) is True
        result = proxy.health_check()
        assert result["healthy"] == 1
        assert result["status"] == "DEGRADED"

    def test_mark_healthy(self, proxy):
        assert proxy.mark_healthy("127.0.0.1", 8083) is True
        result = proxy.health_check()
        assert result["healthy"] == 3
        assert result["status"] == "OK"

    def test_mark_nonexistent(self, proxy):
        assert proxy.mark_unhealthy("1.2.3.4", 9999) is False
        assert proxy.mark_healthy("1.2.3.4", 9999) is False


class TestRouting:
    def test_add_and_get_route(self, proxy):
        proxy.add_route("/api/v1", "backend_main")
        assert proxy.get_route("/api/v1") == "backend_main"
        assert proxy.get_route("/nonexistent") is None

    def test_list_routes(self, proxy):
        proxy.add_route("/api/users", "users_backend")
        proxy.add_route("/api/orders", "orders_backend")
        routes = proxy.list_routes()
        assert len(routes) == 2
        assert routes["/api/users"] == "users_backend"


class TestLoadBalancing:
    def test_round_robin(self, proxy):
        b1 = proxy.round_robin()
        b2 = proxy.round_robin()
        assert b1 is not None
        assert b2 is not None
        assert b1["healthy"] and b2["healthy"]

    def test_round_robin_cycles(self, proxy):
        # Get 4 assignments — should cycle through the 2 healthy backends
        results = [proxy.round_robin() for _ in range(4)]
        assert all(r is not None for r in results)
        ports = [r["port"] for r in results]
        assert 8083 not in ports  # unhealthy backend

    def test_weighted_select(self, proxy):
        backend = proxy.weighted_select()
        assert backend is not None
        assert backend["healthy"] is True
        # Highest weight among healthy backends is 1.0 (port 8081)
        assert backend["port"] == 8081

    def test_no_healthy_backends(self, proxy):
        proxy.mark_unhealthy("127.0.0.1", 8081)
        proxy.mark_unhealthy("127.0.0.1", 8082)
        assert proxy.round_robin() is None
        assert proxy.weighted_select() is None


class TestProxyRequest:
    def test_proxy_request_success(self, proxy):
        result = proxy.proxy_request("/api/test", "POST")
        assert result["status"] == 200
        assert result["method"] == "POST"
        assert result["path"] == "/api/test"
        assert "127.0.0.1" in result["backend"]

    def test_proxy_request_no_backends(self, proxy):
        proxy.mark_unhealthy("127.0.0.1", 8081)
        proxy.mark_unhealthy("127.0.0.1", 8082)
        result = proxy.proxy_request("/api/fail")
        assert result["status"] == 503
        assert "error" in result


class TestStats:
    def test_stats(self, proxy):
        proxy.proxy_request("/api/health")
        proxy.proxy_request("/api/data")
        stats = proxy.get_stats()
        assert stats["total_requests"] >= 2
        assert "error_rate" in stats
        assert "healthy_backends" in stats
        assert "backend_status" in stats
