"""v3.102 Plugin Market tests — 14 test cases"""
import time
import pytest
from src.core.plugin_market import (
    PluginMarket,
    PluginEntry,
    PluginVersion,
    PluginReview,
    get_plugin_market,
    reset_plugin_market,
)


# ============================================================
# Helpers
# ============================================================

def _make_entry(plugin_id: str, name: str = "", versions=None, **kw) -> PluginEntry:
    """Quick PluginEntry factory"""
    return PluginEntry(
        plugin_id=plugin_id,
        name=name or plugin_id,
        versions=versions or [PluginVersion(1, 0, 0)],
        **kw,
    )


def _make_version(s: str, **kw) -> PluginVersion:
    """Quick PluginVersion factory from string like '1.2.3'"""
    v = PluginVersion.parse(s)
    for k, val in kw.items():
        setattr(v, k, val)
    return v


# ============================================================
# PluginVersion Tests
# ============================================================

class TestPluginVersion:
    def test_parse_and_str(self):
        v = PluginVersion.parse("1.2.3")
        assert str(v) == "v1.2.3"
        assert v.to_tuple() == (1, 2, 3)

    def test_parse_with_v_prefix(self):
        v = PluginVersion.parse("v2.0.1")
        assert v.major == 2
        assert v.minor == 0
        assert v.patch == 1

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            PluginVersion.parse("1.2")

    def test_comparison_operators(self):
        v1 = _make_version("1.0.0")
        v2 = _make_version("1.1.0")
        v3 = _make_version("2.0.0")
        assert v2 > v1
        assert v1 < v2
        assert v3 >= v2
        assert v1 <= v2
        assert v1 == PluginVersion.parse("1.0.0")
        assert v1 != v2

    def test_sorting(self):
        versions = [
            _make_version("2.0.0"),
            _make_version("1.0.0"),
            _make_version("1.5.0"),
        ]
        versions.sort()
        assert [str(v) for v in versions] == ["v1.0.0", "v1.5.0", "v2.0.0"]


# ============================================================
# PluginEntry Tests
# ============================================================

class TestPluginEntry:
    def test_latest_version(self):
        entry = _make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("1.2.0"),
            _make_version("1.1.0"),
        ])
        assert str(entry.latest_version) == "v1.2.0"

    def test_latest_version_empty(self):
        entry = PluginEntry(plugin_id="p2", name="Empty")
        assert entry.latest_version is None

    def test_average_rating_empty(self):
        entry = _make_entry("p3")
        assert entry.average_rating == 0.0

    def test_average_rating_with_reviews(self):
        entry = _make_entry("p4")
        entry.add_review(PluginReview(user_id="u1", rating=4))
        entry.add_review(PluginReview(user_id="u2", rating=5))
        assert entry.average_rating == 4.5
        assert entry.review_count == 2

    def test_add_version_avoids_duplicates(self):
        entry = _make_entry("p5", versions=[_make_version("1.0.0")])
        entry.add_version(_make_version("1.0.0", changelog="Updated"))
        assert len(entry.versions) == 1
        assert entry.versions[0].changelog == "Updated"


# ============================================================
# 1) Plugin Registration / Discovery
# ============================================================

