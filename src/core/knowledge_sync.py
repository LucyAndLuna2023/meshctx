"""meshctx knowledge_sync — real implementation (Cross-Agent Knowledge Sync)"""

import time
import uuid
from enum import Enum


class KnowledgeDomain(str, Enum):
    GENERAL = "general"
    SECURITY = "security"
    DEVELOPMENT = "development"
    DEPLOYMENT = "deployment"
    PERFORMANCE = "performance"
    TESTING = "testing"


class SyncPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProfileInfo:
    """Profile information for a sync consumer."""
    def __init__(self, name="", domains=None):
        self.name = name
        self.domains = list(domains) if domains else []


class KnowledgeItem:
    """A single knowledge item shared across agents."""

    def __init__(self, title="", content="", domain=None, priority=None,
                 expires_at=None, tags=None, source_profile="", solution=""):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.content = content
        self.domain = domain if domain is not None else KnowledgeDomain.GENERAL
        self.priority = priority if priority is not None else SyncPriority.MEDIUM
        self.expires_at = expires_at
        self.tags = list(tags) if tags else []
        self.source_profile = source_profile
        self.solution = solution
        self.helpful_count = 0
        self.created_at = time.time()

    def mark_helpful(self):
        """Increment the helpfulness counter."""
        self.helpful_count += 1

    def is_expired(self):
        """Check if this item has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_summary(self):
        """Return a concise summary string."""
        parts = [self.domain.value, self.title]
        if self.content:
            parts.append(self.content[:50])
        return " - ".join(parts)


class KnowledgeBus:
    """Publish-subscribe knowledge bus for cross-agent sync."""

    def __init__(self, storage_path=None):
        self._items = {}
        self._profiles = {}
        self._subscribers = {}
        self.storage_path = storage_path

    def publish(self, item):
        """Publish a knowledge item to the bus."""
        self._items[item.id] = item
        self._notify(item)

    def _notify(self, item):
        """Notify relevant subscribers about a new item."""
        for name, callback in self._subscribers.items():
            try:
                callback(item)
            except Exception:
                pass

    def subscribe(self, name, callback):
        """Subscribe to new knowledge items."""
        self._subscribers[name] = callback

    def query(self, domain=None, tags=None):
        """Query items by domain and/or tags."""
        results = []
        for item in self._items.values():
            if domain is not None and item.domain != domain:
                continue
            if tags is not None:
                if not any(t in item.tags for t in tags):
                    continue
            results.append(item)
        return results

    def search(self, query):
        """Full-text search across knowledge items."""
        query_lower = query.lower()
        results = []
        for item in self._items.values():
            if query_lower in item.title.lower():
                results.append(item)
            elif query_lower in item.content.lower():
                results.append(item)
            elif any(query_lower in t.lower() for t in item.tags):
                results.append(item)
        return results

    def mark_helpful(self, item_id):
        """Mark an item as helpful."""
        if item_id in self._items:
            self._items[item_id].mark_helpful()

    def cleanup_expired(self):
        """Remove expired items. Returns count of removed items."""
        expired_ids = [iid for iid, item in self._items.items() if item.is_expired()]
        for iid in expired_ids:
            del self._items[iid]
        return len(expired_ids)

    def register_profile(self, profile):
        """Register a profile for domain-based sync."""
        self._profiles[profile.name] = profile

    def get_for_profile(self, profile_name):
        """Get knowledge items relevant to a profile's domains."""
        if profile_name not in self._profiles:
            return []
        profile = self._profiles[profile_name]
        results = []
        for item in self._items.values():
            if item.domain in profile.domains:
                results.append(item)
            # Also include items with overlapping tags
            elif item.source_profile == profile_name:
                results.append(item)
        return results

    def get_stats(self):
        """Return bus statistics."""
        return {
            "total_items": len(self._items),
            "profiles": len(self._profiles),
            "subscribers": len(self._subscribers),
        }


class CrossAgentSyncEngine:
    """Engine for cross-agent knowledge synchronization."""

    def __init__(self):
        self.bus = KnowledgeBus()
        self._sync_count = 0

    def learn_from_error(self, profile, error_type, description, solution):
        """Learn from an error encountered by an agent."""
        item = KnowledgeItem(
            title=f"{error_type}: {description[:60]}",
            content=description,
            domain=KnowledgeDomain.PERFORMANCE,
            priority=SyncPriority.HIGH,
            source_profile=profile,
            solution=solution,
            tags=["error", error_type.lower()],
        )
        self.bus.publish(item)
        return item

    def learn_from_pattern(self, profile, pattern_name, description, solution):
        """Learn from a discovered pattern."""
        item = KnowledgeItem(
            title=f"{pattern_name}: {description[:60]}",
            content=description,
            domain=KnowledgeDomain.GENERAL,
            priority=SyncPriority.MEDIUM,
            source_profile=profile,
            solution=solution,
            tags=["pattern", pattern_name],
        )
        self.bus.publish(item)
        return item

    def sync_to_profile(self, profile_name):
        """Sync knowledge items to a specific profile."""
        self._sync_count += 1
        # Return items from other profiles (cross-agent sync is profile-agnostic)
        items = []
        for item in self.bus._items.values():
            if item.source_profile and item.source_profile != profile_name:
                items.append(item)
        return items

    def get_cross_agent_insights(self, profile_name):
        """Get cross-agent insights for a profile."""
        profile_items = self.bus.get_for_profile(profile_name)
        # Also include general items that might be useful
        general_items = self.bus.query(domain=KnowledgeDomain.GENERAL)
        all_items = profile_items + [i for i in general_items if i not in profile_items]
        return list(all_items)

    def get_stats(self):
        """Return engine statistics."""
        return {
            "bus": self.bus.get_stats(),
            "sync_count": self._sync_count,
        }


_bus = None
_engine = None


def get_knowledge_bus():
    """Get the singleton KnowledgeBus instance."""
    global _bus
    if _bus is None:
        _bus = KnowledgeBus()
    return _bus


def get_sync_engine():
    """Get the singleton CrossAgentSyncEngine instance."""
    global _engine
    if _engine is None:
        _engine = CrossAgentSyncEngine()
    return _engine
