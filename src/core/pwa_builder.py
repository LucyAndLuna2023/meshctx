"""meshctx PWA Builder — Progressive Web App manifest, service worker, install prompts, push notifications."""

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Optional


# ── Enums ────────────────────────────────────────────────────────────────────

class DisplayMode(Enum):
    STANDALONE = "standalone"
    FULLSCREEN = "fullscreen"
    MINIMAL_UI = "minimal-ui"
    BROWSER = "browser"


class IconPurpose(Enum):
    ANY = "any"
    MASKABLE = "maskable"
    MONOCHROME = "monochrome"


class CacheStrategy(Enum):
    NETWORK_FIRST = "networkFirst"
    CACHE_FIRST = "cacheFirst"
    STALE_WHILE_REVALIDATE = "staleWhileRevalidate"
    NETWORK_ONLY = "networkOnly"
    CACHE_ONLY = "cacheOnly"


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class PWAIcon:
    src: str = ""
    sizes: str = ""
    type: str = "image/png"
    purpose: IconPurpose = IconPurpose.ANY


@dataclass
class PWAShortcut:
    name: str = ""
    url: str = ""
    description: str = ""


@dataclass
class SWCacheRule:
    url_pattern: str = ""
    strategy: CacheStrategy = CacheStrategy.NETWORK_FIRST
    max_age_seconds: int = 3600


@dataclass
class PushSubscription:
    endpoint: str = ""
    keys: dict = field(default_factory=dict)


@dataclass
class PushNotification:
    title: str = ""
    body: str = ""
    tag: str = ""
    vibrate: list = field(default_factory=list)
    require_interaction: bool = False

    def to_dict(self) -> dict:
        d = {"title": self.title, "body": self.body}
        if self.tag:
            d["tag"] = self.tag
        if self.vibrate:
            d["vibrate"] = self.vibrate
        if self.require_interaction:
            d["requireInteraction"] = self.require_interaction
        return d


@dataclass
class PWAManifestConfig:
    name: str = "MeshCtx PWA"
    short_name: str = "MeshCtx"
    description: str = ""
    start_url: str = "/"
    display: DisplayMode = DisplayMode.STANDALONE
    background_color: str = "#ffffff"
    theme_color: str = "#1976d2"
    lang: str = "zh-CN"
    icons: list = field(default_factory=lambda: [
        PWAIcon(src="/icons/icon-192.png", sizes="192x192", type="image/png"),
        PWAIcon(src="/icons/icon-256.png", sizes="256x256", type="image/png"),
        PWAIcon(src="/icons/icon-512.png", sizes="512x512", type="image/png"),
    ])
    shortcuts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "short_name": self.short_name,
            "start_url": self.start_url,
            "display": self.display.value,
            "lang": self.lang,
            "background_color": self.background_color,
            "theme_color": self.theme_color,
        }
        if self.description:
            d["description"] = self.description
        if self.icons:
            d["icons"] = [
                {"src": i.src, "sizes": i.sizes, "type": i.type, "purpose": i.purpose.value}
                for i in self.icons
            ]
        if self.shortcuts:
            d["shortcuts"] = [
                {"name": s.name, "url": s.url, "description": s.description}
                for s in self.shortcuts
            ]
        return d


# ── InstallPromptManager ────────────────────────────────────────────────────

class InstallPromptManager:
    def __init__(self):
        self._deferred_prompt = None
        self._max_prompts = 3
        self._prompt_shown_count = 0
        self._callbacks: list = []

    def capture_prompt(self, event: dict) -> bool:
        self._deferred_prompt = event
        return True

    def can_show_prompt(self) -> bool:
        return self._deferred_prompt is not None and self._prompt_shown_count < self._max_prompts

    def get_prompt(self) -> Optional[dict]:
        if not self.can_show_prompt():
            return None
        self._prompt_shown_count += 1
        return self._deferred_prompt

    def confirm_install(self) -> dict:
        result = {"outcome": "accepted", "platform": "web"}
        self._fire_callbacks(result)
        self._deferred_prompt = None
        return result

    def dismiss_install(self) -> dict:
        result = {"outcome": "dismissed", "platform": "web"}
        self._fire_callbacks(result)
        return result

    def on_install(self, callback) -> None:
        self._callbacks.append(callback)

    def _fire_callbacks(self, event: dict) -> None:
        for cb in self._callbacks:
            cb(event)

    def generate_install_banner_js(self) -> str:
        return """\
(function() {
  var deferredPrompt;
  window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    deferredPrompt = e;
    var banner = document.getElementById('pwa-install-banner');
    if (banner) banner.style.display = 'block';
  });
  window.addEventListener('appinstalled', function() {
    var banner = document.getElementById('pwa-install-banner');
    if (banner) banner.style.display = 'none';
  });
})();
"""

    def reset(self) -> None:
        self._deferred_prompt = None
        self._prompt_shown_count = 0