class TestRegistration:
    def test_register_and_get(self):
        market = PluginMarket()
        market.register(_make_entry("test-plugin", "Test Plugin", tags=["ai"]))
        entry = market.get("test-plugin")
        assert entry is not None
        assert entry.name == "Test Plugin"
        assert "ai" in entry.tags

    def test_register_merges_existing(self):
        market = PluginMarket()
        e1 = _make_entry("p1", "First", tags=["ai"])
        e2 = _make_entry("p1", "Updated", tags=["ml"], versions=[_make_version("2.0.0")])
        market.register(e1)
        market.register(e2)
        entry = market.get("p1")
        assert entry.name == "First"  # original name preserved
        assert set(entry.tags) == {"ai", "ml"}
        assert len(entry.versions) == 2

    def test_unregister(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        assert market.unregister("p1") is True
        assert market.get("p1") is None
        assert market.unregister("nonexistent") is False

    def test_discover_by_query(self):
        market = PluginMarket()
        market.register(_make_entry("p1", "Image Generator"))
        market.register(_make_entry("p2", "Text Analyzer"))
        market.register(_make_entry("p3", "Image Resizer"))
        results = market.discover(query="image")
        assert len(results) == 2
        names = {p.name for p in results}
        assert "Image Generator" in names
        assert "Image Resizer" in names

    def test_discover_by_category(self):
        market = PluginMarket()
        market.register(_make_entry("p1", category="ai"))
        market.register(_make_entry("p2", category="ui"))
        market.register(_make_entry("p3", category="ai"))
        results = market.discover(category="ai")
        assert len(results) == 2

    def test_discover_by_tags(self):
        market = PluginMarket()
        market.register(_make_entry("p1", tags=["ai", "image"]))
        market.register(_make_entry("p2", tags=["ai", "text"]))
        market.register(_make_entry("p3", tags=["image"]))
        results = market.discover(tags=["ai", "image"])
        assert len(results) == 1
        assert results[0].plugin_id == "p1"

    def test_discover_installed_only(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.register(_make_entry("p2"))
        market.install("p1")
        results = market.discover(installed_only=True)
        assert len(results) == 1
        assert results[0].plugin_id == "p1"

    def test_discover_sort_by_rating(self):
        market = PluginMarket()
        p1 = _make_entry("p1", "A")
        p1.add_review(PluginReview(user_id="u1", rating=5))
        p2 = _make_entry("p2", "B")
        p2.add_review(PluginReview(user_id="u1", rating=3))
        market.register(p1)
        market.register(p2)
        results = market.discover(sort_by="rating")
        assert results[0].plugin_id == "p1"
        assert results[1].plugin_id == "p2"

    def test_search(self):
        market = PluginMarket()
        market.register(_make_entry("p1", "Super Plugin"))
        market.register(_make_entry("p2", "Mega Tool"))
        assert len(market.search("super")) == 1
        assert len(market.search("xyz")) == 0


# ============================================================
# 2) One-Click Install
# ============================================================

class TestInstall:
    def test_install_success(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[_make_version("1.0.0")]))
        result = market.install("p1")
        assert result["success"] is True
        assert result["version_installed"] == "v1.0.0"
        entry = market.get("p1")
        assert entry.installed is True

    def test_install_not_found(self):
        market = PluginMarket()
        result = market.install("nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_install_dependencies(self):
        market = PluginMarket()
        market.register(_make_entry("dep-a", versions=[_make_version("1.0.0")]))
        market.register(_make_entry("main", versions=[_make_version("1.0.0")],
                                   dependencies=["dep-a"]))
        result = market.install("main")
        assert result["success"] is True
        assert "dep-a" in result["dependencies_installed"]
        assert market.get("dep-a").installed is True

    def test_install_specific_version(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("2.0.0"),
        ]))
        result = market.install("p1", version="1.0.0")
        assert result["success"] is True
        assert result["version_installed"] == "v1.0.0"

    def test_install_version_not_found(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[_make_version("1.0.0")]))
        result = market.install("p1", version="9.9.9")
        assert result["success"] is False

    def test_uninstall(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.install("p1")
        assert market.get("p1").installed is True
        result = market.uninstall("p1")
        assert result["success"] is True
        assert market.get("p1").installed is False

    def test_uninstall_not_installed(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        result = market.uninstall("p1")
        assert result["success"] is False

    def test_resolve_dependencies(self):
        market = PluginMarket()
        market.register(_make_entry("a"))
        market.register(_make_entry("b", dependencies=["a"]))
        market.register(_make_entry("c", dependencies=["b"]))
        resolved = market.resolve_dependencies("c")
        assert resolved == ["a", "b", "c"]  # depth-first post-order


# ============================================================
# 3) Rating + Reviews
# ============================================================

class TestReviews:
    def test_add_review(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        result = market.add_review("p1", PluginReview(user_id="u1", rating=4, comment="Nice!"))
        assert result["success"] is True

    def test_duplicate_review_blocked(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.add_review("p1", PluginReview(user_id="u1", rating=4))
        result = market.add_review("p1", PluginReview(user_id="u1", rating=3))
        assert result["success"] is False
        assert "already reviewed" in result["error"]

    def test_review_not_found_plugin(self):
        market = PluginMarket()
        result = market.add_review("ghost", PluginReview(user_id="u1", rating=5))
        assert result["success"] is False

    def test_get_rating_distribution(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.add_review("p1", PluginReview(user_id="u1", rating=5))
        market.add_review("p1", PluginReview(user_id="u2", rating=4))
        market.add_review("p1", PluginReview(user_id="u3", rating=5))
        rating = market.get_rating("p1")
        assert rating["average"] == pytest.approx(4.67, 0.01)
        assert rating["count"] == 3
        assert rating["distribution"][5] == 2
        assert rating["distribution"][4] == 1

    def test_get_reviews_sort_newest(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.add_review("p1", PluginReview(user_id="u1", rating=3, comment="Old"))
        time.sleep(0.01)
        market.add_review("p1", PluginReview(user_id="u2", rating=5, comment="New"))
        reviews = market.get_reviews("p1", sort_by="newest")
        assert reviews[0].comment == "New"

    def test_flag_and_helpful(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.add_review("p1", PluginReview(user_id="u1", rating=3))
        assert market.flag_review("p1", "u1") is True
        assert market.flag_review("p1", "ghost") is False
        assert market.mark_review_helpful("p1", "u1") is True
        assert market.get_reviews("p1")[0].helpful_count == 1

    def test_invalid_rating_raises(self):
        with pytest.raises(ValueError):
            PluginReview(user_id="u1", rating=0)
        with pytest.raises(ValueError):
            PluginReview(user_id="u1", rating=6)


# ============================================================
# 4) Version Management
# ============================================================

class TestVersionManagement:
    def test_get_versions_sorted(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("2.0.0"),
            _make_version("1.5.0"),
        ]))
        versions = market.get_versions("p1")
        assert [str(v) for v in versions] == ["v2.0.0", "v1.5.0", "v1.0.0"]

    def test_check_updates(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("1.1.0"),
        ]))
        market.install("p1", version="1.0.0")
        updates = market.check_updates()
        assert len(updates) == 1
        assert updates[0]["plugin_id"] == "p1"
        assert updates[0]["installed"] == "v1.0.0"
        assert updates[0]["latest"] == "v1.1.0"

    def test_check_updates_none_when_latest(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[_make_version("2.0.0")]))
        market.install("p1")
        assert market.check_updates() == []

    def test_update_plugin(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("2.0.0"),
        ]))
        market.install("p1", version="1.0.0")
        result = market.update_plugin("p1")
        assert result["success"] is True
        assert result["version_installed"] == "v2.0.0"

    def test_update_already_latest(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[_make_version("1.0.0")]))
        market.install("p1")
        result = market.update_plugin("p1")
        assert result["success"] is False

    def test_rollback(self):
        market = PluginMarket()
        market.register(_make_entry("p1", versions=[
            _make_version("1.0.0"),
            _make_version("2.0.0"),
        ]))
        market.install("p1", version="2.0.0")
        result = market.rollback("p1", "1.0.0")
        assert result["success"] is True
        assert result["version_installed"] == "v1.0.0"

    def test_compare_versions(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        result = market.compare_versions("p1", "1.0.0", "2.0.0")
        assert result["comparison"] == "older"
        result = market.compare_versions("p1", "3.0.0", "1.0.0")
        assert result["comparison"] == "newer"
        result = market.compare_versions("p1", "1.0.0", "1.0.0")
        assert result["comparison"] == "equal"


# ============================================================
# Stats & Top Lists
# ============================================================

class TestStats:
    def test_stats_empty(self):
        market = PluginMarket()
        s = market.stats()
        assert s["total_plugins"] == 0
        assert s["installed_plugins"] == 0

    def test_stats_with_plugins(self):
        market = PluginMarket()
        market.register(_make_entry("p1", category="ai"))
        market.register(_make_entry("p2", category="ui"))
        market.install("p1")
        s = market.stats()
        assert s["total_plugins"] == 2
        assert s["installed_plugins"] == 1
        assert s["total_downloads"] == 1

    def test_top_rated(self):
        market = PluginMarket()
        p1 = _make_entry("p1")
        p1.add_review(PluginReview(user_id="u1", rating=5))
        p2 = _make_entry("p2")
        p2.add_review(PluginReview(user_id="u1", rating=2))
        market.register(p1)
        market.register(p2)
        top = market.top_rated()
        assert top[0].plugin_id == "p1"

    def test_top_downloaded(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.register(_make_entry("p2"))
        market.install("p2")
        # Duplicate install rejected (entry.installed guard)
        result = market.install("p2")
        assert not result["success"]  # already installed
        market.install("p1")
        top = market.top_downloaded()
        # Both have count=1, order by registration (p1 first)
        assert top[0].plugin_id == "p1"
        assert top[1].plugin_id == "p2"

    def test_reset(self):
        market = PluginMarket()
        market.register(_make_entry("p1"))
        market.install("p1")
        market.reset()
        assert market.stats()["total_plugins"] == 0
        assert market.get("p1") is None


# ============================================================
# Singleton Tests
# ============================================================

class TestSingleton:
    def test_singleton_same_instance(self):
        reset_plugin_market()
        m1 = get_plugin_market()
        m2 = get_plugin_market()
        assert m1 is m2
        reset_plugin_market()

    def test_reset_creates_new(self):
        reset_plugin_market()
        m1 = get_plugin_market()
        m1.register(_make_entry("p1"))
        reset_plugin_market()
        m2 = get_plugin_market()
        assert m1 is not m2
        assert m2.stats()["total_plugins"] == 0
        reset_plugin_market()
