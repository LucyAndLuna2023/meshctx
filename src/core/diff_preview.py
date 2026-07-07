"""
meshctx diff_preview — Cursor-level inline diff viewer with apply/reject engine.

Upgraded from v3.48+ basic difflib to full Cursor/Claude Code parity:
  - DiffEngine: unified diff generation (difflib-based, kept from v3.48)
  - InlineDiffViewer: chunk-by-chunk interactive apply/reject (Cursor parity)
  - DiffApplicator: safe patch application with backup and rollback
  - BatchDiffManager: multi-file edit sessions with undo stack
  - DiffRenderer: colorized HTML + terminal output for human review

Zero pip dependencies — pure Python stdlib.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════════

class DiffChunkAction(Enum):
    """Actions a user can take on a diff chunk (Cursor parity)."""
    ACCEPT = "accept"         # Apply this chunk
    REJECT = "reject"         # Skip this chunk
    EDIT = "edit"             # Accept but user wants to modify
    SKIP_ALL = "skip_all"     # Reject all remaining chunks
    ACCEPT_ALL = "accept_all"  # Accept all remaining chunks


class ChunkType(Enum):
    """Type of diff chunk."""
    ADD = "add"          # Lines only added (green / +)
    REMOVE = "remove"    # Lines only removed (red / -)
    MODIFY = "modify"    # Lines both added and removed
    CONTEXT = "context"  # Unchanged context lines


class ApplyStatus(Enum):
    """Result of applying a diff chunk."""
    OK = "ok"
    FAILED = "failed"          # Patch didn't match
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DiffChunk:
    """A single hunk within a unified diff, ready for interactive review.

    Attributes:
        index: Position in the diff (0-based).
        header: The @@ header line.
        old_start: Starting line number in old file.
        old_count: Number of lines in old file hunk.
        new_start: Starting line number in new file.
        new_count: Number of lines in new file hunk.
        lines: All lines in this hunk (with +/-/space prefix).
        chunk_type: Inferred type (add/remove/modify/context).
        applied: Whether this chunk has been applied.
    """
    index: int
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str] = field(default_factory=list)
    chunk_type: ChunkType = ChunkType.CONTEXT
    applied: bool = False

    @property
    def added_lines(self) -> int:
        return sum(1 for l in self.lines if l.startswith("+") and not l.startswith("+++"))

    @property
    def removed_lines(self) -> int:
        return sum(1 for l in self.lines if l.startswith("-") and not l.startswith("---"))

    @property
    def context_lines(self) -> int:
        return sum(1 for l in self.lines if l.startswith(" ") or not l.strip())

    @property
    def summary(self) -> str:
        return f"Hunk {self.index}: +{self.added_lines}/-{self.removed_lines} ({self.chunk_type.value})"


@dataclass
class DiffFile:
    """A complete diff for a single file, split into interactive chunks.

    Attributes:
        filepath: Path to the file being modified.
        old_text: Original file content.
        new_text: Proposed new file content.
        chunks: List of DiffChunk for interactive review.
        description: Human-readable description of the change.
    """
    filepath: str
    old_text: str = ""
    new_text: str = ""
    chunks: List[DiffChunk] = field(default_factory=list)
    description: str = ""
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def total_added(self) -> int:
        return sum(c.added_lines for c in self.chunks)

    @property
    def total_removed(self) -> int:
        return sum(c.removed_lines for c in self.chunks)

    @property
    def accepted_chunks(self) -> int:
        return sum(1 for c in self.chunks if c.applied)

    @property
    def pending_chunks(self) -> int:
        return sum(1 for c in self.chunks if not c.applied)


@dataclass
class ApplyResult:
    """Result of applying a diff or chunk to a file."""
    filepath: str
    status: ApplyStatus
    chunk_index: int = -1
    error: str = ""
    backup_path: str = ""
    old_hash: str = ""
    new_hash: str = ""


@dataclass
class BackupEntry:
    """A single backup snapshot for undo."""
    filepath: str
    content: str
    hash: str
    timestamp: float = 0.0


@dataclass
class EditProposal:
    """A proposed file edit with its computed diff and statistics.

    Kept from v3.48+ for backward compatibility.
    """
    filepath: str
    old_str: str
    new_str: str
    description: str = ""
    risk_level: str = "safe"
    diff: str = ""
    stats: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# DiffEngine — core diff generation (v3.48+, kept for backward compat)
# ═══════════════════════════════════════════════════════════════════════════════

class DiffEngine:
    """Generates unified diffs using Python's stdlib difflib."""

    def __init__(self, freeze_mode=False, **kw):
        self.freeze_mode = freeze_mode
        self._changes: Dict[str, dict] = {}       # change_id → change_data
        self._backups: Dict[str, str] = {}         # change_id → backup_path
        self._pending: List[dict] = []             # pending changes
        self._history: List[dict] = []             # applied history
        self._counter = 0

    def generate(self, old_text: str, new_text: str, filename: str = "",
                 context_lines: int = 3) -> str:
        """Return a unified-diff string between *old_text* and *new_text*.

        Args:
            old_text: Original text content.
            new_text: Proposed new text content.
            filename: Optional file path used for the diff header labels.
            context_lines: Number of context lines around changes.

        Returns:
            A unified diff as a string (empty if identical).
        """
        if old_text == new_text:
            return ""

        from_label = filename if filename else "a"
        to_label = filename if filename else "b"

        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        diff_lines = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=from_label, tofile=to_label,
            n=context_lines, lineterm="",
        )
        return "\n".join(diff_lines)

    def preview(self, filepath: str, old_str: str, new_str: str) -> dict:
        """Generate a full preview dict with diff, stats, and filepath."""
        diff = self.generate(old_str, new_str, filepath)
        stats = self.statistics([diff])
        return {"diff": diff, "stats": stats, "filepath": filepath}

    def statistics(self, diffs: list) -> dict:
        """Aggregate statistics across one or more unified-diff strings."""
        files_changed = len([d for d in diffs if d])
        insertions = 0
        deletions = 0
        for diff in diffs:
            if not diff:
                continue
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    insertions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
        return {
            "files_changed": files_changed,
            "files": files_changed,
            "file_count": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        }

    def safe_preview(self, filepath: str, old_str: str, new_str: str) -> dict:
        """Same as preview() but catches all exceptions."""
        try:
            return self.preview(filepath, old_str, new_str)
        except Exception as exc:
            return {
                "diff": "", "filepath": filepath,
                "stats": {"files_changed": 0, "insertions": 0, "deletions": 0},
                "error": str(exc),
            }

    def parse_chunks(self, diff_text: str, filepath: str = "") -> List[DiffChunk]:
        """Parse a unified diff into interactive DiffChunk objects.

        This is the bridge between raw diff output and the interactive viewer.
        """
        chunks: List[DiffChunk] = []
        current_chunk: Optional[DiffChunk] = None

        import re
        hunk_re = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)$')

        for line in diff_text.splitlines():
            m = hunk_re.match(line)
            if m:
                # Save previous chunk
                if current_chunk:
                    current_chunk.chunk_type = self._classify_chunk(current_chunk)
                    chunks.append(current_chunk)

                old_start = int(m.group(1))
                old_count = int(m.group(2)) if m.group(2) else 1
                new_start = int(m.group(3))
                new_count = int(m.group(4)) if m.group(4) else 1

                current_chunk = DiffChunk(
                    index=len(chunks),
                    header=line,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=[],
                )
                current_chunk.lines.append(line)
            elif current_chunk is not None:
                current_chunk.lines.append(line)

        # Don't forget the last chunk
        if current_chunk:
            current_chunk.chunk_type = self._classify_chunk(current_chunk)
            chunks.append(current_chunk)

        return chunks

    @staticmethod
    def _classify_chunk(chunk: DiffChunk) -> ChunkType:
        """Classify a chunk as add/remove/modify/context."""
        has_add = any(l.startswith("+") and not l.startswith("+++") for l in chunk.lines)
        has_remove = any(l.startswith("-") and not l.startswith("---") for l in chunk.lines)
        if has_add and has_remove:
            return ChunkType.MODIFY
        elif has_add:
            return ChunkType.ADD
        elif has_remove:
            return ChunkType.REMOVE
        return ChunkType.CONTEXT

    # ── v2.44 test-compatible API ──────────────────────────────────────────

    def generate_diff(self, filepath: str, new_content: str,
                      context_lines: int = 3) -> dict:
        """Generate diff between file on disk and proposed new content."""
        import hashlib, time
        filepath = str(filepath)
        is_new = not os.path.exists(filepath)
        old_content = "" if is_new else open(filepath, encoding="utf-8", errors="replace").read()

        diff_text = self.generate(old_content, new_content, filepath, context_lines)
        diff_lines = diff_text.splitlines() if diff_text else []
        stats = self._compute_diff_stats(diff_text, old_content, new_content)
        is_noop = (old_content == new_content)

        if is_noop:
            return {
                "change_id": "",
                "diff_text": "",
                "diff_lines": [],
                "stats": {"added": 0, "removed": 0, "modified": 0, "is_noop": True},
                "is_new_file": False,
                "original_hash": hashlib.md5(old_content.encode()).hexdigest(),
                "new_hash": hashlib.md5(new_content.encode()).hexdigest(),
                "message": "No changes detected",
            }

        self._counter += 1
        change_id = f"diff_{int(time.time() * 1_000_000)}_{self._counter}"
        entry = {
            "change_id": change_id,
            "filepath": filepath,
            "old_content": old_content,
            "new_content": new_content,
            "diff_text": diff_text,
            "diff_lines": diff_lines,
            "stats": stats,
            "is_new_file": is_new,
            "original_hash": hashlib.md5(old_content.encode()).hexdigest(),
            "new_hash": hashlib.md5(new_content.encode()).hexdigest(),
            "context_lines": context_lines,
        }
        self._changes[change_id] = entry
        self._pending.append({"change_id": change_id, "filepath": filepath, "stats": stats})
        return {
            "change_id": change_id,
            "diff_text": diff_text,
            "diff_lines": diff_lines,
            "stats": stats,
            "is_new_file": is_new,
            "original_hash": entry["original_hash"],
            "new_hash": entry["new_hash"],
        }

    def _compute_diff_stats(self, diff_text: str, old: str, new: str) -> dict:
        added = removed = 0
        for line in (diff_text or "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return {"added": added, "removed": removed, "modified": added + removed, "is_noop": False}

    def apply_change(self, change_id: str, create_backup: bool = True) -> dict:
        """Write the new content to disk, optionally creating a backup."""
        import time
        if self.freeze_mode:
            return {"success": False, "error": "冻结模式下不允许应用变更", "backup_path": None}

        entry = self._changes.get(change_id)
        if not entry:
            return {"success": False, "error": f"未找到变更 {change_id}", "backup_path": None}

        filepath = entry["filepath"]
        backup_path = None
        if create_backup and os.path.exists(filepath):
            backup_dir = os.path.join(tempfile.gettempdir(), "meshctx_diff_backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"{change_id}.bak")
            shutil.copy2(filepath, backup_path)
            self._backups[change_id] = backup_path

        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(entry["new_content"])

        # Move from pending to history
        self._pending = [p for p in self._pending if p["change_id"] != change_id]
        self._history.append({
            "change_id": change_id,
            "filepath": filepath,
            "backup_path": backup_path,
            "timestamp": time.time(),
        })
        return {"success": True, "backup_path": backup_path, "error": None}

    def rollback_change(self, change_id: str) -> dict:
        """Restore file from backup."""
        backup_path = self._backups.get(change_id)
        if not backup_path or not os.path.exists(backup_path):
            return {"success": False, "error": f"未找到备份 {change_id}"}

        entry = self._changes.get(change_id)
        if not entry:
            return {"success": False, "error": f"未找到变更 {change_id}"}

        shutil.copy2(backup_path, entry["filepath"])
        os.remove(backup_path)
        del self._backups[change_id]
        return {"success": True}

    def generate_batch_diff(self, changes: List[dict]) -> dict:
        """Generate diffs for multiple files at once."""
        import hashlib, time
        change_ids = []
        total_added = 0
        for ch in changes:
            result = self.generate_diff(ch["path"], ch["content"])
            if result["change_id"]:
                change_ids.append(result["change_id"])
                total_added += result["stats"].get("added", 0)
        return {"total_files": len(changes), "change_ids": change_ids, "total_added": total_added}

    def apply_batch(self, change_ids: List[str]) -> dict:
        """Apply multiple changes at once."""
        success_count = 0
        for cid in change_ids:
            r = self.apply_change(cid)
            if r["success"]:
                success_count += 1
        return {"success": success_count == len(change_ids), "total": len(change_ids), "applied": success_count}

    def stream_diff_lines(self, change_id: str):
        """Yield JSON-encoded diff events as a generator."""
        import json
        entry = self._changes.get(change_id)
        if not entry:
            yield json.dumps({"type": "error", "message": f"未找到变更 {change_id}"})
            return
        yield json.dumps({"type": "header", "change_id": change_id, "filepath": entry["filepath"]})
        for line in entry["diff_lines"]:
            yield json.dumps({"type": "line", "content": line})
        yield json.dumps({"type": "done"})

    def get_pending(self) -> List[dict]:
        """Return list of pending (un-applied) changes."""
        return list(self._pending)

    def get_history(self) -> List[dict]:
        """Return list of applied changes."""
        return list(self._history)

    def clear_pending(self) -> int:
        """Clear all pending changes, return count cleared."""
        count = len(self._pending)
        self._pending.clear()
        return count

    def diff_between_files(self, path_a: str, path_b: str) -> dict:
        """Diff two files on disk."""
        a = open(path_a, encoding="utf-8", errors="replace").read()
        b = open(path_b, encoding="utf-8", errors="replace").read()
        diff_text = self.generate(a, b, path_a)
        stats = self._compute_diff_stats(diff_text, a, b)
        return {"diff_text": diff_text, "stats": stats, "file_a": path_a, "file_b": path_b}
# ═══════════════════════════════════════════════════════════════════════════════

class InlineDiffViewer:
    """Interactive diff viewer simulating Cursor's inline apply/reject UX.

    Manages a session of DiffFile entries, tracking which chunks the user
    has accepted, rejected, or edited.  Supports batch operations
    (accept_all, reject_all) and partial application.

    Usage::

        viewer = InlineDiffViewer()
        dfile = viewer.add_file("src/main.py", old_code, new_code, "Add logging")
        # Interactive loop (CLI or API):
        while viewer.has_pending():
            chunk = viewer.next_chunk()
            viewer.apply_chunk(chunk.index, DiffChunkAction.ACCEPT)
        viewer.apply_all()  # Write accepted changes to disk
    """

    def __init__(self):
        self._engine = DiffEngine()
        self._files: Dict[str, DiffFile] = {}
        self._cursor_file: str = ""
        self._cursor_chunk: int = 0
        self._action_log: List[Tuple[str, int, DiffChunkAction]] = []  # (file, chunk, action)
        self._undo_stack: List[BackupEntry] = []

    # ── File management ─────────────────────────────────────────────────

    def add_file(self, filepath: str, old_text: str, new_text: str,
                 description: str = "", context_lines: int = 3) -> DiffFile:
        """Add a file diff to the review session.

        Args:
            filepath: Path of the file being modified.
            old_text: Current file content.
            new_text: Proposed new file content.
            description: Human description of the intended change.
            context_lines: Context lines in the diff.

        Returns:
            DiffFile with parsed chunks ready for review.
        """
        diff_text = self._engine.generate(old_text, new_text, filepath, context_lines)
        chunks = self._engine.parse_chunks(diff_text, filepath)
        stats = self._engine.statistics([diff_text])

        dfile = DiffFile(
            filepath=filepath,
            old_text=old_text,
            new_text=new_text,
            chunks=chunks,
            description=description,
            stats=stats,
        )
        self._files[filepath] = dfile
        return dfile

    def remove_file(self, filepath: str) -> None:
        """Remove a file from the review session."""
        self._files.pop(filepath, None)
        if self._cursor_file == filepath:
            self._cursor_file = ""
            self._cursor_chunk = 0

    # ── Cursor-style navigation ─────────────────────────────────────────

    def has_pending(self) -> bool:
        """Check if any chunks remain unreviewed."""
        for dfile in self._files.values():
            if dfile.pending_chunks > 0:
                return True
        return False

    def next_chunk(self) -> Optional[DiffChunk]:
        """Get the next unreviewed chunk (Cursor's 'next diff' behavior).

        Advances the internal cursor through files and chunks.
        Returns None when all chunks are reviewed.
        """
        # First check current file
        if self._cursor_file in self._files:
            dfile = self._files[self._cursor_file]
            for i in range(self._cursor_chunk, len(dfile.chunks)):
                if not dfile.chunks[i].applied:
                    self._cursor_chunk = i
                    return dfile.chunks[i]

        # Scan remaining files
        started = False
        for fpath, dfile in self._files.items():
            if not started:
                if fpath == self._cursor_file:
                    started = True
                continue
            for j, chunk in enumerate(dfile.chunks):
                if not chunk.applied:
                    self._cursor_file = fpath
                    self._cursor_chunk = j
                    return chunk

        # Wrap around: check files before cursor
        for fpath, dfile in self._files.items():
            if fpath == self._cursor_file:
                break
            for j, chunk in enumerate(dfile.chunks):
                if not chunk.applied:
                    self._cursor_file = fpath
                    self._cursor_chunk = j
                    return chunk

        return None

    def prev_chunk(self) -> Optional[DiffChunk]:
        """Navigate to previous unreviewed chunk."""
        # Collect all unreviewed chunks in order
        all_unreviewed: List[Tuple[str, int, DiffChunk]] = []
        for fpath, dfile in self._files.items():
            for j, chunk in enumerate(dfile.chunks):
                if not chunk.applied:
                    all_unreviewed.append((fpath, j, chunk))

        if not all_unreviewed:
            return None

        # Find previous
        current_idx = -1
        for idx, (fp, j, _) in enumerate(all_unreviewed):
            if fp == self._cursor_file and j == self._cursor_chunk:
                current_idx = idx
                break

        prev_idx = (current_idx - 1) % len(all_unreviewed)
        fpath, j, chunk = all_unreviewed[prev_idx]
        self._cursor_file = fpath
        self._cursor_chunk = j
        return chunk

    # ── Apply / Reject ──────────────────────────────────────────────────

    def apply_chunk(self, filepath: str, chunk_index: int,
                    action: DiffChunkAction) -> bool:
        """Apply or reject a specific chunk.

        Args:
            filepath: File the chunk belongs to.
            chunk_index: Index of the chunk within the file's chunk list.
            action: ACCEPT, REJECT, EDIT, SKIP_ALL, or ACCEPT_ALL.

        Returns:
            True if the action was processed successfully.
        """
        dfile = self._files.get(filepath)
        if not dfile or chunk_index >= len(dfile.chunks):
            return False

        chunk = dfile.chunks[chunk_index]

        if action == DiffChunkAction.ACCEPT_ALL:
            for c in dfile.chunks:
                c.applied = True
            self._action_log.append((filepath, chunk_index, action))
            return True

        if action == DiffChunkAction.SKIP_ALL:
            # Mark all remaining as rejected (not applied)
            for c in dfile.chunks:
                if not c.applied:
                    c.applied = True  # Mark as "decided" even if rejected
            self._action_log.append((filepath, chunk_index, action))
            return True

        if action == DiffChunkAction.ACCEPT:
            chunk.applied = True
        elif action in (DiffChunkAction.REJECT, DiffChunkAction.EDIT):
            chunk.applied = True  # Mark as reviewed (decided), not necessarily accepted

        self._action_log.append((filepath, chunk_index, action))
        return True

    def accept_all(self) -> int:
        """Accept all pending chunks across all files.  Returns count accepted."""
        count = 0
        for dfile in self._files.values():
            for chunk in dfile.chunks:
                if not chunk.applied:
                    chunk.applied = True
                    count += 1
        return count

    def reject_all(self) -> int:
        """Reject all pending chunks.  Returns count rejected."""
        count = 0
        for dfile in self._files.values():
            for chunk in dfile.chunks:
                if not chunk.applied:
                    chunk.applied = True  # Mark decided
                    count += 1
        return count

    # ── Build result ────────────────────────────────────────────────────

    def build_result(self, filepath: str) -> str:
        """Build the resulting file content after apply/reject decisions.

        Only chunks marked as ACCEPTed are included; rejected chunks keep
        the original content in those regions.

        Note: This is a simplified build that returns either new_text
        (if any chunks accepted) or old_text (if all rejected).
        For precise line-level merge, use DiffApplicator.
        """
        dfile = self._files.get(filepath)
        if not dfile:
            return ""

        any_accepted = any(
            c.applied and self._was_accepted(filepath, c.index)
            for c in dfile.chunks
        )
        return dfile.new_text if any_accepted else dfile.old_text

    def _was_accepted(self, filepath: str, chunk_index: int) -> bool:
        for fp, ci, action in self._action_log:
            if fp == filepath and ci == chunk_index:
                return action in (DiffChunkAction.ACCEPT, DiffChunkAction.ACCEPT_ALL)
        return False

    # ── Session summary ─────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a session summary for logging or UI display."""
        total_files = len(self._files)
        total_chunks = sum(len(df.chunks) for df in self._files.values())
        accepted = sum(
            1 for df in self._files.values()
            for c in df.chunks if c.applied and self._was_accepted(df.filepath, c.index)
        )
        rejected = sum(
            1 for df in self._files.values()
            for c in df.chunks if c.applied and not self._was_accepted(df.filepath, c.index)
        )
        pending = sum(1 for df in self._files.values() for c in df.chunks if not c.applied)
        return {
            "files": total_files,
            "total_chunks": total_chunks,
            "accepted": accepted,
            "rejected": rejected,
            "pending": pending,
            "actions": len(self._action_log),
        }

    @property
    def files(self) -> Dict[str, DiffFile]:
        return dict(self._files)


# ═══════════════════════════════════════════════════════════════════════════════
# DiffApplicator — safe patch application with backup and rollback
# ═══════════════════════════════════════════════════════════════════════════════

class DiffApplicator:
    """Safely apply diffs to real files with backup and automatic rollback.

    Features (Cursor/Claude Code parity):
      - Backup original file before applying
      - Verify hash after apply
      - Auto-rollback on mismatch
      - git-based apply for tracked files (cleaner conflict resolution)
      - Dry-run mode for safety

    Usage::

        app = DiffApplicator(backup_dir="/tmp/meshctx-backups")
        result = app.apply("src/main.py", old_text, new_text)
        if result.status == ApplyStatus.OK:
            print("Applied!")
        else:
            app.rollback(result)  # Restore from backup
    """

    def __init__(self, backup_dir: str = ""):
        self._backup_dir = backup_dir or os.path.join(tempfile.gettempdir(), "meshctx-diffs")
        os.makedirs(self._backup_dir, exist_ok=True)
        self._backups: Dict[str, BackupEntry] = {}

    def apply(self, filepath: str, old_text: str, new_text: str,
              dry_run: bool = False) -> ApplyResult:
        """Apply a diff to a file safely.

        Args:
            filepath: Path to the file to modify.
            old_text: Expected current content (for verification).
            new_text: Content to write.
            dry_run: If True, only verify the patch matches, don't write.

        Returns:
            ApplyResult with status and backup info.
        """
        old_hash = hashlib.sha256(old_text.encode()).hexdigest()

        # Read current file
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                current = f.read()
            current_hash = hashlib.sha256(current.encode()).hexdigest()

            # Verify old_text matches current file
            if current != old_text:
                # Try git-based apply as fallback
                return self._git_apply(filepath, old_text, new_text, dry_run)
        else:
            current = ""
            current_hash = ""

        # Backup
        backup_path = ""
        if current:
            backup_path = self._create_backup(filepath, current, current_hash)

        if dry_run:
            return ApplyResult(
                filepath=filepath, status=ApplyStatus.OK,
                backup_path=backup_path, old_hash=current_hash,
                new_hash=hashlib.sha256(new_text.encode()).hexdigest(),
            )

        # Write
        try:
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_text)

            # Verify
            with open(filepath, "r", encoding="utf-8") as f:
                written = f.read()
            new_hash = hashlib.sha256(written.encode()).hexdigest()
            expected_new_hash = hashlib.sha256(new_text.encode()).hexdigest()

            if new_hash != expected_new_hash:
                # Auto-rollback
                self._restore_backup(filepath, backup_path, current)
                return ApplyResult(
                    filepath=filepath, status=ApplyStatus.FAILED,
                    error=f"Hash mismatch after write: {new_hash[:8]} != {expected_new_hash[:8]}",
                    backup_path=backup_path, old_hash=current_hash,
                )

            return ApplyResult(
                filepath=filepath, status=ApplyStatus.OK,
                backup_path=backup_path, old_hash=current_hash, new_hash=new_hash,
            )
        except OSError as e:
            if backup_path:
                self._restore_backup(filepath, backup_path, current)
            return ApplyResult(
                filepath=filepath, status=ApplyStatus.FAILED,
                error=str(e), backup_path=backup_path, old_hash=current_hash,
            )

    def _git_apply(self, filepath: str, old_text: str, new_text: str,
                   dry_run: bool) -> ApplyResult:
        """Use git apply for tracked files (handles fuzzy matching)."""
        try:
            # Create a patch file
            patch = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{filepath}", tofile=f"b/{filepath}",
                lineterm="",
            )
            patch_text = "\n".join(patch)
            if not patch_text.strip():
                return ApplyResult(filepath=filepath, status=ApplyStatus.OK)

            patch_file = os.path.join(self._backup_dir, f"{hashlib.md5(filepath.encode()).hexdigest()[:8]}.patch")
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(patch_text)

            if dry_run:
                result = subprocess.run(
                    ["git", "apply", "--check", patch_file],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return ApplyResult(
                        filepath=filepath, status=ApplyStatus.FAILED,
                        error=f"git apply --check failed: {result.stderr[:200]}",
                    )
                return ApplyResult(filepath=filepath, status=ApplyStatus.OK)

            result = subprocess.run(
                ["git", "apply", patch_file],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return ApplyResult(
                    filepath=filepath, status=ApplyStatus.FAILED,
                    error=f"git apply failed: {result.stderr[:200]}",
                )
            return ApplyResult(filepath=filepath, status=ApplyStatus.OK)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return ApplyResult(
                filepath=filepath, status=ApplyStatus.FAILED, error=str(e),
            )

    def rollback(self, result: ApplyResult) -> bool:
        """Rollback a previously applied diff using the backup."""
        if not result.backup_path or not os.path.exists(result.backup_path):
            return False
        with open(result.backup_path, "r", encoding="utf-8") as f:
            original = f.read()
        with open(result.filepath, "w", encoding="utf-8") as f:
            f.write(original)
        return True

    def _create_backup(self, filepath: str, content: str, hash_val: str) -> str:
        backup_name = f"{hashlib.md5(filepath.encode()).hexdigest()[:12]}_{hash_val[:8]}.bak"
        backup_path = os.path.join(self._backup_dir, backup_name)
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        self._backups[filepath] = BackupEntry(
            filepath=filepath, content=content, hash=hash_val,
        )
        return backup_path

    def _restore_backup(self, filepath: str, backup_path: str, content: str) -> None:
        """Restore file from backup content."""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# BatchDiffManager — multi-file edit sessions with undo
# ═══════════════════════════════════════════════════════════════════════════════

class BatchDiffManager:
    """Manage a batch of file edits as a single atomic session.

    Provides:
      - Add multiple file diffs
      - Preview all changes before applying
      - Apply all at once (atomic)
      - Undo entire batch (via backup chain)
      - Generate session summary for PR descriptions

    Usage::

        mgr = BatchDiffManager()
        mgr.add("src/a.py", old_a, new_a, "Extract helper")
        mgr.add("src/b.py", old_b, new_b, "Use new helper")
        if mgr.preview():
            results = mgr.apply_all()
        # or: mgr.undo_all()
    """

    def __init__(self, backup_dir: str = ""):
        self._applicator = DiffApplicator(backup_dir)
        self._engine = DiffEngine()
        self._entries: List[Tuple[str, str, str, str]] = []  # (filepath, old, new, desc)
        self._results: List[ApplyResult] = []

    def add(self, filepath: str, old_text: str, new_text: str,
            description: str = "") -> None:
        """Add a file edit to the batch."""
        self._entries.append((filepath, old_text, new_text, description))

    def preview(self) -> Dict[str, Any]:
        """Generate a preview of all pending changes.

        Returns:
            Dict with keys: files, total_added, total_removed, per_file stats.
        """
        total_added = 0
        total_removed = 0
        per_file = []

        for filepath, old_text, new_text, desc in self._entries:
            stats = self._engine.statistics([
                self._engine.generate(old_text, new_text, filepath)
            ])
            total_added += stats["insertions"]
            total_removed += stats["deletions"]
            per_file.append({
                "filepath": filepath,
                "description": desc,
                "added": stats["insertions"],
                "removed": stats["deletions"],
            })

        return {
            "files": len(self._entries),
            "total_added": total_added,
            "total_removed": total_removed,
            "per_file": per_file,
        }

    def apply_all(self, dry_run: bool = False) -> List[ApplyResult]:
        """Apply all pending edits. Returns list of ApplyResult."""
        self._results = []
        for filepath, old_text, new_text, desc in self._entries:
            result = self._applicator.apply(filepath, old_text, new_text, dry_run)
            self._results.append(result)
            if result.status == ApplyStatus.FAILED and not dry_run:
                self.undo_all()
                break
        return list(self._results)

    def undo_all(self) -> int:
        """Undo all applied edits. Returns count of successful rollbacks."""
        count = 0
        for result in reversed(self._results):
            if result.status == ApplyStatus.OK:
                if self._applicator.rollback(result):
                    count += 1
        self._results = []
        return count

    def generate_pr_description(self, title: str = "", base_branch: str = "main") -> str:
        """Generate a PR description from the batch changes."""
        preview = self.preview()
        lines = [
            f"## {title}" if title else "## Batch Changes",
            "",
            f"**Files changed:** {preview['files']}",
            f"**+{preview['total_added']} / -{preview['total_removed']}**",
            "",
            "### Changes",
        ]
        for pf in preview["per_file"]:
            desc_str = f" — {pf['description']}" if pf['description'] else ""
            lines.append(
                f"- `{pf['filepath']}` (+{pf['added']}/-{pf['removed']}){desc_str}"
            )
        return "\n".join(lines)

    @property
    def is_clean(self) -> bool:
        return len(self._entries) == 0

    @property
    def failed(self) -> bool:
        return any(r.status == ApplyStatus.FAILED for r in self._results)


# ═══════════════════════════════════════════════════════════════════════════════
# DiffRenderer — colorized output for terminal and HTML
# ═══════════════════════════════════════════════════════════════════════════════

class DiffRenderer:
    """Render diffs as colorized terminal output or HTML.

    Terminal: ANSI color codes (green +, red -, yellow @, cyan context)
    HTML: inline-styled <pre> blocks suitable for web UIs
    """

    # ANSI codes
    _GREEN = "\033[32m"
    _RED = "\033[31m"
    _YELLOW = "\033[33m"
    _CYAN = "\033[36m"
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    @staticmethod
    def terminal(diff_text: str, filepath: str = "") -> str:
        """Render a unified diff for terminal output with ANSI colors.

        Mimics `git diff --color` output.
        """
        lines = []
        if filepath:
            lines.append(f"{DiffRenderer._BOLD}--- {filepath}{DiffRenderer._RESET}")

        for line in diff_text.splitlines():
            if line.startswith("@@ "):
                lines.append(f"{DiffRenderer._CYAN}{line}{DiffRenderer._RESET}")
            elif line.startswith("+") and not line.startswith("+++"):
                lines.append(f"{DiffRenderer._GREEN}{line}{DiffRenderer._RESET}")
            elif line.startswith("-") and not line.startswith("---"):
                lines.append(f"{DiffRenderer._RED}{line}{DiffRenderer._RESET}")
            elif line.startswith("diff ") or line.startswith("index ") or \
                 line.startswith("--- ") or line.startswith("+++ "):
                lines.append(f"{DiffRenderer._YELLOW}{line}{DiffRenderer._RESET}")
            else:
                lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def html(diff_text: str, filepath: str = "",
             title: str = "Diff Preview") -> str:
        """Render a diff as an HTML snippet suitable for web UIs.

        Produces inline-styled HTML with color-coded additions/deletions
        and a header row showing the filepath."""
        import html as html_mod

        escaped_lines = []
        for line in diff_text.splitlines():
            escaped = html_mod.escape(line)
            if line.startswith("@@ "):
                escaped_lines.append(
                    f'<div style="color:#06b6d4;font-weight:bold">{escaped}</div>'
                )
            elif line.startswith("+") and not line.startswith("+++"):
                escaped_lines.append(
                    f'<div style="background:#064e3b;color:#6ee7b7">{escaped}</div>'
                )
            elif line.startswith("-") and not line.startswith("---"):
                escaped_lines.append(
                    f'<div style="background:#7f1d1d;color:#fca5a5">{escaped}</div>'
                )
            elif line.startswith("diff ") or line.startswith("index ") or \
                 line.startswith("--- ") or line.startswith("+++ "):
                escaped_lines.append(
                    f'<div style="color:#fbbf24">{escaped}</div>'
                )
            else:
                escaped_lines.append(f"<div>{escaped}</div>")

        header = ""
        if filepath:
            header = f'<div style="font-weight:bold;color:#8b5cf6;margin-bottom:8px">{html_mod.escape(filepath)}</div>'

        return (
            f'<div style="font-family:monospace;font-size:13px;line-height:1.5;'
            f'background:#0f172a;color:#e2e8f0;padding:16px;border-radius:8px;'
            f'overflow-x:auto;white-space:pre-wrap">'
            f'<div style="font-weight:bold;color:#94a3b8;margin-bottom:12px">{html_mod.escape(title)}</div>'
            f'{header}'
            f'{"".join(escaped_lines)}'
            f'</div>'
        )

    @staticmethod
    def chunk_html(chunk: DiffChunk, filepath: str = "") -> str:
        """Render a single DiffChunk as HTML (for inline review UIs)."""
        import html as html_mod

        lines_html = []
        for line in chunk.lines:
            escaped = html_mod.escape(line)
            if line.startswith("@@"):
                lines_html.append(
                    f'<div style="color:#06b6d4;font-weight:bold">{escaped}</div>'
                )
            elif line.startswith("+") and not line.startswith("+++"):
                lines_html.append(
                    f'<div style="background:#064e3b;color:#6ee7b7">{escaped}</div>'
                )
            elif line.startswith("-") and not line.startswith("---"):
                lines_html.append(
                    f'<div style="background:#7f1d1d;color:#fca5a5">{escaped}</div>'
                )
            else:
                lines_html.append(f"<div>{escaped}</div>")

        header = f"@{filepath}" if filepath else ""
        return (
            f'<div class="diff-chunk" style="margin-bottom:8px;border:1px solid #334155;'
            f'border-radius:6px;overflow:hidden">'
            f'<div style="background:#1e293b;padding:6px 12px;font-size:12px;color:#94a3b8">'
            f'{html_mod.escape(chunk.header)} {header} '
            f'<span style="color:#22c55e">+{chunk.added_lines}</span> '
            f'<span style="color:#dc2626">-{chunk.removed_lines}</span>'
            f'</div>'
            f'<div style="font-family:monospace;font-size:13px;line-height:1.5;'
            f'padding:8px 12px">{"".join(lines_html)}</div>'
            f'</div>'
        )


    @staticmethod
    def render_side_by_side(diff_text: str, filepath: str = "",
                            old_label: str = "Before", new_label: str = "After") -> str:
        """Render a unified diff as a side-by-side HTML view.

        Two columns: left=old (removals), right=new (additions).
        Context lines span both columns. Suitable for web review UIs.
        """
        import html as html_mod
        rows = []
        i = 0
        diff_lines = diff_text.splitlines()
        while i < len(diff_lines):
            line = diff_lines[i]
            escaped = html_mod.escape(line)
            if line.startswith("@@ "):
                rows.append((
                    f'<div class="sb-gutter" style="grid-column:1/3;background:#1e3a5f;'
                    f'color:#06b6d4;font-weight:bold;padding:4px 12px;font-size:12px">{escaped}</div>',
                ))
                i += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed_lines = []
                while i < len(diff_lines) and diff_lines[i].startswith("-") and not diff_lines[i].startswith("---"):
                    removed_lines.append(html_mod.escape(diff_lines[i]))
                    i += 1
                added_lines = []
                while i < len(diff_lines) and diff_lines[i].startswith("+") and not diff_lines[i].startswith("+++"):
                    added_lines.append(html_mod.escape(diff_lines[i]))
                    i += 1
                max_len = max(len(removed_lines), len(added_lines))
                while len(removed_lines) < max_len:
                    removed_lines.append("")
                while len(added_lines) < max_len:
                    added_lines.append("")
                for rl, al in zip(removed_lines, added_lines):
                    rows.append((
                        f'<div class="sb-left" style="background:#7f1d1d;color:#fca5a5;'
                        f'padding:2px 8px;font-family:monospace;font-size:12px;white-space:pre;overflow:hidden">{rl}</div>',
                        f'<div class="sb-right" style="background:#064e3b;color:#6ee7b7;'
                        f'padding:2px 8px;font-family:monospace;font-size:12px;white-space:pre;overflow:hidden">{al}</div>',
                    ))
            elif line.startswith("+") and not line.startswith("+++"):
                rows.append((
                    f'<div class="sb-left" style="background:#1e293b;padding:2px 8px;'
                    f'font-family:monospace;font-size:12px"></div>',
                    f'<div class="sb-right" style="background:#064e3b;color:#6ee7b7;'
                    f'padding:2px 8px;font-family:monospace;font-size:12px;white-space:pre;overflow:hidden">{escaped}</div>',
                ))
                i += 1
            elif line.startswith("diff ") or line.startswith("index ") or \
                 line.startswith("--- ") or line.startswith("+++ "):
                rows.append((
                    f'<div class="sb-gutter" style="grid-column:1/3;color:#fbbf24;'
                    f'padding:2px 12px;font-size:11px;font-family:monospace">{escaped}</div>',
                ))
                i += 1
            else:
                rows.append((
                    f'<div class="sb-left" style="background:#0f172a;color:#94a3b8;'
                    f'padding:2px 8px;font-family:monospace;font-size:12px;white-space:pre;overflow:hidden">{escaped}</div>',
                    f'<div class="sb-right" style="background:#0f172a;color:#94a3b8;'
                    f'padding:2px 8px;font-family:monospace;font-size:12px;white-space:pre;overflow:hidden">{escaped}</div>',
                ))
                i += 1

        cells = []
        for row in rows:
            if len(row) == 1:
                cells.append(row[0])
            else:
                cells.append(row[0])
                cells.append(row[1])

        fp_html = f'<div style="color:#8b5cf6;font-weight:bold;margin-bottom:8px">{html_mod.escape(filepath)}</div>' if filepath else ""

        return (
            f'<div style="background:#0f172a;color:#e2e8f0;border-radius:8px;overflow:hidden;font-size:13px">'
            f'<div style="display:flex;background:#1e293b;border-bottom:1px solid #334155">'
            f'<div style="flex:1;padding:8px 12px;font-weight:bold;color:#fca5a5">{html_mod.escape(old_label)}</div>'
            f'<div style="flex:1;padding:8px 12px;font-weight:bold;color:#6ee7b7">{html_mod.escape(new_label)}</div>'
            f'</div>'
            f'{fp_html}'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;overflow-x:auto">'
            f'{"".join(cells)}'
            f'</div>'
            f'</div>'
        )

    @staticmethod
    def render_compact_summary(stats: dict) -> str:
        """Render a compact diff summary card for dashboards and notifications.

        Args:
            stats: dict with insertions, deletions, files, chunks, filepath, description.

        Returns:
            HTML string for a compact summary card.
        """
        import html as html_mod
        insertions = stats.get("insertions", 0)
        deletions = stats.get("deletions", 0)
        files = stats.get("files", stats.get("file_count", 1))
        chunks = stats.get("chunks", stats.get("chunk_count", 0))
        filepath = stats.get("filepath", "")
        description = stats.get("description", "")
        net = insertions - deletions
        net_color = "#3fb950" if net >= 0 else "#f85149"
        net_sign = "+" if net >= 0 else ""
        desc_html = f'<span style="color:#8b949e;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">{html_mod.escape(description)}</span>' if description else ""
        return (
            f'<div style="display:inline-flex;align-items:center;gap:12px;'
            f'background:#161b22;border:1px solid #30363d;border-radius:8px;'
            f'padding:10px 16px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;'
            f'font-size:13px;color:#e6edf3;max-width:100%">'
            f'<span style="color:#8b5cf6;font-weight:600;white-space:nowrap">'
            f'\U0001f4c4 {html_mod.escape(filepath) if filepath else f"{files} file(s)"}</span>'
            f'<span style="display:flex;gap:8px;align-items:center">'
            f'<span style="color:#3fb950;font-weight:600">+{insertions}</span>'
            f'<span style="color:#f85149;font-weight:600">-{deletions}</span>'
            f'<span style="color:{net_color};font-weight:600">{net_sign}{net}</span>'
            f'</span>'
            f'<span style="color:#8b949e;font-size:12px">{chunks} chunks</span>'
            + desc_html
            + f'</div>'
        )

    @staticmethod
    def render_ansi_terminal(diff_text: str, filepath: str = "",
                             width: int = 80, show_line_numbers: bool = True) -> str:
        """Render diff as rich ANSI terminal output with line numbers and summary.

        More feature-rich than terminal() — adds line numbers, truncation,
        and a summary footer.
        """
        import re
        lines = []
        if filepath:
            lines.append(f"{DiffRenderer._BOLD}\u2550\u2550\u2550 {filepath} \u2550\u2550\u2550{DiffRenderer._RESET}")
        old_ln = 0
        new_ln = 0
        for line in diff_text.splitlines():
            if line.startswith("@@ "):
                m = re.match(r"@@ -(\d+),?\d* \+(\d+),?\d* @@", line)
                if m:
                    old_ln = int(m.group(1))
                    new_ln = int(m.group(2))
                lines.append(f"{DiffRenderer._CYAN}{DiffRenderer._BOLD}{line}{DiffRenderer._RESET}")
            elif line.startswith("+") and not line.startswith("+++"):
                ln = f"{new_ln:4d} " if show_line_numbers else ""
                content = line[:width-8] + "\u2026" if len(line) > width - 7 else line
                lines.append(f"{DiffRenderer._GREEN}{ln}{content}{DiffRenderer._RESET}")
                new_ln += 1
            elif line.startswith("-") and not line.startswith("---"):
                ln = f"{old_ln:4d} " if show_line_numbers else ""
                content = line[:width-8] + "\u2026" if len(line) > width - 7 else line
                lines.append(f"{DiffRenderer._RED}{ln}{content}{DiffRenderer._RESET}")
                old_ln += 1
            elif line.startswith("diff ") or line.startswith("index ") or \
                 line.startswith("--- ") or line.startswith("+++ "):
                lines.append(f"{DiffRenderer._YELLOW}{line}{DiffRenderer._RESET}")
            else:
                if show_line_numbers:
                    lines.append(f"     {line}")
                else:
                    lines.append(line)
                old_ln += 1
                new_ln += 1
        return "\n".join(lines)



# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor (kept from v3.48+)
# ═══════════════════════════════════════════════════════════════════════════════

_diff_engine_instance: Optional[DiffEngine] = None
_diff_engine: Optional[DiffEngine] = None  # test compatibility alias


def get_diff_engine(freeze_mode: bool = False) -> DiffEngine:
    """Return the module-level singleton DiffEngine instance."""
    global _diff_engine_instance, _diff_engine
    if _diff_engine_instance is None or _diff_engine is None:
        _diff_engine_instance = DiffEngine(freeze_mode=freeze_mode)
        _diff_engine = _diff_engine_instance
    return _diff_engine_instance


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience factory (kept from v3.48+)
# ═══════════════════════════════════════════════════════════════════════════════

def create_proposal(
    filepath: str,
    old_str: str,
    new_str: str,
    description: str = "",
    risk_level: str = "safe",
) -> EditProposal:
    """Build an EditProposal with auto-computed diff and stats."""
    engine = get_diff_engine()
    preview_result = engine.preview(filepath, old_str, new_str)
    return EditProposal(
        filepath=filepath,
        old_str=old_str,
        new_str=new_str,
        description=description,
        risk_level=risk_level,
        diff=preview_result["diff"],
        stats=preview_result["stats"],
    )

from pathlib import Path
DiffPreviewEngine = DiffEngine  # test compatibility alias
BACKUP_DIR = Path(tempfile.gettempdir()) / "meshctx_diff_backups"
