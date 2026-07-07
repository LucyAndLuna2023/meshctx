"""meshctx backup_vault — v2.68 + v3.106 Backup Vault"""

import hashlib
import json
import os
import shutil
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════════

class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class BackupTarget(Enum):
    LOCAL = "local"
    S3 = "s3"
    REMOTE = "remote"


class BackupStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BackupResult:
    success: bool
    backup_id: str = ""
    error_message: str = ""
    total_files: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0


@dataclass
class RestoreResult:
    success: bool
    backup_id: str = ""
    error_message: str = ""
    files_restored: int = 0
    bytes_restored: int = 0


@dataclass
class BackupManifest:
    backup_id: str
    backup_type: str
    source_path: str
    target: str
    created_at: str
    encrypted: bool = False
    checksum_algorithm: str = "sha256"
    total_files: int = 0
    total_bytes: int = 0
    parent_backup_id: Optional[str] = None


@dataclass
class BackupEntry:
    backup_id: str
    backup_type: str
    source_path: str
    target: str
    created_at: str
    encrypted: bool = False
    status: str = "completed"
    total_files: int = 0
    total_bytes: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_backup_vault_instance: Optional["BackupVault"] = None


def get_backup_vault(**kw) -> "BackupVault":
    global _backup_vault_instance
    if _backup_vault_instance is None or kw:
        _backup_vault_instance = BackupVault(**kw)
    return _backup_vault_instance


def reset_backup_vault():
    global _backup_vault_instance
    if _backup_vault_instance is not None:
        _backup_vault_instance.clear_all()
    _backup_vault_instance = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

SKIP_PARTS = {".git", "__pycache__", "venv", ".venv", "node_modules",
              ".tox", ".eggs", ".mypy_cache", ".pytest_cache"}

VALID_BACKUP_TYPES = {"full", "incremental"}
VALID_TARGETS = {"local", "s3", "remote"}


def _collect_files(source: Path) -> dict:
    """Collect regular files from source. Returns {relpath: abs_path}."""
    files = {}
    items = sorted(source.rglob("*")) if source.is_dir() else ([source] if source.is_file() else [])
    for f in items:
        if f.is_symlink():
            continue
        if f.is_file():
            parts = set(f.parts)
            if not parts & SKIP_PARTS:
                rel = str(f.relative_to(source)) if source.is_dir() else f.name
                files[rel] = f
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# BackupVault
# ═══════════════════════════════════════════════════════════════════════════════

