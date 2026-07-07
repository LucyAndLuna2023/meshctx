"""meshctx checkpoint — real implementation"""

import os
import shutil
import time
import uuid
import fnmatch
from typing import Dict, Any, List, Optional


class CheckpointManager:
    """File-system checkpoint/rollback manager."""

    def __init__(self, workdir: str, max_snapshots: int = 10, ignore_patterns: Optional[List[str]] = None):
        self.workdir = os.path.abspath(workdir)
        self.max_snapshots = max_snapshots
        self.ignore_patterns = ignore_patterns or []
        self._checkpoints: List[Dict[str, Any]] = []
        self._checkpoint_dir = os.path.join(self.workdir, ".meshctx_checkpoints")
        os.makedirs(self._checkpoint_dir, exist_ok=True)

    def _should_ignore(self, rel_path: str) -> bool:
        """Check if a file should be ignored based on patterns."""
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return True
            # Check directory components
            for part in rel_path.split(os.sep):
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def save(self, label: str = "") -> str:
        """Save a checkpoint of the workdir."""
        cid = str(uuid.uuid4())[:8]
        checkpoint_path = os.path.join(self._checkpoint_dir, cid)
        os.makedirs(checkpoint_path, exist_ok=True)

        file_count = 0
        for root, dirs, files in os.walk(self.workdir):
            # Skip checkpoint dir itself
            if ".meshctx_checkpoints" in root:
                continue
            rel_root = os.path.relpath(root, self.workdir)
            if self._should_ignore(rel_root):
                continue

            for fname in files:
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, self.workdir)
                if self._should_ignore(rel_path):
                    continue
                dest = os.path.join(checkpoint_path, rel_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(fpath, dest)
                file_count += 1

        entry = {
            "id": cid,
            "label": label or f"checkpoint_{cid}",
            "ts": time.time(),
            "files": file_count,
        }
        self._checkpoints.append(entry)

        # Enforce max_snapshots
        while len(self._checkpoints) > self.max_snapshots:
            oldest = self._checkpoints.pop(0)
            old_path = os.path.join(self._checkpoint_dir, oldest["id"])
            shutil.rmtree(old_path, ignore_errors=True)

        return cid

    def list(self) -> List[Dict[str, Any]]:
        """List all saved checkpoints."""
        return list(self._checkpoints)

    def rollback(self, checkpoint_id: Optional[str] = None) -> None:
        """Rollback to a specific checkpoint or the latest one."""
        if not self._checkpoints:
            return

        target = None
        if checkpoint_id:
            for cp in self._checkpoints:
                if cp["id"] == checkpoint_id:
                    target = cp
                    break
        if target is None:
            target = self._checkpoints[-1]

        checkpoint_path = os.path.join(self._checkpoint_dir, target["id"])
        for root, dirs, files in os.walk(checkpoint_path):
            rel_root = os.path.relpath(root, checkpoint_path)
            for fname in files:
                src = os.path.join(root, fname)
                dest = os.path.join(self.workdir, rel_root, fname)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)

    def clear(self) -> None:
        """Clear all checkpoints."""
        self._checkpoints = []
        shutil.rmtree(self._checkpoint_dir, ignore_errors=True)
        os.makedirs(self._checkpoint_dir, exist_ok=True)
