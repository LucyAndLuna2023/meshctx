"""pytest configuration for UI tests."""
import pytest
try:
    import playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


def pytest_collection_modifyitems(config, items):
    for item in items:
        if 'ui' in item.keywords and not _HAS_PLAYWRIGHT:
            item.add_marker(pytest.mark.skip(reason='playwright not installed, skipping UI tests'))


@pytest.fixture
def server_url(base_url: str) -> str:
    """Provide server_url from base_url (set via --base-url)."""
    return base_url