# ── PushManager ──────────────────────────────────────────────────────────────

class PushManager:
    def __init__(self):
        self._vapid_public_key: str = ""
        self._vapid_private_key: str = ""
        self._subscriptions: dict = {}
        self._notification_queue: list = []

    def set_vapid_keys(self, public_key: str, private_key: str) -> None:
        self._vapid_public_key = public_key
        self._vapid_private_key = private_key

    def get_vapid_public_key(self) -> str:
        return self._vapid_public_key

    def subscribe(self, subscription: PushSubscription) -> None:
        self._subscriptions[subscription.endpoint] = subscription

    def get_subscriptions(self) -> list:
        return list(self._subscriptions.values())

    def unsubscribe(self, endpoint: str) -> bool:
        if endpoint in self._subscriptions:
            del self._subscriptions[endpoint]
            return True
        return False

    def queue_notification(self, notification: PushNotification) -> None:
        self._notification_queue.append(notification)

    def flush_notifications(self) -> list:
        out = list(self._notification_queue)
        self._notification_queue.clear()
        return out

    def generate_sw_push_js(self) -> str:
        return """\
self.addEventListener('push', function(event) {
  var data = event.data ? event.data.json() : {};
  var options = {
    body: data.body || '',
    icon: data.icon || '/icons/icon-192.png',
    badge: data.badge || '/icons/badge.png',
    tag: data.tag || '',
    vibrate: data.vibrate || [200, 100, 200],
    data: data.data || {},
    requireInteraction: data.require_interaction || false
  };
  event.waitUntil(
    self.registration.showNotification(data.title || 'MeshCtx', options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({type: 'window'}).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url === '/' && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/');
      }
    })
  );
});
"""


# ── PWABuilder ──────────────────────────────────────────────────────────────

