"""
MeshCtx Versioned Memory — Learn from WorkBuddy
=================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Version-tracked memory with auto-incrementing versions.
Inspired by WorkBuddy's memery system (190 versions).
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
import logging
import threading

logger = logging.getLogger(__name__)

MEMORY_DIR = Path.home() / ".meshctx" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = MEMORY_DIR / "memory-state.json"


class VersionedMemory:
    """Memory system with version tracking and incremental updates."""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.memory_file = MEMORY_DIR / f"{user_id}_memory.md"
        self.state = self._load_state()
        self._lock = threading.Lock()

    def _load_state(self) -> Dict:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {}

    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2)

    @property
    def version(self) -> int:
        return self.state.get(self.user_id, {}).get("current_version", 0)

    def increment(self):
        with self._lock:
            uid_state = self.state.setdefault(self.user_id, {"current_version": 0})
            uid_state["current_version"] += 1
            uid_state["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            self._save_state()
        return self.version

    def read(self) -> str:
        if not self.memory_file.exists():
            return "# Memory Profile\n\n> No memory yet."
        with open(self.memory_file, "r") as f:
            return f.read()

    def update(self, section: str, content: str):
        """Update a specific section of memory."""
        current = self.read()
        new_version = self.increment()

        header = f"# User Memory Profile\n\n"
        header += f"> Last updated: {time.strftime('%Y-%m-%dT%H:%M:%S+08:00')}\n"
        header += f"> Version: {new_version}\n\n"

        # Simple section replacement
        marker = f"## {section}"
        new_section = f"{marker}\n\n{content}\n"

        if marker in current:
            # Replace existing section
            parts = current.split(f"## ")
            new_parts = []
            for p in parts:
                if p.startswith(section):
                    new_parts.append(f"{section}\n\n{content}\n")
                else:
                    new_parts.append(p)
            result = header + "## " + "\n## ".join(new_parts).replace(header, "")
        else:
            result = current + f"\n{new_section}"

        with open(self.memory_file, "w") as f:
            f.write(result)

        return new_version

    def append_section(self, title: str, content: str):
        """Append a new section."""
        current = self.read()
        self.increment()
        new_section = f"\n## {title}\n\n{content}\n"
        with open(self.memory_file, "w") as f:
            f.write(current + new_section)

    def get_stats(self) -> Dict:
        return {
            "user_id": self.user_id,
            "version": self.version,
            "file_size": self.memory_file.stat().st_size if self.memory_file.exists() else 0,
            "last_updated": self.state.get(self.user_id, {}).get("last_updated", "never"),
        }


# Global
_memories: Dict[str, VersionedMemory] = {}


def get_memory(user_id: str = "default") -> VersionedMemory:
    if user_id not in _memories:
        _memories[user_id] = VersionedMemory(user_id)
    return _memories[user_id]
