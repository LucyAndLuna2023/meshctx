"""
meshctx v3.102 — Plugin Market (插件市场)

功能:
1) 插件注册/发现 — register/discover/search with tag filtering
2) 一键安装 — resolve dependencies, download + activate
3) 评分+评论 — star ratings + text reviews with spam detection
4) 版本管理 — semantic versioning, changelogs, update checking

Design: stateless dataclass-driven, module-level singleton.
"""

import logging
import re
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from enum import Enum

logger = logging.getLogger("meshctx.plugin_market")


# ============================================================
# Data Classes
# ============================================================

@dataclass
class PluginVersion:
    """Semantic version entry with changelog"""
    major: int
    minor: int
    patch: int
    changelog: str = ""
    release_date: float = field(default_factory=time.time)
    download_url: str = ""
    sha256: str = ""
    min_meshctx_version: str = "3.0.0"

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"

    def to_tuple(self) -> Tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @classmethod
    def parse(cls, version_str: str) -> "PluginVersion":
        """Parse 'v1.2.3' or '1.2.3' into PluginVersion"""
        v = version_str.lstrip("v")
        parts = v.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version string: {version_str}")
        return cls(
            major=int(parts[0]),
            minor=int(parts[1]),
            patch=int(parts[2]),
        )

    def __gt__(self, other: "PluginVersion") -> bool:
        return self.to_tuple() > other.to_tuple()

    def __ge__(self, other: "PluginVersion") -> bool:
        return self.to_tuple() >= other.to_tuple()

    def __lt__(self, other: "PluginVersion") -> bool:
        return self.to_tuple() < other.to_tuple()

    def __le__(self, other: "PluginVersion") -> bool:
        return self.to_tuple() <= other.to_tuple()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PluginVersion):
            return NotImplemented
        return self.to_tuple() == other.to_tuple()


@dataclass
class PluginReview:
    """User review with star rating and comment"""
    user_id: str
    rating: int  # 1-5 stars
    comment: str = ""
    timestamp: float = field(default_factory=time.time)
    helpful_count: int = 0
    flagged: bool = False

    def __post_init__(self):
        if not 1 <= self.rating <= 5:
            raise ValueError(f"Rating must be 1-5, got {self.rating}")


@dataclass
class PluginEntry:
    """A plugin listed in the market"""
    plugin_id: str
    name: str
    description: str = ""
    author: str = "unknown"
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    versions: List[PluginVersion] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # plugin_ids
    homepage: str = ""
    license: str = "MIT"
    installed: bool = False
    installed_version: Optional[PluginVersion] = None
    install_date: float = 0.0
    download_count: int = 0
    reviews: List[PluginReview] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    verified: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def latest_version(self) -> Optional[PluginVersion]:
        """Return the newest version, or None if no versions"""
        if not self.versions:
            return None
        return max(self.versions, key=lambda v: v.to_tuple())

    @property
    def average_rating(self) -> float:
        """Average star rating, 0.0 if no reviews"""
        if not self.reviews:
            return 0.0
        return sum(r.rating for r in self.reviews) / len(self.reviews)

    @property
    def review_count(self) -> int:
        return len(self.reviews)

    def get_version(self, version_str: str) -> Optional[PluginVersion]:
        """Get a specific version by string"""
        target = PluginVersion.parse(version_str)
        for v in self.versions:
            if v == target:
                return v
        return None

    def add_version(self, version: PluginVersion) -> None:
        """Add a new version, avoiding duplicates"""
        for i, v in enumerate(self.versions):
            if v == version:
                self.versions[i] = version
                return
        self.versions.append(version)
        self.versions.sort(key=lambda v: v.to_tuple())
        self.updated_at = time.time()

    def add_review(self, review: PluginReview) -> None:
        self.reviews.append(review)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "latest_version": str(self.latest_version) if self.latest_version else None,
            "average_rating": round(self.average_rating, 1),
            "review_count": self.review_count,
            "download_count": self.download_count,
            "installed": self.installed,
            "verified": self.verified,
            "dependencies": self.dependencies,
        }


# ============================================================
# PluginMarket
# ============================================================

