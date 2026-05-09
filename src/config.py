"""
meshctx 配置加载器
支持 YAML + 环境变量替换 ${VAR_NAME}
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

# 尝试导入 yaml，没有则用 json
try:
    import yaml
    _has_yaml = True
except ImportError:
    _has_yaml = False


def _expand_env(value: Any) -> Any:
    """递归展开 ${ENV_VAR} 环境变量"""
    if isinstance(value, str):
        def replacer(m):
            var = m.group(1)
            return os.environ.get(var, "")
        return re.sub(r'\$\{(\w+)\}', replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载配置文件
    
    查找顺序:
    1. path 参数
    2. MESHCTX_CONFIG 环境变量
    3. ./meshctx.yaml
    4. ~/.meshctx/config.yaml
    5. 内置默认配置
    """
    search_paths = []
    if path:
        search_paths.append(Path(path))
    if os.environ.get("MESHCTX_CONFIG"):
        search_paths.append(Path(os.environ["MESHCTX_CONFIG"]))
    search_paths.append(Path("meshctx.yaml"))
    search_paths.append(Path.home() / ".meshctx" / "config.yaml")
    # 包内默认配置
    search_paths.append(Path(__file__).parent.parent / "meshctx.yaml")

    for p in search_paths:
        if p.exists():
            return _load_file(p)

    # 回退: 硬编码最小配置
    return _default_config()


def _load_file(path: Path) -> Dict[str, Any]:
    """加载并展开配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        if _has_yaml:
            config = yaml.safe_load(f) or {}
        else:
            import json
            config = json.load(f)
    return _expand_env(config)


def _default_config() -> Dict[str, Any]:
    """最小化默认配置"""
    return {
        "kernel": {"worker_count": 4, "log_level": "info"},
        "models": {
            "default": "bailian-free",
            "providers": {
                "bailian-free": {
                    "provider": "bailian",
                    "model": "qwen-turbo-latest",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": os.environ.get("BAILIAN_API_KEY", ""),
                }
            },
        },
        "memory": {"embedding": {"provider": "local", "model": "hash"}},
        "plugins": {"builtin": ["memory", "metacognition", "orchestrator"], "extra": []},
        "gateway": {"enabled": False},
        "skills": {"auto_create": True, "directory": "~/.meshctx/skills/"},
    }


def get_model_config(config: Dict, name: str = None) -> Dict:
    """获取指定模型配置"""
    models = config.get("models", {})
    name = name or models.get("default", "bailian-free")
    return models.get("providers", {}).get(name, {})


def get_skill_dir(config: Dict) -> Path:
    """获取 Skill 目录"""
    raw = config.get("skills", {}).get("directory", "~/.meshctx/skills/")
    return Path(raw).expanduser().resolve()
