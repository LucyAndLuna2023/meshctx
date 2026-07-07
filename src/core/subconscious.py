"""meshctx subconscious — subconscious observer with multi-channel nudge system."""
import time
from enum import Enum


class NudgePriority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    INSIGHT = 5


class NudgeSource(Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    SYSTEMIC = "systemic"
    MEMORY = "memory"
    PREDICTIVE = "predictive"


_PRIORITY_EMOJI = {
    NudgePriority.CRITICAL: "\U0001f6a8",   # 🚨
    NudgePriority.HIGH: "\u26a0\ufe0f",       # ⚠️
    NudgePriority.MEDIUM: "\U0001f4cc",       # 📌
    NudgePriority.LOW: "\u2139\ufe0f",        # ℹ️
    NudgePriority.INSIGHT: "\U0001f4a1",      # 💡
}


class Nudge:
    def __init__(self, title="", detail="", action="",
                 priority=NudgePriority.MEDIUM, source=NudgeSource.INTERNAL,
                 expires_at=None):
        self.title = title
        self.detail = detail
        self.action = action
        self.priority = priority
        self.source = source
        self.expires_at = expires_at

    def is_expired(self):
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_context(self):
        emoji = _PRIORITY_EMOJI.get(self.priority, "\U0001f4cc")
        return f"{emoji} {self.title}: {self.detail}"


class SubconsciousObserver:
    def __init__(self, config=None):
        config = config or {}
        self._scan_interval = config.get("scan_interval", 300)
        self._max_nudges = config.get("max_nudges", 5)
        self._last_scan = 0
        self._nudges: list[Nudge] = []
        self._nudge_history: list[Nudge] = []
        self._enabled_channels = {
            "internal": config.get("internal", True),
            "external": config.get("external", True),
            "systemic": config.get("systemic", True),
            "memory": config.get("memory", True),
            "predictive": config.get("predictive", True),
        }

    def inject(self, nudges):
        if not nudges:
            return ""
        lines = ["Subconscious Observer:"]
        for n in nudges:
            lines.append(n.to_context())
        return "\n".join(lines)

    def analyze(self, new_nudges):
        self._nudges = [n for n in self._nudges if not n.is_expired()]
        existing_titles = {n.title for n in self._nudges}
        unique_new = [n for n in new_nudges if n.title not in existing_titles]
        self._nudges.extend(unique_new)
        self._nudge_history.extend(unique_new)
        self._nudges.sort(key=lambda n: n.priority.value)
        self._nudges = self._nudges[:self._max_nudges]
        unique_new.sort(key=lambda n: n.priority.value)
        return unique_new[:self._max_nudges]

    def observe_internal(self):
        return []

    def observe_external(self):
        return []

    def observe_systemic(self):
        return []

    def observe_memory(self):
        return []

    def observe_predictive(self):
        return []

    def get_stats(self):
        by_source = {"internal": 0, "external": 0, "systemic": 0, "memory": 0, "predictive": 0}
        by_priority = {"critical": 0, "high": 0, "medium": 0, "low": 0, "insight": 0}
        for n in self._nudge_history:
            src_key = n.source.value
            by_source[src_key] = by_source.get(src_key, 0) + 1
            pri_key = n.priority.name.lower()
            by_priority[pri_key] = by_priority.get(pri_key, 0) + 1
        return {
            "total_nudges_generated": len(self._nudge_history),
            "history_by_source": by_source,
            "history_by_priority": by_priority,
        }

    async def cycle(self):
        self._last_scan = time.time()
        nudges = []
        for channel, enabled in self._enabled_channels.items():
            if not enabled:
                continue
            method = getattr(self, f"observe_{channel}", None)
            if method is not None:
                nudges.extend(method())
        return nudges


_observer = None


def get_observer():
    global _observer
    if _observer is None:
        _observer = SubconsciousObserver()
    return _observer