class PluginMarket:
    """
    Plugin marketplace with registration, install, reviews, and versioning.

    Usage:
        market = PluginMarket()
        market.register(PluginEntry(plugin_id="my-plugin", name="My Plugin", ...))
        market.install("my-plugin")
        market.add_review("my-plugin", PluginReview(user_id="u1", rating=5, comment="Great!"))
        updates = market.check_updates()
    """

    def __init__(self):
        self._plugins: Dict[str, PluginEntry] = {}
        self._lock = threading.RLock()
        self._install_history: List[Dict[str, Any]] = []
        self._total_downloads: int = 0

    # ---- 1) Plugin Registration / Discovery ----

    def register(self, entry: PluginEntry) -> PluginEntry:
        """Register a plugin in the market. Returns the stored entry."""
        with self._lock:
            if entry.plugin_id in self._plugins:
                existing = self._plugins[entry.plugin_id]
                # Merge versions
                for v in entry.versions:
                    existing.add_version(v)
                # Update mutable fields
                existing.description = entry.description or existing.description
                existing.author = entry.author or existing.author
                existing.tags = list(set(existing.tags + entry.tags))
                existing.dependencies = list(set(existing.dependencies + entry.dependencies))
                existing.homepage = entry.homepage or existing.homepage
                existing.license = entry.license or existing.license
                existing.metadata.update(entry.metadata)
                existing.updated_at = time.time()
                return existing
            self._plugins[entry.plugin_id] = entry
            return entry

    def unregister(self, plugin_id: str) -> bool:
        """Remove a plugin from the market. Returns False if not found."""
        with self._lock:
            if plugin_id in self._plugins:
                del self._plugins[plugin_id]
                return True
            return False

    def get(self, plugin_id: str) -> Optional[PluginEntry]:
        """Get a plugin by ID"""
        with self._lock:
            return self._plugins.get(plugin_id)

    def list_all(self) -> List[PluginEntry]:
        """List all registered plugins"""
        with self._lock:
            return list(self._plugins.values())

    def discover(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        installed_only: bool = False,
        verified_only: bool = False,
        sort_by: str = "name",  # name, rating, downloads, updated
        limit: int = 50,
    ) -> List[PluginEntry]:
        """
        Discover plugins with flexible filtering and sorting.

        Args:
            query: Free text search in name + description
            category: Filter by category
            tags: Filter by tags (AND match)
            author: Filter by author
            installed_only: Only show installed plugins
            verified_only: Only show verified plugins
            sort_by: Sorting key
            limit: Max results
        """
        with self._lock:
            results = list(self._plugins.values())

        # Filters
        if query:
            q = query.lower()
            results = [
                p for p in results
                if q in p.name.lower() or q in p.description.lower()
            ]
        if category is not None:
            results = [p for p in results if p.category == category]
        if tags:
            tag_set = set(tags)
            results = [p for p in results if tag_set.issubset(set(p.tags))]
        if author is not None:
            results = [p for p in results if p.author == author]
        if installed_only:
            results = [p for p in results if p.installed]
        if verified_only:
            results = [p for p in results if p.verified]

        # Sort
        if sort_by == "rating":
            results.sort(key=lambda p: p.average_rating, reverse=True)
        elif sort_by == "downloads":
            results.sort(key=lambda p: p.download_count, reverse=True)
        elif sort_by == "updated":
            results.sort(key=lambda p: p.updated_at, reverse=True)
        else:  # name
            results.sort(key=lambda p: p.name.lower())

        return results[:limit]

    def search(self, query: str, limit: int = 20) -> List[PluginEntry]:
        """Quick search by name/description"""
        return self.discover(query=query, limit=limit)

    def get_categories(self) -> List[str]:
        """Return all unique categories"""
        with self._lock:
            return sorted(set(p.category for p in self._plugins.values()))

    def get_tags(self) -> List[str]:
        """Return all unique tags across plugins"""
        with self._lock:
            all_tags: Set[str] = set()
            for p in self._plugins.values():
                all_tags.update(p.tags)
            return sorted(all_tags)

    # ---- 2) One-Click Install ----

    def install(self, plugin_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Install a plugin (one-click). Resolves dependencies recursively.

        Returns a dict with install status and details.
        """
        result: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "success": False,
            "version_installed": None,
            "dependencies_installed": [],
            "error": None,
        }

        entry = self.get(plugin_id)
        if entry is None:
            result["error"] = f"Plugin '{plugin_id}' not found in market"
            return result

        # Resolve dependencies first
        dep_results = []
        for dep_id in entry.dependencies:
            dep_entry = self.get(dep_id)
            if dep_entry is None:
                result["error"] = f"Dependency '{dep_id}' not found in market"
                return result
            if not dep_entry.installed:
                dep_result = self.install(dep_id)
                if not dep_result["success"]:
                    result["error"] = f"Failed to install dependency '{dep_id}': {dep_result['error']}"
                    return result
                dep_results.append(dep_id)

        # Determine version to install
        target_version = entry.latest_version
        if version:
            target_version = entry.get_version(version)
            if target_version is None:
                result["error"] = f"Version '{version}' not found for plugin '{plugin_id}'"
                return result

        if target_version is None:
            result["error"] = f"No versions available for plugin '{plugin_id}'"
            return result

        # Install
        with self._lock:
            entry.installed = True
            entry.installed_version = target_version
            entry.install_date = time.time()
            entry.download_count += 1
            self._total_downloads += 1
            self._install_history.append({
                "plugin_id": plugin_id,
                "version": str(target_version),
                "timestamp": time.time(),
            })

        result["success"] = True
        result["version_installed"] = str(target_version)
        result["dependencies_installed"] = dep_results
        logger.info(f"Installed plugin '{plugin_id}' {target_version}")
        return result

    def uninstall(self, plugin_id: str) -> Dict[str, Any]:
        """Uninstall a plugin"""
        result: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "success": False,
            "error": None,
        }
        entry = self.get(plugin_id)
        if entry is None:
            result["error"] = f"Plugin '{plugin_id}' not found"
            return result
        if not entry.installed:
            result["error"] = f"Plugin '{plugin_id}' is not installed"
            return result

        with self._lock:
            entry.installed = False
            entry.installed_version = None
            entry.install_date = 0.0

        result["success"] = True
        logger.info(f"Uninstalled plugin '{plugin_id}'")
        return result

    def get_installed(self) -> List[PluginEntry]:
        """List all installed plugins"""
        return self.discover(installed_only=True)

    def resolve_dependencies(self, plugin_id: str) -> List[str]:
        """
        Resolve the full dependency tree for a plugin.
        Returns a flat list of all dependency plugin_ids (including the plugin itself).
        """
        resolved: List[str] = []
        seen: Set[str] = set()

        def _resolve(pid: str):
            if pid in seen:
                return
            seen.add(pid)
            entry = self.get(pid)
            if entry is None:
                return
            for dep_id in entry.dependencies:
                _resolve(dep_id)
            resolved.append(pid)

        _resolve(plugin_id)
        return resolved

    # ---- 3) Rating + Reviews ----

    def add_review(self, plugin_id: str, review: PluginReview) -> Dict[str, Any]:
        """
        Add a review (star rating + comment) to a plugin.

        Basic spam detection: rejects empty comments from users who already reviewed.
        """
        result: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "success": False,
            "error": None,
        }

        entry = self.get(plugin_id)
        if entry is None:
            result["error"] = f"Plugin '{plugin_id}' not found"
            return result

        # Spam detection: same user cannot review the same plugin twice
        with self._lock:
            for existing in entry.reviews:
                if existing.user_id == review.user_id:
                    result["error"] = f"User '{review.user_id}' already reviewed '{plugin_id}'"
                    return result

            # Basic comment spam check
            comment = review.comment.strip()
            if comment and len(comment) < 2:
                result["error"] = "Comment too short (minimum 2 characters)"
                return result

            entry.add_review(review)

        result["success"] = True
        logger.info(f"Review added for '{plugin_id}' by '{review.user_id}': {review.rating} stars")
        return result

    def get_reviews(
        self,
        plugin_id: str,
        sort_by: str = "newest",  # newest, highest, lowest, helpful
        limit: int = 50,
    ) -> List[PluginReview]:
        """Get reviews for a plugin"""
        entry = self.get(plugin_id)
        if entry is None:
            return []

        reviews = list(entry.reviews)

        if sort_by == "highest":
            reviews.sort(key=lambda r: r.rating, reverse=True)
        elif sort_by == "lowest":
            reviews.sort(key=lambda r: r.rating)
        elif sort_by == "helpful":
            reviews.sort(key=lambda r: r.helpful_count, reverse=True)
        else:  # newest
            reviews.sort(key=lambda r: r.timestamp, reverse=True)

        return reviews[:limit]

    def get_rating(self, plugin_id: str) -> Dict[str, Any]:
        """Get rating summary for a plugin"""
        entry = self.get(plugin_id)
        if entry is None:
            return {"plugin_id": plugin_id, "average": 0.0, "count": 0, "distribution": {}}

        distribution: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in entry.reviews:
            distribution[r.rating] = distribution.get(r.rating, 0) + 1

        return {
            "plugin_id": plugin_id,
            "average": round(entry.average_rating, 2),
            "count": entry.review_count,
            "distribution": distribution,
        }

    def flag_review(self, plugin_id: str, user_id: str) -> bool:
        """Flag a review as inappropriate"""
        entry = self.get(plugin_id)
        if entry is None:
            return False
        for review in entry.reviews:
            if review.user_id == user_id:
                review.flagged = True
                return True
        return False

    def mark_review_helpful(self, plugin_id: str, user_id: str) -> bool:
        """Increment helpful count on a review"""
        entry = self.get(plugin_id)
        if entry is None:
            return False
        for review in entry.reviews:
            if review.user_id == user_id:
                review.helpful_count += 1
                return True
        return False

    # ---- 4) Version Management ----

    def add_version(self, plugin_id: str, version: PluginVersion) -> bool:
        """Add a new version to an existing plugin"""
        entry = self.get(plugin_id)
        if entry is None:
            return False
        with self._lock:
            entry.add_version(version)
        return True

    def get_versions(self, plugin_id: str) -> List[PluginVersion]:
        """Get all versions for a plugin, sorted newest first"""
        entry = self.get(plugin_id)
        if entry is None:
            return []
        return sorted(entry.versions, key=lambda v: v.to_tuple(), reverse=True)

    def check_updates(self) -> List[Dict[str, Any]]:
        """
        Check for available updates for all installed plugins.

        Returns list of plugins where installed_version < latest_version.
        """
        updates: List[Dict[str, Any]] = []
        with self._lock:
            for entry in self._plugins.values():
                if not entry.installed or entry.installed_version is None:
                    continue
                latest = entry.latest_version
                if latest is None:
                    continue
                if latest > entry.installed_version:
                    updates.append({
                        "plugin_id": entry.plugin_id,
                        "name": entry.name,
                        "installed": str(entry.installed_version),
                        "latest": str(latest),
                        "changelog": latest.changelog,
                    })
        return updates

    def update_plugin(self, plugin_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """
        Update an installed plugin to the latest version (or a specific version).

        Returns same structure as install().
        """
        entry = self.get(plugin_id)
        if entry is None:
            return {"plugin_id": plugin_id, "success": False, "error": "Plugin not found"}
        if not entry.installed:
            return {"plugin_id": plugin_id, "success": False, "error": "Plugin not installed"}

        target = version or (str(entry.latest_version) if entry.latest_version else None)
        if target is None:
            return {"plugin_id": plugin_id, "success": False, "error": "No version available"}

        target_version = PluginVersion.parse(target)
        current = entry.installed_version
        if current is not None and target_version <= current:
            return {
                "plugin_id": plugin_id,
                "success": False,
                "error": f"Already at version {current} (target {target} is not newer)",
            }

        # Re-install at the new version
        return self.install(plugin_id, version=target)

    def rollback(self, plugin_id: str, version: str) -> Dict[str, Any]:
        """Rollback to a previous version"""
        entry = self.get(plugin_id)
        if entry is None:
            return {"plugin_id": plugin_id, "success": False, "error": "Plugin not found"}
        target = entry.get_version(version)
        if target is None:
            return {"plugin_id": plugin_id, "success": False, "error": f"Version '{version}' not found"}
        return self.install(plugin_id, version=version)

    def compare_versions(self, plugin_id: str, v1: str, v2: str) -> Dict[str, Any]:
        """Compare two versions of a plugin"""
        try:
            pv1 = PluginVersion.parse(v1)
            pv2 = PluginVersion.parse(v2)
        except ValueError as e:
            return {"error": str(e)}

        if pv1 > pv2:
            comparison = "newer"
        elif pv1 < pv2:
            comparison = "older"
        else:
            comparison = "equal"

        return {
            "plugin_id": plugin_id,
            "v1": str(pv1),
            "v2": str(pv2),
            "comparison": comparison,
        }

    # ---- Stats / Utility ----

    def stats(self) -> Dict[str, Any]:
        """Market-wide statistics"""
        with self._lock:
            total_plugins = len(self._plugins)
            installed = sum(1 for p in self._plugins.values() if p.installed)
            total_reviews = sum(p.review_count for p in self._plugins.values())
            categories = self.get_categories()
            return {
                "total_plugins": total_plugins,
                "installed_plugins": installed,
                "total_downloads": self._total_downloads,
                "total_reviews": total_reviews,
                "categories": categories,
                "category_count": len(categories),
            }

    def top_rated(self, limit: int = 10) -> List[PluginEntry]:
        """Get top-rated plugins (must have at least 1 review)"""
        with self._lock:
            rated = [p for p in self._plugins.values() if p.review_count > 0]
            rated.sort(key=lambda p: p.average_rating, reverse=True)
            return rated[:limit]

    def top_downloaded(self, limit: int = 10) -> List[PluginEntry]:
        """Get most-downloaded plugins"""
        with self._lock:
            plugins = list(self._plugins.values())
            plugins.sort(key=lambda p: p.download_count, reverse=True)
            return plugins[:limit]

    def reset(self) -> None:
        """Reset the entire market to empty state"""
        with self._lock:
            self._plugins.clear()
            self._install_history.clear()
            self._total_downloads = 0


# ============================================================
# Module-level Singleton
# ============================================================

_plugin_market: Optional[PluginMarket] = None


def get_plugin_market() -> PluginMarket:
    """Get the module-level PluginMarket singleton"""
    global _plugin_market
    if _plugin_market is None:
        _plugin_market = PluginMarket()
    return _plugin_market


def reset_plugin_market() -> None:
    """Reset the module-level PluginMarket singleton"""
    global _plugin_market
    _plugin_market = None
