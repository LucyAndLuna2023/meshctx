"""
meshctx 极简模型系统
和 OpenClaw / Hermes 一样简单

用法:
    meshctx model add deepseek deepseek-chat --key sk-xxx
    meshctx model use qwen-flash
    meshctx model list
    meshctx model test "你好"
"""
import os
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# ═══════════════════════════════════════════════════
# 内置模型目录 — 30+ 模型，零配置可用
# ═══════════════════════════════════════════════════

BUILTIN_MODELS = {
    # ── OpenAI ────────────────────────────────────────
    "openai:gpt-4o":           {"provider":"openai","base_url":"https://api.openai.com/v1","model":"gpt-4o","key_env":"OPENAI_API_KEY"},
    "openai:gpt-4o-mini":      {"provider":"openai","base_url":"https://api.openai.com/v1","model":"gpt-4o-mini","key_env":"OPENAI_API_KEY"},
    "openai:gpt-4.1":          {"provider":"openai","base_url":"https://api.openai.com/v1","model":"gpt-4.1","key_env":"OPENAI_API_KEY"},
    "openai:gpt-4.1-mini":     {"provider":"openai","base_url":"https://api.openai.com/v1","model":"gpt-4.1-mini","key_env":"OPENAI_API_KEY"},
    "openai:gpt-4.1-nano":     {"provider":"openai","base_url":"https://api.openai.com/v1","model":"gpt-4.1-nano","key_env":"OPENAI_API_KEY"},
    "openai:o4-mini":          {"provider":"openai","base_url":"https://api.openai.com/v1","model":"o4-mini","key_env":"OPENAI_API_KEY"},
    "openai:o3":               {"provider":"openai","base_url":"https://api.openai.com/v1","model":"o3","key_env":"OPENAI_API_KEY"},
    "openai:o3-mini":          {"provider":"openai","base_url":"https://api.openai.com/v1","model":"o3-mini","key_env":"OPENAI_API_KEY"},
    # ── Anthropic ─────────────────────────────────────
    "anthropic:claude-opus":   {"provider":"anthropic","base_url":"https://api.anthropic.com/v1","model":"claude-opus-4-20250514","key_env":"ANTHROPIC_API_KEY"},
    "anthropic:claude-sonnet": {"provider":"anthropic","base_url":"https://api.anthropic.com/v1","model":"claude-sonnet-4-20250514","key_env":"ANTHROPIC_API_KEY"},
    "anthropic:claude-haiku":  {"provider":"anthropic","base_url":"https://api.anthropic.com/v1","model":"claude-3.5-haiku","key_env":"ANTHROPIC_API_KEY"},
    # ── Google ────────────────────────────────────────
    "google:gemini-pro":       {"provider":"google","base_url":"https://generativelanguage.googleapis.com/v1beta/openai","model":"gemini-2.5-pro","key_env":"GEMINI_API_KEY"},
    "google:gemini-flash":     {"provider":"google","base_url":"https://generativelanguage.googleapis.com/v1beta/openai","model":"gemini-2.5-flash","key_env":"GEMINI_API_KEY"},
    # ── DeepSeek ──────────────────────────────────────
    "deepseek:v4-pro":         {"provider":"deepseek","base_url":"https://api.deepseek.com","model":"deepseek-v4-pro","key_env":"DEEPSEEK_API_KEY"},
    "deepseek:v4-flash":       {"provider":"deepseek","base_url":"https://api.deepseek.com","model":"deepseek-v4-flash","key_env":"DEEPSEEK_API_KEY"},
    "deepseek:chat":           {"provider":"deepseek","base_url":"https://api.deepseek.com","model":"deepseek-chat","key_env":"DEEPSEEK_API_KEY"},
    "deepseek:reasoner":       {"provider":"deepseek","base_url":"https://api.deepseek.com","model":"deepseek-reasoner","key_env":"DEEPSEEK_API_KEY"},
    # ── 阿里百炼 ──────────────────────────────────────
    "bailian:qwen3-flash":     {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen3-flash","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen3-plus":      {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen3-plus","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen3-max":       {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen3-max","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen-flash":      {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-flash","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen-plus":       {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-plus","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen-turbo":      {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-turbo-latest","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen-max":        {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-max","key_env":"BAILIAN_API_KEY"},
    "bailian:qwen-coder":      {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-coder-plus","key_env":"BAILIAN_API_KEY"},
    "bailian:qwq-plus":        {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwq-plus","key_env":"BAILIAN_API_KEY"},
    "bailian:deepseek-v3":     {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"deepseek-v3","key_env":"BAILIAN_API_KEY"},
    "bailian:deepseek-r1":     {"provider":"bailian","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"deepseek-r1","key_env":"BAILIAN_API_KEY"},
    # ── 智谱 ──────────────────────────────────────────
    "zhipu:glm-4-plus":        {"provider":"zhipu","base_url":"https://open.bigmodel.cn/api/paas/v4","model":"glm-4-plus","key_env":"ZHIPU_API_KEY"},
    "zhipu:glm-4":             {"provider":"zhipu","base_url":"https://open.bigmodel.cn/api/paas/v4","model":"glm-4","key_env":"ZHIPU_API_KEY"},
    "zhipu:glm-4-flash":       {"provider":"zhipu","base_url":"https://open.bigmodel.cn/api/paas/v4","model":"glm-4-flash","key_env":"ZHIPU_API_KEY"},
    # ── 月之暗面 ──────────────────────────────────────
    "moonshot:kimi":           {"provider":"moonshot","base_url":"https://api.moonshot.cn/v1","model":"moonshot-v1-8k","key_env":"MOONSHOT_API_KEY"},
    "moonshot:kimi-32k":       {"provider":"moonshot","base_url":"https://api.moonshot.cn/v1","model":"moonshot-v1-32k","key_env":"MOONSHOT_API_KEY"},
    # ── 字节豆包 ──────────────────────────────────────
    "doubao:pro-32k":          {"provider":"doubao","base_url":"https://ark.cn-beijing.volces.com/api/v3","model":"doubao-pro-32k","key_env":"DOUBAO_API_KEY"},
    "doubao:lite":             {"provider":"doubao","base_url":"https://ark.cn-beijing.volces.com/api/v3","model":"doubao-lite-32k","key_env":"DOUBAO_API_KEY"},
    # ── 阶跃星辰 ──────────────────────────────────────
    "step:step-2":             {"provider":"stepfun","base_url":"https://api.stepfun.com/v1","model":"step-2-16k","key_env":"STEPFUN_API_KEY"},
    # ── MiniMax ───────────────────────────────────────
    "minimax:abab7":           {"provider":"minimax","base_url":"https://api.minimax.chat/v1","model":"abab7-chat","key_env":"MINIMAX_API_KEY"},
    "minimax:abab6.5":         {"provider":"minimax","base_url":"https://api.minimax.chat/v1","model":"abab6.5-chat","key_env":"MINIMAX_API_KEY"},
    # ── 百川 ──────────────────────────────────────────
    "baichuan:baichuan4":      {"provider":"baichuan","base_url":"https://api.baichuan-ai.com/v1","model":"Baichuan4","key_env":"BAICHUAN_API_KEY"},
    # ── Mistral ───────────────────────────────────────
    "mistral:large":           {"provider":"mistral","base_url":"https://api.mistral.ai/v1","model":"mistral-large-latest","key_env":"MISTRAL_API_KEY"},
    "mistral:small":           {"provider":"mistral","base_url":"https://api.mistral.ai/v1","model":"mistral-small-latest","key_env":"MISTRAL_API_KEY"},
    # ── Groq ──────────────────────────────────────────
    "groq:llama-3.3-70b":      {"provider":"groq","base_url":"https://api.groq.com/openai/v1","model":"llama-3.3-70b-versatile","key_env":"GROQ_API_KEY"},
    # ── Perplexity ────────────────────────────────────
    "perplexity:sonar":        {"provider":"perplexity","base_url":"https://api.perplexity.ai","model":"sonar","key_env":"PERPLEXITY_API_KEY"},
    # ── xAI ───────────────────────────────────────────
    "xai:grok-3":              {"provider":"xai","base_url":"https://api.x.ai/v1","model":"grok-3-beta","key_env":"XAI_API_KEY"},
    # ── Ollama本地 ────────────────────────────────────
    "ollama:llama3.3":         {"provider":"ollama","base_url":"http://localhost:11434/v1","model":"llama3.3","key_env":"OLLAMA_API_KEY"},
    "ollama:qwen3":            {"provider":"ollama","base_url":"http://localhost:11434/v1","model":"qwen3","key_env":"OLLAMA_API_KEY"},
}


# 环境变量 → API Key 的自动扫描映射
ENV_KEY_MAP = {
    "BAILIAN_API_KEY":         "bailian:*",
    "DEEPSEEK_API_KEY":        "deepseek:*",
    "OPENAI_API_KEY":          "openai:*",
    "ANTHROPIC_API_KEY":       "anthropic:*",
    "GEMINI_API_KEY":          "google:*",
    "ZHIPU_API_KEY":           "zhipu:*",
    "MOONSHOT_API_KEY":        "moonshot:*",
    "YI_API_KEY":              "yi:*",
    "MINIMAX_API_KEY":         "minimax:*",
    "BAICHUAN_API_KEY":        "baichuan:*",
}


class ModelRegistry:
    """
    极简单例模型注册中心
    
    用法:
        registry = ModelRegistry()
        registry.add("deepseek:chat", key="sk-xxx")
        model = registry.get("deepseek:chat")
        resp = model.chat([{"role":"user","content":"Hi"}])
    """

    def __init__(self, config_path: str = None):
        self._entries: Dict[str, Dict] = {}  # model_id → {key, model, base_url}
        self._clients: Dict[str, Any] = {}   # model_id → OpenAI client
        self._config_path = config_path
        
        # 从环境变量自动扫描
        self._scan_env()
        
        # 从配置文件加载
        if config_path:
            self._load_config(config_path)
            
        # 确保有默认模型
        if not self._entries:
            self._ensure_default()

    def _scan_env(self):
        """自动扫描环境变量，发现所有可用模型"""
        for env_var, pattern in ENV_KEY_MAP.items():
            key = os.environ.get(env_var, "")
            if not key:
                continue
            
            prefix = pattern.replace(":*", ":")
            for model_id, info in BUILTIN_MODELS.items():
                if model_id.startswith(prefix) and info["key_env"] == env_var:
                    self._entries[model_id] = {
                        "key": key,
                        "model": info["model"],
                        "base_url": info["base_url"],
                        "provider": info["provider"],
                    }

    def _load_config(self, path: str):
        """从 meshctx.yaml 加载已配置的模型"""
        import yaml, re
        try:
            with open(path) as f:
                config = yaml.safe_load(f) or {}
        except:
            return
        
        models_section = config.get("models", {})
        entries = models_section.get("entries", {})
        
        for model_id, cfg in entries.items():
            key = cfg.get("key", "")
            # 展开 ${ENV_VAR}
            key = re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), ""), key)
            
            if model_id in BUILTIN_MODELS:
                info = BUILTIN_MODELS[model_id]
                self._entries[model_id] = {
                    "key": key or os.environ.get(info["key_env"], ""),
                    "model": cfg.get("model") or info["model"],
                    "base_url": cfg.get("base_url") or info["base_url"],
                    "provider": info["provider"],
                }
            else:
                self._entries[model_id] = {
                    "key": key,
                    "model": cfg.get("model", "default"),
                    "base_url": cfg.get("base_url", ""),
                    "provider": cfg.get("provider", "openai"),
                }

    def _ensure_default(self):
        """确保至少有一个可用模型"""
        # 尝试验证已有的
        for model_id in self._entries:
            if self._entries[model_id].get("key"):
                return
        
        # 回退: 尝试 bailian key
        key = os.environ.get("BAILIAN_API_KEY", "")
        if key:
            self._entries["bailian:qwen-flash"] = {
                "key": key,
                "model": "qwen-flash",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "provider": "bailian",
            }

    # ── 增删改查 ──────────────────────────────────────────

    def add(self, model_id: str, key: str = "", model: str = "", base_url: str = ""):
        """添加模型 (一行搞定)"""
        if model_id in BUILTIN_MODELS:
            info = BUILTIN_MODELS[model_id]
            self._entries[model_id] = {
                "key": key or os.environ.get(info["key_env"], ""),
                "model": model or info["model"],
                "base_url": base_url or info["base_url"],
                "provider": info["provider"],
            }
        else:
            # 自定义模型
            self._entries[model_id] = {
                "key": key,
                "model": model or "default",
                "base_url": base_url or "",
                "provider": "openai",
            }
        # 清除缓存
        self._clients.pop(model_id, None)
        return self._entries[model_id]

    def remove(self, model_id: str):
        self._entries.pop(model_id, None)
        self._clients.pop(model_id, None)

    def get(self, model_id: str = None) -> Optional[Any]:
        """获取模型客户端 (OpenAI-compatible)"""
        from openai import OpenAI
        
        # 如果没指定，用默认
        if model_id is None:
            if self._entries:
                model_id = next(iter(self._entries))
            else:
                return None

        # 模糊匹配
        if model_id not in self._entries:
            # 尝试部分匹配: "qwen-flash" → "bailian:qwen-flash"
            for eid in self._entries:
                if model_id in eid:
                    model_id = eid
                    break
        
        if model_id not in self._entries:
            return None

        # 缓存客户端
        if model_id not in self._clients:
            cfg = self._entries[model_id]
            if not cfg.get("key"):
                return None
            self._clients[model_id] = OpenAI(
                api_key=cfg["key"],
                base_url=cfg["base_url"],
            )
        
        return ModelClient(
            client=self._clients[model_id],
            model_id=model_id,
            model_name=self._entries[model_id]["model"],
        )

    def list_all(self) -> List[Dict]:
        """列出所有已配置模型"""
        result = []
        for model_id, cfg in self._entries.items():
            result.append({
                "id": model_id,
                "provider": cfg.get("provider", "?"),
                "model": cfg.get("model", "?"),
                "ready": bool(cfg.get("key")),
            })
        return result

    def list_available(self) -> List[str]:
        """列出内置目录中所有可用的模型ID"""
        return list(BUILTIN_MODELS.keys())

    def auto_configure(self):
        """一键自动配置: 扫描所有环境变量, 配置所有可用模型"""
        self._scan_env()
        return self.list_all()


@dataclass
class ModelClient:
    """模型客户端"""
    client: Any
    model_id: str
    model_name: str

    def chat(self, messages: List[Dict], temperature=0.7, max_tokens=4096) -> Dict:
        """发送对话请求"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            choice = resp.choices[0]
            return {
                "content": choice.message.content or "",
                "model": resp.model,
                "tokens": resp.usage.total_tokens if resp.usage else 0,
            }
        except Exception as e:
            return {"content": f"[错误: {e}]", "model": self.model_name, "tokens": 0}

    def chat_stream(self, messages: List[Dict], temperature=0.7, max_tokens=4096):
        """流式对话 — 逐token返回"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"[错误: {e}]"


# ── 全局单例 ──────────────────────────────────────────

_registry: Optional[ModelRegistry] = None


def get_registry(config_path: str = None) -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry(config_path)
    return _registry


def chat(model_id: str, prompt: str) -> str:
    """一行对话: meshctx.chat("qwen-flash", "你好")"""
    reg = get_registry()
    client = reg.get(model_id)
    if not client:
        return f"[模型 {model_id} 未配置]"
    resp = client.chat([{"role": "user", "content": prompt}])
    return resp["content"]
