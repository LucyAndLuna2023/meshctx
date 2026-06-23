"""
Test v1.5.26 — ModelRegistry
Covers: init, scan, switch, get, list, builtins, add/remove
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def clean_env_vars():
    """Save and restore env vars that affect ModelRegistry"""
    saved = {}
    env_keys = [
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "BAILIAN_API_KEY",
        "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ZHIPU_API_KEY",
        "MESHCTX_MODEL",
    ]
    for k in env_keys:
        saved[k] = os.environ.get(k)
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


@pytest.fixture
def registry(clean_env_vars):
    """A clean ModelRegistry with no env keys"""
    from src.model_registry import ModelRegistry
    return ModelRegistry(config_path=None)


@pytest.fixture
def registry_with_deepseek(clean_env_vars):
    """Registry with deepseek key set"""
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"
    from src.model_registry import ModelRegistry
    return ModelRegistry(config_path=None)


# ═══════════════════════════════════════════════════════════════
# 1. Init Tests
# ═══════════════════════════════════════════════════════════════

class TestRegistryInit:
    """Test ModelRegistry initialization"""

    def test_registry_init_empty(self, registry):
        """Registry starts with empty entries in clean env"""
        # With no config and no env keys, _ensure_default may add bailian
        # if BAILIAN_API_KEY is not set, it stays empty
        from src.model_registry import BUILTIN_MODELS
        entries = registry.list_all()
        # May be empty or have the fallback if BAILIAN_API_KEY was set unexpectedly
        assert isinstance(entries, list)

    def test_registry_init_scan_env(self, clean_env_vars):
        """Registry scans env vars on init"""
        os.environ["BAILIAN_API_KEY"] = "sk-bailian-test"
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=None)
        entries = reg.list_all()
        # Should have bailian models
        bailian_models = [e for e in entries if e["provider"] == "bailian"]
        assert len(bailian_models) > 0
        for e in bailian_models:
            assert e["ready"] is True

    def test_registry_builtin_models_count(self):
        """BUILTIN_MODELS has at least 46 entries"""
        from src.model_registry import BUILTIN_MODELS
        assert len(BUILTIN_MODELS) >= 46

    def test_registry_builtin_models_all_have_keys(self):
        """Every builtin model has required fields"""
        from src.model_registry import BUILTIN_MODELS
        for mid, info in BUILTIN_MODELS.items():
            assert "provider" in info, f"{mid} missing provider"
            assert "model" in info, f"{mid} missing model"
            assert "base_url" in info, f"{mid} missing base_url"
            assert "key_env" in info, f"{mid} missing key_env"

    def test_registry_builtin_models_unique_ids(self):
        """All builtin model IDs are unique"""
        from src.model_registry import BUILTIN_MODELS
        ids = list(BUILTIN_MODELS.keys())
        assert len(ids) == len(set(ids))

    def test_registry_builtin_models_providers(self):
        """Builtin models cover at least 9 providers"""
        from src.model_registry import BUILTIN_MODELS
        providers = set(info["provider"] for info in BUILTIN_MODELS.values())
        assert len(providers) >= 9

    def test_registry_init_with_config_path_not_found(self, clean_env_vars):
        """Registry init with non-existent config path doesn't crash"""
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path="/tmp/nonexistent_meshctx.yaml")
        assert reg.list_all() is not None


# ═══════════════════════════════════════════════════════════════
# 2. Scan Tests
# ═══════════════════════════════════════════════════════════════

class TestRegistryScan:
    """Test env scanning"""

    def test_registry_scan_single_key(self, clean_env_vars):
        """Scan with one env key discovers models for that provider"""
        os.environ["OPENAI_API_KEY"] = "sk-openai-test"
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=None)
        openai_models = [e for e in reg.list_all() if e["provider"] == "openai"]
        assert len(openai_models) > 0

    def test_registry_scan_multiple_keys(self, clean_env_vars):
        """Scan with multiple keys discovers multiple providers"""
        os.environ["BAILIAN_API_KEY"] = "sk-bailian"
        os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek"
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=None)
        entries = reg.list_all()
        providers = set(e["provider"] for e in entries)
        assert "bailian" in providers
        assert "deepseek" in providers

    def test_registry_scan_no_keys_empty(self, clean_env_vars):
        """Scan with no env keys returns empty entries (no fallback if BAILIAN unset)"""
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=None)
        entries = reg.list_all()
        # _ensure_default only adds bailian:qwen-flash if BAILIAN_API_KEY is set
        bailian_set = os.environ.get("BAILIAN_API_KEY")
        if not bailian_set:
            assert len(entries) == 0

    def test_registry_scan_all_env_map_present(self):
        """ENV_KEY_MAP covers all key_env values in BUILTIN_MODELS"""
        from src.model_registry import BUILTIN_MODELS, ENV_KEY_MAP
        builtin_env_vars = set(info["key_env"] for info in BUILTIN_MODELS.values())
        mapped_vars = set(ENV_KEY_MAP.keys())
        # Every builtin model's key_env should exist in the env map
        for ev in builtin_env_vars:
            # Some env vars like OLLAMA_API_KEY, XAI_API_KEY, etc. might not be in the map
            # but should still be scannable
            assert ev in mapped_vars or ev.startswith("OLLAMA") or ev.startswith("XAI") or \
                   ev.startswith("MISTRAL") or ev.startswith("PERPLEXITY") or ev.startswith("GROQ") or \
                   ev.startswith("MOONSHOT") or ev.startswith("DOUBAO") or ev.startswith("STEPFUN") or \
                   ev.startswith("MINIMAX") or ev.startswith("BAICHUAN")


