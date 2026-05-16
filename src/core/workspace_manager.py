"""
MeshCtx Workspace Manager — Learn from OpenWork
=================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Multi-workspace support with active tracking, last-used timestamps.
Inspired by OpenWork's orchestrator-state.json workspace management.
"""
import json
import time
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".meshctx"
STATE_FILE = STATE_DIR / "workspaces.json"
STATE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Workspace:
    """A MeshCtx workspace."""
    id: str = ""
    name: str = "default"
    path: str = ""
    workspace_type: str = "local"  # local, git, remote
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    description: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "workspace_type": self.workspace_type,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Workspace":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "default"),
            path=d.get("path", ""),
            workspace_type=d.get("workspace_type", "local"),
            created_at=d.get("created_at", 0),
            last_used_at=d.get("last_used_at", 0),
            description=d.get("description", ""),
            tags=d.get("tags", []),
        )


class WorkspaceManager:
    """Multi-workspace management (learned from OpenWork)."""

    def __init__(self):
        self.state = self._load()

    def _load(self) -> Dict:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {"workspaces": [], "active_id": ""}

    def _save(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    @property
    def active(self) -> Optional[Workspace]:
        aid = self.state.get("active_id", "")
        for w in self._get_all():
            if w.id == aid:
                return w
        return None

    def _get_all(self) -> List[Workspace]:
        return [Workspace.from_dict(w) for w in self.state.get("workspaces", [])]

    def list_all(self) -> List[Dict]:
        return [w.to_dict() for w in self._get_all()]

    def add(self, name: str, path: str, workspace_type: str = "local",
            description: str = "", tags: List[str] = None) -> Workspace:
        import uuid
        ws = Workspace(
            id=f"ws-{uuid.uuid4().hex[:12]}",
            name=name,
            path=str(Path(path).resolve()),
            workspace_type=workspace_type,
            description=description,
            tags=tags or [],
        )
        self.state["workspaces"].append(ws.to_dict())
        if not self.state.get("active_id"):
            self.state["active_id"] = ws.id
        self._save()
        return ws

    def set_active(self, ws_id: str) -> bool:
        for w in self.state.get("workspaces", []):
            if w.get("id") == ws_id:
                self.state["active_id"] = ws_id
                w["last_used_at"] = time.time()
                self._save()
                return True
        return False

    def remove(self, ws_id: str) -> bool:
        ws_list = self.state.get("workspaces", [])
        for i, w in enumerate(ws_list):
            if w.get("id") == ws_id:
                del ws_list[i]
                if self.state.get("active_id") == ws_id:
                    self.state["active_id"] = ws_list[0].get("id", "") if ws_list else ""
                self._save()
                return True
        return False

    def touch(self, ws_id: str):
        for w in self.state.get("workspaces", []):
            if w.get("id") == ws_id:
                w["last_used_at"] = time.time()
                self._save()
                return

    def get_current_context(self) -> Dict:
        """Get context for the active workspace."""
        active = self.active
        if not active:
            return {"workspace": None, "path": os.getcwd()}
        return {
            "workspace": active.to_dict(),
            "path": active.path,
            "indexer_ready": os.path.exists(active.path) if active.path else False,
        }


# Global
_manager = WorkspaceManager()


def get_workspace_manager() -> WorkspaceManager:
    return _manager
