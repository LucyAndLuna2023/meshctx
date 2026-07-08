"""Session Resume — 开源版 (stub)"""
import json
import logging
from pathlib import Path

logger = logging.getLogger("meshctx.session_resume")


class SessionState:
    """Represents a stored session state."""
    def __init__(self, id, profile, messages):
        self.id = id
        self.profile = profile
        self.messages = messages


class SessionResumeEngine:
    """Engine for saving and resuming sessions using file-based storage."""

    def __init__(self, storage):
        self.storage = Path(storage)
        self.storage.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id):
        return self.storage / f"{session_id}.json"

    def save(self, session_id, data):
        """Save session data to disk."""
        path = self._session_path(session_id)
        path.write_text(json.dumps(data))

    def resume(self, session_id):
        """Resume a session. Returns session data dict or None if not found."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_recent(self, limit):
        """List up to `limit` most recently modified sessions."""
        paths = sorted(
            self.storage.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [json.loads(p.read_text()) for p in paths[:limit]]

    def get_stats(self):
        """Return statistics about stored sessions."""
        sessions = list(self.storage.glob("*.json"))
        return {"sessions": len(sessions)}


class _SessionResume:
    def resume(self, *a, **kw): return None
    def stats(self): return {}
    def detect_previous_session(self, **kw):
        """检测是否存在上次会话存档"""
        return None  # 开源版不实现自动恢复
    def restore(self, session_id, **kw):
        """恢复指定会话"""
        return {"context_continuity": 0, "items_restored": {"decisions": 0, "rules": 0}, "resume_time_ms": 0}
    def apply_to_kernel(self, kernel, **kw):
        """将会话上下文注入内核"""
        return []

_resume = _SessionResume()
def get_session_resume(): return _resume

