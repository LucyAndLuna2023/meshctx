import pytest

@pytest.fixture(autouse=True)
def _reset_global_state():
    """每个测试后重置全局单例，防止测试间状态污染。"""
    yield
    import importlib
    try:
        from src.core.kernel import Kernel
        Kernel._instance = None
    except Exception:
        pass

@pytest.fixture(scope="function")
def server_url(request):
    return "http://localhost:3000"
