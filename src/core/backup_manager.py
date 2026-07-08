"""backup_manager — Backup snapshot management with policy-based rotation.

Creates compressed archives (tar.gz) of directories, tracks metadata as JSON,
and supports restore, delete, and smart rotation (daily/weekly/monthly retention).
Uses only Python stdlib — shutil, tarfile, json, pathlib, datetime, os.
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# BackupSnapshot — immutable record of one backup
# ---------------------------------------------------------------------------

@dataclass
class BackupSnapshot:
    """Represents a single backup snapshot.

    Attributes:
        id: Unique snapshot identifier (timestamp-based).
        timestamp: Unix epoch timestamp when the snapshot was created.
        tag: Optional user-provided label for this snapshot.
        files: List of relative file paths included in the snapshot.
        size: Total size in bytes of all files in the snapshot.
        path: Absolute path to the archive file on disk.
    """
    id: str
    timestamp: float
    tag: str
    files: list[str] = field(default_factory=list)
    size: int = 0
    path: str = ""


# ---------------------------------------------------------------------------
# BackupManager — create, list, restore, delete, rotate snapshots
# ---------------------------------------------------------------------------

class BackupManager:
    """Manages backup snapshots stored as compressed tar archives with JSON metadata.

    Directory layout::

        backup_root/
          archives/    ← .tar.gz files
          metadata/    ← .json metadata files

    Usage::

        bm = BackupManager("~/.meshctx/backups")
        snap = bm.create_snapshot("/path/to/project", tag="v1.0")
        bm.list_snapshots()
        bm.restore(snap.id, "/tmp/restored")
        bm.rotate(max_snapshots=10)
    """

    def __init__(self, backup_root: str = "~/.meshctx/backups"):
        self.backup_root = Path(backup_root).expanduser().resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self._metadata_dir = self.backup_root / "metadata"
        self._archive_dir = self.backup_root / "archives"
        self._metadata_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    # -- helpers ------------------------------------------------------------

    def _snapshot_id(self) -> str:
        """Generate a unique, sortable snapshot ID from the current time."""
        return datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def _metadata_path(self, snapshot_id: str) -> Path:
        return self._metadata_dir / f"{snapshot_id}.json"

    def _archive_path(self, snapshot_id: str) -> Path:
        return self._archive_dir / f"{snapshot_id}.tar.gz"

    def _resolve_archive(self, snapshot: BackupSnapshot) -> Path:
        """Return the path to an existing archive, trying stored path then default."""
        stored = Path(snapshot.path)
        if stored.exists():
            return stored
        default = self._archive_path(snapshot.id)
        if default.exists():
            return default
        raise FileNotFoundError(
            f"Archive not found for snapshot {snapshot.id} "
            f"(tried {stored} and {default})"
        )

    def _collect_files(self, source: Path) -> tuple[list[str], int]:
        """Walk *source* and return (relative_file_paths, total_bytes)."""
        files: list[str] = []
        total_size: int = 0
        for entry in source.rglob("*"):
            if entry.is_file():
                rel = str(entry.relative_to(source))
                files.append(rel)
                total_size += entry.stat().st_size
        return files, total_size

    def _save_metadata(self, snapshot: BackupSnapshot) -> None:
        """Persist snapshot metadata to a JSON file."""
        data = {
            "id": snapshot.id,
            "timestamp": snapshot.timestamp,
            "tag": snapshot.tag,
            "files": snapshot.files,
            "size": snapshot.size,
            "path": snapshot.path,
        }
        with open(self._metadata_path(snapshot.id), "w") as fh:
            json.dump(data, fh, indent=2)

    def _load_metadata(self, snapshot_id: str) -> Optional[BackupSnapshot]:
        """Load a single snapshot's metadata from its JSON file."""
        path = self._metadata_path(snapshot_id)
        if not path.exists():
            return None
        with open(path) as fh:
            data = json.load(fh)
        return BackupSnapshot(**data)

    # -- public API ---------------------------------------------------------

    def create_snapshot(self, dir_path: str, tag: str = "") -> BackupSnapshot:
        """Create a compressed snapshot of *dir_path* and return its metadata.

        Args:
            dir_path: Path to the directory to back up.
            tag: Optional human-readable label (e.g. ``"pre-deploy"``).

        Returns:
            A ``BackupSnapshot`` describing the new archive.

        Raises:
            FileNotFoundError: If *dir_path* does not exist.
            NotADirectoryError: If *dir_path* is not a directory.
        """
        source = Path(dir_path).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path}")
        if not source.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        snapshot_id = self._snapshot_id()
        timestamp = datetime.now().timestamp()

        # Enumerate files and compute total size
        file_list, total_size = self._collect_files(source)

        # Create the compressed archive  (shutil.make_archive)
        archive_base = str(self._archive_dir / snapshot_id)
        archive_path = shutil.make_archive(
            base_name=archive_base,
            format="gztar",
            root_dir=str(source.parent),
            base_dir=source.name,
        )

        snapshot = BackupSnapshot(
            id=snapshot_id,
            timestamp=timestamp,
            tag=tag,
            files=file_list,
            size=total_size,
            path=archive_path,
        )

        self._save_metadata(snapshot)
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[BackupSnapshot]:
        """Return a single snapshot by ID, or None if not found."""
        return self._load_metadata(snapshot_id)

    def list_snapshots(self) -> list[BackupSnapshot]:
        """Return all snapshots sorted newest-first by timestamp."""
        snapshots: list[BackupSnapshot] = []
        for meta_file in sorted(self._metadata_dir.glob("*.json")):
            snapshot = self._load_metadata(meta_file.stem)
            if snapshot is not None:
                snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots

    def list_files_in_snapshot(self, snapshot_id: str) -> list[str]:
        """List file entries inside a snapshot archive using :mod:`tarfile`.

        Useful for inspecting an archive without extracting it.
        """
        snapshot = self._load_metadata(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot not found: {snapshot_id}")
        archive_path = self._resolve_archive(snapshot)
        files: list[str] = []
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    files.append(member.name)
        return files

    def restore(self, snapshot_id: str, target_dir: str) -> None:
        """Extract a snapshot archive into *target_dir*.

        The target directory is created if it does not exist.
        """
        snapshot = self._load_metadata(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot not found: {snapshot_id}")
        archive_path = self._resolve_archive(snapshot)
        target = Path(target_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(archive_path), str(target), "gztar")

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot's archive and metadata.  Returns ``True`` if deleted."""
        snapshot = self._load_metadata(snapshot_id)
        if snapshot is None:
            return False

        # Remove archive (try stored path first, then default path)
        stored = Path(snapshot.path)
        if stored.exists():
            stored.unlink()
        else:
            default = self._archive_path(snapshot_id)
            if default.exists():
                default.unlink()

        # Remove metadata JSON
        meta = self._metadata_path(snapshot_id)
        if meta.exists():
            meta.unlink()

        return True

    def rotate(self, max_snapshots: int = 10) -> list[str]:
        """Prune snapshots using a policy-based retention scheme.

        **Retention policy** (applied to snapshots beyond the
        *max_snapshots* most recent):

        * **Daily**   — keep one snapshot per day for the last 7 days.
        * **Weekly**  — keep one snapshot per ISO week for the next 4 weeks.
        * **Monthly** — keep one snapshot per calendar month for up to 1 year.
        * Older snapshots are deleted.

        Returns the list of deleted snapshot IDs.
        """
        snapshots = self.list_snapshots()
        if len(snapshots) <= max_snapshots:
            return []

        # Always keep the N most recent
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        keep_ids: set[str] = {s.id for s in snapshots[:max_snapshots]}

        # Apply policy to the remaining (older) snapshots
        remaining = snapshots[max_snapshots:]
        now = datetime.now()

        from datetime import date as _date
        daily: dict[_date, BackupSnapshot] = {}
        weekly: dict[tuple[int, int], BackupSnapshot] = {}
        monthly: dict[tuple[int, int], BackupSnapshot] = {}

        for s in remaining:
            dt = datetime.fromtimestamp(s.timestamp)
            age = now - dt

            if age <= timedelta(days=7):
                # Daily bucket — keep newest per day
                day_key = dt.date()
                if day_key not in daily or s.timestamp > daily[day_key].timestamp:
                    daily[day_key] = s
            elif age <= timedelta(days=30):
                # Weekly bucket — keep newest per ISO week
                iso = dt.isocalendar()
                week_key = (iso[0], iso[1])
                if week_key not in weekly or s.timestamp > weekly[week_key].timestamp:
                    weekly[week_key] = s
            elif age <= timedelta(days=365):
                # Monthly bucket — keep newest per calendar month
                month_key = (dt.year, dt.month)
                if month_key not in monthly or s.timestamp > monthly[month_key].timestamp:
                    monthly[month_key] = s
            # Older than 365 days: not retained

        for snap in list(daily.values()) + list(weekly.values()) + list(monthly.values()):
            keep_ids.add(snap.id)

        # Delete everything not marked for keeping
        deleted: list[str] = []
        for s in snapshots:
            if s.id not in keep_ids:
                if self.delete_snapshot(s.id):
                    deleted.append(s.id)

        return deleted


# ---------------------------------------------------------------------------
# _P compatibility stub — keeps module importable when real classes aren't
# needed.  Module-level __getattr__ returns a _P proxy for any undefined name.
# ---------------------------------------------------------------------------

from ._stub import _P
