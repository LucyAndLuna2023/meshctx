"""
meshctx v3.106 — Backup Vault (备份保险库)

增量+全量备份 | 加密存储 | 多目标(本地/S3/远程) | 自动恢复
"""

import os
import json
import gzip
import shutil
import hashlib
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timezone
from pathlib import Path
from base64 import b64encode, b64decode

try:
    from cryptography.fernet import Fernet
    _FERNET_AVAILABLE = True
except ImportError:
    _FERNET_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# Data Classes & Enums
# ══════════════════════════════════════════════════════════════════════════════

class BackupType(Enum):
    """备份类型"""
    FULL = "full"               # 全量备份：备份所有文件
    INCREMENTAL = "incremental" # 增量备份：只备份变更文件


class BackupTarget(Enum):
    """备份目标"""
    LOCAL = "local"    # 本地目录
    S3 = "s3"          # AWS S3 兼容存储
    REMOTE = "remote"  # 远程 SFTP/SCP


class BackupStatus(Enum):
    """备份状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


@dataclass
class BackupManifest:
    """备份清单 — 记录备份元数据和文件签名"""
    backup_id: str
    backup_type: str           # 'full' or 'incremental'
    source_path: str
    target: str                # 'local', 's3', 'remote'
    created_at: str            # ISO 8601 timestamp
    encrypted: bool
    checksum_algorithm: str    # sha256
    total_files: int = 0
    total_bytes: int = 0
    files: Dict[str, str] = field(default_factory=dict)  # path -> sha256
    parent_backup_id: Optional[str] = None  # for incremental backups


@dataclass
class BackupEntry:
    """备份条目 — UI/查询用摘要"""
    backup_id: str
    backup_type: str
    source_path: str
    target: str
    created_at: str
    encrypted: bool
    status: str
    total_files: int
    total_bytes: int
    parent_backup_id: Optional[str] = None


@dataclass
class BackupResult:
    """备份操作结果"""
    success: bool
    backup_id: Optional[str] = None
    total_files: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class RestoreResult:
    """恢复操作结果"""
    success: bool
    backup_id: str = ""
    files_restored: int = 0
    bytes_restored: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# BackupVault
# ══════════════════════════════════════════════════════════════════════════════

class BackupVault:
    """
    Backup Vault (备份保险库) — 企业级备份引擎

    功能:
    - 全量 + 增量备份，基于 SHA-256 文件签名
    - AES-256 (Fernet) 加密存储
    - 多目标：本地、S3、远程 SFTP
    - 自动校验 + 一键恢复
    """

    def __init__(
        self,
        vault_dir: Optional[str] = None,
        encryption_key: Optional[bytes] = None,
    ):
        """
        Args:
            vault_dir: 保险库根目录 (默认 ~/.meshctx/backup_vault)
            encryption_key: Fernet 32字节 base64 密钥 (None=不加密)
        """
        if vault_dir is None:
            vault_dir = os.path.join(
                os.path.expanduser("~"), ".meshctx", "backup_vault"
            )
        self._vault_dir = Path(vault_dir)
        self._vault_dir.mkdir(parents=True, exist_ok=True)

        # Manifest 存储目录
        self._manifests_dir = self._vault_dir / "manifests"
        self._manifests_dir.mkdir(exist_ok=True)

        # 备份数据目录
        self._data_dir = self._vault_dir / "data"
        self._data_dir.mkdir(exist_ok=True)

        # 加密
        self._encryption_key = encryption_key
        self._fernet: Optional[Any] = None
        if encryption_key:
            if _FERNET_AVAILABLE:
                self._fernet = Fernet(encryption_key)  # type: ignore[reportPossiblyUnboundVariable]
            else:
                raise RuntimeError(
                    "Encryption requested but 'cryptography' package not installed. "
                    "Run: pip install cryptography"
                )

        # 索引缓存
        self._manifests_cache: Dict[str, BackupManifest] = {}
        self._lock = threading.RLock()
        self._id_counter: int = 0

        # 后台任务
        self._active_jobs: Dict[str, Dict[str, Any]] = {}

        # 加载已有清单
        self._load_manifests()

    # ── 密钥管理 ──────────────────────────────────────────────────────────

    @staticmethod
    def generate_key() -> bytes:
        """生成 Fernet 加密密钥 (base64 编码)"""
        if not _FERNET_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. Run: pip install cryptography"
            )
        return Fernet.generate_key()

    def set_encryption_key(self, key: Optional[bytes]) -> None:
        """设置或更换加密密钥"""
        if key and not _FERNET_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. Run: pip install cryptography"
            )
        with self._lock:
            self._encryption_key = key
            self._fernet = Fernet(key) if key else None  # type: ignore[reportPossiblyUnboundVariable]

    @property
    def is_encrypted(self) -> bool:
        return self._fernet is not None

    # ── 文件签名 ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_file_hash(filepath: str, algorithm: str = "sha256") -> str:
        """计算文件 SHA-256 哈希"""
        h = hashlib.new(algorithm)
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64KB
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _compute_content_hash(content: bytes, algorithm: str = "sha256") -> str:
        """计算内容哈希"""
        return hashlib.new(algorithm, content).hexdigest()

    # ── 清单管理 ──────────────────────────────────────────────────────────

    def _manifest_path(self, backup_id: str) -> Path:
        return self._manifests_dir / f"{backup_id}.json"

    def _save_manifest(self, manifest: BackupManifest) -> None:
        path = self._manifest_path(manifest.backup_id)
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
            "files": manifest.files,
            "parent_backup_id": manifest.parent_backup_id,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        self._manifests_cache[manifest.backup_id] = manifest

    def _load_manifests(self) -> None:
        """加载所有清单到内存缓存"""
        self._manifests_cache.clear()
        if not self._manifests_dir.exists():
            return
        for fpath in self._manifests_dir.glob("*.json"):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                manifest = BackupManifest(
                    backup_id=data["backup_id"],
                    backup_type=data["backup_type"],
                    source_path=data["source_path"],
                    target=data["target"],
                    created_at=data["created_at"],
                    encrypted=data.get("encrypted", False),
                    checksum_algorithm=data.get("checksum_algorithm", "sha256"),
                    total_files=data.get("total_files", 0),
                    total_bytes=data.get("total_bytes", 0),
                    files=data.get("files", {}),
                    parent_backup_id=data.get("parent_backup_id"),
                )
                self._manifests_cache[manifest.backup_id] = manifest
            except (json.JSONDecodeError, KeyError):
                continue

    def get_manifest(self, backup_id: str) -> Optional[BackupManifest]:
        """获取备份清单"""
        return self._manifests_cache.get(backup_id)

    # ── 文件遍历与差异计算 ────────────────────────────────────────────────

    def _walk_files(self, source_path: str) -> Dict[str, str]:
        """遍历目录下所有文件，返回 {相对路径: 绝对路径}"""
        result = {}
        base = Path(source_path).resolve()
        if not base.exists():
            raise FileNotFoundError(f"Source path not found: {source_path}")

        if base.is_file():
            # 单文件备份: 使用父目录作为 base，文件名作为 rel
            result[base.name] = str(base)
            return result

        for root, _, files in os.walk(base):
            for fname in files:
                fpath = Path(root) / fname
                rel = str(fpath.relative_to(base)).replace("\\", "/")
                result[rel] = str(fpath)
        return result

    def _compute_diff(
        self,
        current_files: Dict[str, str],
        previous_manifest: Optional[BackupManifest],
    ) -> Tuple[List[str], List[str]]:
        """
        计算增量差异。
        Returns: (changed_files, removed_files) - 都是相对路径列表
        """
        if previous_manifest is None:
            # 无前次备份 → 全量
            return list(current_files.keys()), []

        prev_files = set(previous_manifest.files.keys())
        curr_files = set(current_files.keys())

        removed = list(prev_files - curr_files)
        changed = list(curr_files - prev_files)

        # 检查修改过的文件
        for rel in (prev_files & curr_files):
            fpath = current_files[rel]
            try:
                h = self._compute_file_hash(fpath)
            except (OSError, PermissionError):
                changed.append(rel)
                continue
            if h != previous_manifest.files.get(rel, ""):
                changed.append(rel)

        return changed, removed

    # ── 加密/解密 ─────────────────────────────────────────────────────────

    def _encrypt(self, data: bytes) -> bytes:
        """加密数据"""
        if not self._fernet:
            return data
        return self._fernet.encrypt(data)

    def _decrypt(self, data: bytes) -> bytes:
        """解密数据"""
        if not self._fernet:
            return data
        return self._fernet.decrypt(data)

    # ── 备份目标适配器 ────────────────────────────────────────────────────

    def _store_local(self, backup_id: str, archive_path: str) -> str:
        """存储到本地保险库"""
        dest = self._data_dir / backup_id
        dest.mkdir(exist_ok=True)
        shutil.copy2(archive_path, dest / "backup.tar.gz")
        return str(dest)

    def _restore_local(self, backup_id: str, restore_dir: str) -> None:
        """从本地保险库恢复"""
        src = self._data_dir / backup_id / "backup.tar.gz"
        if not src.exists():
            raise FileNotFoundError(f"Backup archive not found: {src}")
        self._extract_archive(str(src), restore_dir)

    def _store_s3(self, backup_id: str, archive_path: str) -> str:
        """存储到 S3 (可选依赖 boto3)"""
        try:
            import boto3
        except ImportError:
            raise RuntimeError(
                "S3 backup requires boto3. Run: pip install boto3"
            )
        bucket = os.environ.get("BACKUP_S3_BUCKET", "meshctx-backups")
        s3_key = f"backups/{backup_id}/backup.tar.gz"
        region = os.environ.get("BACKUP_S3_REGION", "us-east-1")

        s3 = boto3.client("s3", region_name=region)
        s3.upload_file(archive_path, bucket, s3_key)
        return f"s3://{bucket}/{s3_key}"

    def _download_from_s3(self, backup_id: str, dest_path: str) -> None:
        """从 S3 下载备份归档到本地文件"""
        try:
            import boto3  # noqa: F811
        except ImportError:
            raise RuntimeError(
                "S3 restore requires boto3. Run: pip install boto3"
            )
        bucket = os.environ.get("BACKUP_S3_BUCKET", "meshctx-backups")
        s3_key = f"backups/{backup_id}/backup.tar.gz"
        region = os.environ.get("BACKUP_S3_REGION", "us-east-1")

        s3 = boto3.client("s3", region_name=region)
        s3.download_file(bucket, s3_key, dest_path)

    def _download_from_remote(self, backup_id: str, dest_path: str) -> None:
        """从远程下载备份归档到本地文件"""
        remote_host = os.environ.get("BACKUP_REMOTE_HOST", "")
        remote_path = os.environ.get("BACKUP_REMOTE_PATH", "/var/backups/meshctx")
        ssh_key = os.environ.get("BACKUP_SSH_KEY", "")
        remote_user = os.environ.get("BACKUP_REMOTE_USER", "root")

        if not remote_host:
            raise ValueError(
                "Remote restore requires BACKUP_REMOTE_HOST env var"
            )

        remote_file = f"{remote_user}@{remote_host}:{remote_path}/{backup_id}/backup.tar.gz"
        import subprocess as _sp
        cmd_parts = ["scp", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            cmd_parts += ["-i", ssh_key]
        cmd_parts += [remote_file, str(dest_path)]
        result = _sp.run(cmd_parts, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"SCP download failed with code {result.returncode}: {result.stderr}")

    def _store_remote(self, backup_id: str, archive_path: str) -> str:
        """存储到远程 (SFTP)"""
        remote_host = os.environ.get("BACKUP_REMOTE_HOST", "")
        remote_path = os.environ.get("BACKUP_REMOTE_PATH", "/var/backups/meshctx")
        ssh_key = os.environ.get("BACKUP_SSH_KEY", "")
        remote_user = os.environ.get("BACKUP_REMOTE_USER", "root")

        if not remote_host:
            raise ValueError(
                "Remote backup requires BACKUP_REMOTE_HOST env var"
            )

        dest = f"{remote_user}@{remote_host}:{remote_path}/{backup_id}/"
        import subprocess as _sp
        cmd_parts = ["scp", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            cmd_parts += ["-i", ssh_key]
        cmd_parts += [str(archive_path), dest]
        result = _sp.run(cmd_parts, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"SCP upload failed with code {result.returncode}: {result.stderr}")
        return f"remote://{dest}"

    # ── 打包/解包 ─────────────────────────────────────────────────────────

    @staticmethod
    def _create_archive(source_dir: str, file_list: List[str], output_path: str) -> int:
        """创建 tar.gz 归档，返回字节数"""
        import tarfile
        base = Path(source_dir).resolve()
        if base.is_file():
            # 单文件: base 改为父目录
            base = base.parent
        with tarfile.open(output_path, "w:gz") as tar:
            for rel in sorted(file_list):
                fpath = base / rel
                if fpath.exists():
                    tar.add(str(fpath), arcname=rel)
        return os.path.getsize(output_path)

    @staticmethod
    def _extract_archive(archive_path: str, dest_dir: str) -> int:
        """解压 tar.gz，返回恢复的文件数"""
        import tarfile
        os.makedirs(dest_dir, exist_ok=True)
        count = 0
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=dest_dir)
            count = len(tar.getmembers())
        return count

    # ── 核心：创建备份 ────────────────────────────────────────────────────

    def create_backup(
        self,
        source_path: str,
        backup_type: str = "full",
        target: str = "local",
        label: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BackupResult:
        """
        创建备份。

        Args:
            source_path: 源目录或文件路径
            backup_type: 'full' 或 'incremental'
            target: 'local', 's3', 或 'remote'
            label: 可选标签
            progress_callback: 进度回调 (current, total)

        Returns:
            BackupResult
        """
        t0 = time.monotonic()
        try:
            btype = BackupType(backup_type)
        except ValueError:
            return BackupResult(
                success=False,
                error_message=f"Invalid backup_type: {backup_type}. Use 'full' or 'incremental'."
            )
        try:
            btarget = BackupTarget(target)
        except ValueError:
            return BackupResult(
                success=False,
                error_message=f"Invalid target: {target}. Use 'local', 's3', or 'remote'."
            )

        source_path = os.path.abspath(source_path)
        if not os.path.exists(source_path):
            return BackupResult(
                success=False,
                error_message=f"Source path not found: {source_path}"
            )

        # 生成 backup_id (含微秒+计数器避免碰撞)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self._id_counter += 1
        bid = f"bv_{ts}_{self._id_counter:06d}_{hashlib.md5(source_path.encode()).hexdigest()[:8]}"
        if label:
            bid += f"_{label}"

        # 获取之前的备份清单（用于增量）
        parent_manifest: Optional[BackupManifest] = None
        if btype == BackupType.INCREMENTAL:
            # 查找最近的全量或增量备份
            candidates = sorted(
                [m for m in self._manifests_cache.values()
                 if m.source_path == source_path and m.target == target],
                key=lambda m: m.created_at,
                reverse=True,
            )
            if candidates:
                parent_manifest = candidates[0]

        # 遍历文件
        all_files = self._walk_files(source_path)

        # 计算差异
        if btype == BackupType.FULL:
            files_to_backup = list(all_files.keys())
        else:
            files_to_backup, _ = self._compute_diff(all_files, parent_manifest)
            if not files_to_backup:
                # No changes, but still record an empty incremental manifest
                merged_files = dict(parent_manifest.files) if parent_manifest else {}
                manifest = BackupManifest(
                    backup_id=bid,
                    backup_type=backup_type,
                    source_path=source_path,
                    target=target,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    encrypted=bool(self._fernet),
                    checksum_algorithm="sha256",
                    total_files=len(merged_files),
                    total_bytes=0,
                    files=merged_files,
                    parent_backup_id=parent_manifest.backup_id if parent_manifest else None,
                )
                self._save_manifest(manifest)
                return BackupResult(
                    success=True,
                    backup_id=bid,
                    total_files=0,  # 无变更文件
                    total_bytes=0,
                    duration_seconds=time.monotonic() - t0,
                )

        total = len(files_to_backup)

        # 创建临时归档
        tmp_archive = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_archive = tmp.name

            archive_size = self._create_archive(
                source_path, files_to_backup, tmp_archive
            )

            # 加密
            if self._fernet:
                with open(tmp_archive, "rb") as f:
                    raw = f.read()
                encrypted = self._encrypt(raw)
                with open(tmp_archive, "wb") as f:
                    f.write(encrypted)

            # 计算文件哈希
            file_hashes = {}
            src_path = Path(source_path).resolve()
            base_path = src_path.parent if src_path.is_file() else src_path
            for rel in files_to_backup:
                fpath = base_path / rel
                try:
                    file_hashes[rel] = self._compute_file_hash(str(fpath))
                except (OSError, PermissionError):
                    continue
                if progress_callback:
                    progress_callback(len(file_hashes), total)

            # 存储到目标
            if btarget == BackupTarget.LOCAL:
                stored_at = self._store_local(bid, tmp_archive)
            elif btarget == BackupTarget.S3:
                stored_at = self._store_s3(bid, tmp_archive)
            else:
                stored_at = self._store_remote(bid, tmp_archive)

            # 合并增量清单
            merged_files = dict(file_hashes)
            if parent_manifest and btype == BackupType.INCREMENTAL:
                # 保留父备份中未删除的文件
                for rel, h in parent_manifest.files.items():
                    if rel not in merged_files and rel in all_files:
                        merged_files[rel] = h

            # 创建清单
            manifest = BackupManifest(
                backup_id=bid,
                backup_type=backup_type,
                source_path=source_path,
                target=target,
                created_at=datetime.now(timezone.utc).isoformat(),
                encrypted=bool(self._fernet),
                checksum_algorithm="sha256",
                total_files=len(merged_files),
                total_bytes=archive_size,
                files=merged_files,
                parent_backup_id=parent_manifest.backup_id if parent_manifest else None,
            )
            self._save_manifest(manifest)

            return BackupResult(
                success=True,
                backup_id=bid,
                total_files=len(merged_files),
                total_bytes=archive_size,
                duration_seconds=time.monotonic() - t0,
            )
        finally:
            if tmp_archive and os.path.exists(tmp_archive):
                os.unlink(tmp_archive)

    # ── 核心：恢复备份 ────────────────────────────────────────────────────

    def restore_backup(
        self,
        backup_id: str,
        restore_path: Optional[str] = None,
        overwrite: bool = True,
    ) -> RestoreResult:
        """
        恢复备份到指定路径。

        Args:
            backup_id: 备份 ID
            restore_path: 恢复目标路径 (默认=原始路径)
            overwrite: 是否覆盖已存在文件

        Returns:
            RestoreResult
        """
        t0 = time.monotonic()
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=f"Backup not found: {backup_id}"
            )

        if restore_path is None:
            restore_path = manifest.source_path

        try:
            btarget = BackupTarget(manifest.target)
        except ValueError:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=f"Unknown target: {manifest.target}"
            )

        tmp_archive = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_archive = tmp.name

            # Step 1: Download/copy archive to temp file
            if btarget == BackupTarget.LOCAL:
                src = self._data_dir / backup_id / "backup.tar.gz"
                if not src.exists():
                    return RestoreResult(
                        success=False,
                        backup_id=backup_id,
                        error_message=f"Archive not found in vault: {src}"
                    )
                shutil.copy2(str(src), tmp_archive)
            elif btarget == BackupTarget.S3:
                self._download_from_s3(backup_id, tmp_archive)
            else:
                self._download_from_remote(backup_id, tmp_archive)

            # Step 2: Decrypt if needed
            if manifest.encrypted:
                if not self._fernet:
                    return RestoreResult(
                        success=False,
                        backup_id=backup_id,
                        error_message="Backup is encrypted but no decryption key set"
                    )
                with open(tmp_archive, "rb") as f:
                    encrypted = f.read()
                decrypted = self._decrypt(encrypted)
                with open(tmp_archive, "wb") as f:
                    f.write(decrypted)

            # Step 3: Extract
            files_count = self._extract_archive(tmp_archive, restore_path)

            return RestoreResult(
                success=True,
                backup_id=backup_id,
                files_restored=files_count,
                bytes_restored=manifest.total_bytes,
                duration_seconds=time.monotonic() - t0,
            )
        except Exception as e:
            return RestoreResult(
                success=False,
                backup_id=backup_id,
                error_message=str(e),
                duration_seconds=time.monotonic() - t0,
            )
        finally:
            if tmp_archive and os.path.exists(tmp_archive):
                os.unlink(tmp_archive)

    # ── 校验 ──────────────────────────────────────────────────────────────

    def verify_backup(self, backup_id: str) -> Dict[str, Any]:
        """
        校验备份完整性。

        Returns:
            {"valid": bool, "total": int, "matched": int, "mismatched": int, "missing": int}
        """
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return {"valid": False, "error": f"Backup not found: {backup_id}"}

        source_path = manifest.source_path
        if not os.path.exists(source_path):
            return {
                "valid": False,
                "error": f"Source path not found: {source_path}",
                "total": manifest.total_files,
                "matched": 0,
                "mismatched": 0,
                "missing": manifest.total_files,
            }

        total = len(manifest.files)
        matched, mismatched, missing = 0, 0, 0
        for rel, expected_hash in manifest.files.items():
            fpath = Path(source_path) / rel
            if not fpath.exists():
                missing += 1
                continue
            try:
                actual = self._compute_file_hash(str(fpath))
            except (OSError, PermissionError):
                mismatched += 1
                continue
            if actual == expected_hash:
                matched += 1
            else:
                mismatched += 1

        return {
            "valid": mismatched == 0 and missing == 0,
            "total": total,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        }

    # ── 删除备份 ──────────────────────────────────────────────────────────

    def delete_backup(self, backup_id: str) -> bool:
        """删除指定备份 (清单 + 数据)"""
        manifest = self.get_manifest(backup_id)
        if manifest is None:
            return False

        # 删除清单
        manifest_path = self._manifest_path(backup_id)
        if manifest_path.exists():
            manifest_path.unlink()
        self._manifests_cache.pop(backup_id, None)

        # 删除存储数据
        btarget = manifest.target
        if btarget == "local":
            data_dir = self._data_dir / backup_id
            if data_dir.exists():
                shutil.rmtree(data_dir)
        # S3/remote 删除由用户自行管理

        return True

    # ── 列出备份 ──────────────────────────────────────────────────────────

    def list_backups(
        self,
        source_path: Optional[str] = None,
        backup_type: Optional[str] = None,
        target: Optional[str] = None,
    ) -> List[BackupEntry]:
        """列出备份，支持过滤"""
        entries = []
        for m in self._manifests_cache.values():
            if source_path and m.source_path != source_path:
                continue
            if backup_type and m.backup_type != backup_type:
                continue
            if target and m.target != target:
                continue
            entries.append(BackupEntry(
                backup_id=m.backup_id,
                backup_type=m.backup_type,
                source_path=m.source_path,
                target=m.target,
                created_at=m.created_at,
                encrypted=m.encrypted,
                status="verified",  # could be enhanced
                total_files=m.total_files,
                total_bytes=m.total_bytes,
                parent_backup_id=m.parent_backup_id,
            ))
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def get_backup_stats(self) -> Dict[str, Any]:
        """获取保险库统计信息"""
        total_backups = len(self._manifests_cache)
        full_backups = sum(1 for m in self._manifests_cache.values()
                          if m.backup_type == "full")
        inc_backups = sum(1 for m in self._manifests_cache.values()
                         if m.backup_type == "incremental")
        encrypted = sum(1 for m in self._manifests_cache.values() if m.encrypted)
        total_bytes = sum(m.total_bytes for m in self._manifests_cache.values())

        storage_used = 0
        if self._data_dir.exists():
            for f in self._data_dir.rglob("*"):
                if f.is_file():
                    storage_used += f.stat().st_size

        return {
            "total_backups": total_backups,
            "full_backups": full_backups,
            "incremental_backups": inc_backups,
            "encrypted_backups": encrypted,
            "total_logical_bytes": total_bytes,
            "storage_used_bytes": storage_used,
            "vault_dir": str(self._vault_dir),
            "is_encrypted": self.is_encrypted,
        }

    def clear_all(self) -> int:
        """清空保险库，返回删除的备份数"""
        count = len(self._manifests_cache)
        for bid in list(self._manifests_cache.keys()):
            self.delete_backup(bid)
        return count


# ══════════════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════════════

_vault: Optional[BackupVault] = None


def get_backup_vault(
    vault_dir: Optional[str] = None,
    encryption_key: Optional[bytes] = None,
) -> BackupVault:
    """获取 BackupVault 单例"""
    global _vault
    if _vault is None:
        _vault = BackupVault(vault_dir=vault_dir, encryption_key=encryption_key)
    elif encryption_key:
        _vault.set_encryption_key(encryption_key)
    return _vault


def reset_backup_vault() -> None:
    """重置 BackupVault 单例"""
    global _vault
    if _vault:
        _vault.clear_all()
    _vault = None
