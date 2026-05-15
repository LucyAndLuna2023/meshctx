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
