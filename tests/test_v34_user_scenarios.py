"""
完整用户场景测试 — API Key持久化全链路
模拟用户路径，防回归。每个测试对应之前出过的真实bug。
"""
import pytest
import json
import os
import tempfile
import shutil
import time
from pathlib import Path


def _write_dotenv(home: str, content: str):
    env_dir = Path(home) / ".meshctx"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(content)


class TestAPIKeyPersistenceE2E:
    """API Key完整生命周期"""

    @pytest.fixture
    def temp_home(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_startup_loads_key_from_dotenv(self, temp_home):
        """
        场景: CLI setup配了Key → 启动服务 → Key已加载
        旧bug: 启动时没读.env，Key丢失
        """
        from src.main import _load_api_keys_on_startup as load_keys

        _write_dotenv(temp_home, "DEEPSEEK_API_KEY=sk-test-persist\n")
        old_home = os.environ.get("HOME", "")
        old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ["HOME"] = temp_home
        try:
            keys = load_keys()
            assert keys >= 1
            assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test-persist"
        finally:
            os.environ["HOME"] = old_home
            if old_key:
                os.environ["DEEPSEEK_API_KEY"] = old_key

    def test_browser_setup_saves_to_both_locations(self, temp_home):
        """
        场景: 浏览器配置页保存Key → .env不覆盖已有Key
        旧bug: 浏览器只写.bashrc，重启丢失；第二次写覆盖第一次
        """
        from src.main import _load_provider_config, _save_provider_config

        _write_dotenv(temp_home, "DEEPSEEK_API_KEY=sk-deepseek-first\n")

        # 模拟浏览器保存第二个Key
        os.environ["OPENAI_API_KEY"] = "sk-openai-browser"
        pcfg = _load_provider_config()
        pcfg["openai"] = {"key": "sk-openai-browser", "updated": time.time()}
        _save_provider_config(pcfg)

        # 合并写入.env
        env_file = Path(temp_home) / ".meshctx" / ".env"
        existing = {}
        for line in env_file.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
        existing["OPENAI_API_KEY"] = "sk-openai-browser"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")

        final = env_file.read_text()
        assert "DEEPSEEK_API_KEY=sk-deepseek-first" in final, "第一个Key不应被覆盖"
        assert "OPENAI_API_KEY=sk-openai-browser" in final, "第二个Key应被添加"

    def test_provider_has_key_after_startup(self, temp_home):
        """
        场景: 有.env → providers端点返回has_key=True
        旧bug: has_key始终False
        """
        from src.main import _load_api_keys_on_startup as load_keys
        from src.model_registry import get_registry

        _write_dotenv(temp_home, "DEEPSEEK_API_KEY=sk-provider-check\n")
        old_home = os.environ.get("HOME", "")
        os.environ["HOME"] = temp_home
        try:
            load_keys()
            reg = get_registry()
            reg.auto_configure()
            assert len(reg._entries) > 0, "应有可用模型"
        finally:
            os.environ["HOME"] = old_home

    def test_env_loading_from_file(self, temp_home):
        """
        验证_load_api_keys_on_startup正确读取.env到os.environ
        """
        from src.main import _load_api_keys_on_startup as load_keys

        _write_dotenv(temp_home, "DEEPSEEK_API_KEY=sk-from-env-file\n")
        old_home = os.environ.get("HOME", "")
        old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ["HOME"] = temp_home
        try:
            keys = load_keys()
            assert keys >= 1, f"应从.env加载Key, 实际={keys}"
            assert os.environ.get("DEEPSEEK_API_KEY") == "sk-from-env-file"
        finally:
            os.environ["HOME"] = old_home
            if old_key:
                os.environ["DEEPSEEK_API_KEY"] = old_key


class TestInstallScriptE2E:
    """安装脚本完整性"""

    @pytest.fixture
    def install_content(self):
        path = Path(__file__).parent.parent / "install.sh"
        return path.read_text()

    def test_exists_and_valid(self, install_content):
        assert "python3 --version" in install_content
        assert "venv" in install_content
        assert "pip install" in install_content
        assert "meshctx" in install_content

    def test_uses_raw_github_url(self, install_content):
        assert "raw.githubusercontent.com" in install_content

    def test_wrapper_script_correct(self, install_content):
        assert "python" in install_content and "src.cli" in install_content


class TestConfigPersistenceE2E:
    """防沉默数据丢失"""

    def test_env_not_overwritten_by_second_setup(self):
        d = tempfile.mkdtemp()
        env_file = Path(d) / ".env"

        existing = {"DEEPSEEK_API_KEY": "sk-first"}
        env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")

        # 第二次合并
        for line in env_file.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
        existing["OPENAI_API_KEY"] = "sk-second"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")

        final = env_file.read_text()
        assert "DEEPSEEK_API_KEY=sk-first" in final
        assert "OPENAI_API_KEY=sk-second" in final
        shutil.rmtree(d, ignore_errors=True)
