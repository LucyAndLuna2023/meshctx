#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测统一模型接入层 — 支持全世界主流模型（模型无关架构）

所有 LongMemEval runner 统一从这里取模型客户端，不再硬编码 provider。

用法：
    MODEL_ID=deepseek:chat   python3 run_meshctx_memory.py   # 默认
    MODEL_ID=openrouter:gpt-4o  python3 run_meshctx_memory.py
    MODEL_ID=anthropic:claude-sonnet  python3 run_meshctx_memory.py
    MODEL_ID=google:gemini-flash  python3 run_meshctx_memory.py
    MODEL_ID=bailian:qwen3-plus  python3 run_meshctx_memory.py
    MODEL_ID=deepseek:reasoner  python3 run_meshctx_memory.py

已注册模型（src/model_registry.py BUILTIN_MODELS）：OpenAI gpt-4o/o3/o4、Anthropic
Claude、Google Gemini、xAI Grok、OpenRouter(200+)、DeepSeek、阿里 Qwen、智谱 GLM、
月之暗面 Kimi、字节豆包、腾讯混元、讯飞星火、Perplexity、Together Llama 等。
key 从对应 KEY_ENV 环境变量读取（.env 或 os.environ 均可）。

设计：默认 deepseek:chat（测试用当前模型即可）；模型切换只改环境变量，评测代码零改动。
"""
import os

DEFAULT_MODEL_ID = "deepseek:chat"


def resolve_model_id() -> str:
    """MODEL_ID 环境变量 → 模型 id；缺省 deepseek:chat（测试用当前模型即可）。"""
    return os.environ.get("MODEL_ID", "").strip() or DEFAULT_MODEL_ID


def get_client(model_id: str = None):
    """按 model_id 从 model_registry 取 OpenAI 兼容客户端。

    回退链：model_registry（支持全部已注册模型）→ 直接构造（OpenAI 兼容 base_url）。
    """
    model_id = model_id or resolve_model_id()
    try:
        from src.model_registry import ModelRegistry
        reg = ModelRegistry()
        reg.add(model_id)
        mc = reg.get(model_id)
        if mc is not None and getattr(mc, "client", None) is not None:
            return mc.client, mc.model_name
        # registry 无 key 时回退：仍可显式提供 OPENAI_API_KEY
    except Exception:
        pass
    # 通用回退：按 registry 的 key_env / base_url 取（任意 provider），
    # 读不到再回退 OpenAI 兼容通用 key
    from openai import OpenAI

    def _resolve_key(mid: str) -> str:
        env_name = None
        try:
            from src.model_registry import BUILTIN_MODELS
            env_name = (BUILTIN_MODELS.get(mid) or {}).get("key_env")
        except Exception:
            pass
        if env_name:
            k = os.environ.get(env_name) or _load_env_key(env_name)
            if k:
                return k
            # key_env 明确但未配置：仅 deepseek/openai 端点可回退兼容通用 key，
            # 其他 provider 硬凑通用 key 会 401 静默失败——直接明确报错
            if mid.split(":", 1)[0] not in ("deepseek", "openai"):
                raise RuntimeError(
                    f"模型 {mid} 需要 {env_name}（未在环境变量或 .env 配置，不静默降级）"
                )
        for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
            k = os.environ.get(name) or _load_env_key(name)
            if k:
                return k
        return ""

    key = _resolve_key(model_id)
    base = os.environ.get("OPENAI_BASE_URL")
    if not base:
        try:
            from src.model_registry import BUILTIN_MODELS
            base = (BUILTIN_MODELS.get(model_id) or {}).get("base_url") or "https://api.deepseek.com"
        except Exception:
            base = "https://api.deepseek.com"
    if not key:
        raise RuntimeError(f"模型 {model_id} 的 API key 未配置（检查环境变量或 .env）")
    # model 名优先取 BUILTIN_MODELS 注册值（如 deepseek:chat → deepseek-chat）
    name = model_id.split(":", 1)[-1] if ":" in model_id else model_id
    try:
        from src.model_registry import BUILTIN_MODELS
        entry = BUILTIN_MODELS.get(model_id)
        if entry is not None:
            name = entry.get("model") or name
    except Exception:
        # src 不可导入：已注册格式（provider:model）不能静默降级成 "chat" 错误名
        if ":" in model_id:
            raise RuntimeError(
                f"无法解析模型名 {model_id}: model_registry 不可用（src 未导入）。"
                "请确认在仓库根目录运行，或改用不带 provider 前缀的自定义模型名"
            ) from None
        # 未带前缀的自定义模型名：原样透传
    return OpenAI(api_key=key, base_url=base), name


def _load_env_key(name: str) -> str:
    env_path = os.environ.get("MESHCTX_ENV_FILE", "")
    if not env_path:
        for p in ("/home/administrator/.meshctx/.env", "~/.meshctx/.env"):
            if os.path.exists(os.path.expanduser(p)):
                env_path = p
                break
    if not env_path:
        return ""
    try:
        for ln in open(os.path.expanduser(env_path), encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith(name + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


_client = None
_model_name = None


def ask(prompt: str, max_tokens: int = 80, temperature: float = 0.0,
        model_id: str = None) -> str:
    """统一 chat 调用（OpenAI 兼容协议，覆盖全部已注册 provider）。

    注：reasoner 类模型忽略 temperature，max_tokens 仅约束最终输出；
    content 为空时回退 reasoning_content（reasoner 兼容）。
    """
    global _client, _model_name
    if _client is None:
        _client, _model_name = get_client(model_id or resolve_model_id())
    for attempt in range(3):
        try:
            resp = _client.chat.completions.create(
                model=_model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            msg = resp.choices[0].message
            return (msg.content or "").strip() or (getattr(msg, "reasoning_content", "") or "").strip()
        except Exception as e:
            if attempt == 2:
                raise
            import time
            time.sleep(3)
    return ""


def model_name() -> str:
    return _model_name or resolve_model_id()


if __name__ == "__main__":
    import sys
    mid = resolve_model_id()
    c, name = get_client(mid)
    print(f"模型接入 OK: MODEL_ID={mid} → model={name} provider客户端={type(c).__name__}")
    print("冒烟:", ask("回复 OK 两字", max_tokens=16))
    print("已注册模型:", end=" ")
    try:
        from src.model_registry import BUILTIN_MODELS
        print(len(BUILTIN_MODELS), "个")
    except Exception:
        print("?")