class BackupVault:
    def __init__(self, config_dir=None, vault_dir=None, encryption_key=None, **kw):
        d = vault_dir or config_dir or "/tmp/backup_vault"
        self._vault_dir = Path(d)
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir = self._vault_dir / "_manifests"
        self._manifests_dir.mkdir(parents=True, exist_ok=True)
        self._backups_dir = self._vault_dir / "_backups"
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        self._manifests: dict[str, dict] = {}
        self._load_manifests_from_disk()

        # v2.68 compat: backup_paths + config file
        self._backup_paths: list[str] = []
        self._load_config()

        # Encryption
        self._encryption_key = encryption_key
        self._fernet = None
        if encryption_key is not None:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(encryption_key)
            except ImportError:
                raise RuntimeError("cryptography not installed")

    @property
    def is_encrypted(self) -> bool:
        return self._fernet is not None

    @classmethod
    def generate_key(cls) -> bytes:
        try:
            from cryptography.fernet import Fernet
            return Fernet.generate_key()
        except ImportError:
            raise RuntimeError("cryptography not installed")

    def set_encryption_key(self, key: bytes):
        from cryptography.fernet import Fernet
        self._encryption_key = key
        self._fernet = Fernet(key)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _load_config(self):
        cf = self._vault_dir / "backup_vault.json"
        if cf.exists():
            try:
                data = json.loads(cf.read_text())
                self._backup_paths = data.get("backup_paths", [])
            except (json.JSONDecodeError, OSError):
                self._backup_paths = []

    def _save_config(self):
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        (self._vault_dir / "backup_vault.json").write_text(
            json.dumps({"backup_paths": self._backup_paths}, indent=2)
        )

    def _load_manifests_from_disk(self):
        """Load all manifests from disk into memory."""
        self._manifests.clear()
        for mp in self._manifests_dir.glob("*.json"):
            try:
                data = json.loads(mp.read_text())
                self._manifests[data["backup_id"]] = data
            except (json.JSONDecodeError, OSError, KeyError):
                pass

    def _save_manifest(self, manifest: BackupManifest, files_checksums: dict):
        data = {
            "backup_id": manifest.backup_id,
            "backup_type": manifest.backup_type,
            "source_path": manifest.source_path,
            "target": manifest.target,
            "created_at": manifest.created_at,
            "encrypted": manifest.encrypted,
            "checksum_algorithm": manifest.checksum_algorithm,
            "total_files": manifest.total_files,
            "total_bytes": manifest.total_bytes,
            "parent_backup_id": manifest.parent_backup_id,
            "files": files_checksums,
        }
        self._manifests[manifest.backup_id] = data
        mp = self._manifests_dir / f"{manifest.backup_id}.json"
        mp.write_text(json.dumps(data, indent=2))

    def _load_manifest_data(self, backup_id: str) -> Optional[dict]:
        return self._manifests.get(backup_id)

    def _archive_path(self, backup_id: str) -> Path:
        return self._backups_dir / f"{backup_id}.tar.gz"

    def _compute_stats(self) -> dict:
        total = len(self._manifests)
        full_count = sum(1 for d in self._manifests.values() if d.get("backup_type") == "full")
        inc_count = sum(1 for d in self._manifests.values() if d.get("backup_type") == "incremental")
        storage = 0
        for ap in self._backups_dir.glob("*.tar.gz"):
            try:
                storage += ap.stat().st_size
            except OSError:
                pass
        return {
            "total_backups": total,
            "full_backups": full_count,
            "incremental_backups": inc_count,
            "vault_dir": str(self._vault_dir),
            "storage_used_bytes": storage,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # v2.68 API — path management
    # ═══════════════════════════════════════════════════════════════════════

    def add_backup_path(self, path: str, **kw) -> dict:
        bp = str(Path(path).resolve())
        if bp in self._backup_paths:
            return {"success": False}
        self._backup_paths.append(bp)
        Path(bp).mkdir(parents=True, exist_ok=True)
        self._save_config()
        return {"success": True}

    def list_backup_paths(self, **kw) -> list[str]:
        return list(self._backup_paths)

    def remove_backup_path(self, path: str, **kw) -> dict:
        bp = str(Path(path).resolve())
        if bp in self._backup_paths:
            self._backup_paths.remove(bp)
        self._save_config()
        return {"success": True}

    def suggest_backup_paths(self, **kw) -> list[str]:
        suggestions = []
        home = Path.home()
        candidates = [
            home / "meshctx-backups",
            home / ".meshctx" / "backups",
            home / "backups",
            Path("/var/backups/meshctx"),
        ]
        for c in candidates:
            suggestions.append(str(c))
        return suggestions

    # ═══════════════════════════════════════════════════════════════════════
    # v2.68 API — backup / find / restore / stats
    # ═══════════════════════════════════════════════════════════════════════

    def backup(self, source_path, version=None, label=None, **kw) -> dict:
        source = Path(source_path)
        if not self._backup_paths:
            return {
                "success": False,
                "suggested_paths": self.suggest_backup_paths(),
            }

        ts = int(time.time())
        short_id = uuid.uuid4().hex[:12]
        backup_id = f"backup-{ts}-{short_id}"

        files = []
        for f in sorted(source.rglob("*")):
            if f.is_symlink():
                continue
            if f.is_file():
                parts = set(f.parts)
                if not parts & SKIP_PARTS:
                    files.append(f)

        meta = {
            "version": version or "unknown",
            "label": label or "",
            "file_count": len(files),
            "backup_id": backup_id,
            "timestamp": ts,
            "source": str(source),
        }

        success_count = 0
        total = len(self._backup_paths)
        for bp_path in self._backup_paths:
            bp = Path(bp_path)
            bp.mkdir(parents=True, exist_ok=True)

            archive_path = bp / f"{backup_id}.tar.gz"
            meta_path = bp / f"{backup_id}" / "_backup_meta.json"

            meta_dir = bp / f"{backup_id}"
            meta_dir.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2))

            with tarfile.open(archive_path, "w:gz") as tar:
                for f in files:
                    tar.add(f, arcname=str(f.relative_to(source)))
            success_count += 1

        return {
            "success_count": f"{success_count}/{total}",
            "backup_id": backup_id,
            "version": version or "unknown",
            "file_count": len(files),
        }

    def find_backups(self, **kw) -> list[dict]:
        backups = []
        for bp_path in self._backup_paths:
            bp = Path(bp_path)
            if not bp.exists():
                continue
            for archive in sorted(bp.glob("backup-*.tar.gz")):
                backup_id = archive.stem.replace(".tar", "")
                backups.append({
                    "backup_id": backup_id,
                    "path": str(archive),
                    "backup_path": bp_path,
                })
        return backups

    def restore(self, backup_id, restore_target, **kw) -> dict:
        restore_target = Path(restore_target)
        archive_path = None
        for bp_path in self._backup_paths:
            candidate = Path(bp_path) / f"{backup_id}.tar.gz"
            if candidate.exists():
                archive_path = candidate
                break

        if archive_path is None:
            return {"success": False, "error": "backup not found"}

        restore_target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=restore_target)

        return {"success": True}

    def get_stats(self, **kw) -> dict:
        return {
            "backup_paths": self.list_backup_paths(),
            "suggested_paths": self.suggest_backup_paths(),
        }

    def get_setup_instructions(self, **kw) -> str:
        return (
            "备份保险库 (Backup Vault) 设置说明:\n"
            "使用 meshctx backup add <路径> 添加备份路径。\n"
            "示例: meshctx backup add ~/my-backups\n"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # v3.106 API — create_backup
    # ═══════════════════════════════════════════════════════════════════════

    def create_backup(self, source_path, backup_type="full", target="local", **kw) -> BackupResult:
        source = Path(source_path).resolve()

        # Validate backup_type
        if backup_type not in VALID_BACKUP_TYPES:
            return BackupResult(
                success=False,
                error_message=f"Invalid backup_type: {backup_type}",
            )

        # Validate target
        if target not in VALID_TARGETS:
            return BackupResult(
                success=False,
                error_message=f"Invalid target: {target}",
            )

        # Check source exists
        if not source.exists():
            return BackupResult(
                success=False,
                error_message=f"Source not found: {source_path}",
            )

        t0 = time.time()
        backup_id = f"bv-{uuid.uuid4().hex[:12]}-{int(t0)}"

        # Find parent for incremental
        parent_id = None
        parent_files = {}
        if backup_type == "incremental":
            parent = self._find_latest_full_backup(str(source))
            if parent is not None:
                parent_id = parent["backup_id"]
                parent_files = parent.get("files", {})

        # Collect files
        current_files = _collect_files(source)

        # Compute checksums
        current_checksums = {}
        for rel, fpath in current_files.items():
            current_checksums[rel] = _sha256(fpath)

        # Determine which files to include
        if backup_type == "incremental" and parent_files:
            changed = {}
            for rel, csum in current_checksums.items():
                if rel not in parent_files or parent_files[rel] != csum:
                    changed[rel] = current_files[rel]
            files_to_backup = changed
            # Merged total = parent's total + changed count (but not double-counting)
            merged_total = len(parent_files)
            for rel in changed:
                if rel not in parent_files:
                    merged_total += 1
        else:
            files_to_backup = current_files
            merged_total = len(current_files)

        # Compute total bytes
        total_bytes = 0
        for fpath in files_to_backup.values():
            total_bytes += fpath.stat().st_size

        # Create archive
        archive_path = self._archive_path(backup_id)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))

        with tarfile.open(archive_path, "w:gz") as tar:
            for rel, fpath in files_to_backup.items():
                tar.add(str(fpath), arcname=rel)

        # If encrypted, encrypt the archive
        encrypted = self.is_encrypted
        if encrypted:
            self._encrypt_file(archive_path)

        # Save manifest
        manifest = BackupManifest(
            backup_id=backup_id,
            backup_type=backup_type,
            source_path=str(source),
            target=target,
            created_at=created_at,
            encrypted=encrypted,
            checksum_algorithm="sha256",
            total_files=merged_total,
            total_bytes=total_bytes,
            parent_backup_id=parent_id,
        )

        # For incremental, merge parent files with current changed files
        if backup_type == "incremental" and parent_files:
            merged = dict(parent_files)
            for rel, csum in current_checksums.items():
                merged[rel] = csum
            self._save_manifest(manifest, merged)
        else:
            self._save_manifest(manifest, current_checksums)

        duration = time.time() - t0

        return BackupResult(
            success=True,
            backup_id=backup_id,
            total_files=len(files_to_backup),
            total_bytes=total_bytes,
            duration_seconds=duration,
        )

    def _find_latest_full_backup(self, source_path: str) -> Optional[dict]:
        """Find the most recent full backup for the given source path."""
        best = None
        best_ts = ""
        for data in self._manifests.values():
            if data.get("backup_type") == "full" and data.get("source_path") == source_path:
                if best is None or data.get("created_at", "") > best_ts:
                    best = data
                    best_ts = data.get("created_at", "")
        return best

    def _encrypt_file(self, path: Path):
        data = path.read_bytes()
        encrypted = self._fernet.encrypt(data)
        path.write_bytes(encrypted)

    def _decrypt_file(self, path: Path) -> bytes:
        data = path.read_bytes()
        return self._fernet.decrypt(data)

    # ═══════════════════════════════════════════════════════════════════════
    # v3.106 API — manage
    # ═══════════════════════════════════════════════════════════════════════

    def get_manifest(self, backup_id: str) -> Optional[BackupManifest]:
        data = self._load_manifest_data(backup_id)
        if data is None:
            return None
        return BackupManifest(
            backup_id=data["backup_id"],
            backup_type=data["backup_type"],
            source_path=data["source_path"],
            target=data["target"],
            created_at=data["created_at"],
            encrypted=data.get("encrypted", False),
            checksum_algorithm=data.get("checksum_algorithm", "sha256"),
            total_files=data.get("total_files", 0),
            total_bytes=data.get("total_bytes", 0),
            parent_backup_id=data.get("parent_backup_id"),
        )

    def restore_backup(self, backup_id: str, restore_path: Optional[str] = None, **kw) -> RestoreResult:
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return RestoreResult(success=False, backup_id=backup_id, error_message="Backup not found")

        archive_path = self._archive_path(backup_id)
        if not archive_path.exists():
            return RestoreResult(success=False, backup_id=backup_id, error_message="Backup archive not found")

        # Determine restore target
        if restore_path is not None:
            target = Path(restore_path)
        else:
            target = Path(manifest.source_path)

        target.mkdir(parents=True, exist_ok=True)

        # Handle encrypted archives
        if manifest.encrypted:
            if not self.is_encrypted:
                return RestoreResult(
                    success=False, backup_id=backup_id,
                    error_message="Cannot restore encrypted backup: no decryption key available"
                )
            decrypted_data = self._decrypt_file(archive_path)
            import io
            with tarfile.open(fileobj=io.BytesIO(decrypted_data), mode="r:gz") as tar:
                tar.extractall(path=target)
        else:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=target)

        # Count restored files
        files_restored = 0
        bytes_restored = 0
        for f in target.rglob("*"):
            if f.is_file() and not f.is_symlink():
                files_restored += 1
                bytes_restored += f.stat().st_size

        return RestoreResult(
            success=True,
            backup_id=backup_id,
            files_restored=files_restored,
            bytes_restored=bytes_restored,
        )

    def list_backups(self, backup_type: Optional[str] = None, source_path: Optional[str] = None, **kw) -> list[BackupEntry]:
        entries = []
        for data in self._manifests.values():
            if backup_type is not None and data.get("backup_type") != backup_type:
                continue
            if source_path is not None and data.get("source_path") != source_path:
                continue
            entries.append(BackupEntry(
                backup_id=data["backup_id"],
                backup_type=data["backup_type"],
                source_path=data["source_path"],
                target=data["target"],
                created_at=data["created_at"],
                encrypted=data.get("encrypted", False),
                status="completed",
                total_files=data.get("total_files", 0),
                total_bytes=data.get("total_bytes", 0),
            ))
        return entries

    def delete_backup(self, backup_id: str) -> bool:
        archive_path = self._archive_path(backup_id)
        manifest_path = self._manifests_dir / f"{backup_id}.json"
        in_memory = backup_id in self._manifests
        on_disk = archive_path.exists() or manifest_path.exists()
        self._manifests.pop(backup_id, None)
        if manifest_path.exists():
            manifest_path.unlink()
        if archive_path.exists():
            archive_path.unlink()
        return in_memory or on_disk

    def verify_backup(self, backup_id: str) -> dict:
        data = self._load_manifest_data(backup_id)
        if data is None:
            return {"valid": False, "mismatched": 0, "missing": 0, "error": "Backup not found"}

        source_path = Path(data["source_path"])
        if not source_path.exists():
            return {"valid": False, "mismatched": 0, "missing": len(data.get("files", {})), "error": "Source path not found"}

        expected_files = data.get("files", {})
        mismatched = 0
        missing = 0

        for rel, expected_hash in expected_files.items():
            fpath = source_path / rel
            if not fpath.exists():
                missing += 1
            elif _sha256(fpath) != expected_hash:
                mismatched += 1

        valid = (mismatched == 0 and missing == 0)
        return {"valid": valid, "mismatched": mismatched, "missing": missing}

    def get_backup_stats(self, **kw) -> dict:
        return self._compute_stats()

    def clear_all(self) -> int:
        count = len(self._manifests)
        self._manifests.clear()
        for mp in self._manifests_dir.glob("*.json"):
            mp.unlink()
        for ap in self._backups_dir.glob("*.tar.gz"):
            ap.unlink()
        return count

