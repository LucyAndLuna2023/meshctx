"""Config Migration Tool — v3.02"""
import json, logging, shutil, time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class ConfigMigrator:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".meshctx"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._migrations: List[Dict] = []

    def migrate(self, from_version: str, to_version: str) -> Dict:
        backup_path = self.config_dir / f"config_backup_{from_version}.json"
        current = self.config_dir / "config.json"
        if current.exists():
            shutil.copy2(current, backup_path)
        
        migration = {
            "from": from_version, "to": to_version,
            "timestamp": time.time(), "backup": str(backup_path),
            "changes": ["配置已备份", f"版本 {from_version}→{to_version}"],
        }
        self._migrations.append(migration)
        
        # 更新版本记录
        ver_file = self.config_dir / ".version"
        ver_file.write_text(to_version)
        
        return {"success": True, "migration": migration}

    def rollback(self, to_version: str) -> Dict:
        backup = self.config_dir / f"config_backup_{to_version}.json"
        if backup.exists():
            shutil.copy2(backup, self.config_dir / "config.json")
            return {"success": True, "rolled_back_to": to_version}
        return {"success": False, "error": "备份不存在"}

    def list_migrations(self) -> List[Dict]: return self._migrations
    def get_stats(self) -> Dict:
        return {"migrations": len(self._migrations), "config_dir": str(self.config_dir),
                "latest": self._migrations[-1] if self._migrations else None}

_migrator: Optional[ConfigMigrator] = None
def get_config_migrator() -> ConfigMigrator:
    global _migrator
    if _migrator is None: _migrator = ConfigMigrator()
    return _migrator
