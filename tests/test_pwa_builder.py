"""v3.91 PWA Manifest Builder tests"""
import json
import pytest
from src.core.pwa_builder import (
    PWABuilder, PWAManifestConfig, PWAIcon, PWAShortcut,
    SWCacheRule, CacheStrategy, DisplayMode, IconPurpose,
    InstallPromptManager, PushManager, PushSubscription, PushNotification,
    get_pwa_builder, reset_pwa_builder,
)


class TestPWAManifestConfig:
    def test_defaults(self):
        cfg = PWAManifestConfig()
        assert cfg.name == "MeshCtx PWA"
        assert cfg.display == DisplayMode.STANDALONE
        assert cfg.lang == "zh-CN"

    def test_to_dict_minimal(self):
        cfg = PWAManifestConfig(name="TestApp", short_name="Test", start_url="/app")
        d = cfg.to_dict()
        assert d["name"] == "TestApp"
        assert d["short_name"] == "Test"
        assert d["start_url"] == "/app"
        assert d["display"] == "standalone"

    def test_to_dict_with_shortcuts(self):
        cfg = PWAManifestConfig(name="App", short_name="App")
        cfg.shortcuts = [
            PWAShortcut(name="Home", url="/", description="Go home")
        ]
        d = cfg.to_dict()
        assert len(d["shortcuts"]) == 1
        assert d["shortcuts"][0]["name"] == "Home"


class TestPWABuilderManifest:
    """1) Manifest生成"""

    def test_generate_manifest_default(self):
        builder = PWABuilder()
        manifest = builder.generate_manifest()
        data = json.loads(manifest)
        assert data["name"] == "MeshCtx PWA"
        assert data["short_name"] == "MeshCtx"
        assert "icons" in data
        assert len(data["icons"]) >= 2

    def test_generate_manifest_custom(self):
        cfg = PWAManifestConfig(
            name="MyApp", short_name="MyApp",
            description="A test app", start_url="/home",
            background_color="#111", theme_color="#222",
        )
        builder = PWABuilder(cfg)
        manifest = builder.generate_manifest()
        data = json.loads(manifest)
        assert data["name"] == "MyApp"
        assert data["background_color"] == "#111"
        assert data["theme_color"] == "#222"
        assert data["start_url"] == "/home"

    def test_add_icon(self):
        builder = PWABuilder()
        builder.add_icon(PWAIcon(src="/icon-256.png", sizes="256x256"))
        cfg = builder.get_config()
        # 3 defaults + 1 new = 4
        assert len(cfg.icons) == 4

    def test_generate_manifest_html(self):
        builder = PWABuilder()
        html = builder.generate_manifest_html()
        assert '<link rel="manifest"' in html
        assert 'href="/manifest.json"' in html

    def test_validate_manifest_ok(self):
        builder = PWABuilder()
        issues = builder.validate_manifest()
        assert issues == []

    def test_validate_manifest_missing_name(self):
        cfg = PWAManifestConfig(name="", short_name="")
        builder = PWABuilder(cfg)
        issues = builder.validate_manifest()
        assert any("name is required" in i for i in issues)
        assert any("short_name is required" in i for i in issues)


class TestPWABuilderServiceWorker:
    """2) Service Worker + 离线缓存"""

    def test_generate_sw_default(self):
        builder = PWABuilder()
        sw = builder.generate_service_worker()
        assert "CACHE_NAME = 'meshctx-pwa-v3.91'" in sw
        assert "self.addEventListener('install'" in sw
        assert "self.addEventListener('activate'" in sw
        assert "self.addEventListener('fetch'" in sw

    def test_generate_sw_with_precache(self):
        builder = PWABuilder()
        builder.set_precache_urls(["/", "/styles.css", "/app.js"])
        sw = builder.generate_service_worker()
        assert '"/"' in sw
        assert '"/styles.css"' in sw
        assert '"/app.js"' in sw

    def test_generate_sw_with_cache_rules(self):
        builder = PWABuilder()
        builder.add_cache_rule(SWCacheRule(
            url_pattern="/api/", strategy=CacheStrategy.NETWORK_FIRST, max_age_seconds=3600
        ))
        builder.add_cache_rule(SWCacheRule(
            url_pattern="/static/", strategy=CacheStrategy.CACHE_FIRST, max_age_seconds=86400
        ))
        sw = builder.generate_service_worker()
        assert 'path.startsWith("/api/")' in sw
        assert 'networkFirst' in sw
        assert 'path.startsWith("/static/")' in sw
        assert 'cacheFirst' in sw

    def test_generate_sw_no_cache_rules(self):
        builder = PWABuilder()
        sw = builder.generate_service_worker()
        assert "network-only fallback" in sw or "fetch(event.request)" in sw

    def test_strategy_helpers_js(self):
        builder = PWABuilder()
        helpers = builder.generate_strategy_helpers_js()
        assert "cacheFirst" in helpers
        assert "networkFirst" in helpers
        assert "staleWhileRevalidate" in helpers
        assert "networkOnly" in helpers
        assert "cacheOnly" in helpers

    def test_add_extra_sw_code(self):
        builder = PWABuilder()
        builder.add_extra_sw_code("console.log('custom');")
        sw = builder.generate_service_worker()
        assert "console.log('custom')" in sw


