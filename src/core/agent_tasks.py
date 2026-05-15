"""
MeshCtx Agent Task Store — Persistent Task History
====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.
"""
import json
import time
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

TASKS_DIR = Path.home() / ".meshctx" / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AgentTask:
    """A recorded agent task."""
    id: str = ""
    title: str = ""
    status: str = "pending"  # pending/running/done/failed/cancelled
    priority: int = 5
    created_at: float = field(default_factory=time.time)
    started_at: float = 0
    completed_at: float = 0
    duration_ms: float = 0
    result: str = ""
    error: str = ""
    agent: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "title": self.title,
            "status": self.status, "priority": self.priority,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "result": self.result[:500] if self.result else "",
            "error": self.error, "agent": self.agent,
        }

    def save(self):
        if not self.id:
            self.id = f"task_{int(time.time())}_{id(self) % 10000}"
        path = TASKS_DIR / f"{self.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, task_id: str) -> Optional["AgentTask"]:
        path = TASKS_DIR / f"{task_id}.json"
        if not path.exists():
            return None
        with open(path, "r") as f:
            d = json.load(f)
        t = cls(id=d.get("id", ""), title=d.get("title", ""))
        t.status = d.get("status", "pending")
        t.priority = d.get("priority", 5)
        t.created_at = d.get("created_at", 0)
        t.started_at = d.get("started_at", 0)
        t.completed_at = d.get("completed_at", 0)
        t.duration_ms = d.get("duration_ms", 0)
        t.result = d.get("result", "")
        t.error = d.get("error", "")
        t.agent = d.get("agent", "")
        return t

    @classmethod
    def list_recent(cls, limit: int = 20) -> List[Dict]:
        tasks = []
        for p in sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(p) as f:
                    d = json.load(f)
                tasks.append(d)
                if len(tasks) >= limit:
                    break
            except Exception:
                pass
        return tasks

    @classmethod
    def stats(cls) -> Dict:
        """Task statistics."""
        total = 0
        done = 0
        failed = 0
        running = 0
        for p in TASKS_DIR.glob("*.json"):
            try:
                with open(p) as f:
                    d = json.load(f)
                total += 1
                s = d.get("status", "")
                if s == "done": done += 1
                elif s == "failed": failed += 1
                elif s == "running": running += 1
            except Exception:
                pass
        return {"total": total, "done": done, "failed": failed, "running": running}
