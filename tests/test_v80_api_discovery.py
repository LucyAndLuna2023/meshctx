"""v3.80 API Discovery — tests"""
import pytest
from src.core.api_docs import APIDiscoveryEngine, get_api_discovery

class TestDiscovery:
    def test_scan(self):
        e = APIDiscoveryEngine()
        endpoints = e.scan()
        assert isinstance(endpoints, list)

    def test_openapi(self):
        e = APIDiscoveryEngine()
        e.scan()
        spec = e.generate_openapi()
        assert "openapi" in spec; assert "paths" in spec

    def test_singleton(self):
        assert get_api_discovery() is get_api_discovery()
