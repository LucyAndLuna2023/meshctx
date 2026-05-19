"""
文件快照回滚系统 — Checkpoint Manager
========================================
TDD: 7/7 tests. tar.gz-based checkpoint/rollback.

存储: ~/.meshctx/checkpoints/{session_id}/
"""
import os
import json
import uuid
import tarfile
import fnmatch
import time
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_PATTERNS = [
    "*.pyc", "__pycache__", ".git", "*.log", "*.tmp", "node_modules"
]


class CheckpointManager:
    """文件系统快照管理 — 支持保存、列表、回滚、清空。"""

    def __init__(self, workdir: str, max_snapshots: int = 50,
                 ignore_patterns: Optional[List[str]] = None):
        self.workdir = Path(workdir).resolve()
        self.max_snapshots = max_snapshots
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
        self.session_id = uuid.uuid4().hex
        self._storage = Path.home() / ".meshctx" / "checkpoints" / self.session_id
        self._storage.mkdir(parents=True, exist_ok=True)
        self._index_path = self._storage / "index.json"
        self._index: List[Dict] = []
        self._load_index()

    # ── internal helpers ──────────────────────────────────────────

    def _load_index(self):
        if self._index_path.exists():
            with open(self._index_path) as f:
                self._index = json.load(f)

    def _save_index(self):
        with open(self._index_path, "w") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    def _should_ignore(self, name: str) -> bool:
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _get_files_to_archive(self) -> List[Path]:
        """Collect regular files in workdir, skipping ignore_patterns."""
        files = []
        for entry in self.workdir.rglob("*"):
            # Check every path component against ignore patterns
            parts = entry.relative_to(self.workdir).parts
            if any(self._should_ignore(p) for p in parts):
                continue
            if entry.is_file():
                files.append(entry)
        return files

    # ── public API ────────────────────────────────────────────────

    def save(self, label: str = "") -> str:
        """Create a checkpoint snapshot. Returns checkpoint_id (UUID hex)."""
        cid = uuid.uuid4().hex
        archive_path = self._storage / f"{cid}.tar.gz"

        files = self._get_files_to_archive()
        file_count = len(files)

        with tarfile.open(archive_path, "w:gz") as tar:
            for fpath in files:
                arcname = fpath.relative_to(self.workdir)
                tar.add(fpath, arcname=str(arcname))

        meta = {
            "id": cid,
            "label": label,
            "timestamp": time.time(),
            "file_count": file_count,
        }
        self._index.append(meta)

        # Enforce max_snapshots cap — oldest first
        while len(self._index) > self.max_snapshots:
            removed = self._index.pop(0)
            old_archive = self._storage / f"{removed['id']}.tar.gz"
            if old_archive.exists():
                old_archive.unlink()

        self._save_index()
        logger.info("Checkpoint saved: %s (%d files)", cid, file_count)
        return cid

    def list(self) -> List[Dict]:
        """Return all checkpoints ordered oldest→newest.

        Each entry: {id, label, timestamp, file_count}
        """
        return list(self._index)

    def rollback(self, checkpoint_id: Optional[str] = None):
        """Restore workdir to a checkpoint.

        Without arguments restores the most recent checkpoint.
        """
        if not self._index:
            raise ValueError("No checkpoints available for rollback")

        if checkpoint_id is None:
            target = self._index[-1]
        else:
            matches = [c for c in self._index if c["id"] == checkpoint_id]
            if not matches:
                raise ValueError(f"Checkpoint {checkpoint_id} not found")
            target = matches[0]

        archive_path = self._storage / f"{target['id']}.tar.gz"
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive missing: {archive_path}")

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(str(self.workdir))

        logger.info("Rolled back to checkpoint %s (%s)", target["id"], target["label"])

    def clear(self):
        """Remove all snapshots for this session."""
        for item in self._index:
            arch = self._storage / f"{item['id']}.tar.gz"
            if arch.exists():
                arch.unlink()
        if self._index_path.exists():
            self._index_path.unlink()
        self._index.clear()
        logger.info("All checkpoints cleared")