class PWABuilder:
    VERSION = "3.91.0"

    def __init__(self, config: Optional[PWAManifestConfig] = None):
        self._config: PWAManifestConfig = config if config is not None else PWAManifestConfig()
        self._precache_urls: list = ["/"]
        self._cache_rules: list = []
        self._extra_sw_code: list = []
        self._push_manager: PushManager = PushManager()
        self._install_manager: InstallPromptManager = InstallPromptManager()

    def get_config(self) -> PWAManifestConfig:
        return self._config

    def set_config(self, config: PWAManifestConfig) -> None:
        self._config = config

    def generate_manifest(self) -> str:
        return json.dumps(self._config.to_dict(), ensure_ascii=False)

    def generate_manifest_html(self) -> str:
        return '<link rel="manifest" href="/manifest.json">'

    def validate_manifest(self) -> list:
        issues = []
        cfg = self._config
        if not cfg.name:
            issues.append("name is required")
        if not cfg.short_name:
            issues.append("short_name is required")
        return issues

    def add_icon(self, icon: PWAIcon) -> None:
        self._config.icons.append(icon)

    def add_shortcut(self, shortcut: PWAShortcut) -> None:
        self._config.shortcuts.append(shortcut)

    def set_precache_urls(self, urls: list) -> None:
        self._precache_urls = list(urls)

    def add_cache_rule(self, rule: SWCacheRule) -> None:
        self._cache_rules.append(rule)

    def add_extra_sw_code(self, code: str) -> None:
        self._extra_sw_code.append(code)

    def get_push_manager(self) -> PushManager:
        return self._push_manager

    def _cache_rules_js(self) -> str:
        lines = []
        for rule in self._cache_rules:
            escaped = rule.url_pattern.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(
                f'  if (path.startsWith("{escaped}")) return {rule.strategy.value}(request, {rule.max_age_seconds});'
            )
        return "\n".join(lines)

    def _make_precache_list_js(self) -> str:
        return ",\n".join(f'    "{url}"' for url in self._precache_urls)

    def generate_strategy_helpers_js(self) -> str:
        return """\
async function cacheFirst(request, maxAge) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function networkFirst(request, maxAge) {
  try {
    const response = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    return cached || new Response('', {status: 408});
  }
}

async function staleWhileRevalidate(request, maxAge) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then(function(response) {
    if (response.ok) cache.put(request, response.clone());
    return response;
  });
  return cached || fetchPromise;
}

async function networkOnly(request, maxAge) {
  return fetch(request);
}

async function cacheOnly(request, maxAge) {
  const cache = await caches.open(CACHE_NAME);
  return cache.match(request);
}
"""

    def generate_service_worker(self) -> str:
        precache_list = self._make_precache_list_js()
        cache_rules = self._cache_rules_js()
        extra_code = "\n".join(self._extra_sw_code)

        sw = f"""\
const CACHE_NAME = 'meshctx-pwa-v3.91';
const PRECACHE_URLS = [
{precache_list}
];

// ── Strategy Helpers ──
{self.generate_strategy_helpers_js()}

// ── Install ──
self.addEventListener('install', function(event) {{
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {{
      return cache.addAll(PRECACHE_URLS);
    }})
  );
}});

// ── Activate ──
self.addEventListener('activate', function(event) {{
  event.waitUntil(
    caches.keys().then(function(keys) {{
      return Promise.all(
        keys.filter(function(key) {{ return key !== CACHE_NAME; }})
            .map(function(key) {{ return caches.delete(key); }})
      );
    }})
  );
}});

// ── Fetch ──
self.addEventListener('fetch', function(event) {{
  const request = event.request;
  const url = new URL(request.url);
  const path = url.pathname;

{cache_rules or "  // network-only fallback"}

  event.respondWith(fetch(request));
}});

{self._push_manager.generate_sw_push_js()}

{extra_code}
"""
        return sw

    def generate_push_subscribe_js(self) -> str:
        vapid_key = self._push_manager.get_vapid_public_key()
        return f"""\
function subscribeToPush() {{
  return navigator.serviceWorker.ready.then(function(registration) {{
    return registration.pushManager.subscribe({{
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array('{vapid_key}')
    }});
  }});
}}
"""

    def generate_register_sw_js(self, sw_path: str = "/sw.js") -> str:
        return f"""\
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('{sw_path}').then(function(reg) {{
    console.log('SW registered:', reg.scope);
  }}).catch(function(err) {{
    console.error('SW registration failed:', err);
  }});
}}
"""

    def generate_index_html_snippet(self) -> str:
        parts = [
            self.generate_manifest_html(),
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
            '<meta name="apple-mobile-web-app-title" content="MeshCtx">',
            '<link rel="apple-touch-icon" href="/icons/icon-192.png">',
        ]
        if self._push_manager.get_vapid_public_key():
            parts.append(f"<script>{self.generate_push_subscribe_js()}</script>")
        parts.append(f"<script>{self.generate_register_sw_js()}</script>")
        return "\n".join(parts)

    def generate_full_html_snippet(self) -> str:
        parts = [
            self.generate_manifest_html(),
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
            '<meta name="apple-mobile-web-app-title" content="MeshCtx">',
            '<link rel="apple-touch-icon" href="/icons/icon-192.png">',
            '<meta name="theme-color" content="#1976d2">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        ]
        parts.append(f"<script>{self.generate_register_sw_js()}</script>")

        if self._push_manager.get_vapid_public_key():
            parts.append(f"<script>{self.generate_push_subscribe_js()}</script>")
        
        parts.append(f"<script>{self._install_manager.generate_install_banner_js()}</script>")
        return "\n".join(parts)

    def generate_all(self) -> dict:
        return {
            "manifest.json": self.generate_manifest(),
            "sw.js": self.generate_service_worker(),
            "index.html_snippet": self.generate_index_html_snippet(),
            "sw_helpers.js": self.generate_strategy_helpers_js(),
        }

    def get_stats(self) -> dict:
        return {
            "version": self.VERSION,
            "cache_rules": len(self._cache_rules),
            "precache_urls": len(self._precache_urls),
            "icons": len(self._config.icons),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_builder: Optional[PWABuilder] = None


def get_pwa_builder() -> PWABuilder:
    global _builder
    if _builder is None:
        _builder = PWABuilder()
    return _builder


def reset_pwa_builder() -> None:
    global _builder
    _builder = None
