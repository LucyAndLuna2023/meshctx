"""v2.65 Plugin Marketplace"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    category: str
    install_command: str = ""
    downloads: int = 0
    enabled: bool = True


@dataclass(order=True)
class PluginVersion:
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
    user_id: str = ""
    rating: int = 0
    comment: str = ""
    helpful_count: int = 0

    def __post_init__(self):
        if not 1 <= self.rating <= 5:
            raise ValueError(f"Rating must be between 1 and 5, got {self.rating}")


@dataclass
class PluginEntry:
    plugin_id: str = ""
    name: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    _reviews: list = field(default_factory=list)
    category: str = ""
    installed: bool = False
    enabled: bool = True
    dependencies: list = field(default_factory=list)

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


class PluginMarket:
    """Plugin marketplace with registration, discovery, install, reviews, and version management."""

    # Pre-populated official plugins (backwards compat: PluginInfo objects indexed by name)
    _OFFICIAL_PLUGINS: dict = {
        "slack-gateway":        PluginInfo(name="slack-gateway", version="1.2.0", description="Slack消息集成网关", category="gateway"),
        "discord-gateway":      PluginInfo(name="discord-gateway", version="1.1.0", description="Discord消息集成网关", category="gateway"),
        "telegram-gateway":     PluginInfo(name="telegram-gateway", version="1.0.0", description="Telegram消息集成网关", category="gateway"),
        "wechat-gateway":       PluginInfo(name="wechat-gateway", version="1.0.0", description="微信消息集成网关", category="gateway"),
        "whatsapp-gateway":     PluginInfo(name="whatsapp-gateway", version="1.0.0", description="WhatsApp消息集成网关", category="gateway"),
        "hierarchical-memory":  PluginInfo(name="hierarchical-memory", version="1.3.0", description="层次化记忆存储", category="memory"),
        "sdm-memory":           PluginInfo(name="sdm-memory", version="1.0.0", description="SDM稀疏分布式记忆", category="memory"),
        "memory-compactor":     PluginInfo(name="memory-compactor", version="1.0.0", description="记忆压缩与归档", category="memory"),
        "knowledge-graph":      PluginInfo(name="knowledge-graph", version="2.0.0", description="知识图谱构建与查询", category="memory"),
        "security-scanner":     PluginInfo(name="security-scanner", version="1.1.0", description="代码安全扫描", category="security"),
        "prompt-shield":        PluginInfo(name="prompt-shield", version="1.0.0", description="Prompt注入防护", category="security"),
        "code-reviewer":        PluginInfo(name="code-reviewer", version="1.2.0", description="AI代码审查", category="tools"),
        "code-sandbox":         PluginInfo(name="code-sandbox", version="1.0.0", description="安全代码沙箱执行", category="tools"),
        "deep-research":        PluginInfo(name="deep-research", version="1.1.0", description="深度研究代理", category="tools"),
        "web-crawler":          PluginInfo(name="web-crawler", version="1.0.0", description="智能网页爬虫", category="tools"),
        "monitoring-agent":     PluginInfo(name="monitoring-agent", version="1.0.0", description="系统监控代理", category="monitoring"),
        "alert-engine":         PluginInfo(name="alert-engine", version="1.0.0", description="告警引擎", category="monitoring"),
    }

    def __init__(self, data_dir=None):
        if data_dir is None:
            import tempfile
            self._temp_dir = tempfile.TemporaryDirectory()
            self.data_dir = Path(self._temp_dir.name) / "plugins"
        else:
            self.data_dir = Path(data_dir)
            self._temp_dir = None
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._plugins: dict[str, PluginEntry] = {}
        self._install_counts: dict[str, int] = {}
        self._installed_versions: dict[str, str] = {}
        # Backwards compat: _installed maps name → PluginInfo for installed plugins
        self._installed: dict[str, PluginInfo] = {}
        self._disabled: set = set()
        self._load_state()

    # ── persistence ─────────────────────────────────────────────────────
    def _state_file(self) -> Path:
        return self.data_dir / "state.json"

    def _save_state(self) -> None:
        state = {
            "plugins": {
                pid: {
                    "plugin_id": e.plugin_id,
                    "name": e.name,
                    "description": e.description,
                    "tags": e.tags,
                    "versions": [{"major": v.major, "minor": v.minor, "patch": v.patch} for v in e.versions],
                    "category": e.category,
                    "installed": e.installed,
                    "enabled": e.enabled,
                    "dependencies": e.dependencies,
                }
                for pid, e in self._plugins.items()
            },
            "install_counts": self._install_counts,
            "installed_versions": self._installed_versions,
            "disabled": list(self._disabled),
        }
        self._state_file().write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self) -> None:
        sf = self._state_file()
        if not sf.exists():
            return
        try:
            raw = json.loads(sf.read_text(encoding="utf-8"))
            for pid, data in raw.get("plugins", {}).items():
                versions = [PluginVersion(**v) for v in data.get("versions", [])]
                entry = PluginEntry(
                    plugin_id=data["plugin_id"],
                    name=data["name"],
                    description=data.get("description", ""),
                    tags=data.get("tags", []),
                    versions=versions,
                    category=data.get("category", ""),
                    installed=data.get("installed", False),
                    enabled=data.get("enabled", True),
                    dependencies=data.get("dependencies", []),
                )
                self._plugins[pid] = entry
                if entry.installed and entry.name in self._OFFICIAL_PLUGINS:
                    info = self._OFFICIAL_PLUGINS[entry.name]
                    info.downloads = self._install_counts.get(pid, 0)
                    self._installed[entry.name] = info
            self._install_counts = raw.get("install_counts", {})
            self._installed_versions = raw.get("installed_versions", {})
            self._disabled = set(raw.get("disabled", []))
        except (json.JSONDecodeError, TypeError):
            pass

    def _ensure_registered(self, name: str) -> Optional[PluginEntry]:
        """Ensure a plugin from _OFFICIAL_PLUGINS is registered in _plugins."""
        info = self._OFFICIAL_PLUGINS.get(name)
        if info is None:
            return None
        pid = info.name
        if pid not in self._plugins:
            ver = PluginVersion.parse(info.version)
            entry = PluginEntry(
                plugin_id=pid,
                name=info.name,
                description=info.description,
                tags=[info.category],
                versions=[ver],
                category=info.category,
                installed=False,
                enabled=True,
            )
            self._plugins[pid] = entry
        return self._plugins[pid]

    # ── Registration ────────────────────────────────────────────────────
    def register(self, entry: PluginEntry) -> None:
        pid = entry.plugin_id
        if pid in self._plugins:
            existing = self._plugins[pid]
            existing.tags = list(set(existing.tags + entry.tags))
            for v in entry.versions:
                existing.add_version(v)
            for r in entry._reviews:
                if not any(e.user_id == r.user_id for e in existing._reviews):
                    existing.add_review(r)
        else:
            self._plugins[pid] = entry
        self._save_state()

    def get(self, plugin_id: str) -> Optional[PluginEntry]:
        return self._plugins.get(plugin_id)

    def unregister(self, plugin_id: str) -> bool:
        if plugin_id not in self._plugins:
            return False
        del self._plugins[plugin_id]
        self._install_counts.pop(plugin_id, None)
        self._installed_versions.pop(plugin_id, None)
        self._save_state()
        return True

    # ── Discovery ───────────────────────────────────────────────────────
    def discover(self, query=None, category=None, tags=None, installed_only=False, sort_by=None) -> list[PluginEntry]:
        results = list(self._plugins.values())
        if query:
            q = query.lower()
            results = [p for p in results if q in p.name.lower() or q in p.description.lower()]
        if category:
            results = [p for p in results if p.category == category]
        if tags:
            results = [p for p in results if all(t in p.tags for t in tags)]
        if installed_only:
            results = [p for p in results if p.installed]
        if sort_by == "rating":
            results.sort(key=lambda p: p.average_rating, reverse=True)
        return results

    def search(self, query: str = None, category: str = None) -> list:
        """Search plugins. Returns list of PluginInfo objects for backwards compat."""
        # Ensure all official plugins are registered
        for name in self._OFFICIAL_PLUGINS:
            self._ensure_registered(name)

        entries = self.discover(query=query, category=category)
        # Convert to PluginInfo for backwards compat
        results = []
        for e in entries:
            info = self._OFFICIAL_PLUGINS.get(e.name)
            if info is None:
                info = PluginInfo(
                    name=e.name, version=str(e.latest_version) if e.latest_version else "0.0.0",
                    description=e.description, category=e.category,
                )
            results.append(info)
        return results

    # ── Install / Uninstall ─────────────────────────────────────────────
    def install(self, plugin_id: str, version: str = None) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            entry = self._ensure_registered(plugin_id)
        if entry is None:
            return {"success": False, "error": f"Plugin '{plugin_id}' not found in market"}

        # Already installed → reject duplicate
        if entry.installed:
            return {"success": False, "error": f"Plugin '{plugin_id}' is already installed"}

        # Skip install if install_command is empty (test mode)
        info = self._OFFICIAL_PLUGINS.get(plugin_id)
        if info and info.install_command:
            pass  # would actually install

        # Resolve and install dependencies
        deps_installed = []
        for dep_id in entry.dependencies:
            dep_entry = self._plugins.get(dep_id)
            if dep_entry and not dep_entry.installed:
                dep_result = self.install(dep_id)
                if dep_result["success"]:
                    deps_installed.append(dep_id)

        # Find the version to install
        if version:
            target_v = None
            for v in entry.versions:
                if str(v) == f"v{version}" or str(v) == version:
                    target_v = v
                    break
            if target_v is None:
                return {"success": False, "error": f"Version '{version}' not found"}
        else:
            target_v = entry.latest_version
            if target_v is None:
                return {"success": False, "error": "No versions available"}

        version_str = str(target_v)
        entry.installed = True
        entry.enabled = True
        self._installed_versions[plugin_id] = version_str
        self._install_counts[plugin_id] = self._install_counts.get(plugin_id, 0) + 1

        # Track in _installed for backwards compat
        if info:
            info.downloads = self._install_counts[plugin_id]
            self._installed[plugin_id] = info

        self._disabled.discard(plugin_id)
        self._save_state()

        result = {"success": True, "version_installed": version_str, "message": f"安装成功: {plugin_id}"}
        if deps_installed:
            result["dependencies_installed"] = deps_installed
        return result

    def uninstall(self, plugin_id: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None or not entry.installed:
            return {"success": False, "error": f"Plugin '{plugin_id}' is not installed"}
        entry.installed = False
        entry.enabled = False
        self._installed_versions.pop(plugin_id, None)
        self._installed.pop(plugin_id, None)
        self._save_state()
        return {"success": True}

    def disable(self, plugin_id: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return {"success": False, "error": f"Plugin '{plugin_id}' not found"}
        if not entry.installed:
            return {"success": False, "error": f"Plugin '{plugin_id}' is not installed"}
        entry.enabled = False
        self._disabled.add(plugin_id)
        self._save_state()
        return {"success": True}

    def enable(self, plugin_id: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return {"success": False, "error": f"Plugin '{plugin_id}' not found"}
        if not entry.installed:
            return {"success": False, "error": f"Plugin '{plugin_id}' is not installed"}
        entry.enabled = True
        self._disabled.discard(plugin_id)
        self._save_state()
        return {"success": True}

    def list_installed(self) -> list:
        """Return list of installed PluginInfo objects."""
        return [info for name, info in self._installed.items()]

    def get_categories(self) -> list:
        """Return sorted list of unique category names."""
        cats = set()
        for name, info in self._OFFICIAL_PLUGINS.items():
            cats.add(info.category)
        for entry in self._plugins.values():
            if entry.category:
                cats.add(entry.category)
        return sorted(cats)

    def get_stats(self) -> dict:
        """Return detailed stats dict for backwards compat."""
        total = len(self._OFFICIAL_PLUGINS)
        installed = len(self._installed)
        active = sum(1 for name in self._installed if name not in self._disabled)
        one_liner = f"{installed}/{total} installed, {active} active"
        return {
            "total_plugins": total,
            "installed": installed,
            "active": active,
            "one_liner": one_liner,
        }

    def resolve_dependencies(self, plugin_id: str) -> list[str]:
        """Return dependency resolution order (depth-first post-order)."""
        resolved = []
        visited = set()

        def dfs(pid):
            if pid in visited:
                return
            visited.add(pid)
            entry = self._plugins.get(pid)
            if entry:
                for dep in entry.dependencies:
                    dfs(dep)
            resolved.append(pid)

        dfs(plugin_id)
        return resolved

    # ── Reviews ─────────────────────────────────────────────────────────
    def add_review(self, plugin_id: str, review: PluginReview) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return {"success": False, "error": "Plugin not found"}
        for existing in entry._reviews:
            if existing.user_id == review.user_id:
                return {"success": False, "error": "User has already reviewed this plugin"}
        entry.add_review(review)
        self._save_state()
        return {"success": True}

    def get_rating(self, plugin_id: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return {"average": 0.0, "count": 0, "distribution": {}}
        reviews = entry._reviews
        if not reviews:
            return {"average": 0.0, "count": 0, "distribution": {}}
        avg = sum(r.rating for r in reviews) / len(reviews)
        dist = {}
        for r in reviews:
            dist[r.rating] = dist.get(r.rating, 0) + 1
        return {"average": avg, "count": len(reviews), "distribution": dist}

    def get_reviews(self, plugin_id: str, sort_by: str = None) -> list[PluginReview]:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return []
        reviews = list(entry._reviews)
        if sort_by == "newest":
            reviews.reverse()
        return reviews

    def flag_review(self, plugin_id: str, user_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return False
        for r in entry._reviews:
            if r.user_id == user_id:
                return True
        return False

    def mark_review_helpful(self, plugin_id: str, user_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return False
        for r in entry._reviews:
            if r.user_id == user_id:
                r.helpful_count += 1
                return True
        return False

    # ── Version Management ──────────────────────────────────────────────
    def get_versions(self, plugin_id: str) -> list[PluginVersion]:
        entry = self._plugins.get(plugin_id)
        if entry is None:
            return []
        return sorted(entry.versions, reverse=True)

    def check_updates(self) -> list[dict]:
        updates = []
        for pid, entry in self._plugins.items():
            if not entry.installed:
                continue
            installed_ver = self._installed_versions.get(pid)
            if installed_ver and entry.latest_version:
                latest = str(entry.latest_version)
                if installed_ver != latest:
                    updates.append({
                        "plugin_id": pid,
                        "installed": installed_ver,
                        "latest": latest,
                    })
        return updates

    def update_plugin(self, plugin_id: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None or not entry.installed:
            return {"success": False, "error": "Plugin not installed"}
        installed_ver = self._installed_versions.get(plugin_id)
        latest = entry.latest_version
        if latest is None:
            return {"success": False, "error": "No versions available"}
        if installed_ver == str(latest):
            return {"success": False, "error": "Already at latest version"}
        self._installed_versions[plugin_id] = str(latest)
        self._save_state()
        return {"success": True, "version_installed": str(latest)}

    def rollback(self, plugin_id: str, version: str) -> dict:
        entry = self._plugins.get(plugin_id)
        if entry is None or not entry.installed:
            return {"success": False, "error": "Plugin not installed"}
        target_v_str = f"v{version}" if not version.startswith("v") else version
        found = False
        for v in entry.versions:
            if str(v) == target_v_str:
                found = True
                break
        if not found:
            return {"success": False, "error": f"Version '{version}' not found"}
        self._installed_versions[plugin_id] = target_v_str
        self._save_state()
        return {"success": True, "version_installed": target_v_str}

    def compare_versions(self, plugin_id: str, v1: str, v2: str) -> dict:
        pv1 = PluginVersion.parse(v1)
        pv2 = PluginVersion.parse(v2)
        if pv1 < pv2:
            return {"comparison": "older"}
        elif pv1 > pv2:
            return {"comparison": "newer"}
        else:
            return {"comparison": "equal"}

    # ── Stats ───────────────────────────────────────────────────────────
    def stats(self) -> dict:
        total = len(self._plugins)
        installed = sum(1 for p in self._plugins.values() if p.installed)
        total_downloads = sum(self._install_counts.values())
        return {
            "total_plugins": total,
            "installed_plugins": installed,
            "total_downloads": total_downloads,
        }

    def top_rated(self) -> list[PluginEntry]:
        entries = [e for e in self._plugins.values() if e._reviews]
        entries.sort(key=lambda e: e.average_rating, reverse=True)
        return entries

    def top_downloaded(self) -> list[PluginEntry]:
        entries = list(self._plugins.values())
        entries.sort(key=lambda e: self._install_counts.get(e.plugin_id, 0), reverse=True)
        return entries

    def reset(self) -> None:
        self._plugins.clear()
        self._install_counts.clear()
        self._installed_versions.clear()
        self._installed.clear()
        self._disabled.clear()
        self._save_state()


# ── Singleton ──────────────────────────────────────────────────────────
_plugin_market: Optional[PluginMarket] = None


def get_plugin_market() -> PluginMarket:
    global _plugin_market
    if _plugin_market is None:
        _plugin_market = PluginMarket()
    return _plugin_market


def reset_plugin_market() -> None:
    global _plugin_market
    _plugin_market = None


PluginMarketplace = PluginMarket  # backwards compatibility alias
