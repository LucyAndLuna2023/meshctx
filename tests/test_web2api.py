"""v3.86 Web-to-API Proxy tests"""
import pytest
from src.core.web2api import Web2APIProxy, WebAPIConfig, ProxyRequest, ProxyResponse, get_web2api


class TestWebAPIConfig:
    def test_creation(self):
        c = WebAPIConfig(name="gemini", base_url="https://gemini.google.com/api", cookie="test")
        assert c.name == "gemini"
        assert c.auth_type == "cookie"


class TestProxyRequest:
    def test_creation(self):
        req = ProxyRequest(model="gemini-pro", messages=[{"role": "user", "content": "hi"}])
        assert req.model == "gemini-pro"
        assert req.stream is False

    def test_stream_mode(self):
        req = ProxyRequest(model="test", messages=[], stream=True)
        assert req.stream is True


class TestWeb2APIProxy:
    def test_init(self):
        proxy = Web2APIProxy()
        assert proxy is not None

    def test_add_provider(self):
        proxy = Web2APIProxy()
        proxy.add_provider("test-provider", WebAPIConfig(name="test", base_url="http://localhost/test"))
        assert "test-provider" in proxy.list_providers()

    def test_list_providers_empty(self):
        proxy = Web2APIProxy()
        assert proxy.list_providers() == []

    def test_stats_initial(self):
        proxy = Web2APIProxy()
        stats = proxy.get_stats()
        assert stats["requests"] == 0
        assert stats["errors"] == 0

    def test_chat_unknown_provider(self):
        proxy = Web2APIProxy()
        with pytest.raises(ValueError, match="Unknown provider"):
            proxy.chat("nonexistent", ProxyRequest(model="x", messages=[]))

    def test_chat_stream(self):
        proxy = Web2APIProxy()
        proxy.add_provider("test", WebAPIConfig(name="test", base_url="http://localhost/test"))
        chunks = list(proxy.chat_stream("test", ProxyRequest(model="x", messages=[{"role": "user", "content": "hi"}])))
        assert len(chunks) > 0


def test_singleton():
    a1 = get_web2api()
    a2 = get_web2api()
    assert a1 is a2
