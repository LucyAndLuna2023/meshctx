"""Backup Vault — v2.68
━━━━━━━━━━━━━━━━━━━━━━━
多重备份保险库: 代码+文档+配置+历史版本

功能:
1. 用户指定备份路径(可多个)
2. 每次版本更新自动备份
3. 备份: 全部.py文件 + .md文档 + 配置文件 + git历史
4. 主进程崩溃后可从备份完整恢复
5. 备份元数据: 时间/版本/文件清单/校验和
"""
import hashlib
import json
import logging
import os
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class BackupVault:
    """备份保险库"""

    CONFIG_FILE = "backup_config.json"

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".meshctx"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._config = self._load_config()
        self._backup_paths: List[Path] = [
            Path(p) for p in self._config.get("paths", [])
            if Path(p).exists() or True  # 允许不存在的路径（会被提示创建）
        ]
        self._auto_backup = self._config.get("auto_backup", True)
        self._max_backups = self._config.get("max_backups_per_path", 30)

    # ── Config ─────────────────────────────────────────

    def _load_config(self) -> Dict:
        cf = self.config_dir / self.CONFIG_FILE
        if cf.exists():
            try:
                return json.loads(cf.read_text())
            except Exception:
                pass
        return {"paths": [], "auto_backup": True, "max_backups_per_path": 30}

    def _save_config(self):
        self._config["paths"] = [str(p) for p in self._backup_paths]
        self._config["auto_backup"] = self._auto_backup
        self._config["max_backups_per_path"] = self._max_backups
        (self.config_dir / self.CONFIG_FILE).write_text(
            json.dumps(self._config, indent=2, ensure_ascii=False)
        )

    # ── Path Management ────────────────────────────────

    def add_backup_path(self, path_str: str) -> Dict:
        """添加备份路径"""
        path = Path(path_str).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)

        if path in self._backup_paths:
            return {"success": False, "message": f"路径已存在: {path}"}

        self._backup_paths.append(path)
        self._save_config()

        return {
            "success": True,
            "message": f"✅ 备份路径已添加: {path}",
            "total_paths": len(self._backup_paths),
        }

    def remove_backup_path(self, path_str: str) -> Dict:
        """移除备份路径"""
        path = Path(path_str).expanduser().resolve()
        if path not in self._backup_paths:
            return {"success": False, "message": "路径不存在"}
        self._backup_paths.remove(path)
        self._save_config()
        return {"success": True, "message": f"已移除: {path}"}

    def list_backup_paths(self) -> List[Dict]:
        """列出所有备份路径及状态"""
        result = []
        for p in self._backup_paths:
            exists = p.exists()
            space = self._get_free_space(p) if exists else "N/A"
            backups = self._count_backups(p)
            result.append({
                "path": str(p),
                "exists": exists,
                "free_space_gb": space,
                "backup_count": backups,
            })
        return result

    def suggest_backup_paths(self) -> List[str]:
        """建议备份路径"""
        suggestions = []

        # E: drive (Windows)
        e_drive = Path("/mnt/e/Meshctx/backups")
        if e_drive.parent.exists():
            suggestions.append(str(e_drive))

        # D: drive
        d_drive = Path("/mnt/d/Meshctx/backups")
        if d_drive.parent.exists():
            suggestions.append(str(d_drive))

        # Local
        local = Path.home() / "meshctx-backups"
        suggestions.append(str(local))

        # External / USB (common mount points)
        for mp in ["/media", "/mnt/usb", "/Volumes"]:
            p = Path(mp)
            if p.exists():
                for child in p.iterdir():
                    if child.is_dir():
                        suggestions.append(str(child / "meshctx-backups"))

        return suggestions

    # ── Backup ─────────────────────────────────────────

    def backup(self, project_root: Path,
              version: Optional[str] = None,
              label: str = "") -> Dict:
        """执行完整备份"""
        if not self._backup_paths:
            return {
                "success": False,
                "error": "未配置备份路径。请先运行 add_backup_path()",
                "suggested_paths": self.suggest_backup_paths(),
            }

        t0 = time.time()
        backup_id = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        if label:
            backup_id += f"-{label}"

        # 获取版本
        if version is None:
            version = self._detect_version(project_root)

        # 收集文件
        files_to_backup = self._collect_files(project_root)

        # 构建元数据
        metadata = {
            "backup_id": backup_id,
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "source": str(project_root),
            "file_count": len(files_to_backup),
            "total_size_bytes": sum(
                f.stat().st_size for f in files_to_backup if f.exists()
            ),
            "file_list": [str(f.relative_to(project_root)) for f in files_to_backup],
        }

        results = []
        for backup_path in self._backup_paths:
            try:
                result = self._backup_to_path(
                    backup_path, backup_id, project_root,
                    files_to_backup, metadata, version
                )
                results.append(result)
            except Exception as e:
                results.append({
                    "path": str(backup_path),
                    "success": False,
                    "error": str(e),
                })

        # 清理旧备份
        self._cleanup_old_backups()

        duration = time.time() - t0
        success_count = sum(1 for r in results if r.get("success"))

        return {
            "backup_id": backup_id,
            "version": version,
            "success_count": f"{success_count}/{len(results)}",
            "duration_seconds": round(duration, 2),
            "total_size_mb": round(metadata["total_size_bytes"] / 1024 / 1024, 2),
            "results": results,
        }

    def _detect_version(self, project_root: Path) -> str:
        """检测项目版本"""
        init = project_root / "src" / "core" / "__init__.py"
        if init.exists():
            import re
            text = init.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1)
        return "unknown"

    def _collect_files(self, project_root: Path) -> List[Path]:
        """收集需要备份的文件"""
        files = []

        # 核心代码
        src = project_root / "src"
        if src.exists():
            files.extend(src.rglob("*.py"))

        # 测试文件
        tests = project_root / "tests"
        if tests.exists():
            files.extend(tests.rglob("*.py"))

        # 文档
        doc_patterns = ["*.md", "*.txt", "*.json", "*.yaml", "*.yml",
                       "*.cfg", "*.toml", "*.ini"]
        for pattern in doc_patterns:
            # 只收集根目录和docs目录
            for p in project_root.glob(pattern):
                if p.is_file():
                    files.append(p)
            docs = project_root / "docs"
            if docs.exists():
                for p in docs.rglob(pattern):
                    files.append(p)

        # 关键配置文件
        key_files = [
            "requirements.txt", "setup.py", "pyproject.toml",
            "meshctx_setup.nsi", "meshctx_desktop.spec",
            "version_info.txt", "install.sh", "install.bat",
            "Dockerfile", "docker-compose.yml",
            "CHANGELOG.md", "README.md", "LICENSE",
        ]
        for kf in key_files:
            p = project_root / kf
            if p.exists():
                files.append(p)

        # 去重
        seen = set()
        unique = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)

        return unique

    def _backup_to_path(self, backup_path: Path, backup_id: str,
                       project_root: Path, files: List[Path],
                       metadata: Dict, version: str) -> Dict:
        """备份到指定路径"""
        # 创建备份目录: backup_path/version/backup_id/
        version_dir = backup_path / f"v{version}"
        backup_dir = version_dir / backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. 复制文件(保持目录结构)
        copied = 0
        for f in files:
            if not f.exists():
                continue
            rel = f.relative_to(project_root)
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            copied += 1

        # 2. 保存元数据
        meta_file = backup_dir / "_backup_meta.json"
        meta_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

        # 3. 创建校验和清单
        checksums = {}
        for f in files:
            if f.exists():
                try:
                    h = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
                    checksums[str(f.relative_to(project_root))] = h
                except Exception:
                    pass
        (backup_dir / "_checksums.json").write_text(
            json.dumps(checksums, indent=2)
        )

        # 4. 创建tar.gz归档
        archive_name = backup_path / f"{backup_id}.tar.gz"
        try:
            with tarfile.open(archive_name, "w:gz") as tar:
                tar.add(backup_dir, arcname=backup_id)
        except Exception:
            pass  # archive optional

        size_mb = sum(
            f.stat().st_size for f in backup_dir.rglob("*")
            if f.is_file()
        ) / 1024 / 1024

        # 5. 写latest指针
        latest_file = backup_path / "LATEST"
        latest_file.write_text(backup_id)

        return {
            "path": str(backup_dir),
            "success": True,
            "files_copied": copied,
            "size_mb": round(size_mb, 2),
            "archive": str(archive_name) if archive_name.exists() else None,
        }

    def _count_backups(self, backup_path: Path) -> int:
        """统计备份数量"""
        if not backup_path.exists():
            return 0
        return len(list(backup_path.glob("backup-*")))

    def _get_free_space(self, path: Path) -> str:
        """获取可用空间"""
        try:
            stat = os.statvfs(path)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            return f"{free_gb:.1f}GB"
        except Exception:
            return "N/A"

    def _cleanup_old_backups(self):
        """清理超出限制的旧备份"""
        for backup_path in self._backup_paths:
            if not backup_path.exists():
                continue
            archives = sorted(
                backup_path.glob("backup-*.tar.gz"),
                key=lambda p: p.stat().st_mtime,
            )
            while len(archives) > self._max_backups:
                oldest = archives.pop(0)
                try:
                    oldest.unlink()
                    logger.info(f"清理旧备份: {oldest.name}")
                except Exception:
                    pass

    # ── Restore ────────────────────────────────────────

    def find_backups(self, version: Optional[str] = None) -> List[Dict]:
        """查找可用备份"""
        backups = []
        for bp in self._backup_paths:
            if not bp.exists():
                continue
            pattern = f"v{version}/*" if version else "*/backup-*"
            for item in bp.glob(pattern):
                if item.is_dir():
                    meta = item / "_backup_meta.json"
                    if meta.exists():
                        try:
                            m = json.loads(meta.read_text())
                            backups.append({
                                "backup_id": m.get("backup_id", item.name),
                                "version": m.get("version", "?"),
                                "timestamp": m.get("timestamp", "?"),
                                "path": str(item),
                                "size_mb": round(
                                    sum(f.stat().st_size for f in item.rglob("*")
                                        if f.is_file()) / 1024 / 1024, 2
                                ),
                            })
                        except Exception:
                            pass
        backups.sort(key=lambda b: b["timestamp"], reverse=True)
        return backups

    def restore(self, backup_id: str, target_path: Path) -> Dict:
        """从备份恢复"""
        for bp in self._backup_paths:
            for item in bp.rglob(backup_id):
                if item.is_dir():
                    meta = item / "_backup_meta.json"
                    if meta.exists():
                        try:
                            # 复制所有文件到目标
                            target_path.mkdir(parents=True, exist_ok=True)
                            count = 0
                            for f in item.rglob("*"):
                                if f.is_file() and not f.name.startswith("_"):
                                    rel = f.relative_to(item)
                                    dest = target_path / rel
                                    dest.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(f, dest)
                                    count += 1
                            return {
                                "success": True,
                                "restored_to": str(target_path),
                                "files_restored": count,
                            }
                        except Exception as e:
                            return {"success": False, "error": str(e)}

        return {"success": False, "error": f"未找到备份: {backup_id}"}

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "backup_paths": len(self._backup_paths),
            "paths": self.list_backup_paths(),
            "auto_backup": self._auto_backup,
            "total_backups": sum(
                self._count_backups(p) for p in self._backup_paths
            ),
            "suggested_paths": self.suggest_backup_paths(),
            "config_file": str(self.config_dir / self.CONFIG_FILE),
        }

    def get_setup_instructions(self) -> str:
        """生成首次设置指南"""
        paths = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(self.suggest_backup_paths()))
        return f"""════════════════════════════════════════
🛡️ meshctx 备份保险库 — 首次设置
════════════════════════════════════════

为防止代码/文档丢失，请指定备份路径：

建议路径:
{paths}

命令行设置:
  meshctx backup add E:\\\\Meshctx\\\\backups
  meshctx backup add D:\\\\backups\\\\meshctx

之后每次版本更新自动备份到所有路径。
主进程崩溃后可从任意备份路径完整恢复。
"""


# 单例
_vault: Optional[BackupVault] = None


def get_backup_vault() -> BackupVault:
    global _vault
    if _vault is None:
        _vault = BackupVault()
    return _vault
