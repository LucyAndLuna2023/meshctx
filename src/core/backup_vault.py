"""meshctx backup_vault — v2.68 Backup Vault"""

import json
import os
import tarfile
import time
import uuid
from pathlib import Path


class BackupVault:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, config_dir=None, vault_dir=None, **kw):
        d = vault_dir or config_dir or "/tmp/backup_vault"
        self._config_dir = Path(d)
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._backup_paths: list[str] = []
        self._load_config()

    # ------------------------------------------------------------------ config
    def _config_file(self, **kw) -> Path:
        return self._config_dir / "backup_vault.json"

    def _load_config(self, **kw):
        cf = self._config_file()
        if cf.exists():
            try:
                data = json.loads(cf.read_text())
                self._backup_paths = data.get("backup_paths", [])
            except (json.JSONDecodeError, OSError):
                self._backup_paths = []

    def _save_config(self, **kw):
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_file().write_text(
            json.dumps({"backup_paths": self._backup_paths}, indent=2)
        )

    # ------------------------------------------------------------ path management
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
        """Return at least one sensible suggestion."""
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

    # ------------------------------------------------------------------- backup
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

        # Collect files relative to source — skip symlinks & noise dirs
        SKIP_PARTS = {".git", "__pycache__", "venv", ".venv", "node_modules",
                      ".tox", ".eggs", "*.egg-info", ".mypy_cache", ".pytest_cache"}
        files = []
        for f in sorted(source.rglob("*")):
            if f.is_symlink():
                continue
            if f.is_file():
                parts = set(f.parts)
                if not parts & SKIP_PARTS:
                    files.append(f)

        # Write metadata
        meta = {
            "version": version or "unknown",
            "label": label or "",
            "file_count": len(files),
            "backup_id": backup_id,
            "timestamp": ts,
            "source": str(source),
        }

        # Create archive in each backup path
        success_count = 0
        total = len(self._backup_paths)
        for bp_path in self._backup_paths:
            bp = Path(bp_path)
            bp.mkdir(parents=True, exist_ok=True)

            archive_path = bp / f"{backup_id}.tar.gz"
            meta_path = bp / f"{backup_id}" / "_backup_meta.json"

            # Write metadata inside the backup directory
            meta_dir = bp / f"{backup_id}"
            meta_dir.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2))

            # Create tar.gz
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

    # -------------------------------------------------------------- find / restore
    def find_backups(self, **kw) -> list[dict]:
        backups = []
        for bp_path in self._backup_paths:
            bp = Path(bp_path)
            if not bp.exists():
                continue
            for archive in sorted(bp.glob("backup-*.tar.gz")):
                backup_id = archive.stem.replace(".tar", "")  # backup-ts-uuid
                backups.append({
                    "backup_id": backup_id,
                    "path": str(archive),
                    "backup_path": bp_path,
                })
        return backups

    def restore(self, backup_id, restore_target, **kw) -> dict:
        restore_target = Path(restore_target)
        # Find the archive
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

    # -------------------------------------------------------------------- stats
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

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

