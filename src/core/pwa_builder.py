"""
meshctx v3.91 — PWA Manifest Builder (渐进式Web应用生成器)

自动生成manifest.json + sw.js，支持离线缓存策略、
安装提示检测与推送通知集成。
"""

import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Literal, Callable, Any
from enum import Enum

logger = logging.getLogger("meshctx.pwa_builder")


class CacheStrategy(str, Enum):
    """离线缓存策略"""
    CACHE_FIRST = "cache_first"
    NETWORK_FIRST = "network_first"
    STALE_WHILE_REVALIDATE = "stale_while_revalidate"
    NETWORK_ONLY = "network_only"
    CACHE_ONLY = "cache_only"


class DisplayMode(str, Enum):
    """PWA显示模式"""
    STANDALONE = "standalone"
    FULLSCREEN = "fullscreen"
    MINIMAL_UI = "minimal-ui"
    BROWSER = "browser"


class IconPurpose(str, Enum):
    """图标用途"""
    ANY = "any"
    MASKABLE = "maskable"
    MONOCHROME = "monochrome"


@dataclass
class PWAIcon:
    """PWA图标定义"""
    src: str
    sizes: str = "192x192"
    type: str = "image/png"
    purpose: IconPurpose = IconPurpose.ANY


@dataclass
class PWAShortcut:
    """应用快捷方式"""
    name: str
    url: str
    description: str = ""
    icons: List[PWAIcon] = field(default_factory=list)


@dataclass
class PWAManifestConfig:
    """manifest.json配置"""
    name: str = "MeshCtx PWA"
    short_name: str = "MeshCtx"
    description: str = "MeshCtx Progressive Web Application"
    start_url: str = "/"
    scope: str = "/"
    display: DisplayMode = DisplayMode.STANDALONE
    background_color: str = "#ffffff"
    theme_color: str = "#000000"
    orientation: str = "any"
    lang: str = "zh-CN"
    dir: str = "ltr"
    icons: List[PWAIcon] = field(default_factory=list)
    shortcuts: List[PWAShortcut] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    iarc_rating_id: str = ""
    related_applications: List[Dict] = field(default_factory=list)
    prefer_related_applications: bool = False
    screenshots: List[Dict] = field(default_factory=list)
    protocol_handlers: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = {
            "name": self.name,
            "short_name": self.short_name,
            "description": self.description,
            "start_url": self.start_url,
            "scope": self.scope,
            "display": self.display.value,
            "background_color": self.background_color,
            "theme_color": self.theme_color,
            "orientation": self.orientation,
            "lang": self.lang,
            "dir": self.dir,
            "icons": [
                {"src": i.src, "sizes": i.sizes, "type": i.type,
                 "purpose": i.purpose.value} for i in self.icons
            ],
        }
        if self.shortcuts:
            d["shortcuts"] = [
                {
                    "name": s.name,
                    "url": s.url,
                    "description": s.description,
                    "icons": [
                        {"src": ic.src, "sizes": ic.sizes, "type": ic.type}
                        for ic in s.icons
                    ] if s.icons else [],
                }
                for s in self.shortcuts
            ]
        if self.categories:
            d["categories"] = self.categories
        if self.iarc_rating_id:
            d["iarc_rating_id"] = self.iarc_rating_id
        if self.related_applications:
            d["related_applications"] = self.related_applications
        if self.prefer_related_applications:
            d["prefer_related_applications"] = True
        if self.screenshots:
            d["screenshots"] = self.screenshots
        if self.protocol_handlers:
            d["protocol_handlers"] = self.protocol_handlers
        return d


@dataclass
class SWCacheRule:
    """Service Worker缓存规则"""
    url_pattern: str
    strategy: CacheStrategy = CacheStrategy.CACHE_FIRST
    max_age_seconds: int = 86400
    max_entries: int = 200


@dataclass
class PushSubscription:
    """推送订阅信息"""
    endpoint: str
    keys: Dict[str, str]
    expiration_time: Optional[int] = None


