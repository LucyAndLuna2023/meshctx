"""Tests for Credential Pool — v2.37"""
import pytest
from pathlib import Path
import tempfile
import os
from src.core.credential_pool import (
    PooledKey, PoolConfig, CredentialPoolManager,
    get_credential_pool, reset_credential_pool,
)


class TestPooledKey:
    def test_create_key(self):
        k = PooledKey(key="sk-test123", provider="deepseek")
        assert k.key == "sk-test123"
        assert k.provider == "deepseek"
        assert k.status == "active"
        assert k.call_count == 0

    def test_to_dict_and_back(self):
        k = PooledKey(key="sk-abc", provider="openai", label="prod")
        d = k.to_dict()
        k2 = PooledKey.from_dict(d)
        assert k2.key == "sk-abc"
        assert k2.provider == "openai"
        assert k2.label == "prod"

    def test_from_dict_defaults(self):
        k = PooledKey.from_dict({"key": "sk-x", "provider": "test"})
        assert k.status == "active"
        assert k.call_count == 0


class TestPoolConfig:
    def test_create_config(self):
        cfg = PoolConfig(provider="deepseek")
        assert cfg.provider == "deepseek"
        assert cfg.strategy == "round_robin"
        assert cfg.keys == []

    def test_to_dict_and_back(self):
        cfg = PoolConfig(provider="openai", strategy="least_used")
        cfg.keys.append(PooledKey(key="sk-a", provider="openai"))
        d = cfg.to_dict()
        cfg2 = PoolConfig.from_dict(d)
        assert cfg2.provider == "openai"
        assert cfg2.strategy == "least_used"
        assert len(cfg2.keys) == 1


class TestCredentialPoolBasics:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.pool_file = Path(self.tmp) / "test_pools.json"
        self.mgr = CredentialPoolManager(pool_file=str(self.pool_file))

    def test_init_empty(self):
        assert self.mgr.list_providers() == []

    def test_ensure_pool(self):
        pool = self.mgr.ensure_pool("deepseek")
        assert pool.provider == "deepseek"
        assert "deepseek" in self.mgr.list_providers()

    def test_add_key(self):
        pk = self.mgr.add_key("deepseek", "sk-abc123", "prod")
        assert pk.key == "sk-abc123"
        assert pk.label == "prod"
        keys = self.mgr.list_keys("deepseek")
        assert len(keys) == 1

    def test_add_duplicate_key_ignored(self):
        self.mgr.add_key("deepseek", "sk-same")
        self.mgr.add_key("deepseek", "sk-same")
        assert len(self.mgr.list_keys("deepseek")) == 1

    def test_remove_key(self):
        self.mgr.add_key("openai", "sk-1")
        self.mgr.add_key("openai", "sk-2")
        assert self.mgr.remove_key("openai", 0)
        keys = self.mgr.list_keys("openai")
        assert len(keys) == 1
        assert keys[0]["key"] == "sk-2"

    def test_remove_last_key_clears_pool(self):
        self.mgr.add_key("test", "sk-only")
        self.mgr.remove_key("test", 0)
        assert "test" not in self.mgr.list_providers()

    def test_remove_invalid_index(self):
        self.mgr.add_key("test", "sk-1")
        assert not self.mgr.remove_key("test", 99)
        assert not self.mgr.remove_key("nonexistent", 0)


class TestKeyRotation:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.pool_file = Path(self.tmp) / "test_pools.json"
        self.mgr = CredentialPoolManager(pool_file=str(self.pool_file))

    def test_get_key_round_robin(self):
        self.mgr.add_key("test", "sk-a")
        self.mgr.add_key("test", "sk-b")
        self.mgr.add_key("test", "sk-c")

        k1 = self.mgr.get_key("test")
        k2 = self.mgr.get_key("test")
        k3 = self.mgr.get_key("test")
        k4 = self.mgr.get_key("test")  # wraps around

        assert k1 == "sk-a"
        assert k2 == "sk-b"
        assert k3 == "sk-c"
        assert k4 == "sk-a"

    def test_get_key_least_used(self):
        self.mgr.add_key("test", "sk-a")
        self.mgr.add_key("test", "sk-b")
        self.mgr.set_strategy("test", "least_used")

        # Use sk-a once
        self.mgr.get_key("test")
        # Now sk-b should be preferred (0 calls vs 1)
        k2 = self.mgr.get_key("test")
        assert k2 == "sk-b"

    def test_get_key_random(self):
        self.mgr.add_key("test", "sk-x")
        self.mgr.set_strategy("test", "random")
        k = self.mgr.get_key("test")
        assert k == "sk-x"  # only one key

    def test_get_key_no_pool(self):
        assert self.mgr.get_key("nonexistent") is None

    def test_exhausted_key_skipped(self):
        self.mgr.add_key("test", "sk-a")
        self.mgr.add_key("test", "sk-b")
        self.mgr.mark_exhausted("test", "sk-a", "rate limited")
        # Should skip sk-a, return sk-b
        k = self.mgr.get_key("test")
        assert k == "sk-b"

    def test_all_exhausted_returns_none(self):
        self.mgr.add_key("test", "sk-a")
        self.mgr.mark_exhausted("test", "sk-a")
        assert self.mgr.get_key("test") is None

    def test_exhausted_key_recovers_after_cooldown(self):
        self.mgr.add_key("test", "sk-a")
        self.mgr.mark_exhausted("test", "sk-a", "429")
        import time
        # Artificially set exhausted_at to long ago
        pool = self.mgr.pools["test"]
        pool.keys[0].exhausted_at = time.time() - 1000
        pool.cooldown_seconds = 300
        k = self.mgr.get_key("test")
        assert k == "sk-a"


