"""
MeshCtx Conversation Persistence — Survive Restarts
=====================================================
Simple JSON file-based conversation store with auto-save.
"""
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Optional
import logging
import threading

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".meshctx" / "conversations"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Conversation:
    def __init__(self, conv_id: str = "", title: str = "New Chat"):
        self.id = conv_id or f"conv_{int(time.time())}_{os.urandom(4).hex()}"
        self.title = title
        self.messages: List[Dict] = []
        self.model: str = ""
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.message_count: int = 0

    def add(self, role: str, content: str):
        msg = {"role": role, "content": content, "time": time.time()}
        self.messages.append(msg)
        self.message_count = len(self.messages)
        self.updated_at = time.time()
        if role == "user" and self.title == "New Chat":
            self.title = content[:60]

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "messages": self.messages[-100:],  # Keep last 100
        }

    def save(self):
        path = DATA_DIR / f"{self.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, conv_id: str) -> Optional["Conversation"]:
        path = DATA_DIR / f"{conv_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = cls(data["id"], data.get("title", ""))
        c.messages = data.get("messages", [])
        c.model = data.get("model", "")
        c.created_at = data.get("created_at", 0)
        c.updated_at = data.get("updated_at", 0)
        c.message_count = data.get("message_count", 0)
        return c

    @classmethod
    def list_all(cls) -> List[Dict]:
        convs = []
        for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                convs.append({
                    "id": data.get("id", path.stem),
                    "title": data.get("title", ""),
                    "model": data.get("model", ""),
                    "message_count": data.get("message_count", 0),
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                })
            except Exception:
                pass
        return convs[:50]

    @classmethod
    def delete(cls, conv_id: str) -> bool:
        path = DATA_DIR / f"{conv_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    @classmethod
    def delete_all(cls) -> int:
        count = 0
        for path in DATA_DIR.glob("*.json"):
            path.unlink()
            count += 1
        return count

    @classmethod
    def rename(cls, conv_id: str, new_title: str) -> bool:
        """Rename a conversation by updating its title in the JSON file."""
        path = DATA_DIR / f"{conv_id}.json"
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["title"] = new_title
            data["updated_at"] = time.time()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Update in-memory cache if active
            if conv_id in _active:
                _active[conv_id].title = new_title
                _active[conv_id].updated_at = time.time()
            return True
        except Exception:
            return False

    @classmethod
    def prune(cls, older_than_days: int = 30) -> Dict:
        """Delete all conversations older than N days. Returns stats."""
        cutoff = time.time() - (older_than_days * 86400)
        deleted = 0
        total_size = 0
        for path in DATA_DIR.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if mtime < cutoff:
                    total_size += path.stat().st_size
                    path.unlink()
                    deleted += 1
                    # Also remove from active cache
                    conv_id = path.stem
                    if conv_id in _active:
                        del _active[conv_id]
            except OSError:
                pass
        return {
            "deleted": deleted,
            "freed_bytes": total_size,
            "older_than_days": older_than_days,
            "cutoff_timestamp": cutoff,
        }

    @classmethod
    def stats(cls) -> Dict:
        """Return session store statistics."""
        files = list(DATA_DIR.glob("*.json"))
        total_size = sum(p.stat().st_size for p in files if p.exists())
        total_messages = 0
        oldest_ts = float("inf")
        newest_ts = 0
        model_counts: Dict[str, int] = {}
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                total_messages += data.get("message_count", 0)
                ts = data.get("created_at", 0)
                if ts < oldest_ts:
                    oldest_ts = ts
                if ts > newest_ts:
                    newest_ts = ts
                model = data.get("model", "unknown")
                model_counts[model] = model_counts.get(model, 0) + 1
            except Exception:
                pass
        return {
            "total_sessions": len(files),
            "total_messages": total_messages,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "oldest_session_ts": oldest_ts if oldest_ts != float("inf") else 0,
            "newest_session_ts": newest_ts,
            "active_in_memory": len(_active),
            "model_distribution": model_counts,
        }

    @classmethod
    def browse_meta(cls, limit: int = 50, offset: int = 0,
                    search: str = "") -> List[Dict]:
        """Browse session metadata with optional search and pagination."""
        all_meta = cls.list_all()
        # Filter by search term (in title)
        if search:
            search_lower = search.lower()
            all_meta = [m for m in all_meta
                        if search_lower in m.get("title", "").lower()]
        # Apply pagination
        return all_meta[offset:offset + limit]


# In-memory active conversation cache
_active: Dict[str, Conversation] = {}


def get_or_create(conv_id: str = "") -> Conversation:
    if conv_id and conv_id in _active:
        return _active[conv_id]
    if conv_id:
        loaded = Conversation.load(conv_id)
        if loaded:
            _active[conv_id] = loaded
            return loaded
    c = Conversation(conv_id)
    _active[c.id] = c
    return c


def auto_save(conv_id: str):
    if conv_id in _active:
        _active[conv_id].save()
