"""Backup Vault — 开源版 (stub)"""
class _BackupVault:
    def backup(self, *a, **kw): return True
    def restore(self, *a, **kw): return None

_vault = _BackupVault()
def get_backup_vault(): return _vault