class TestKeyStatusManagement:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.pool_file = Path(self.tmp) / "test_pools.json"
        self.mgr = CredentialPoolManager(pool_file=str(self.pool_file))

    def test_mark_exhausted(self):
        self.mgr.add_key("test", "sk-key")
        assert self.mgr.mark_exhausted("test", "sk-key", "429")
        keys = self.mgr.list_keys("test")
        assert keys[0]["status"] == "exhausted"

    def test_mark_revoked(self):
        self.mgr.add_key("test", "sk-key")
        self.mgr.mark_revoked("test", "sk-key")
        keys = self.mgr.list_keys("test")
        assert keys[0]["status"] == "revoked"

    def test_reset_key(self):
        self.mgr.add_key("test", "sk-key")
        self.mgr.mark_exhausted("test", "sk-key")
        assert self.mgr.reset_key("test", 0)
        keys = self.mgr.list_keys("test")
        assert keys[0]["status"] == "active"

    def test_reset_provider(self):
        self.mgr.add_key("test", "sk-1")
        self.mgr.add_key("test", "sk-2")
        self.mgr.mark_exhausted("test", "sk-1")
        self.mgr.mark_exhausted("test", "sk-2")
        assert self.mgr.reset_provider("test") == 2
        for k in self.mgr.list_keys("test"):
            assert k["status"] == "active"

    def test_set_strategy_invalid(self):
        assert not self.mgr.set_strategy("test", "invalid_strategy")

    def test_set_strategy_valid(self):
        self.mgr.ensure_pool("test")
        assert self.mgr.set_strategy("test", "random")
        assert self.mgr.pools["test"].strategy == "random"


class TestPersistence:
    def test_save_and_reload(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        pool_file = Path(tmp) / "pools.json"

        mgr1 = CredentialPoolManager(pool_file=str(pool_file))
        mgr1.add_key("deepseek", "sk-ds1", "primary")
        mgr1.add_key("deepseek", "sk-ds2", "backup")
        mgr1.add_key("openai", "sk-oa1")
        mgr1.set_strategy("deepseek", "least_used")

        # Reload
        mgr2 = CredentialPoolManager(pool_file=str(pool_file))
        assert "deepseek" in mgr2.list_providers()
        assert "openai" in mgr2.list_providers()
        keys = mgr2.list_keys("deepseek")
        assert len(keys) == 2
        assert mgr2.pools["deepseek"].strategy == "least_used"

    def test_empty_persistence_no_crash(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        pool_file = Path(tmp) / "nonexistent.json"
        mgr = CredentialPoolManager(pool_file=str(pool_file))
        assert mgr.list_providers() == []


class TestStats:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.pool_file = Path(self.tmp) / "test_pools.json"
        self.mgr = CredentialPoolManager(pool_file=str(self.pool_file))

    def test_stats_empty(self):
        stats = self.mgr.get_stats()
        assert stats["total_pools"] == 0
        assert stats["total_keys"] == 0

    def test_stats_with_data(self):
        self.mgr.add_key("deepseek", "sk-ds1")
        self.mgr.add_key("deepseek", "sk-ds2")
        self.mgr.add_key("openai", "sk-oa1")
        self.mgr.mark_exhausted("deepseek", "sk-ds2")

        stats = self.mgr.get_stats()
        assert stats["total_pools"] == 2
        assert stats["total_keys"] == 3
        assert stats["active_keys"] == 2
        assert stats["exhausted_keys"] == 1


class TestSingleton:
    def test_singleton_same_instance(self):
        reset_credential_pool()
        p1 = get_credential_pool()
        p2 = get_credential_pool()
        assert p1 is p2

    def test_reset_creates_new(self):
        reset_credential_pool()
        p1 = get_credential_pool()
        reset_credential_pool()
        p2 = get_credential_pool()
        assert p1 is not p2


class TestClearAll:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.pool_file = Path(self.tmp) / "test_pools.json"
        self.mgr = CredentialPoolManager(pool_file=str(self.pool_file))

    def test_clear_all(self):
        self.mgr.add_key("a", "k1")
        self.mgr.add_key("b", "k2")
        self.mgr.clear_all()
        assert self.mgr.list_providers() == []
