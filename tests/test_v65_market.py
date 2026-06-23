"""v2.65 Plugin Marketplace — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mkt(tmp_path):
    from src.core.plugin_market import PluginMarketplace
    return PluginMarketplace(data_dir=tmp_path / "plugins")


class TestSearch:
    def test_search_all(self, mkt):
        results = mkt.search()
        assert len(results) >= 14

    def test_search_by_name(self, mkt):
        results = mkt.search("slack")
        assert len(results) >= 1
        assert results[0].name == "slack-gateway"

    def test_search_by_category(self, mkt):
        results = mkt.search(category="gateway")
        assert len(results) >= 3
        for r in results:
            assert r.category == "gateway"

    def test_search_no_match(self, mkt):
        results = mkt.search("nonexistent_plugin_xyz")
        assert len(results) == 0


class TestInstall:
    def test_install_success(self, mkt):
        # Disable actual pip install for testing
        mkt._OFFICIAL_PLUGINS["slack-gateway"].install_command = ""
        result = mkt.install("slack-gateway")
        assert result["success"] is True
        assert "安装成功" in result["message"]

    def test_install_duplicate(self, mkt):
        mkt._OFFICIAL_PLUGINS["slack-gateway"].install_command = ""
        mkt.install("slack-gateway")
        result = mkt.install("slack-gateway")
        assert result["success"] is False

    def test_install_nonexistent(self, mkt):
        result = mkt.install("unicorn-plugin")
        assert result["success"] is False

    def test_install_increments_downloads(self, mkt):
        mkt._OFFICIAL_PLUGINS["slack-gateway"].install_command = ""
        mkt.install("slack-gateway")
        plugin = mkt._installed["slack-gateway"]
        assert plugin.downloads >= 1

    def test_install_multiple(self, mkt):
        for p in ["slack-gateway","discord-gateway","telegram-gateway"]:
            mkt._OFFICIAL_PLUGINS[p].install_command = ""
            mkt.install(p)
        installed = mkt.list_installed()
        assert len(installed) == 3


class TestUninstall:
    def test_uninstall_success(self, mkt):
        mkt.install("slack-gateway")
        result = mkt.uninstall("slack-gateway")
        assert result["success"] is True

    def test_uninstall_not_installed(self, mkt):
        result = mkt.uninstall("slack-gateway")
        assert result["success"] is False


class TestEnableDisable:
    def test_disable(self, mkt):
        mkt.install("slack-gateway")
        result = mkt.disable("slack-gateway")
        assert result["success"] is True

    def test_enable(self, mkt):
        mkt.install("slack-gateway")
        mkt.disable("slack-gateway")
        result = mkt.enable("slack-gateway")
        assert result["success"] is True


class TestCategories:
    def test_get_categories(self, mkt):
        cats = mkt.get_categories()
        assert "gateway" in cats
        assert "memory" in cats
        assert "security" in cats
        assert "tools" in cats
        assert len(cats) >= 4


class TestStats:
    def test_stats(self, mkt):
        mkt.install("slack-gateway")
        mkt.install("discord-gateway")
        stats = mkt.get_stats()
        assert stats["total_plugins"] >= 14
        assert stats["installed"] == 2
        assert stats["active"] == 2
        assert "one_liner" in stats

    def test_empty_stats(self, mkt):
        stats = mkt.get_stats()
        assert stats["installed"] == 0


class TestPersistence:
    def test_state_persists(self, tmp_path):
        from src.core.plugin_market import PluginMarketplace
        m1 = PluginMarketplace(data_dir=tmp_path / "p1")
        m1._OFFICIAL_PLUGINS["slack-gateway"].install_command = ""
        m1.install("slack-gateway")

        m2 = PluginMarketplace(data_dir=tmp_path / "p1")
        installed = m2.list_installed()
        assert len(installed) == 1
        assert installed[0].name == "slack-gateway"


class TestPluginInfo:
    def test_all_plugins_have_versions(self, mkt):
        for name, p in mkt._OFFICIAL_PLUGINS.items():
            assert p.version != "", f"{name} 缺少版本号"
            assert p.description != "", f"{name} 缺少描述"
            assert p.category in ("gateway","memory","security","tools","monitoring"), \
                f"{name} 类别无效: {p.category}"
