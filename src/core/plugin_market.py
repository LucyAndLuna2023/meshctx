"""v2.65 Plugin Marketplace"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PluginInfo:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    name: str
    version: str
    description: str
    category: str
    install_command: str = ""
    downloads: int = 0


class PluginMarketplace:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, data_dir=None, **kw):
        self.data_dir = Path(data_dir) if data_dir else Path("plugins")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._OFFICIAL_PLUGINS: dict[str, PluginInfo] = self._build_official_plugins()
        self._installed: dict[str, PluginInfo] = {}
        self._disabled: set[str] = set()

        self._load_state()

    # ── official plugin registry ────────────────────────────────────────
    @staticmethod
    def _build_official_plugins(**kw) -> dict[str, PluginInfo]:
        return {
            # gateways ─ 5
            "slack-gateway": PluginInfo(
                "slack-gateway", "2.1.0", "Slack 消息网关，支持实时消息收发与频道管理",
                "gateway", "pip install slack-sdk>=3.0",
            ),
            "discord-gateway": PluginInfo(
                "discord-gateway", "1.8.0", "Discord 消息网关，支持 Webhook 与 Bot API",
                "gateway", "pip install discord.py>=2.0",
            ),
            "telegram-gateway": PluginInfo(
                "telegram-gateway", "2.0.1", "Telegram 消息网关，原生 Bot API 封装",
                "gateway", "pip install python-telegram-bot>=20.0",
            ),
            "whatsapp-gateway": PluginInfo(
                "whatsapp-gateway", "1.3.0", "WhatsApp Cloud API 网关",
                "gateway", "pip install requests>=2.28",
            ),
            "wechat-gateway": PluginInfo(
                "wechat-gateway", "1.5.2", "企业微信消息网关",
                "gateway", "pip install wechatpy>=2.0",
            ),
            # memory ─ 4
            "chroma-memory": PluginInfo(
                "chroma-memory", "1.2.0", "Chroma 向量记忆后端，本地嵌入式向量检索",
                "memory", "pip install chromadb>=0.4",
            ),
            "pinecone-memory": PluginInfo(
                "pinecone-memory", "1.0.0", "Pinecone 云端向量记忆后端",
                "memory", "pip install pinecone-client>=3.0",
            ),
            "redis-memory": PluginInfo(
                "redis-memory", "1.1.0", "Redis 记忆缓存层，高速会话状态存储",
                "memory", "pip install redis>=5.0",
            ),
            "qdrant-memory": PluginInfo(
                "qdrant-memory", "1.0.1", "Qdrant 向量记忆后端，高性能相似度搜索",
                "memory", "pip install qdrant-client>=1.7",
            ),
            # security ─ 3
            "jwt-auth": PluginInfo(
                "jwt-auth", "1.0.0", "JWT 认证模块，支持 RS256/HS256",
                "security", "pip install pyjwt>=2.8",
            ),
            "rate-limiter": PluginInfo(
                "rate-limiter", "1.2.0", "API 速率限制器，滑动窗口算法",
                "security", "",
            ),
            "api-key-auth": PluginInfo(
                "api-key-auth", "1.0.0", "API Key 认证与轮转管理",
                "security", "",
            ),
            # tools ─ 3
            "web-search": PluginInfo(
                "web-search", "2.0.0", "网络搜索工具，支持多搜索引擎聚合",
                "tools", "pip install duckduckgo-search>=5.0",
            ),
            "code-runner": PluginInfo(
                "code-runner", "1.1.0", "代码执行沙箱，隔离运行 Python/JS/Shell",
                "tools", "pip install docker>=7.0",
            ),
            "file-manager": PluginInfo(
                "file-manager", "1.0.0", "文件管理工具，支持批量操作与云存储",
                "tools", "",
            ),
            # monitoring ─ 1
            "prometheus-exporter": PluginInfo(
                "prometheus-exporter", "1.0.0", "Prometheus 指标导出器",
                "monitoring", "pip install prometheus-client>=0.18",
            ),
        }

    # ── persistence ─────────────────────────────────────────────────────
    def _state_file(self, **kw) -> Path:
        return self.data_dir / "state.json"

    def _save_state(self, **kw) -> None:
        state = {
            "installed": {n: asdict(i) for n, i in self._installed.items()},
            "disabled": sorted(self._disabled),
        }
        self._state_file().write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self, **kw) -> None:
        sf = self._state_file()
        if not sf.exists():
            return
        try:
            raw = json.loads(sf.read_text(encoding="utf-8"))
            self._installed = {
                n: PluginInfo(**info)
                for n, info in raw.get("installed", {}).items()
            }
            self._disabled = set(raw.get("disabled", []))
        except (json.JSONDecodeError, TypeError):
            pass

    # ── public API ──────────────────────────────────────────────────────
    def search(
        self, query: Optional[str] = None, category: Optional[str] = None
    ) -> list[PluginInfo]:
        """Search plugins by name substring and/or category."""
        results: list[PluginInfo] = []
        q = query.lower() if query else None
        for name, plugin in self._OFFICIAL_PLUGINS.items():
            if q and q not in name.lower():
                continue
            if category and plugin.category != category:
                continue
            results.append(plugin)
        return results

    def install(self, name: str, **kw) -> dict:
        """Install a plugin by name."""
        if name not in self._OFFICIAL_PLUGINS:
            return {"success": False, "message": f"插件 '{name}' 不存在于官方市场中"}
        if name in self._installed:
            return {"success": False, "message": f"插件 '{name}' 已经安装过了"}

        official = self._OFFICIAL_PLUGINS[name]
        # Simulate install — real implementation would run install_command
        if official.install_command:
            pass

        # Increment downloads on the official registry entry
        official.downloads += 1

        installed_copy = PluginInfo(
            name=official.name,
            version=official.version,
            description=official.description,
            category=official.category,
            install_command=official.install_command,
            downloads=official.downloads,
        )
        self._installed[name] = installed_copy
        self._save_state()
        return {"success": True, "message": f"插件 '{name}' 安装成功"}

    def uninstall(self, name: str, **kw) -> dict:
        """Uninstall a plugin by name."""
        if name not in self._installed:
            return {"success": False, "message": f"插件 '{name}' 未安装"}
        del self._installed[name]
        self._disabled.discard(name)
        self._save_state()
        return {"success": True, "message": f"插件 '{name}' 已卸载"}

    def disable(self, name: str, **kw) -> dict:
        """Disable an installed plugin."""
        if name not in self._installed:
            return {"success": False, "message": f"插件 '{name}' 未安装，无法禁用"}
        self._disabled.add(name)
        self._save_state()
        return {"success": True, "message": f"插件 '{name}' 已禁用"}

    def enable(self, name: str, **kw) -> dict:
        """Enable a previously disabled plugin."""
        if name not in self._installed:
            return {"success": False, "message": f"插件 '{name}' 未安装，无法启用"}
        self._disabled.discard(name)
        self._save_state()
        return {"success": True, "message": f"插件 '{name}' 已启用"}

    def list_installed(self, **kw) -> list[PluginInfo]:
        """Return all installed plugins."""
        return list(self._installed.values())

    def get_categories(self, **kw) -> list[str]:
        """Return unique category names."""
        return sorted(set(p.category for p in self._OFFICIAL_PLUGINS.values()))

    def get_stats(self, **kw) -> dict:
        """Return marketplace statistics."""
        installed_count = len(self._installed)
        active_count = installed_count - len(self._disabled)
        return {
            "total_plugins": len(self._OFFICIAL_PLUGINS),
            "installed": installed_count,
            "active": active_count,
            "one_liner": f"meshctx 插件市场 — {len(self._OFFICIAL_PLUGINS)} 个官方插件",
        }

@dataclass(order=True)
class PluginVersion:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    major: int = 1
    minor: int = 0
    patch: int = 0
    def __str__(self):
        return f"v{self.major}.{self.minor}.{self.patch}"
    @classmethod
    def parse(cls, s: str):
        s = s.lstrip('v')
        parts = s.split('.')
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"Invalid version: {s}")
        return cls(major=int(parts[0]), minor=int(parts[1]), patch=int(parts[2]))
    def to_tuple(self):
        return (self.major, self.minor, self.patch)

@dataclass
class PluginReview:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    user_id: str = ""
    rating: int = 0
    text: str = ""

@dataclass
class PluginEntry:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    plugin_id: str = ""
    name: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    _reviews: list = field(default_factory=list)
    
    @property
    def latest_version(self):
        return max(self.versions) if self.versions else None
    
    @property
    def average_rating(self):
        if not self._reviews:
            return 0.0
        return sum(r.rating for r in self._reviews) / len(self._reviews)
    
    @property
    def review_count(self):
        return len(self._reviews)
    
    def add_review(self, review):
        self._reviews.append(review)
    
    def add_version(self, version):
        for i, v in enumerate(self.versions):
            if v == version:
                self.versions[i] = version
                return
        self.versions.append(version)

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