class TestInstallPrompt:
    """3) 安装提示"""

    def test_capture_prompt(self):
        mgr = InstallPromptManager()
        assert mgr.capture_prompt({"platforms": ["web"]})
        assert mgr._deferred_prompt is not None

    def test_can_show_prompt_no_capture(self):
        mgr = InstallPromptManager()
        assert not mgr.can_show_prompt()

    def test_can_show_prompt_after_capture(self):
        mgr = InstallPromptManager()
        mgr.capture_prompt({"platforms": ["web"]})
        assert mgr.can_show_prompt()

    def test_max_prompts_exceeded(self):
        mgr = InstallPromptManager()
        mgr._max_prompts = 2
        mgr.capture_prompt({"platforms": ["web"]})
        assert mgr.can_show_prompt()
        mgr.get_prompt()  # 1st
        assert mgr.can_show_prompt()
        mgr.get_prompt()  # 2nd
        assert not mgr.can_show_prompt()

    def test_confirm_install(self):
        mgr = InstallPromptManager()
        mgr.capture_prompt({"platforms": ["web"]})
        result = mgr.confirm_install()
        assert result["outcome"] == "accepted"
        assert mgr._deferred_prompt is None

    def test_dismiss_install(self):
        mgr = InstallPromptManager()
        mgr.capture_prompt({"platforms": ["web"]})
        result = mgr.dismiss_install()
        assert result["outcome"] == "dismissed"

    def test_on_install_callback(self):
        mgr = InstallPromptManager()
        events = []
        mgr.on_install(lambda e: events.append(e))
        mgr.capture_prompt({"platforms": ["web"]})
        mgr.confirm_install()
        assert len(events) == 1
        assert events[0]["outcome"] == "accepted"

    def test_install_banner_js(self):
        mgr = InstallPromptManager()
        js = mgr.generate_install_banner_js()
        assert "beforeinstallprompt" in js
        assert "pwa-install-banner" in js

    def test_reset(self):
        mgr = InstallPromptManager()
        mgr.capture_prompt({})
        mgr._prompt_shown_count = 5
        mgr.reset()
        assert mgr._deferred_prompt is None
        assert mgr._prompt_shown_count == 0