@dataclass
class PushNotification:
    """推送通知"""
    title: str
    body: str = ""
    icon: str = "/icon-192x192.png"
    badge: str = "/badge-72x72.png"
    tag: str = ""
    data: Dict = field(default_factory=dict)
    actions: List[Dict] = field(default_factory=list)
    require_interaction: bool = False
    vibrate: List[int] = field(default_factory=list)
    timestamp: int = 0
    silent: bool = False

    def to_dict(self) -> Dict:
        d = {
            "title": self.title,
            "body": self.body,
            "icon": self.icon,
            "badge": self.badge,
            "tag": self.tag,
            "data": self.data,
            "actions": self.actions,
            "requireInteraction": self.require_interaction,
            "vibrate": self.vibrate,
            "timestamp": self.timestamp,
            "silent": self.silent,
        }
        return {k: v for k, v in d.items() if v not in ("", [], {}, 0, None)}


class InstallPromptManager:
    """安装提示管理器 — 控制beforeinstallprompt事件与安装流程"""

    def __init__(self):
        self._deferred_prompt: Optional[Dict] = None
        self._install_listeners: List[Callable[..., Any]] = []
        self._prompt_shown_count: int = 0
        self._max_prompts: int = 3
        self._prompt_cooldown_days: int = 1

    def capture_prompt(self, event_data: Dict) -> bool:
        """捕获安装提示事件"""
        self._deferred_prompt = event_data
        return self._deferred_prompt is not None

    def can_show_prompt(self) -> bool:
        """检查是否可以显示安装提示"""
        if self._deferred_prompt is None:
            return False
        if self._prompt_shown_count >= self._max_prompts:
            return False
        return True

    def get_prompt(self) -> Optional[Dict]:
        """获取当前待处理的安装提示"""
        if not self.can_show_prompt():
            return None
        self._prompt_shown_count += 1
        return self._deferred_prompt

    def confirm_install(self) -> Dict:
        """确认安装"""
        result = {
            "action": "install",
            "outcome": "accepted",
            "timestamp": int(__import__("time").time()),
        }
        for listener in self._install_listeners:
            try:
                listener(result)
            except Exception:
                pass
        self._deferred_prompt = None
        return result

    def dismiss_install(self) -> Dict:
        """拒绝安装"""
        result = {
            "action": "install",
            "outcome": "dismissed",
            "timestamp": int(__import__("time").time()),
        }
        for listener in self._install_listeners:
            try:
                listener(result)
            except Exception:
                pass
        return result

    def on_install(self, callback: Callable[..., Any]):
        """注册安装事件监听器"""
        self._install_listeners.append(callback)

    def reset(self):
        self._deferred_prompt = None
        self._prompt_shown_count = 0

    def generate_install_banner_js(self) -> str:
        """生成安装横幅的JavaScript代码"""
        return """
// MeshCtx v3.91 Install Banner
(function() {
  let deferredPrompt = null;
  const banner = document.createElement('div');
  banner.id = 'pwa-install-banner';
  banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#000;color:#fff;padding:16px;display:none;z-index:9999;display:flex;align-items:center;justify-content:space-between;font-family:sans-serif;';
  banner.innerHTML = '<span>Install this app for a better experience</span><div><button id="pwa-install-btn" style="background:#fff;color:#000;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin-right:8px;">Install</button><button id="pwa-dismiss-btn" style="background:transparent;color:#fff;border:1px solid #fff;padding:8px 16px;border-radius:4px;cursor:pointer;">Dismiss</button></div>';
  document.body.appendChild(banner);

  window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    deferredPrompt = e;
    banner.style.display = 'flex';
  });

  document.getElementById('pwa-install-btn').addEventListener('click', function() {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(function(result) {
      console.log('PWA install:', result.outcome);
      deferredPrompt = null;
      banner.style.display = 'none';
    });
  });

  document.getElementById('pwa-dismiss-btn').addEventListener('click', function() {
    banner.style.display = 'none';
  });

  window.addEventListener('appinstalled', function() {
    banner.style.display = 'none';
    console.log('PWA installed successfully');
  });
})();
"""


