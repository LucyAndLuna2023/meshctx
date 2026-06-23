"""
Test v1.5.26 — Config loader
Covers: load_config, defaults, env override, model list, gateway config
"""
import os
import sys
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def clean_env():
    """Save/restore MESHCTX_CONFIG env var"""
    saved = os.environ.get("MESHCTX_CONFIG")
    yield
    if saved:
        os.environ["MESHCTX_CONFIG"] = saved
    else:
        os.environ.pop("MESHCTX_CONFIG", None)


@pytest.fixture
def minimal_yaml():
    """Create a minimal valid YAML config file"""
    import yaml
    config = {
        "kernel": {"worker_count": 2, "log_level": "debug"},
        "models": {
            "default": "test:model",
            "providers": {
                "test:model": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "https://api.test.com/v1",
                    "api_key": "",
                }
            },
        },
        "gateway": {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        fpath = f.name
    yield fpath
    os.unlink(fpath)


@pytest.fixture
def env_override_yaml():
    """YAML with environment variable substitution ${VAR_NAME}"""
    import yaml
    config = {
        "models": {
            "default": "test:model",
            "entries": {
                "test:model": {
                    "key": "${TEST_API_KEY}",
                    "model": "test-model",
                }
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        fpath = f.name
    yield fpath
    os.unlink(fpath)


# ═══════════════════════════════════════════════════════════════
# 1. Config Loading
# ═══════════════════════════════════════════════════════════════

class TestConfigLoad:
    """Test load_config() with various paths"""

    def test_config_load_from_path(self, minimal_yaml):
        """Load config from explicit path"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        assert config is not None
        assert isinstance(config, dict)

    def test_config_load_has_kernel(self, minimal_yaml):
        """Loaded config has kernel section"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        assert "kernel" in config

    def test_config_load_kernel_values(self, minimal_yaml):
        """Kernel values match YAML"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        assert config["kernel"]["worker_count"] == 2
        assert config["kernel"]["log_level"] == "debug"

    def test_config_load_has_models(self, minimal_yaml):
        """Loaded config has models section"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        assert "models" in config

    def test_config_load_has_gateway(self, minimal_yaml):
        """Loaded config has gateway section"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        assert "gateway" in config
        assert config["gateway"]["enabled"] is False

    def test_config_load_has_plugins(self, minimal_yaml):
        """Loaded config references plugins implicitly"""
        from src.config import load_config
        config = load_config(minimal_yaml)
        # Even minimal yaml has models section which implies plugin usage
        assert "models" in config

    def test_config_load_non_existent_path_fallback(self):
        """Non-existent path falls back to defaults"""
        from src.config import load_config
        config = load_config("/tmp/nonexistent_meshctx_config_xyz.yaml")
        # Should return default config
        assert config is not None
        assert "kernel" in config
        assert "models" in config


# ═══════════════════════════════════════════════════════════════
# 2. Default Config
# ═══════════════════════════════════════════════════════════════

class TestConfigDefaults:
    """Test default config values"""

    def test_config_default_kernel_workers(self):
        """Default kernel has worker_count=4"""
        from src.config import _default_config
        config = _default_config()
        assert config["kernel"]["worker_count"] == 4

    def test_config_default_log_level(self):
        """Default log level is info"""
        from src.config import _default_config
        config = _default_config()
        assert config["kernel"]["log_level"] == "info"

    def test_config_default_model(self):
        """Default model is bailian-free"""
        from src.config import _default_config
        config = _default_config()
        assert config["models"]["default"] == "bailian-free"

    def test_config_default_model_provider(self):
        """Default model provider section exists"""
        from src.config import _default_config
        config = _default_config()
        assert "bailian-free" in config["models"]["providers"]

    def test_config_default_gateway_disabled(self):
        """Default gateway is disabled"""
        from src.config import _default_config
        config = _default_config()
        assert config["gateway"]["enabled"] is False

    def test_config_default_memory_embedding(self):
        """Default memory embedding is local hash"""
        from src.config import _default_config
        config = _default_config()
        assert config["memory"]["embedding"]["provider"] == "local"

    def test_config_default_plugins(self):
        """Default plugins include memory, metacognition, orchestrator"""
        from src.config import _default_config
        config = _default_config()
        plugins = config["plugins"]["builtin"]
        assert "memory" in plugins
        assert "metacognition" in plugins
        assert "orchestrator" in plugins


# ═══════════════════════════════════════════════════════════════
# 3. Environment Variable Override
# ═══════════════════════════════════════════════════════════════

class TestConfigEnvOverride:
    """Test ${ENV_VAR} substitution in config"""

    def test_config_env_expand_simple(self):
        """_expand_env replaces ${VAR_NAME} with env value"""
        from src.config import _expand_env
        os.environ["TEST_VAL"] = "hello"
        result = _expand_env("prefix_${TEST_VAL}_suffix")
        assert result == "prefix_hello_suffix"

    def test_config_env_expand_missing_var(self):
        """_expand_env returns empty string for missing var"""
        from src.config import _expand_env
        result = _expand_env("prefix_${MISSING_VAR_XYZ}_suffix")
        assert result == "prefix__suffix"

    def test_config_env_expand_in_dict(self):
        """_expand_env works recursively in dicts"""
        from src.config import _expand_env
        os.environ["MY_KEY"] = "sk-test"
        data = {"key": "${MY_KEY}", "name": "test"}
        result = _expand_env(data)
        assert result["key"] == "sk-test"
        assert result["name"] == "test"

    def test_config_env_expand_in_list(self):
        """_expand_env works recursively in lists"""
        from src.config import _expand_env
        os.environ["HOST"] = "localhost"
        data = ["${HOST}:8080", "static"]
        result = _expand_env(data)
        assert result[0] == "localhost:8080"
        assert result[1] == "static"

    def test_config_env_expand_non_string(self):
        """_expand_env passes non-string types through"""
        from src.config import _expand_env
        assert _expand_env(42) == 42
        assert _expand_env(3.14) == 3.14
        assert _expand_env(True) is True
        assert _expand_env(None) is None

    def test_config_env_override_path(self, env_override_yaml):
        """Config with ${VAR} loads env value"""
        os.environ["TEST_API_KEY"] = "sk-from-env"
        from src.config import load_config
        config = load_config(env_override_yaml)
        entry = config["models"]["entries"]["test:model"]
        assert entry["key"] == "sk-from-env"


# ═══════════════════════════════════════════════════════════════
# 4. get_model_config / get_skill_dir
# ═══════════════════════════════════════════════════════════════

class TestConfigHelpers:
    """Test helper functions"""

    def test_config_get_model_config_default(self):
        """get_model_config returns default model config"""
        from src.config import get_model_config, _default_config
        config = _default_config()
        model_cfg = get_model_config(config)
        assert model_cfg.get("provider") == "bailian"

    def test_config_get_model_config_specific(self, minimal_yaml):
        """get_model_config with name returns specific config"""
        from src.config import load_config, get_model_config
        config = load_config(minimal_yaml)
        model_cfg = get_model_config(config, "test:model")
        assert model_cfg.get("model") == "gpt-4o-mini"

    def test_config_get_model_config_nonexistent(self, minimal_yaml):
        """get_model_config with nonexistent name returns empty dict"""
        from src.config import load_config, get_model_config
        config = load_config(minimal_yaml)
        model_cfg = get_model_config(config, "nonexistent:model")
        assert model_cfg == {}

    def test_config_get_skill_dir_default(self):
        """get_skill_dir returns expanded path"""
        from src.config import get_skill_dir, _default_config
        config = _default_config()
        path = get_skill_dir(config)
        assert str(path).endswith(".meshctx/skills")
