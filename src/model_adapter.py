"""
meshctx 统一模型适配器
一行切换百炼/DeepSeek/OpenAI，不换代码
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ModelResponse:
    """统一的模型返回"""
    content: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"


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
        self._init_client()

    def _init_client(self):
        """初始化对应 provider 的客户端"""
        api_key = self.cfg.get("api_key", "")
        base_url = self.cfg.get("base_url", "")
        model = self.cfg.get("model", "")

        if not api_key and self.provider != "local":
            raise ValueError(
                f"Missing API key for provider '{self.provider}'. "
                f"Set {self.provider.upper()}_API_KEY env var or in config."
            )

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            self._model = model
            self._ready = True
        except ImportError:
            raise ImportError("pip install openai 以使用模型功能")

    def chat(self, messages: List[Dict[str, str]],
             system: str = None,
             temperature: float = None,
             max_tokens: int = None) -> ModelResponse:
        """发送对话请求"""
        if not self._ready:
            return ModelResponse(content="[模型未初始化]", model="none")

        # 构建消息
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        temp = temperature or self.cfg.get("temperature", 0.7)
        mt = max_tokens or self.cfg.get("max_tokens", 4096)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=msgs,
                temperature=temp,
                max_tokens=mt,
            )
            choice = resp.choices[0]
            content = choice.message.content or ""
            # 清理非法 Unicode 代理字符
            content = content.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace')
            return ModelResponse(
                content=content,
                model=resp.model,
                tokens_used=resp.usage.total_tokens if resp.usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as e:
            return ModelResponse(
                content=f"[模型调用失败: {e}]",
                model=self._model,
            )

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
        except:
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
        except:
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