class TestPushNotifications:
    """4) 推送通知"""

    def test_set_vapid_keys(self):
        mgr = PushManager()
        mgr.set_vapid_keys("pub_key_123", "priv_key_456")
        assert mgr.get_vapid_public_key() == "pub_key_123"

    def test_subscribe(self):
        mgr = PushManager()
        sub = PushSubscription(endpoint="https://push.example.com/1", keys={"p256dh": "a", "auth": "b"})
        mgr.subscribe(sub)
        assert len(mgr.get_subscriptions()) == 1
        assert mgr.get_subscriptions()[0].endpoint == "https://push.example.com/1"

    def test_subscribe_duplicate_updates(self):
        mgr = PushManager()
        sub1 = PushSubscription(endpoint="https://push.example.com/1", keys={"p256dh": "a"})
        sub2 = PushSubscription(endpoint="https://push.example.com/1", keys={"p256dh": "b"})
        mgr.subscribe(sub1)
        mgr.subscribe(sub2)
        subs = mgr.get_subscriptions()
        assert len(subs) == 1
        assert subs[0].keys["p256dh"] == "b"

    def test_unsubscribe(self):
        mgr = PushManager()
        mgr.subscribe(PushSubscription(endpoint="ep1", keys={}))
        mgr.subscribe(PushSubscription(endpoint="ep2", keys={}))
        assert mgr.unsubscribe("ep1") is True
        assert len(mgr.get_subscriptions()) == 1

    def test_unsubscribe_nonexistent(self):
        mgr = PushManager()
        assert mgr.unsubscribe("nonexistent") is False

    def test_queue_and_flush_notifications(self):
        mgr = PushManager()
        n1 = PushNotification(title="Hello", body="World")
        n2 = PushNotification(title="Test")
        mgr.queue_notification(n1)
        mgr.queue_notification(n2)
        flushed = mgr.flush_notifications()
        assert len(flushed) == 2
        assert flushed[0].title == "Hello"
        assert flushed[1].title == "Test"
        assert len(mgr.flush_notifications()) == 0  # queue empty now

    def test_push_notification_to_dict(self):
        n = PushNotification(
            title="Alert", body="Something happened", tag="important",
            vibrate=[200, 100, 200], require_interaction=True,
        )
        d = n.to_dict()
        assert d["title"] == "Alert"
        assert d["body"] == "Something happened"
        assert d["tag"] == "important"
        assert d["vibrate"] == [200, 100, 200]

    def test_sw_push_js(self):
        mgr = PushManager()
        js = mgr.generate_sw_push_js()
        assert "self.addEventListener('push'" in js
        assert "notificationclick" in js
        assert "showNotification" in js

    def test_push_subscribe_js(self):
        builder = PWABuilder()
        builder.get_push_manager().set_vapid_keys("ABC123", "secret")
        js = builder.generate_push_subscribe_js()
        assert "ABC123" in js
        assert "pushManager.subscribe" in js


class TestPWABuilderFull:
    """5) 端到端集成"""

    def test_generate_all(self):
        builder = PWABuilder()
        builder.set_precache_urls(["/", "/app.css"])
        builder.add_cache_rule(SWCacheRule(url_pattern="/images/", strategy=CacheStrategy.CACHE_FIRST))
        builder.get_push_manager().set_vapid_keys("test-pub-key", "test-priv-key")

        result = builder.generate_all()
        assert "manifest.json" in result
        assert "sw.js" in result
        assert "index.html_snippet" in result
        assert "sw_helpers.js" in result

        # manifest.json is valid JSON
        manifest = json.loads(result["manifest.json"])
        assert manifest["name"] == "MeshCtx PWA"

        # sw.js contains push handler
        assert "notificationclick" in result["sw.js"]

        # HTML snippet contains all tags
        assert '<link rel="manifest"' in result["index.html_snippet"]
        assert "register('" in result["index.html_snippet"]
        assert "subscribeToPush" in result["index.html_snippet"]

    def test_full_html_snippet(self):
        builder = PWABuilder()
        snippet = builder.generate_full_html_snippet()
        assert "manifest.json" in snippet
        assert "serviceWorker" in snippet
        assert "apple-mobile-web-app-capable" in snippet
        assert "beforeinstallprompt" in snippet

    def test_get_stats(self):
        builder = PWABuilder()
        builder.add_cache_rule(SWCacheRule(url_pattern="/css/", strategy=CacheStrategy.CACHE_FIRST))
        builder.add_cache_rule(SWCacheRule(url_pattern="/js/", strategy=CacheStrategy.NETWORK_FIRST))
        builder.set_precache_urls(["/", "/app.js", "/style.css"])
        stats = builder.get_stats()
        assert stats["version"] == "3.91.0"
        assert stats["cache_rules"] == 2
        assert stats["precache_urls"] == 3
        assert stats["icons"] >= 2

    def test_singleton(self):
        reset_pwa_builder()
        b1 = get_pwa_builder()
        b2 = get_pwa_builder()
        assert b1 is b2
        reset_pwa_builder()

    def test_set_config_updates(self):
        builder = PWABuilder()
        new_cfg = PWAManifestConfig(name="Updated", short_name="Up")
        builder.set_config(new_cfg)
        assert builder.get_config().name == "Updated"

    def test_add_shortcut(self):
        builder = PWABuilder()
        builder.add_shortcut(PWAShortcut(name="Settings", url="/settings", description="Settings page"))
        assert len(builder.get_config().shortcuts) == 1

    def test_generate_register_sw_js(self):
        builder = PWABuilder()
        js = builder.generate_register_sw_js("/custom-sw.js")
        assert "'/custom-sw.js'" in js
        assert "serviceWorker" in js
