"""v3.106 Backup Vault 备份保险库测试"""
import os
import time
import json
import shutil
import tempfile
import pytest
from pathlib import Path

from src.core.backup_vault import (
    BackupVault,
    BackupType,
    BackupTarget,
    BackupStatus,
    BackupManifest,
    BackupEntry,
    BackupResult,
    RestoreResult,
    get_backup_vault,
    reset_backup_vault,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_vault_dir():
    """Create a temporary vault directory"""
    d = tempfile.mkdtemp(prefix="bv_test_vault_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_source_dir():
    """Create a temporary source directory with sample files"""
    d = tempfile.mkdtemp(prefix="bv_test_src_")
    # Create some files
    for i in range(5):
        path = os.path.join(d, f"file_{i}.txt")
        with open(path, "w") as f:
            f.write(f"Content of file {i}\n" * (i + 1))
    # Create a subdirectory
    sub = os.path.join(d, "subdir")
    os.makedirs(sub, exist_ok=True)
    for i in range(3):
        path = os.path.join(sub, f"sub_{i}.txt")
        with open(path, "w") as f:
            f.write(f"Sub content {i}\n" * 5)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def vault(temp_vault_dir):
    """Create a fresh BackupVault instance"""
    reset_backup_vault()
    return BackupVault(vault_dir=temp_vault_dir)


# ══════════════════════════════════════════════════════════════════════════════
# Test Cases
# ══════════════════════════════════════════════════════════════════════════════

class TestBackupVaultFullLocal:
    """1) 全量本地备份 & 恢复"""

    def test_full_backup_creates_manifest(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert result.success, f"Backup failed: {result.error_message}"
        assert result.backup_id is not None
        assert result.total_files > 0
        assert result.total_bytes > 0
        assert result.duration_seconds >= 0

        # Verify manifest exists
        manifest = vault.get_manifest(result.backup_id)
        assert manifest is not None
        assert manifest.backup_type == "full"
        assert manifest.target == "local"
        assert manifest.source_path == os.path.abspath(temp_source_dir)
        assert manifest.total_files > 0

    def test_full_backup_and_restore(self, vault, temp_source_dir, temp_vault_dir):
        # Create backup
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert result.success

        # Restore to a new location
        restore_dir = os.path.join(temp_vault_dir, "restored")
        restore = vault.restore_backup(result.backup_id, restore_path=restore_dir)
        assert restore.success, f"Restore failed: {restore.error_message}"
        assert restore.files_restored > 0
        assert restore.bytes_restored > 0

        # Verify restored files exist
        for i in range(5):
            path = os.path.join(restore_dir, f"file_{i}.txt")
            assert os.path.exists(path), f"Missing restored file: {path}"
        # Check subdirectory
        assert os.path.exists(os.path.join(restore_dir, "subdir", "sub_0.txt"))

    def test_restore_to_original_path(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert result.success

        # Verify it restores to original path by default (no explicit restore_path)
        restore = vault.restore_backup(result.backup_id)
        # Should succeed (files already exist — extracting over them)
        assert restore.success, f"Restore failed: {restore.error_message}"


class TestBackupVaultIncremental:
    """2) 增量备份测试"""

    def test_incremental_without_parent_does_full(self, vault, temp_source_dir):
        """When no previous backup exists, incremental behaves like full"""
        result = vault.create_backup(temp_source_dir, backup_type="incremental", target="local")
        assert result.success
        assert result.total_files > 0
        manifest = vault.get_manifest(result.backup_id)
        assert manifest.backup_type == "incremental"
        assert manifest.parent_backup_id is None

    def test_incremental_only_backs_up_changes(self, vault, temp_source_dir):
        # First full backup
        r1 = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert r1.success

        # Modify a file
        with open(os.path.join(temp_source_dir, "file_0.txt"), "a") as f:
            f.write("CHANGED CONTENT\n")

        # Add a new file
        with open(os.path.join(temp_source_dir, "new_file.txt"), "w") as f:
            f.write("Brand new file\n")

        # Incremental backup
        r2 = vault.create_backup(temp_source_dir, backup_type="incremental", target="local")
        assert r2.success
        manifest = vault.get_manifest(r2.backup_id)
        assert manifest.parent_backup_id == r1.backup_id
        # Should have all files in the merged manifest
        assert manifest.total_files >= 9  # 5 + 3 + 1 new = 9

    def test_incremental_no_changes_returns_quickly(self, vault, temp_source_dir):
        """When nothing changes, incremental returns 0 files"""
        r1 = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert r1.success

        # Second incremental with no changes
        r2 = vault.create_backup(temp_source_dir, backup_type="incremental", target="local")
        assert r2.success
        # 0 new/changed files → no backup needed
        assert r2.total_files == 0  # Nothing new to backup

    def test_incremental_chain_restore(self, vault, temp_source_dir, temp_vault_dir):
        """Full + incremental chain should restore all files"""
        # Full backup
        r1 = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert r1.success

        # Add a file
        new_path = os.path.join(temp_source_dir, "incremental_file.txt")
        with open(new_path, "w") as f:
            f.write("Added in increment\n")

        # Incremental
        r2 = vault.create_backup(temp_source_dir, backup_type="incremental", target="local")
        assert r2.success

        # Restore full first, then incremental
        restore1 = os.path.join(temp_vault_dir, "restore_full")
        rest = vault.restore_backup(r1.backup_id, restore_path=restore1)
        assert rest.success
        assert os.path.exists(os.path.join(restore1, "file_0.txt"))

        restore2 = os.path.join(temp_vault_dir, "restore_inc")
        # Restore incremental — the manifest merges all files
        rest = vault.restore_backup(r2.backup_id, restore_path=restore2)
        assert rest.success
        assert os.path.exists(os.path.join(restore2, "incremental_file.txt"))


class TestBackupVaultEncryption:
    """3) 加密备份测试"""

    def test_generate_key(self, vault):
        try:
            key = BackupVault.generate_key()
            assert isinstance(key, bytes)
            assert len(key) == 44  # Fernet key is 44 base64 chars
        except RuntimeError:
            pytest.skip("cryptography not installed")

    def test_encrypted_backup_and_restore(self, temp_vault_dir, temp_source_dir):
        try:
            key = BackupVault.generate_key()
            vault = BackupVault(vault_dir=temp_vault_dir, encryption_key=key)
        except RuntimeError:
            pytest.skip("cryptography not installed")

        assert vault.is_encrypted

        # Create encrypted backup
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert result.success
        assert result.backup_id is not None

        # Manifest should indicate encryption
        manifest = vault.get_manifest(result.backup_id)
        assert manifest is not None
        assert manifest.encrypted is True

        # Restore with same key
        restore_dir = os.path.join(temp_vault_dir, "restored_enc")
        restore = vault.restore_backup(result.backup_id, restore_path=restore_dir)
        assert restore.success
        assert os.path.exists(os.path.join(restore_dir, "file_0.txt"))

    def test_cannot_restore_encrypted_without_key(self, temp_vault_dir, temp_source_dir):
        try:
            key = BackupVault.generate_key()
            vault = BackupVault(vault_dir=temp_vault_dir, encryption_key=key)
        except RuntimeError:
            pytest.skip("cryptography not installed")

        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        assert result.success

        # Create a new vault without encryption key
        vault2 = BackupVault(vault_dir=temp_vault_dir)  # same dir, no key
        restore_dir = os.path.join(temp_vault_dir, "should_fail")
        restore = vault2.restore_backup(result.backup_id, restore_path=restore_dir)
        assert not restore.success
        assert "no decryption key" in restore.error_message.lower()


class TestBackupVaultManagement:
    """4) 备份管理 (list/delete/verify/stats)"""

    def test_list_backups(self, vault, temp_source_dir):
        r1 = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        r2 = vault.create_backup(temp_source_dir, backup_type="incremental", target="local")

        all_backups = vault.list_backups()
        assert len(all_backups) >= 2

        # Filter by type
        full_only = vault.list_backups(backup_type="full")
        assert all(b.backup_type == "full" for b in full_only)

        # Filter by source
        src_only = vault.list_backups(source_path=os.path.abspath(temp_source_dir))
        assert len(src_only) >= 2

    def test_delete_backup(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        bid = result.backup_id

        assert vault.get_manifest(bid) is not None
        assert vault.delete_backup(bid) is True
        assert vault.get_manifest(bid) is None

        # Delete again → False
        assert vault.delete_backup(bid) is False

    def test_delete_nonexistent_returns_false(self, vault):
        assert vault.delete_backup("nonexistent_id") is False

    def test_verify_backup_valid(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")
        v = vault.verify_backup(result.backup_id)
        assert v["valid"] is True
        assert v["mismatched"] == 0
        assert v["missing"] == 0

    def test_verify_backup_detects_changes(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")

        # Corrupt a file
        with open(os.path.join(temp_source_dir, "file_0.txt"), "w") as f:
            f.write("CORRUPTED CONTENT")

        v = vault.verify_backup(result.backup_id)
        assert v["valid"] is False
        assert v["mismatched"] >= 1

    def test_verify_backup_missing_source(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="local")

        # Remove source dir
        shutil.rmtree(temp_source_dir)
        v = vault.verify_backup(result.backup_id)
        assert v["valid"] is False
        assert "error" in v or v["missing"] > 0

    def test_get_stats(self, vault, temp_source_dir):
        vault.create_backup(temp_source_dir, backup_type="full", target="local")
        vault.create_backup(temp_source_dir, backup_type="incremental", target="local")

        stats = vault.get_backup_stats()
        assert stats["total_backups"] >= 2
        assert stats["full_backups"] >= 1
        assert stats["incremental_backups"] >= 1
        assert "vault_dir" in stats
        assert isinstance(stats["storage_used_bytes"], int)

    def test_clear_all(self, vault, temp_source_dir):
        vault.create_backup(temp_source_dir, backup_type="full", target="local")
        vault.create_backup(temp_source_dir, backup_type="incremental", target="local")
        assert len(vault.list_backups()) >= 2

        deleted = vault.clear_all()
        assert deleted >= 2
        assert len(vault.list_backups()) == 0


class TestBackupVaultErrors:
    """5) 错误处理测试"""

    def test_invalid_backup_type_returns_error(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="invalid", target="local")
        assert not result.success
        assert "Invalid backup_type" in result.error_message

    def test_invalid_target_returns_error(self, vault, temp_source_dir):
        result = vault.create_backup(temp_source_dir, backup_type="full", target="ftp")
        assert not result.success
        assert "Invalid target" in result.error_message

    def test_nonexistent_source_returns_error(self, vault):
        result = vault.create_backup("/nonexistent/path/12345", backup_type="full")
        assert not result.success
        assert "not found" in result.error_message.lower()

    def test_restore_nonexistent_backup_returns_error(self, vault):
        restore = vault.restore_backup("nonexistent_bv_id", restore_path="/tmp")
        assert not restore.success
        assert "not found" in restore.error_message.lower()

    def test_empty_source_creates_empty_backup(self, vault, temp_vault_dir):
        empty_dir = os.path.join(temp_vault_dir, "empty_src")
        os.makedirs(empty_dir, exist_ok=True)
        result = vault.create_backup(empty_dir, backup_type="full", target="local")
        assert result.success
        assert result.total_files == 0


class TestBackupVaultSingleton:
    """6) 单例模式测试"""

    def test_get_backup_vault_returns_singleton(self, temp_vault_dir):
        reset_backup_vault()
        v1 = get_backup_vault(vault_dir=temp_vault_dir)
        v2 = get_backup_vault()
        assert v1 is v2

    def test_reset_clears_singleton(self, temp_vault_dir):
        reset_backup_vault()
        v1 = get_backup_vault(vault_dir=temp_vault_dir)
        v1.create_backup(temp_vault_dir, backup_type="full")
        assert len(v1.list_backups()) >= 1

        reset_backup_vault()
        v2 = get_backup_vault(vault_dir=temp_vault_dir)
        assert v1 is not v2
        assert len(v2.list_backups()) == 0


class TestBackupVaultSingleFile:
    """7) 单文件备份测试"""

    def test_backup_single_file(self, vault, temp_vault_dir):
        file_path = os.path.join(temp_vault_dir, "solo.txt")
        with open(file_path, "w") as f:
            f.write("Single file backup test\n")

        result = vault.create_backup(file_path, backup_type="full", target="local")
        assert result.success
        assert result.total_files == 1

        manifest = vault.get_manifest(result.backup_id)
        assert manifest.total_files == 1

    def test_restore_single_file(self, vault, temp_vault_dir):
        file_path = os.path.join(temp_vault_dir, "solo.txt")
        with open(file_path, "w") as f:
            f.write("Single file backup test\n")

        result = vault.create_backup(file_path, backup_type="full", target="local")
        restore_dir = os.path.join(temp_vault_dir, "restored_solo")
        restore = vault.restore_backup(result.backup_id, restore_path=restore_dir)
        assert restore.success
        assert os.path.exists(os.path.join(restore_dir, "solo.txt"))


class TestBackupVaultMethodsExist:
    """8) 模块接口完整性测试"""

    def test_all_enums_exist(self):
        assert BackupType.FULL.value == "full"
        assert BackupType.INCREMENTAL.value == "incremental"
        assert BackupTarget.LOCAL.value == "local"
        assert BackupTarget.S3.value == "s3"
        assert BackupTarget.REMOTE.value == "remote"
        assert BackupStatus.PENDING.value == "pending"
        assert BackupStatus.COMPLETED.value == "completed"

    def test_all_dataclasses_constructible(self):
        manifest = BackupManifest(
            backup_id="test_id",
            backup_type="full",
            source_path="/tmp",
            target="local",
            created_at="2026-01-01T00:00:00Z",
            encrypted=False,
            checksum_algorithm="sha256",
        )
        assert manifest.backup_id == "test_id"

        entry = BackupEntry(
            backup_id="test_id",
            backup_type="full",
            source_path="/tmp",
            target="local",
            created_at="2026-01-01T00:00:00Z",
            encrypted=False,
            status="completed",
            total_files=10,
            total_bytes=1000,
        )
        assert entry.total_files == 10

        bresult = BackupResult(success=True, backup_id="bid", total_files=5, total_bytes=500)
        assert bresult.success

        rresult = RestoreResult(success=True, backup_id="bid", files_restored=5)
        assert rresult.files_restored == 5

    def test_all_public_methods_exist(self, vault):
        """Verify all key methods are callable"""
        assert callable(vault.create_backup)
        assert callable(vault.restore_backup)
        assert callable(vault.list_backups)
        assert callable(vault.verify_backup)
        assert callable(vault.delete_backup)
        assert callable(vault.get_backup_stats)
        assert callable(vault.clear_all)
        assert callable(vault.get_manifest)
        assert callable(vault.generate_key)
        assert callable(vault.set_encryption_key)
        assert hasattr(vault, "is_encrypted")
