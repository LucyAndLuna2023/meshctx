"""
meshctx 统一模型适配器
一行切换百炼/DeepSeek/OpenAI，不换代码
"""
import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger("meshctx.model_adapter")
from dataclasses import dataclass
import os

# 流式输出超时(秒)
_STREAM_READ_TIMEOUT = 60
_STREAM_IDLE_TIMEOUT = 60
_CLIENT_TIMEOUT = 120


@dataclass
class ModelResponse:
    """统一的模型返回"""
    content: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict]] = None
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


class ModelAdapter:
    """
    统一模型适配器
    
    用法:
        adapter = ModelAdapter(config.get_model_config("deepseek"))
        resp = adapter.chat([{"role":"user","content":"Hello"}])
    """

    def __init__(self, model_config: Dict):
        self.cfg = model_config
        self.provider = model_config.get("provider", "bailian")
        self._client = None
        self.cache_stats = {"hits": 0, "misses": 0,
                            "hit_tokens": 0, "miss_tokens": 0, "requests": 0}
        self._init_client()

    def _init_client(self):
        """初始化对应 provider 的客户端"""
        api_key = self.cfg.get("api_key") or self.cfg.get("key") or ""
        if not api_key:
            # 按 provider 查对应环境变量（覆盖 30+ 供应商）
            _PROVIDER_ENV = {
                "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
                "bailian": "BAILIAN_API_KEY", "alibaba": "DASHSCOPE_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY",
                "xai": "XAI_API_KEY", "openrouter": "OPENROUTER_API_KEY",
                "moonshot": "MOONSHOT_API_KEY", "zhipu": "ZHIPU_API_KEY",
                "minimax": "MINIMAX_API_KEY", "together": "TOGETHER_API_KEY",
                "mistral": "MISTRAL_API_KEY", "groq": "GROQ_API_KEY",
                "cohere": "COHERE_API_KEY", "perplexity": "PERPLEXITY_API_KEY",
                "siliconflow": "SILICONFLOW_API_KEY",
            }
            env_name = _PROVIDER_ENV.get(self.provider)
            if env_name:
                api_key = os.environ.get(env_name, "")
        if not api_key:
            # 兜底：常见 key 依次尝试
            for k in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                      "BAILIAN_API_KEY", "DASHSCOPE_API_KEY"):
                api_key = os.environ.get(k, "")
                if api_key:
                    break
        base_url = self.cfg.get("base_url", "")
        model = self.cfg.get("model", "")

        if not api_key and self.provider != "local":
            raise ValueError(
                f"Missing API key for provider '{self.provider}'. "
                f"Set {self.provider.upper()}_API_KEY env var or in config."
            )

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url,
                                timeout=_CLIENT_TIMEOUT)
            self._model = model
            self._ready = True
        except ImportError:
            raise ImportError("pip install openai 以使用模型功能")

    def chat(self, messages: List[Dict[str, str]],
             system: str = None,
             temperature: float = None,
             max_tokens: int = None,
             tools: List[Dict] = None,
             tool_choice: str = "auto") -> ModelResponse:
        """发送对话请求，支持原生 function calling"""
        if not self._ready:
            return ModelResponse(content="[模型未初始化]", model="none")

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        temp = temperature or self.cfg.get("temperature", 0.7)
        mt = max_tokens or self.cfg.get("max_tokens", 4096)

        kwargs = dict(model=self._model, messages=msgs, temperature=temp, max_tokens=mt)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            resp = self._client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            content = choice.message.content or ""
            content = content.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')

            # T1: provider context caching 命中统计
            hit_tokens = miss_tokens = 0
            if getattr(resp, "usage", None):
                hit_tokens = int(getattr(resp.usage, "prompt_cache_hit_tokens", 0) or 0)
                miss_tokens = int(getattr(resp.usage, "prompt_cache_miss_tokens", 0) or 0)
            self.cache_stats["requests"] += 1
            self.cache_stats["hit_tokens"] += hit_tokens
            self.cache_stats["miss_tokens"] += miss_tokens
            if hit_tokens > 0:
                self.cache_stats["hits"] += 1
            else:
                self.cache_stats["misses"] += 1
            if hit_tokens or miss_tokens:
                logger.info("prompt cache: hit=%d miss=%d tokens (req #%d)",
                            hit_tokens, miss_tokens, self.cache_stats["requests"])

            # Extract tool calls if present
            tool_calls = []
            if choice.message.tool_calls:
                import json
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        logger.debug("model_adapter error", exc_info=True)
                        args = {}
                    tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})

            return ModelResponse(
                content=content,
                model=resp.model,
                tokens_used=resp.usage.total_tokens if resp.usage else 0,
                finish_reason=choice.finish_reason or "stop",
                tool_calls=tool_calls,
                cache_hit_tokens=hit_tokens,
                cache_miss_tokens=miss_tokens,
            )
        except Exception as e:
            return ModelResponse(
                content=f"[模型调用失败: {e}]",
                model=self._model,
            )

    def chat_stream(self, messages: List[Dict[str, str]],
                    system: str = None,
                    temperature: float = None,
                    max_tokens: int = None,
                    tools: List[Dict] = None):
        """流式对话 — 逐 token yield"""
        if not self._ready:
            yield "[模型未初始化]"
            return

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        temp = temperature or self.cfg.get("temperature", 0.7)
        mt = max_tokens or self.cfg.get("max_tokens", 4096)

        kwargs = dict(model=self._model, messages=msgs, temperature=temp, max_tokens=mt, stream=True,
                      stream_options={"include_usage": True})
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        tool_calls_acc = {}  # index -> {id, name, args_str}
        final_content = ""

        _last_chunk = time.monotonic()
        try:
            for chunk in self._client.chat.completions.create(**kwargs, timeout=_STREAM_READ_TIMEOUT):
                _now = time.monotonic()
                if _now - _last_chunk > _STREAM_IDLE_TIMEOUT:
                    yield "\n[流式错误: 流式响应空闲超时]"
                    return
                _last_chunk = _now
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Content
                if delta.content:
                    final_content += delta.content
                    yield delta.content

                # Tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "args_str": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["args_str"] += tc.function.arguments
        except Exception as e:
            yield f"\n[流式错误: {e}]"

        # Parse accumulated tool calls
        if tool_calls_acc:
            import json
            parsed_tools = []
            for idx in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["args_str"])
                except Exception:
                    logger.debug("model_adapter chat error", exc_info=True)
                    args = {}
                parsed_tools.append({"id": tc["id"], "name": tc["name"], "arguments": args})

            # Yield tool calls as a special marker at end
            yield ("__TOOL_CALLS__", parsed_tools, final_content)

    def extract_memories(self, content: str, context: str = "") -> List[Dict]:
        """从内容提取记忆 (结构化输出)"""
        prompt = f"""从以下内容提取所有值得长期记住的关键信息。以JSON数组输出，每条包含 key/value/importance(0-1)。

上下文: {context[:500]}
内容: {content[:1000]}

只输出JSON数组:"""

        resp = self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1000,
        )

        # 解析 JSON
        import json
        try:
            text = resp.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception:
            logger.debug("model_adapter error", exc_info=True)
            return []

    def generate_skill(self, task_pattern: Dict) -> Optional[Dict]:
        """从成功模式生成 Skill 定义"""
        prompt = f"""根据以下重复成功的任务模式，生成一个可复用的 Skill 定义。

任务模式: {task_pattern}

输出JSON:
{{
  "name": "skill名称(英文,连字符)",
  "description": "一句话描述",
  "trigger": "什么时候触发这个skill",
  "steps": ["步骤1", "步骤2", "步骤3"],
  "tools": ["需要的工具"],
  "model": "推荐模型(bailian-free/deepseek/openai)"
}}"""

        resp = self.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )

        import json
        try:
            text = resp.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception:
            logger.debug("model_adapter error", exc_info=True)
            return None

    @property
    def is_ready(self) -> bool:
        return getattr(self, '_ready', False)

    @property
    def model_name(self) -> str:
        return getattr(self, '_model', 'none')


# ── 模型工厂 ──────────────────────────────────────────

_model_cache: Dict[str, ModelAdapter] = {}


def get_model(name: str = None, config: Dict = None) -> ModelAdapter:
    """获取模型实例(带缓存)"""
    from .config import get_model_config

    if config is None:
        from .config import load_config
        config = load_config()

    model_cfg = get_model_config(config, name)
    cache_key = f"{model_cfg.get('provider')}:{model_cfg.get('model')}"

    if cache_key not in _model_cache:
        _model_cache[cache_key] = ModelAdapter(model_cfg)

    return _model_cache[cache_key]