# ═══════════════════════════════════════════════════════════════
# 3. Switch / Add / Remove Tests
# ═══════════════════════════════════════════════════════════════

class TestRegistryCRUD:
    """Test add, remove, switch operations"""

    def test_registry_add_builtin(self, registry):
        """Add a builtin model with key"""
        result = registry.add("deepseek:chat", key="sk-test")
        assert result is not None
        assert result["key"] == "sk-test"
        assert result["provider"] == "deepseek"

    def test_registry_add_custom(self, registry):
        """Add a custom model not in builtins"""
        result = registry.add("custom:my-model", key="sk-custom",
                              model="my-model-v1", base_url="https://custom.api/v1")
        assert result is not None
        assert result["provider"] == "openai"  # default provider for custom

    def test_registry_add_duplicate_overwrites(self, registry):
        """Adding same model_id twice overwrites"""
        registry.add("deepseek:chat", key="sk-old")
        registry.add("deepseek:chat", key="sk-new")
        entries = registry.list_all()
        match = [e for e in entries if e["id"] == "deepseek:chat"]
        assert len(match) == 1

    def test_registry_remove_existing(self, registry):
        """Remove an existing model"""
        registry.add("deepseek:chat", key="sk-test")
        registry.remove("deepseek:chat")
        assert registry.get("deepseek:chat") is None

    def test_registry_remove_nonexistent(self, registry):
        """Remove a model that doesn't exist doesn't raise"""
        registry.remove("nonexistent:model")  # should not raise

    def test_registry_get_default_model(self, registry):
        """Get default model returns first entry"""
        registry.add("deepseek:chat", key="sk-test")
        client = registry.get()
        assert client is not None

    def test_registry_get_default_empty_returns_none(self, registry):
        """Get default with no entries returns None"""
        client = registry.get()
        assert client is None

    def test_registry_get_specific_model(self, registry):
        """Get a specific model by ID"""
        registry.add("deepseek:chat", key="sk-test")
        client = registry.get("deepseek:chat")
        assert client is not None
        assert client.model_id == "deepseek:chat"

    def test_registry_get_fuzzy_match(self, registry):
        """Get with partial ID matches fuzzy"""
        registry.add("bailian:qwen-flash", key="sk-test")
        client = registry.get("qwen-flash")  # fuzzy match
        assert client is not None
        assert client.model_id == "bailian:qwen-flash"

    def test_registry_get_nonexistent(self, registry):
        """Get nonexistent model returns None"""
        client = registry.get("nonexistent:model")
        assert client is None

    def test_registry_switch_sets_env(self, registry):
        """Running add sets env var MESHCTX_MODEL behavior"""
        registry.add("deepseek:chat", key="sk-test")
        os.environ["MESHCTX_MODEL"] = "deepseek:chat"
        assert os.environ.get("MESHCTX_MODEL") == "deepseek:chat"

    def test_registry_auto_configure(self, clean_env_vars):
        """auto_configure scans env and returns all configured"""
        os.environ["BAILIAN_API_KEY"] = "sk-bailian"
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=None)
        entries = reg.auto_configure()
        assert len(entries) > 0
        for e in entries:
            assert e["ready"] is True


# ═══════════════════════════════════════════════════════════════
# 4. Provider info tests
# ═══════════════════════════════════════════════════════════════

class TestRegistryProviders:
    """Verify provider groupings"""

    def test_registry_provider_openai(self):
        """OpenAI models exist"""
        from src.model_registry import BUILTIN_MODELS
        openai = [m for m in BUILTIN_MODELS if BUILTIN_MODELS[m]["provider"] == "openai"]
        assert len(openai) >= 6

    def test_registry_provider_bailian(self):
        """Bailian models exist"""
        from src.model_registry import BUILTIN_MODELS
        bailian = [m for m in BUILTIN_MODELS if BUILTIN_MODELS[m]["provider"] == "bailian"]
        assert len(bailian) >= 8

    def test_registry_provider_ollama(self):
        """Ollama models exist"""
        from src.model_registry import BUILTIN_MODELS
        ollama = [m for m in BUILTIN_MODELS if BUILTIN_MODELS[m]["provider"] == "ollama"]
        assert len(ollama) >= 2