class PushManager:
    """推送通知管理器 — VAPID密钥生成与通知调度"""

    def __init__(self):
        self._subscriptions: List[PushSubscription] = []
        self._vapid_public_key: str = ""
        self._vapid_private_key: str = ""
        self._notification_queue: List[PushNotification] = []

    def set_vapid_keys(self, public_key: str, private_key: str = ""):
        """设置VAPID密钥对"""
        self._vapid_public_key = public_key
        self._vapid_private_key = private_key

    def get_vapid_public_key(self) -> str:
        return self._vapid_public_key

    def subscribe(self, subscription: PushSubscription):
        """添加推送订阅"""
        existing = [s for s in self._subscriptions if s.endpoint == subscription.endpoint]
        if existing:
            existing[0].keys = subscription.keys
            existing[0].expiration_time = subscription.expiration_time
        else:
            self._subscriptions.append(subscription)

    def unsubscribe(self, endpoint: str) -> bool:
        """移除推送订阅"""
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s.endpoint != endpoint]
        return len(self._subscriptions) < before

    def get_subscriptions(self) -> List[PushSubscription]:
        return list(self._subscriptions)

    def queue_notification(self, notification: PushNotification):
        """将通知加入队列"""
        self._notification_queue.append(notification)

    def flush_notifications(self) -> List[PushNotification]:
        """清空并返回通知队列"""
        queue = list(self._notification_queue)
        self._notification_queue.clear()
        return queue

    def generate_sw_push_js(self) -> str:
        """生成Service Worker推送事件处理JS"""
        return """
// MeshCtx v3.91 Push Handler
self.addEventListener('push', function(event) {
  if (!event.data) return;
  const data = event.data.json();
  const options = {
    body: data.body || '',
    icon: data.icon || '/icon-192x192.png',
    badge: data.badge || '/badge-72x72.png',
    tag: data.tag || '',
    data: data.data || {},
    actions: data.actions || [],
    requireInteraction: data.requireInteraction || false,
    vibrate: data.vibrate || [200, 100, 200],
    timestamp: data.timestamp || Date.now(),
    silent: data.silent || false,
  };
  event.waitUntil(self.registration.showNotification(data.title || 'New Notification', options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({type: 'window', includeUncontrolled: true}).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow('/');
    })
  );
});
"""


