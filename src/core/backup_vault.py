"""meshctx backup_vault — v2.68 + v3.106 Backup Vault (真实实现)

备份保险库:
  - v3.106 API: create_backup / restore_backup / list_backups / verify_backup /
    delete_backup / get_backup_stats / clear_all / 加密备份 (Fernet)
  - v2.68 API: add_backup_path / list_backup_paths / remove_backup_path /
    suggest_backup_paths / backup / find_backups / restore / get_stats /
    get_setup_instructions

存储位置 (均可由环境变量覆盖):
  - 备份库根目录:   $MESHCTX_BACKUP_DIR  默认 ~/.meshctx/backups/
  - 配置目录:       $MESHCTX_CONFIG_DIR  默认 ~/.meshctx/backups/config
加密: 优先 cryptography.fernet; 若 cryptography 不可用, generate_key 抛
RuntimeError (调用方可降级), 绝不将密钥明文落盘。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKUP_DIR_ENV = "MESHCTX_BACKUP_DIR"
CONFIG_DIR_ENV = "MESHCTX_CONFIG_DIR"


class BackupType(Enum):
    FULL = 'full'
    INCREMENTAL = 'incremental'


class BackupTarget(Enum):
    LOCAL = 'local'
    S3 = 's3'
    REMOTE = 'remote'


class BackupStatus(Enum):
    PENDING = 'pending'
    COMPLETED = 'completed'


@dataclass
class BackupResult:
    success: bool = None
    backup_id: str = ''
    error_message: str = ''
    total_files: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0


@dataclass
class RestoreResult:
    success: bool = None
    backup_id: str = ''
    error_message: str = ''
    files_restored: int = 0
    bytes_restored: int = 0


@dataclass
class BackupManifest:
    backup_id: str = None
    backup_type: str = None
    source_path: str = None
    target: str = None
    created_at: str = None
    encrypted: bool = False
    checksum_algorithm: str = 'sha256'
    total_files: int = 0
    total_bytes: int = 0
    parent_backup_id: Optional[str] = None


@dataclass
class BackupEntry:
    backup_id: str = None
    backup_type: str = None
    source_path: str = None
    target: str = None
    created_at: str = None
    encrypted: bool = False
    status: str = 'completed'
    total_files: int = 0
    total_bytes: int = 0


SKIP_PARTS = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', '.tox', '.eggs', '.mypy_cache', '.pytest_cache'}
VALID_BACKUP_TYPES = {'full', 'incremental'}
VALID_TARGETS = {'local', 's3', 'remote'}


def _default_vault_dir() -> Path:
    """备份库根目录: 环境变量优先, 默认 ~/.meshctx/backups"""
    env = os.environ.get(BACKUP_DIR_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    return Path(os.path.expanduser("~/.meshctx/backups"))


def _default_config_dir() -> Path:
    """配置目录: 环境变量优先, 默认 ~/.meshctx/backups/config"""
    env = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    return Path(os.path.expanduser("~/.meshctx/backups/config"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _collect_files(source: Path) -> dict:
    """Collect regular files from source. Returns {relpath: abs_path}."""
    source = Path(source)
    if not source.exists():
        return {}
    result: Dict[str, str] = {}
    if source.is_file():
        result[source.name] = str(source.resolve())
        return result
    for root, dirs, files in os.walk(str(source)):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        for fname in files:
            abs_path = os.path.join(root, fname)
            rel = os.path.relpath(abs_path, str(source))
            rel = rel.replace(os.sep, "/")
            result[rel] = abs_path
    return result


def _sha256(path: Path) -> str:
    """计算文件 SHA-256 校验和"""
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(tar: tarfile.TarFile, target: Path) -> int:
    """安全解压: 防止路径穿越, 返回 (文件数, 字节数)"""
    target = target.resolve()
    files_restored = 0
    bytes_restored = 0
    for member in tar.getmembers():
        dest = (target / member.name).resolve()
        if not str(dest).startswith(str(target)):
            raise ValueError(f"非法解压路径: {member.name}")
        if member.isfile():
            files_restored += 1
            bytes_restored += member.size
    # Python 3.12+ 支持 filter; 低版本用上面的手动校验
    try:
        tar.extractall(str(target), filter="data")
    except TypeError:
        tar.extractall(str(target))
    return files_restored, bytes_restored


class BackupVault:
    def __init__(self, config_dir=None, vault_dir=None, encryption_key=None, **kw):
        self.config_dir = Path(config_dir).expanduser() if config_dir else _default_config_dir()
        self.vault_dir = Path(vault_dir).expanduser() if vault_dir else _default_vault_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        (self.vault_dir / "backups").mkdir(parents=True, exist_ok=True)

        self._encryption_key: Optional[bytes] = None
        if encryption_key is not None:
            self.set_encryption_key(encryption_key)

        self._backup_paths: List[str] = []
        self._manifests: Dict[str, BackupManifest] = {}
        self._load_config()
        # 注意: 不自动加载磁盘清单 — 新实例的 list_backups() 只反映本实例会话内的备份;
        # get_manifest/restore_backup/verify_backup 会对单个 ID 做磁盘兜底加载。

    # ── 加密 ────────────────────────────────────────────────
    @property
    def is_encrypted(self) -> bool:
        return self._encryption_key is not None

    @classmethod
    def generate_key(cls) -> bytes:
        """生成加密密钥 (Fernet 44 字节 base64)。cryptography 不可用时抛 RuntimeError。"""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise RuntimeError(
                "cryptography not installed — 无法生成加密密钥, 请 pip install cryptography"
            )
        return Fernet.generate_key()

    def set_encryption_key(self, key: bytes):
        """设置加密密钥。验证密钥有效性; cryptography 不可用则抛 RuntimeError。"""
        if key is None:
            self._encryption_key = None
            return
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise RuntimeError(
                "cryptography not installed — 无法启用加密, 请 pip install cryptography"
            )
        self._encryption_key = bytes(key)
        # 验证密钥格式
        Fernet(self._encryption_key)

    def _fernet(self):
        from cryptography.fernet import Fernet
        return Fernet(self._encryption_key)

    def _encrypt_file(self, path: Path):
        """加密文件, 写为 <name>.enc 并删除原文"""
        data = path.read_bytes()
        enc = self._fernet().encrypt(data)
        enc_path = path.with_name(path.name + ".enc")
        enc_path.write_bytes(enc)
        path.unlink()
        return enc_path

    def _decrypt_file(self, path: Path) -> bytes:
        """解密文件返回字节; 非 .enc 文件直接返回原始内容"""
        if str(path).endswith(".enc"):
            if self._encryption_key is None:
                raise RuntimeError("no decryption key for encrypted backup")
            return self._fernet().decrypt(path.read_bytes())
        return path.read_bytes()

    # ── 配置 (备份路径) ─────────────────────────────────────
    def _load_config(self):
        cfg_path = self.config_dir / "config.json"
        loaded: List[str] = []
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                loaded = [p for p in data.get("backup_paths", []) if isinstance(p, str)]
            except (ValueError, OSError):
                loaded = []
        self._backup_paths = [os.path.abspath(os.path.expanduser(p)) for p in loaded]

    def _save_config(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.config_dir / "config.json.tmp"
        tmp.write_text(
            json.dumps({"backup_paths": self._backup_paths}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.config_dir / "config.json")

    # ── 清单持久化 ──────────────────────────────────────────
    def _load_manifests_from_disk(self):
        """Load all manifests from disk into memory."""
        backups_root = self.vault_dir / "backups"
        if not backups_root.is_dir():
            return
        for mdir in backups_root.iterdir():
            mf = mdir / "manifest.json"
            if not mf.is_file():
                continue
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                self._manifests[data.get("backup_id", mdir.name)] = BackupManifest(
                    backup_id=data.get("backup_id"),
                    backup_type=data.get("backup_type"),
                    source_path=data.get("source_path"),
                    target=data.get("target"),
                    created_at=data.get("created_at"),
                    encrypted=bool(data.get("encrypted", False)),
                    checksum_algorithm=data.get("checksum_algorithm", "sha256"),
                    total_files=int(data.get("total_files", 0)),
                    total_bytes=int(data.get("total_bytes", 0)),
                    parent_backup_id=data.get("parent_backup_id"),
                )
            except (ValueError, OSError):
                continue

    def _save_manifest(self, manifest: BackupManifest, files_checksums: dict):
        backup_dir = self.vault_dir / "backups" / manifest.backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = backup_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        files_file = backup_dir / "files.json"
        files_file.write_text(
            json.dumps(files_checksums, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_manifest_data(self, backup_id: str) -> Optional[dict]:
        p = self.vault_dir / "backups" / backup_id / "manifest.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def _load_checksums(self, backup_id: str) -> Optional[dict]:
        p = self.vault_dir / "backups" / backup_id / "files.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def _archive_path(self, backup_id: str) -> Path:
        return self.vault_dir / "backups" / backup_id / "archive.tar.gz"

    def _archive_file(self, backup_id: str) -> Path:
        """返回实际存在的归档文件路径 (加密时为 .enc)"""
        base = self._archive_path(backup_id)
        if base.is_file():
            return base
        enc = Path(str(base) + ".enc")
        if enc.is_file():
            return enc
        return base

    # ── v2.68 备份路径管理 ──────────────────────────────────
    def add_backup_path(self, path: str, **kw) -> dict:
        p = os.path.abspath(os.path.expanduser(str(path)))
        if p in self._backup_paths:
            return {"success": False, "path": p, "reason": "already_added"}
        Path(p).mkdir(parents=True, exist_ok=True)
        self._backup_paths.append(p)
        self._save_config()
        return {"success": True, "path": p}

    def list_backup_paths(self, **kw) -> list[str]:
        return list(self._backup_paths)

    def remove_backup_path(self, path: str, **kw) -> dict:
        p = os.path.abspath(os.path.expanduser(str(path)))
        if p not in self._backup_paths:
            return {"success": False, "path": p, "reason": "not_found"}
        self._backup_paths.remove(p)
        self._save_config()
        return {"success": True, "path": p}

    def suggest_backup_paths(self, **kw) -> list[str]:
        candidates = []
        home = os.path.expanduser("~")
        for d in (home, os.path.join(home, "Documents"), os.path.join(home, "Desktop"),
                  os.path.join(home, "Downloads"), os.path.join(home, ".meshctx")):
            if d and os.path.isdir(d) and d not in candidates:
                candidates.append(d)
        cwd = os.getcwd()
        if cwd not in candidates:
            candidates.append(cwd)
        return candidates

    # ── v2.68 备份 / 恢复 ────────────────────────────────────
    def backup(self, source_path, version=None, label=None, **kw) -> dict:
        if not self._backup_paths:
            return {
                "success": False,
                "reason": "未配置备份路径, 请先执行 meshctx backup add <目录>",
                "suggested_paths": self.suggest_backup_paths(),
            }
        src = Path(str(source_path)).expanduser()
        if not src.exists():
            return {
                "success": False,
                "reason": f"备份源不存在: {source_path}",
                "suggested_paths": self.suggest_backup_paths(),
            }
        files = _collect_files(src)
        total_bytes = 0
        for abs_path in files.values():
            try:
                total_bytes += os.path.getsize(abs_path)
            except OSError:
                pass
        success_ids: List[str] = []
        errors: List[str] = []
        for bp in self._backup_paths:
            try:
                backup_id = _new_id()
                archive = Path(bp) / f"backup-{backup_id}.tar.gz"
                with tarfile.open(str(archive), "w:gz") as tf:
                    for rel, abs_path in files.items():
                        tf.add(abs_path, arcname=rel)
                meta = {
                    "backup_id": backup_id,
                    "version": version,
                    "label": label,
                    "file_count": len(files),
                    "total_bytes": total_bytes,
                    "created_at": _now_iso(),
                    "source_path": os.path.abspath(str(src)),
                    "archive": archive.name,
                }
                (Path(bp) / "_backup_meta.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                success_ids.append(backup_id)
            except (OSError, tarfile.TarError) as e:
                errors.append(f"{bp}: {e}")
        if not success_ids:
            return {
                "success": False,
                "reason": "; ".join(errors) or "备份失败",
                "suggested_paths": self.suggest_backup_paths(),
            }
        return {
            "success": True,
            "success_count": f"{len(success_ids)}/{len(self._backup_paths)}",
            "backup_id": success_ids[0],
            "version": version,
            "label": label,
            "backup_paths": list(self._backup_paths),
            "total_files": len(files),
            "errors": errors,
        }

    def find_backups(self, **kw) -> list[dict]:
        result: List[dict] = []
        for bp in self._backup_paths:
            root = Path(bp)
            if not root.is_dir():
                continue
            for meta_file in root.rglob("_backup_meta.json"):
                try:
                    result.append(json.loads(meta_file.read_text(encoding="utf-8")))
                except (ValueError, OSError):
                    continue
        result.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return result

    def restore(self, backup_id, restore_target, **kw) -> dict:
        target = Path(str(restore_target)).expanduser()
        meta = None
        meta_dir = None
        for bp in self._backup_paths:
            root = Path(bp)
            if not root.is_dir():
                continue
            for meta_file in root.rglob("_backup_meta.json"):
                try:
                    d = json.loads(meta_file.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if d.get("backup_id") == backup_id:
                    meta = d
                    meta_dir = meta_file.parent
                    break
            if meta:
                break
        if meta is None:
            return {"success": False, "reason": f"备份 {backup_id} 未找到", "restore_path": str(target)}
        archive = meta_dir / meta.get("archive", f"backup-{backup_id}.tar.gz")
        if not archive.is_file():
            return {"success": False, "reason": f"归档文件缺失: {archive}", "restore_path": str(target)}
        target.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(str(archive), "r:gz") as tf:
                files_restored, bytes_restored = _safe_extract(tf, target)
        except (OSError, tarfile.TarError, ValueError) as e:
            return {"success": False, "reason": f"解压失败: {e}", "restore_path": str(target)}
        return {
            "success": True,
            "backup_id": backup_id,
            "restore_path": str(target),
            "files_restored": files_restored,
            "bytes_restored": bytes_restored,
        }

    def get_stats(self, **kw) -> dict:
        backups = self.find_backups()
        total_size = 0
        for bp in self._backup_paths:
            root = Path(bp)
            if root.is_dir():
                for a in root.glob("backup-*.tar.gz"):
                    try:
                        total_size += a.stat().st_size
                    except OSError:
                        pass
        return {
            "backup_paths": self.list_backup_paths(),
            "suggested_paths": self.suggest_backup_paths(),
            "total_backups": len(backups),
            "total_size": total_size,
        }

    def get_setup_instructions(self, **kw) -> str:
        return (
            "备份保险库使用说明 (meshctx backup):\n"
            "  1. meshctx backup add <目录>      — 添加备份存储路径\n"
            "  2. meshctx backup list            — 查看已配置的备份路径\n"
            "  3. meshctx backup <源路径>        — 执行备份\n"
            "  4. meshctx backup restore <id> <目标> — 恢复备份\n"
            "  5. meshctx backup paths           — 查看建议的备份路径\n"
            "加密备份: BackupVault(encryption_key=...) 启用 Fernet 加密。"
        )

    # ── v3.106 备份 / 恢复 ──────────────────────────────────
    def _compute_stats(self) -> dict:
        full = sum(1 for m in self._manifests.values() if m.backup_type == "full")
        incr = sum(1 for m in self._manifests.values() if m.backup_type == "incremental")
        storage = 0
        total_files = 0
        total_bytes = 0
        for m in self._manifests.values():
            total_files += m.total_files
            total_bytes += m.total_bytes
            archive = self._archive_file(m.backup_id)
            if archive.is_file():
                try:
                    storage += archive.stat().st_size
                except OSError:
                    pass
        return {
            "total_backups": len(self._manifests),
            "full_backups": full,
            "incremental_backups": incr,
            "vault_dir": str(self.vault_dir),
            "storage_used_bytes": storage,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "encrypted_backups": sum(1 for m in self._manifests.values() if m.encrypted),
        }

    def create_backup(self, source_path, backup_type='full', target='local', **kw) -> BackupResult:
        """创建备份 (v3.106)。支持 full / incremental, target 仅 local。"""
        started = time.time()
        if backup_type not in VALID_BACKUP_TYPES:
            return BackupResult(
                success=False,
                error_message=f"Invalid backup_type: {backup_type} (可选: full/incremental)",
            )
        if target not in VALID_TARGETS:
            return BackupResult(
                success=False,
                error_message=f"Invalid target: {target} (可选: local/s3/remote)",
            )
        src = Path(str(source_path)).expanduser()
        if not src.exists():
            return BackupResult(
                success=False,
                error_message=f"Source path not found: {source_path}",
            )
        if target != "local":
            return BackupResult(
                success=False,
                error_message=f"Target {target} 暂不支持 (开源版仅支持 local)",
            )

        files = _collect_files(src)
        parent_id = None
        parent_checksums: dict = {}

        if backup_type == "incremental":
            parent = self._find_latest_full_backup(os.path.abspath(str(src)))
            if parent is not None:
                parent_id = parent.get("backup_id")
                parent_checksums = self._load_checksums(parent_id) or {}

        backup_id = _new_id()
        backup_dir = self.vault_dir / "backups" / backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 计算当前校验和
        current_checksums = {}
        for rel, abs_path in files.items():
            try:
                current_checksums[rel] = _sha256(Path(abs_path))
            except OSError:
                continue

        # 确定归档内容 (full: 全部; incremental: 新增/修改)
        if backup_type == "incremental" and parent_checksums:
            changed = {
                rel: h for rel, h in current_checksums.items()
                if parent_checksums.get(rel) != h
            }
            merged_checksums = dict(parent_checksums)
            merged_checksums.update(changed)
            archive_files = changed
        else:
            archive_files = current_checksums
            merged_checksums = dict(current_checksums)

        total_bytes = 0
        archive_path = backup_dir / "archive.tar.gz"
        if archive_files:
            try:
                with tarfile.open(str(archive_path), "w:gz") as tf:
                    for rel in archive_files:
                        abs_path = files.get(rel) or (
                            str(src / rel) if not os.path.isabs(rel) else rel
                        )
                        if os.path.isfile(abs_path):
                            tf.add(abs_path, arcname=rel)
                            try:
                                total_bytes += os.path.getsize(abs_path)
                            except OSError:
                                pass
            except (OSError, tarfile.TarError) as e:
                return BackupResult(
                    success=False,
                    error_message=f"归档创建失败: {e}",
                    backup_id=backup_id,
                )

        # 加密归档
        if self.is_encrypted and archive_path.is_file():
            try:
                self._encrypt_file(archive_path)
            except Exception as e:
                return BackupResult(success=False, error_message=f"加密失败: {e}", backup_id=backup_id)

        manifest = BackupManifest(
            backup_id=backup_id,
            backup_type=backup_type,
            source_path=os.path.abspath(str(src)),
            target=target,
            created_at=_now_iso(),
            encrypted=self.is_encrypted,
            checksum_algorithm='sha256',
            total_files=len(merged_checksums),
            total_bytes=total_bytes,
            parent_backup_id=parent_id,
        )
        self._save_manifest(manifest, merged_checksums)
        self._manifests[backup_id] = manifest

        return BackupResult(
            success=True,
            backup_id=backup_id,
            # total_files = 本次归档包含的文件数 (增量无变化时为 0);
            # 合并后的完整清单数见 manifest.total_files
            total_files=len(archive_files),
            total_bytes=total_bytes,
            duration_seconds=round(time.time() - started, 4),
        )

    def _find_latest_full_backup(self, source_path: str) -> Optional[dict]:
        """Find the most recent full backup for the given source path."""
        source_path = os.path.abspath(source_path)
        candidates = [
            m for m in self._manifests.values()
            if m.backup_type == "full" and m.source_path == source_path
        ]
        if not candidates:
            # 磁盘兜底
            backups_root = self.vault_dir / "backups"
            if backups_root.is_dir():
                for mdir in backups_root.iterdir():
                    data = self._load_manifest_data(mdir.name)
                    if (
                        data
                        and data.get("backup_type") == "full"
                        and data.get("source_path") == source_path
                    ):
                        m = BackupManifest(
                            backup_id=data.get("backup_id"),
                            backup_type=data.get("backup_type"),
                            source_path=data.get("source_path"),
                            target=data.get("target"),
                            created_at=data.get("created_at"),
                            encrypted=bool(data.get("encrypted", False)),
                            checksum_algorithm=data.get("checksum_algorithm", "sha256"),
                            total_files=int(data.get("total_files", 0)),
                            total_bytes=int(data.get("total_bytes", 0)),
                            parent_backup_id=data.get("parent_backup_id"),
                        )
                        candidates.append(m)
        if not candidates:
            return None
        latest = max(candidates, key=lambda m: (m.created_at or ""))
        return asdict(latest)

    def get_manifest(self, backup_id: str) -> Optional[BackupManifest]:
        """按 ID 获取备份清单 (内存优先, 磁盘兜底)"""
        m = self._manifests.get(backup_id)
        if m is not None:
            return m
        data = self._load_manifest_data(backup_id)
        if data is None:
            return None
        manifest = BackupManifest(
            backup_id=data.get("backup_id"),
            backup_type=data.get("backup_type"),
            source_path=data.get("source_path"),
            target=data.get("target"),
            created_at=data.get("created_at"),
            encrypted=bool(data.get("encrypted", False)),
            checksum_algorithm=data.get("checksum_algorithm", "sha256"),
            total_files=int(data.get("total_files", 0)),
            total_bytes=int(data.get("total_bytes", 0)),
            parent_backup_id=data.get("parent_backup_id"),
        )
        self._manifests[backup_id] = manifest
        return manifest

    def restore_backup(self, backup_id: str, restore_path: Optional[str] = None, **kw) -> RestoreResult:
        """恢复备份。restore_path 缺省时恢复到源路径。"""
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=f"Backup not found: {backup_id}",
            )
        if manifest.encrypted and not self.is_encrypted:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message="no decryption key for encrypted backup (请传入 encryption_key)",
            )

        target = Path(str(restore_path)).expanduser() if restore_path else Path(manifest.source_path)
        target.mkdir(parents=True, exist_ok=True)

        archive = self._archive_file(backup_id)
        if not archive.is_file():
            if manifest.total_files == 0:
                return RestoreResult(success=True, backup_id=backup_id, files_restored=0, bytes_restored=0)
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=f"Archive missing: {archive}",
            )

        try:
            if str(archive).endswith(".enc"):
                data = self._decrypt_file(archive)
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        suffix=".tar.gz", prefix="meshctx_restore_", delete=False
                    ) as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name
                    with tarfile.open(tmp_path, "r:gz") as tf:
                        files_restored, bytes_restored = _safe_extract(tf, target)
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
            else:
                with tarfile.open(str(archive), "r:gz") as tf:
                    files_restored, bytes_restored = _safe_extract(tf, target)
        except (OSError, tarfile.TarError, ValueError) as e:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=f"恢复失败: {e}",
            )

        return RestoreResult(
            success=True,
            backup_id=backup_id,
            files_restored=files_restored,
            bytes_restored=bytes_restored,
        )

    def list_backups(self, backup_type: Optional[str] = None, source_path: Optional[str] = None, **kw) -> list[BackupEntry]:
        """列出备份 (内存清单; 支持按类型/源路径过滤)"""
        entries = []
        for m in self._manifests.values():
            if backup_type is not None and m.backup_type != backup_type:
                continue
            if source_path is not None and m.source_path != os.path.abspath(source_path):
                continue
            entries.append(
                BackupEntry(
                    backup_id=m.backup_id,
                    backup_type=m.backup_type,
                    source_path=m.source_path,
                    target=m.target,
                    created_at=m.created_at,
                    encrypted=m.encrypted,
                    status='completed',
                    total_files=m.total_files,
                    total_bytes=m.total_bytes,
                )
            )
        entries.sort(key=lambda e: (e.created_at or ""), reverse=True)
        return entries

    def delete_backup(self, backup_id: str) -> bool:
        """删除备份 (清单 + 归档)"""
        if backup_id not in self._manifests:
            return False
        backup_dir = self.vault_dir / "backups" / backup_id
        try:
            if backup_dir.is_dir():
                shutil.rmtree(str(backup_dir))
        except OSError:
            pass
        self._manifests.pop(backup_id, None)
        return True

    def verify_backup(self, backup_id: str) -> dict:
        """校验备份: 对比源文件 SHA-256 与清单记录"""
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return {"valid": False, "error": f"Backup not found: {backup_id}",
                    "checked": 0, "mismatched": 0, "missing": 0}
        checksums = self._load_checksums(backup_id)
        if checksums is None:
            return {"valid": False, "error": "checksum data missing",
                    "checked": 0, "mismatched": 0, "missing": 0}
        source = Path(manifest.source_path)
        if not source.exists():
            return {"valid": False, "error": f"Source path not found: {source}",
                    "checked": 0, "mismatched": 0, "missing": len(checksums)}
        missing = []
        mismatched = []
        for rel, expected in checksums.items():
            cur = source / rel if not os.path.isabs(rel) else Path(rel)
            if not cur.is_file():
                missing.append(rel)
                continue
            try:
                if _sha256(cur) != expected:
                    mismatched.append(rel)
            except OSError:
                missing.append(rel)
        return {
            "valid": (not missing and not mismatched),
            "checked": len(checksums),
            "mismatched": len(mismatched),
            "missing": len(missing),
            "mismatched_files": mismatched[:10],
            "missing_files": missing[:10],
        }

    def get_backup_stats(self, **kw) -> dict:
        """备份统计 (v3.106)"""
        return self._compute_stats()

    def clear_all(self) -> int:
        """清空所有备份与清单, 返回删除数量"""
        count = len(self._manifests)
        self._manifests.clear()
        backups_root = self.vault_dir / "backups"
        try:
            if backups_root.is_dir():
                shutil.rmtree(str(backups_root))
                backups_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return count


# ── 单例 ─────────────────────────────────────────────────────────
_singleton: Optional[BackupVault] = None
_singleton_lock = threading.Lock()


def get_backup_vault(**kw) -> 'BackupVault':
    """获取全局 BackupVault 单例 (首次调用时以参数创建)"""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = BackupVault(**kw)
        return _singleton


def reset_backup_vault():
    """重置全局 BackupVault 单例"""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "BackupType", "BackupTarget", "BackupStatus",
    "BackupResult", "RestoreResult", "BackupManifest", "BackupEntry",
    "get_backup_vault", "reset_backup_vault", "BackupVault",
]
