"""v2.68 Backup Vault — 测试"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def vault(tmp_path):
    from src.core.backup_vault import BackupVault
    v = BackupVault(config_dir=tmp_path)
    return v


@pytest.fixture
def vault_with_path(tmp_path):
    from src.core.backup_vault import BackupVault
    v = BackupVault(config_dir=tmp_path / "config")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    v.add_backup_path(str(backup_dir))
    return v, tmp_path


class TestPathManagement:
    def test_add_path(self, vault, tmp_path):
        bp = tmp_path / "my_backups"
        result = vault.add_backup_path(str(bp))
        assert result["success"] is True
        assert bp.exists()

    def test_add_duplicate(self, vault, tmp_path):
        bp = tmp_path / "dup_backup"
        vault.add_backup_path(str(bp))
        result = vault.add_backup_path(str(bp))
        assert result["success"] is False

    def test_list_paths(self, vault, tmp_path):
        bp = tmp_path / "list_test"
        vault.add_backup_path(str(bp))
        paths = vault.list_backup_paths()
        assert len(paths) >= 1

    def test_remove_path(self, vault, tmp_path):
        bp = tmp_path / "remove_test"
        vault.add_backup_path(str(bp))
        result = vault.remove_backup_path(str(bp))
        assert result["success"] is True
        assert len(vault.list_backup_paths()) == 0

    def test_suggest_paths(self, vault):
        suggestions = vault.suggest_backup_paths()
        assert len(suggestions) >= 1


class TestBackup:
    def test_backup_without_paths(self, vault_with_path):
        """不加路径时的备份提示"""
        from src.core.backup_vault import BackupVault
        v = BackupVault(config_dir=Path("/tmp/nonexistent_vault_test"))
        result = v.backup(Path(__file__).parent.parent)
        assert result["success"] is False
        assert "suggested_paths" in result

    def test_backup_success(self, vault_with_path):
        v, tmp = vault_with_path
        result = v.backup(
            Path(__file__).parent.parent,
            version="2.68.0",
            label="test"
        )
        assert result["success_count"] == "1/1"
        assert "backup_id" in result
        assert result["version"] == "2.68.0"

    def test_backup_creates_files(self, vault_with_path):
        v, tmp = vault_with_path
        v.backup(Path(__file__).parent.parent, version="1.0.0")

        # Check backup exists
        bp = tmp / "backups"
        backups = list(bp.rglob("backup-*"))
        assert len(backups) > 0

    def test_backup_metadata(self, vault_with_path):
        v, tmp = vault_with_path
        v.backup(Path(__file__).parent.parent, version="1.0.0")

        bp = tmp / "backups"
        meta_files = list(bp.rglob("_backup_meta.json"))
        assert len(meta_files) > 0
        meta = json.loads(meta_files[0].read_text())
        assert "version" in meta
        assert "file_count" in meta

    def test_backup_targz(self, vault_with_path):
        v, tmp = vault_with_path
        v.backup(Path(__file__).parent.parent, version="1.0.0")

        bp = tmp / "backups"
        archives = list(bp.glob("backup-*.tar.gz"))
        assert len(archives) > 0


class TestFindRestore:
    def test_find_backups(self, vault_with_path):
        v, tmp = vault_with_path
        v.backup(Path(__file__).parent.parent, version="1.0.0")
        backups = v.find_backups()
        assert len(backups) >= 1

    def test_restore(self, vault_with_path):
        v, tmp = vault_with_path
        r = v.backup(Path(__file__).parent.parent, version="1.0.0")
        bid = r["backup_id"]

        restore_target = tmp / "restored"
        result = v.restore(bid, restore_target)
        assert result["success"] is True
        assert restore_target.exists()


class TestStats:
    def test_stats(self, vault):
        stats = vault.get_stats()
        assert "backup_paths" in stats
        assert "suggested_paths" in stats

    def test_setup_instructions(self, vault):
        instr = vault.get_setup_instructions()
        assert "备份保险库" in instr
        assert "meshctx backup add" in instr


class TestConfigPersistence:
    def test_config_saved(self, tmp_path):
        from src.core.backup_vault import BackupVault
        cfg_dir = tmp_path / "cfg"
        v1 = BackupVault(config_dir=cfg_dir)
        v1.add_backup_path(str(tmp_path / "p1"))

        v2 = BackupVault(config_dir=cfg_dir)
        paths = v2.list_backup_paths()
        assert len(paths) == 1