class PWABuilder:
    """
    v3.91 PWA Manifest生成器

    功能:
    1) 自动生成manifest.json + sw.js
    2) 离线缓存策略 (5种)
    3) 安装提示管理
    4) 推送通知集成
    """

    VERSION = "3.91.0"
    CACHE_NAME_PREFIX = "meshctx-pwa-v3.91"

    def __init__(self, config: Optional[PWAManifestConfig] = None):
        self._config = config or PWAManifestConfig()
        self._cache_rules: List[SWCacheRule] = []
        self._precache_urls: List[str] = []
        self._install_manager = InstallPromptManager()
        self._push_manager = PushManager()
        self._extra_sw_code: str = ""

        # 默认图标
        if not self._config.icons:
            self._config.icons = [
                PWAIcon(src="/icon-192x192.png", sizes="192x192"),
                PWAIcon(src="/icon-512x512.png", sizes="512x512"),
                PWAIcon(src="/icon-512x512.png", sizes="512x512",
                        purpose=IconPurpose.MASKABLE),
            ]

    # ─── 1) Manifest生成 ─────────────────────────────────────────

    def set_config(self, config: PWAManifestConfig):
        """设置/更新manifest配置"""
        self._config = config

    def get_config(self) -> PWAManifestConfig:
        return self._config

    def generate_manifest(self, pretty: bool = True) -> str:
        """生成manifest.json字符串"""
        data = self._config.to_dict()
        indent = 2 if pretty else None
        return json.dumps(data, ensure_ascii=False, indent=indent)

    def generate_manifest_html(self) -> str:
        """生成<link>标签用于HTML <head>"""
        return '<link rel="manifest" href="/manifest.json">'

    def add_icon(self, icon: PWAIcon):
        """添加图标"""
        self._config.icons.append(icon)

    def add_shortcut(self, shortcut: PWAShortcut):
        """添加快捷方式"""
        self._config.shortcuts.append(shortcut)

    # ─── 2) Service Worker + 离线缓存策略 ─────────────────────────

    def add_cache_rule(self, rule: SWCacheRule):
        """添加缓存规则"""
        self._cache_rules.append(rule)

    def set_precache_urls(self, urls: List[str]):
        """设置预缓存URL列表"""
        self._precache_urls = urls

    def add_extra_sw_code(self, code: str):
        """添加额外的Service Worker代码"""
        self._extra_sw_code += "\n" + code

    def generate_service_worker(self) -> str:
        """生成sw.js完整代码"""
        cache_name = self.CACHE_NAME_PREFIX
        precache_json = json.dumps(self._precache_urls)

        strategy_handlers = self._build_strategy_switches()

        sw = f"""/**
 * MeshCtx v3.91 PWA Service Worker — Auto-generated
 * Cache: {cache_name}
 */
const CACHE_NAME = '{cache_name}';
const PRECACHE_URLS = {precache_json};

// Install: precache
self.addEventListener('install', (event) => {{
  console.log('[SW v3.91] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {{
      console.log('[SW v3.91] Precaching', PRECACHE_URLS.length, 'URLs');
      return cache.addAll(PRECACHE_URLS);
    }}).then(() => self.skipWaiting())
  );
}});

// Activate: cleanup old caches
self.addEventListener('activate', (event) => {{
  console.log('[SW v3.91] Activating...');
  event.waitUntil(
    caches.keys().then((keys) => {{
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }}).then(() => self.clients.claim())
  );
}});

// Fetch: strategy-based routing
self.addEventListener('fetch', (event) => {{
  const url = new URL(event.request.url);
  const path = url.pathname;
{strategy_handlers}
}}));

// Background Sync
self.addEventListener('sync', (event) => {{
  if (event.tag === 'meshctx-sync') {{
    event.waitUntil(Promise.resolve(console.log('[SW v3.91] Background sync')));
  }}
}});

{self._push_manager.generate_sw_push_js()}

{self._extra_sw_code}
"""
        return sw

    def _build_strategy_switches(self) -> str:
        """构建缓存策略的路由switch代码"""
        if not self._cache_rules:
            return """
  // No custom cache rules — network-only fallback
  event.respondWith(fetch(event.request));"""

        lines = []
        for i, rule in enumerate(self._cache_rules):
            prefix = "  } else " if i > 0 else "  "
            method = self._strategy_method(rule.strategy)
            lines.append(
                f'{prefix}if (path.startsWith("{rule.url_pattern}")) {{\n'
                f'    event.respondWith({method}(event.request, {rule.max_age_seconds}));'
            )

        lines.append(
            '  } else {\n'
            '    event.respondWith(fetch(event.request));\n'
            '  }'
        )
        return '\n'.join(lines)

    @staticmethod
    def _strategy_method(strategy: CacheStrategy) -> str:
        mapping = {
            CacheStrategy.CACHE_FIRST: "cacheFirst",
            CacheStrategy.NETWORK_FIRST: "networkFirst",
            CacheStrategy.STALE_WHILE_REVALIDATE: "staleWhileRevalidate",
            CacheStrategy.NETWORK_ONLY: "networkOnly",
            CacheStrategy.CACHE_ONLY: "cacheOnly",
        }
        return mapping[strategy]

    def generate_strategy_helpers_js(self) -> str:
        """生成缓存策略辅助函数(JS)"""
        return f"""
// MeshCtx v3.91 Cache Strategies
const cacheFirst = async (request, maxAge = 86400) => {{
  const cache = await caches.open('{self.CACHE_NAME_PREFIX}');
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}};

const networkFirst = async (request, maxAge = 86400) => {{
  const cache = await caches.open('{self.CACHE_NAME_PREFIX}');
  try {{
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  }} catch (e) {{
    const cached = await cache.match(request);
    if (cached) return cached;
    throw e;
  }}
}};

const staleWhileRevalidate = async (request, maxAge = 86400) => {{
  const cache = await caches.open('{self.CACHE_NAME_PREFIX}');
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then((response) => {{
    if (response.ok) cache.put(request, response.clone());
    return response;
  }});
  return cached || fetchPromise;
}};

const networkOnly = async (request) => fetch(request);

const cacheOnly = async (request) => {{
  const cache = await caches.open('{self.CACHE_NAME_PREFIX}');
  return cache.match(request);
}};
"""

    # ─── 3) 安装提示 ─────────────────────────────────────────────

    def get_install_manager(self) -> InstallPromptManager:
        return self._install_manager

    def generate_install_banner_js(self) -> str:
        """生成安装横幅JS"""
        return self._install_manager.generate_install_banner_js()

    def generate_register_sw_js(self, sw_path: str = "/sw.js") -> str:
        """生成Service Worker注册JS"""
        return f"""
// MeshCtx v3.91 SW Registration
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => {{
    navigator.serviceWorker.register('{sw_path}')
      .then((reg) => console.log('[PWA v3.91] SW registered:', reg.scope))
      .catch((err) => console.error('[PWA v3.91] SW registration failed:', err));
  }});
}}
"""

    # ─── 4) 推送通知 ─────────────────────────────────────────────

    def get_push_manager(self) -> PushManager:
        return self._push_manager

    def generate_push_subscribe_js(self) -> str:
        """生成推送订阅JS"""
        vapid_key = self._push_manager.get_vapid_public_key() or "YOUR_VAPID_PUBLIC_KEY"
        return f"""
// MeshCtx v3.91 Push Subscription
function subscribeToPush(swRegistration) {{
  return swRegistration.pushManager.subscribe({{
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array('{vapid_key}')
  }});
}}

function urlBase64ToUint8Array(base64String) {{
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}}
"""

    def generate_full_html_snippet(self, sw_path: str = "/sw.js") -> str:
        """生成完整HTML集成代码段 (<head> + 脚本)"""
        return f"""<!-- MeshCtx v3.91 PWA Integration -->
{self.generate_manifest_html()}
<meta name="theme-color" content="{self._config.theme_color}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{self._config.short_name}">
<link rel="apple-touch-icon" href="/icon-192x192.png">

<script>
{self.generate_register_sw_js(sw_path)}

{self.generate_install_banner_js()}

{self.generate_push_subscribe_js()}
</script>
"""

    # ─── 工具方法 ────────────────────────────────────────────────

    def generate_all(self, sw_path: str = "/sw.js") -> Dict[str, str]:
        """一次性生成所有工件: manifest.json + sw.js + HTML snippet"""
        return {
            "manifest.json": self.generate_manifest(),
            "sw.js": self.generate_service_worker(),
            "index.html_snippet": self.generate_full_html_snippet(sw_path),
            "sw_helpers.js": self.generate_strategy_helpers_js(),
        }

    def validate_manifest(self) -> List[str]:
        """校验manifest配置，返回问题列表"""
        issues = []
        cfg = self._config
        if not cfg.name:
            issues.append("name is required")
        if not cfg.short_name:
            issues.append("short_name is required")
        if len(cfg.short_name) > 12:
            issues.append("short_name should be <= 12 chars")
        if not cfg.start_url:
            issues.append("start_url is required")
        if not cfg.icons:
            issues.append("at least one icon is required (192x192 and 512x512 recommended)")
        sizes = set()
        for icon in cfg.icons:
            sizes.add(icon.sizes)
        if "192x192" not in sizes:
            issues.append("192x192 icon recommended")
        if "512x512" not in sizes:
            issues.append("512x512 icon recommended")
        return issues

    def get_stats(self) -> Dict:
        """获取构建器统计信息"""
        return {
            "version": self.VERSION,
            "cache_rules": len(self._cache_rules),
            "precache_urls": len(self._precache_urls),
            "icons": len(self._config.icons),
            "shortcuts": len(self._config.shortcuts),
            "push_subscriptions": len(self._push_manager.get_subscriptions()),
            "install_prompt_pending": self._install_manager._deferred_prompt is not None,
            "manifest_issues": len(self.validate_manifest()),
        }


# 模块级单例
_pwa_builder: Optional[PWABuilder] = None


def get_pwa_builder() -> PWABuilder:
    """获取PWABuilder模块级单例"""
    global _pwa_builder
    if _pwa_builder is None:
        _pwa_builder = PWABuilder()
    return _pwa_builder


def reset_pwa_builder():
    """重置模块级单例"""
    global _pwa_builder
    _pwa_builder = None
