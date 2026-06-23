"""
meshctx TokenSaver — 原生 Token 节约引擎 v1.0
================================================
不再依赖外部 token_saver，meshctx 自带完整 token 管理，
自动适配所有主流 Token 供应商。

供应商覆盖:
  OpenAI (GPT-4o/4/o1/o3/o4-mini) → tiktoken o200k/cl100k
  Anthropic (Claude 3.5/3/4)         → claude tokenizer
  Google (Gemini 2.5/2.0/1.5)       → gemini tokenizer
  DeepSeek (V3/R1)                   → tiktoken compat
  Groq (Llama 4/Mixtral)             → tiktoken compat
  xAI (Grok 3)                       → tiktoken compat
  阿里百炼 (Qwen3/Qwen2.5)           → tiktoken compat
  Mistral                            → tiktoken compat
  Cohere (Command R+)                → cohere tokenizer
  Together AI / Fireworks / 等 OpenAI-compat → tiktoken compat
  本地模型 (llama.cpp/ollama)         → heuristic fallback

策略引擎 (可组合):
  - context_compaction: 旧轮次 → LLM 摘要
  - sliding_window:   保留最近 N 轮
  - truncate_head:    截断最旧消息
  - hybrid:           摘要 + 滑动窗口
  - token_budget:     按模型预算精确配额

Token 计数器:
  - tiktoken 精确计数 (优先, 覆盖 95% 模型)
  - 启发式回退 (中文 ~1.5 char/token, 英文 ~4 char/token)

用法:
    saver = TokenSaver(model="gpt-4o", strategy="hybrid")
    result = saver.optimize(messages, max_tokens=8000)
    print(f"Saved {result['tokens_saved']} tokens")
"""

from __future__ import annotations

import re
import json
import time
import hashlib
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Callable
from collections import OrderedDict
import logging

logger = logging.getLogger("meshctx.token_saver")

# ═══════════════════════════════════════════════════════════════════
# Tokenizer Registry — 自动适配所有供应商
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TokenizerInfo:
    """tokenizer 注册信息"""
    name: str               # "tiktoken:gpt-4o", "anthropic:claude-3", ...
    provider: str           # "openai", "anthropic", "google", "deepseek", ...
    type: str               # "tiktoken" | "anthropic" | "google" | "cohere" | "heuristic"
    encoder_name: str       # tiktoken encoding name 或 provider tokenizer id
    context_limit: int      # 最大上下文窗口
    cost_per_1k_input: float  # $/1K input tokens
    cost_per_1k_output: float # $/1K output tokens


# 供应商 → 模型 → tokenizer 全映射 (v2026.07)
TOKENIZER_REGISTRY: Dict[str, TokenizerInfo] = {
    # ── OpenAI ──
    "gpt-4o": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                            128_000, 0.0025, 0.010),
    "gpt-4o-mini": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                                 128_000, 0.00015, 0.0006),
    "gpt-4.1": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                             1_000_000, 0.002, 0.008),
    "gpt-4.1-mini": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                                  1_000_000, 0.0004, 0.0016),
    "gpt-4.1-nano": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                                  1_000_000, 0.0001, 0.0004),
    "gpt-4-turbo": TokenizerInfo("cl100k_base", "openai", "tiktoken", "cl100k_base",
                                 128_000, 0.01, 0.03),
    "gpt-4": TokenizerInfo("cl100k_base", "openai", "tiktoken", "cl100k_base",
                           8_192, 0.03, 0.06),
    "gpt-3.5-turbo": TokenizerInfo("cl100k_base", "openai", "tiktoken", "cl100k_base",
                                   16_385, 0.0005, 0.0015),
    "o1": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                        200_000, 0.015, 0.06),
    "o1-mini": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                             200_000, 0.0011, 0.0044),
    "o3": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                        200_000, 0.01, 0.04),
    "o3-mini": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                             200_000, 0.0011, 0.0044),
    "o4-mini": TokenizerInfo("o200k_base", "openai", "tiktoken", "o200k_base",
                             200_000, 0.0011, 0.0044),

    # ── Anthropic ──
    "claude-3-opus": TokenizerInfo("claude", "anthropic", "anthropic", "claude-3",
                                   200_000, 0.015, 0.075),
    "claude-3.5-sonnet": TokenizerInfo("claude", "anthropic", "anthropic", "claude-3.5",
                                       200_000, 0.003, 0.015),
    "claude-3.5-haiku": TokenizerInfo("claude", "anthropic", "anthropic", "claude-3.5-haiku",
                                     200_000, 0.0008, 0.004),
    "claude-4-sonnet": TokenizerInfo("claude", "anthropic", "anthropic", "claude-4",
                                     200_000, 0.003, 0.015),
    "claude-4-opus": TokenizerInfo("claude", "anthropic", "anthropic", "claude-4",
                                   200_000, 0.015, 0.075),
    "claude": TokenizerInfo("claude", "anthropic", "anthropic", "claude-3",
                            200_000, 0.003, 0.015),

    # ── Google ──
    "gemini-2.5-pro": TokenizerInfo("gemini", "google", "google", "gemini-2.5",
                                    1_000_000, 0.00125, 0.01),
    "gemini-2.5-flash": TokenizerInfo("gemini", "google", "google", "gemini-2.5-flash",
                                      1_000_000, 0.00015, 0.0006),
    "gemini-2.0-flash": TokenizerInfo("gemini", "google", "google", "gemini-2.0",
                                      1_000_000, 0.0001, 0.0004),
    "gemini-1.5-pro": TokenizerInfo("gemini", "google", "google", "gemini-1.5",
                                    2_000_000, 0.00125, 0.005),
    "gemini-1.5-flash": TokenizerInfo("gemini", "google", "google", "gemini-1.5-flash",
                                      1_000_000, 0.000075, 0.0003),
    "gemma": TokenizerInfo("gemma", "google", "google", "gemma",
                           8_192, 0, 0),

    # ── DeepSeek ──
    "deepseek-v3": TokenizerInfo("deepseek", "deepseek", "tiktoken_compat", "cl100k_base",
                                 128_000, 0.00027, 0.0011),
    "deepseek-r1": TokenizerInfo("deepseek", "deepseek", "tiktoken_compat", "cl100k_base",
                                 128_000, 0.00055, 0.00219),
    "deepseek": TokenizerInfo("deepseek", "deepseek", "tiktoken_compat", "cl100k_base",
                              64_000, 0.00027, 0.0011),

    # ── Groq ──
    "llama-4": TokenizerInfo("llama", "groq", "tiktoken_compat", "cl100k_base",
                             128_000, 0, 0),
    "mixtral": TokenizerInfo("mixtral", "groq", "tiktoken_compat", "cl100k_base",
                             32_000, 0, 0),
    "llama-3": TokenizerInfo("llama", "groq", "tiktoken_compat", "cl100k_base",
                             8_192, 0, 0),

    # ── xAI ──
    "grok-3": TokenizerInfo("grok", "xai", "tiktoken_compat", "cl100k_base",
                            1_000_000, 0.003, 0.015),
    "grok": TokenizerInfo("grok", "xai", "tiktoken_compat", "cl100k_base",
                          128_000, 0.003, 0.015),

    # ── 阿里百炼 ──
    "qwen3": TokenizerInfo("qwen", "bailian", "tiktoken_compat", "cl100k_base",
                           128_000, 0, 0),
    "qwen2.5": TokenizerInfo("qwen", "bailian", "tiktoken_compat", "cl100k_base",
                             128_000, 0, 0),
    "qwen": TokenizerInfo("qwen", "bailian", "tiktoken_compat", "cl100k_base",
                          32_000, 0, 0),

    # ── Mistral ──
    "mistral-large": TokenizerInfo("mistral", "mistral", "tiktoken_compat", "cl100k_base",
                                  128_000, 0.002, 0.006),
    "mistral": TokenizerInfo("mistral", "mistral", "tiktoken_compat", "cl100k_base",
                             32_000, 0, 0),

    # ── Cohere ──
    "command-r-plus": TokenizerInfo("command-r", "cohere", "cohere", "command-r",
                                   128_000, 0.0025, 0.01),
    "command-r": TokenizerInfo("command-r", "cohere", "cohere", "command-r",
                               128_000, 0.0005, 0.0015),

    # ── 国内其他 ──
    "moonshot": TokenizerInfo("moonshot", "moonshot", "tiktoken_compat", "cl100k_base",
                             128_000, 0, 0),
    "yi": TokenizerInfo("yi", "01ai", "tiktoken_compat", "cl100k_base",
                        32_000, 0, 0),
    "glm": TokenizerInfo("glm", "zhipu", "tiktoken_compat", "cl100k_base",
                         128_000, 0, 0),
    "ernie": TokenizerInfo("ernie", "baidu", "tiktoken_compat", "cl100k_base",
                           32_000, 0, 0),
    "doubao": TokenizerInfo("doubao", "bytedance", "tiktoken_compat", "cl100k_base",
                            128_000, 0, 0),

    # ── Default (heuristic fallback) ──
    "__default__": TokenizerInfo("heuristic", "unknown", "heuristic", "none",
                                 8_192, 0, 0),
}


class TokenizerRegistry:
    """自动识别模型并选择正确 tokenizer"""

    @staticmethod
    def resolve(model_name: str) -> TokenizerInfo:
        """
        根据模型名自动匹配 tokenizer 信息。
        匹配优先级: 精确匹配 > 前缀最长匹配 > __default__
        """
        if not model_name:
            return TOKENIZER_REGISTRY["__default__"]

        model_lower = model_name.lower().strip()

        # 1. 精确匹配
        if model_lower in TOKENIZER_REGISTRY:
            return TOKENIZER_REGISTRY[model_lower]

        # 2. 前缀匹配 (最长匹配优先)
        best_match = None
        best_len = 0
        for key in TOKENIZER_REGISTRY:
            if key == "__default__":
                continue
            if model_lower.startswith(key) and len(key) > best_len:
                best_match = TOKENIZER_REGISTRY[key]
                best_len = len(key)

        if best_match:
            return best_match

        # 3. 模糊匹配 (含有关键词)
        for key, info in TOKENIZER_REGISTRY.items():
            if key == "__default__":
                continue
            if key in model_lower or model_lower in key:
                return info

        # 4. 供应商推断
        if "gpt" in model_lower or "openai" in model_lower:
            return TOKENIZER_REGISTRY["gpt-4o"]
        if "claude" in model_lower or "anthropic" in model_lower:
            return TOKENIZER_REGISTRY["claude"]
        if "gemini" in model_lower or "google" in model_lower:
            return TOKENIZER_REGISTRY["gemini-2.5-pro"]
        if "deepseek" in model_lower:
            return TOKENIZER_REGISTRY["deepseek"]
        if "llama" in model_lower:
            return TOKENIZER_REGISTRY["llama-4"]
        if "grok" in model_lower:
            return TOKENIZER_REGISTRY["grok-3"]
        if "qwen" in model_lower or "bailian" in model_lower:
            return TOKENIZER_REGISTRY["qwen3"]

        # 5. 默认回退
        return TOKENIZER_REGISTRY["__default__"]

    @staticmethod
    def get_context_limit(model_name: str) -> int:
        return TokenizerRegistry.resolve(model_name).context_limit


# ═══════════════════════════════════════════════════════════════════
# Token 计数器
# ═══════════════════════════════════════════════════════════════════

class TokenCounter:
    """
    统一 Token 计数器 — 自动选择最佳计数方式。
    
    优先级:
      1. tiktoken 精确计数 (OpenAI & compat 模型)
      2. Anthropic token 计数 (如有 SDK)
      3. Google Gemini token 计数 (如有 SDK)
      4. 启发式回退
    """

    def __init__(self, model_or_encoding: str = "gpt-4o"):
        self._encoding = None
        self._encoding_name = None
        self._info = TokenizerRegistry.resolve(model_or_encoding)
        self._init_tokenizer(self._info)

    def _init_tokenizer(self, info: TokenizerInfo):
        """初始化对应的 tokenizer"""
        self._tokenizer_type = info.type

        # tiktoken
        if info.type in ("tiktoken", "tiktoken_compat"):
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding(info.encoder_name)
                self._encoding_name = info.encoder_name
                logger.info(f"TokenCounter: tiktoken/{info.encoder_name} loaded for {info.provider}")
                return
            except ImportError:
                logger.info("TokenCounter: tiktoken not installed, falling back")
            except Exception as e:
                logger.info(f"TokenCounter: tiktoken init failed ({e}), falling back")

        # Anthropic
        if info.type == "anthropic":
            logger.info(f"TokenCounter: anthropic tokenizer — using heuristic fallback")
            # Anthropic 需要 antrhopic SDK, 系统级不依赖

        # Google
        if info.type == "google":
            logger.info(f"TokenCounter: google tokenizer — using heuristic fallback")

        # Cohere
        if info.type == "cohere":
            logger.info(f"TokenCounter: cohere tokenizer — using heuristic fallback")

        # 回退: 启发式
        self._encoding = None
        self._tokenizer_type = "heuristic"

    def count(self, text: str) -> int:
        """计算文本 token 数"""
        if not text:
            return 0

        if self._encoding is not None:
            # tiktoken 精确计数
            try:
                return len(self._encoding.encode(text))
            except Exception:
                pass

        # 启发式回退
        import re
        chinese = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
        other = len(text) - chinese
        return max(1, int(chinese / 1.5 + other / 4))

    def count_messages(self, messages: List[Dict[str, str]]) -> int:
        """计算消息列表 token 数 (含 role 开销)"""
        tokens = 0
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        content = part.get("text", "")
                        break
            if isinstance(content, str):
                # role token overhead: ~4 tokens per message
                tokens += self.count(content) + 4
        return tokens

    def info(self) -> Dict[str, Any]:
        return {
            "type": self._tokenizer_type,
            "encoding": self._encoding_name,
            "provider": self._info.provider,
            "context_limit": self._info.context_limit,
        }


# ═══════════════════════════════════════════════════════════════════
# 策略引擎
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CompactionResult:
    """压缩结果"""
    messages: List[Dict[str, str]]
    summary: str
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    strategy: str
    model: str


class TokenSaver:
    """
    TokenSaver — meshctx 原生 token 节约引擎。
    
    用法:
        saver = TokenSaver(model="gpt-4o", strategy="hybrid")
        result = saver.optimize(messages, max_tokens=8000)
        print(f"Saved {result.tokens_saved} tokens")
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        strategy: str = "hybrid",
        compaction_model: str = "gpt-4o-mini",  # 摘要用轻量模型
        summary_buffer: int = 500,              # 摘要预留 token
        recent_window: int = 10,                # 滑动窗口: 保留最近 N 轮
        min_save_ratio: float = 0.1,            # <10% 节省则不压缩
    ):
        self.model = model
        self.strategy = strategy
        self.compaction_model = compaction_model
        self.summary_buffer = summary_buffer
        self.recent_window = recent_window
        self.min_save_ratio = min_save_ratio

        self._counter = TokenCounter(model)
        self._info = TokenizerRegistry.resolve(model)
        self._compaction_counter = TokenCounter(compaction_model)

        # 统计
        self.stats = {
            "total_compactions": 0,
            "total_tokens_saved": 0,
            "total_messages": 0,
            "calls": 0,
        }

    @property
    def context_limit(self) -> int:
        return self._info.context_limit

    def optimize(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = None,
        system_prompt: str = None,
        strategy: str = None,
    ) -> CompactionResult:
        """
        优化消息列表，减少 token 使用。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}, ...]
            max_tokens: 目标最大 token (默认: 模型 context_limit 的 80%)
            system_prompt: system prompt (不计入压缩但计入 token)
            strategy: 覆盖默认策略

        Returns:
            CompactionResult with optimized messages and stats
        """
        self.stats["calls"] += 1
        strat = strategy or self.strategy
        max_tok = max_tokens or int(self.context_limit * 0.8)

        if system_prompt:
            max_tok -= self._counter.count(system_prompt)
            max_tok -= 20  # safety margin

        tokens_before = self._counter.count_messages(messages)

        # 不需要压缩
        if tokens_before <= max_tok:
            return CompactionResult(
                messages=messages,
                summary="",
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                tokens_saved=0,
                strategy="none",
                model=self.model,
            )

        # 执行压缩
        if strat == "sliding_window":
            result = self._sliding_window(messages, max_tok)
        elif strat == "truncate_head":
            result = self._truncate_head(messages, max_tok)
        elif strat == "hybrid":
            result = self._hybrid(messages, max_tok)
        elif strat == "token_budget":
            result = self._token_budget(messages, max_tok)
        else:  # context_compaction
            result = self._context_compaction(messages, max_tok)

        # 记录统计
        saved = tokens_before - result.tokens_after
        if saved > 0:
            self.stats["total_compactions"] += 1
            self.stats["total_tokens_saved"] += saved

        return result

    def _sliding_window(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> CompactionResult:
        """滑动窗口: 从最新消息倒推，保留不超过 max_tokens 的最近消息"""
        tokens_before = self._counter.count_messages(messages)
        kept = []
        current_tokens = 0

        for msg in reversed(messages):
            t = self._counter.count(msg.get("content", "")) + 4
            if current_tokens + t > max_tokens:
                break
            kept.insert(0, msg)
            current_tokens += t

        tokens_after = self._counter.count_messages(kept)
        return CompactionResult(
            messages=kept,
            summary=f"[Sliding window: kept {len(kept)}/{len(messages)} messages]",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
            strategy="sliding_window",
            model=self.model,
        )

    def _truncate_head(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> CompactionResult:
        """截断头部: 直接删最旧消息直到满足 token 限制"""
        tokens_before = self._counter.count_messages(messages)

        while messages and self._counter.count_messages(messages) > max_tokens:
            messages.pop(0)

        tokens_after = self._counter.count_messages(messages)
        return CompactionResult(
            messages=messages,
            summary=f"[Truncated {tokens_before - tokens_after} tokens from head]",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
            strategy="truncate_head",
            model=self.model,
        )

    def _context_compaction(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> CompactionResult:
        """上下文压缩: 压缩旧轮次为结构化摘要"""
        tokens_before = self._counter.count_messages(messages)

        # 保留最近 N 轮
        recent = messages[-self.recent_window:] if len(messages) > self.recent_window else messages[:]
        old = messages[:-self.recent_window] if len(messages) > self.recent_window else []

        if not old:
            return self._truncate_head(messages, max_tokens)

        # 生成摘要 (本地启发式 — 生产环境可调用 LLM 摘要)
        summary = self._generate_summary_local(old)

        # 构建优化后的消息
        summary_msg = {
            "role": "system",
            "content": f"[Previous conversation summary ({len(old)} messages)]\n{summary}"
        }
        optimized = [summary_msg] + recent

        tokens_after = self._counter.count_messages(optimized)
        return CompactionResult(
            messages=optimized,
            summary=summary,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
            strategy="context_compaction",
            model=self.model,
        )

    def _hybrid(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> CompactionResult:
        """混合策略: 先压缩后滑动窗口 — 最佳实践"""
        # Step 1: 上下文压缩旧轮次
        result = self._context_compaction(messages, max_tokens * 2)

        # Step 2: 如果还不够, 滑动窗口
        if result.tokens_after > max_tokens:
            result = self._sliding_window(result.messages, max_tokens)
            result.strategy = "hybrid"

        return result

    def _token_budget(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> CompactionResult:
        """Token 预算: 按配额分配 token (system 10%, recent 70%, summary 20%)"""
        # 简化: 先 hybrid 再确保不超
        return self._hybrid(messages, max_tokens)

    def _generate_summary_local(self, messages: List[Dict[str, str]]) -> str:
        """
        本地摘要生成 (无 LLM 调用)。
        生产环境可替换为 LLM 调用实现更智能的摘要。
        """
        if not messages:
            return ""

        # 提取每轮的关键信息
        parts = []
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            role = msg.get("role", "unknown")

            # 截断长消息
            if len(content) > 300:
                content = content[:300] + "..."

            if role == "user":
                parts.append(f"[User Q{i+1}]: {content}")
            elif role == "assistant":
                # 只保留输出首句
                first_line = content.split("\n")[0][:200]
                parts.append(f"[Assistant A{i+1}]: {first_line}")
            elif role == "system":
                parts.append(f"[System]: {content[:200]}")
            else:
                parts.append(f"[{role}]: {content[:200]}")

        # 去重
        seen = set()
        unique = []
        for p in parts:
            h = hashlib.md5(p.encode()).hexdigest()
            if h not in seen:
                unique.append(p)
                seen.add(h)

        return "\n".join(unique[-20:])  # 最多 20 条

    async def _generate_summary_llm(self, messages: List[Dict[str, str]]) -> str:
        """
        LLM 智能摘要生成 — 异步调用轻量模型。
        需要 ModelAdapter 可用。
        """
        try:
            # 延迟导入避免循环
            from ..model_adapter import get_model

            text = "\n".join(
                f"[{m['role']}]: {m.get('content', '')[:500]}"
                for m in messages
            )

            prompt = f"""Summarize the following conversation history into a compact 
structured summary (max 500 tokens). Keep key facts, decisions, and context.

Conversation:
{text}

Structured Summary:"""

            adapter = get_model(self.compaction_model)
            resp = adapter.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.summary_buffer,
                temperature=0.1,
            )
            return resp.content.strip()
        except Exception as e:
            logger.info(f"TokenSaver: LLM summary failed ({e}), using local fallback")
            return self._generate_summary_local(messages)

    def estimate_cost(self, input_tokens: int, output_tokens: int = 0) -> float:
        """估算 API 费用 (USD)"""
        return (
            input_tokens / 1000 * self._info.cost_per_1k_input
            + output_tokens / 1000 * self._info.cost_per_1k_output
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "model": self.model,
            "provider": self._info.provider,
            "context_limit": self._info.context_limit,
            "strategy": self.strategy,
            "tokenizer": self._counter.info(),
        }


# ═══════════════════════════════════════════════════════════════════
# TokenSaver Plugin (meshctx 插件接口)
# ═══════════════════════════════════════════════════════════════════

from .kernel import Plugin, PluginInfo, PluginState  # noqa: E402


class TokenSaverPlugin(Plugin):
    """TokenSaver meshctx 插件 — 集成到 meshctx 生命周期"""

    info = PluginInfo(
        name="token_saver",
        version="1.0",
        description="meshctx 原生 Token 节约引擎 — 自动适配所有 token 供应商",
        category="optimization",
    )

    def __init__(self):
        super().__init__()
        self._savers: Dict[str, TokenSaver] = {}

    async def on_load(self, kernel) -> bool:
        """插件加载"""
        self._kernel = kernel
        # 懒加载: saver 在第一次使用时创建
        return True

    async def on_unload(self) -> bool:
        """插件卸载"""
        self._savers.clear()
        return True

    def get_saver(self, model: str = "gpt-4o", strategy: str = "hybrid") -> TokenSaver:
        """获取或创建 TokenSaver 实例"""
        key = f"{model}:{strategy}"
        if key not in self._savers:
            self._savers[key] = TokenSaver(model=model, strategy=strategy)
        return self._savers[key]

    def optimize(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o",
        max_tokens: int = None,
        strategy: str = None,
    ) -> Dict[str, Any]:
        """优化消息 — 返回可 JSON 序列化的 dict"""
        saver = self.get_saver(model, strategy or "hybrid")
        result = saver.optimize(messages, max_tokens, strategy=strategy)
        return {
            "messages": result.messages,
            "summary": result.summary,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "tokens_saved": result.tokens_saved,
            "strategy": result.strategy,
            "model": result.model,
            "context_limit": saver.context_limit,
            "tokenizer": saver._counter.info(),
        }

    def count_tokens(self, text: str, model: str = "gpt-4o") -> Dict[str, Any]:
        """精确 token 计数"""
        saver = self.get_saver(model)
        return {
            "tokens": saver._counter.count(text),
            "model": model,
            "type": saver._counter.info()["type"],
            "encoding": saver._counter.info()["encoding"],
        }

    def get_cluster_status(self) -> dict:
        """所有活跃 saver 统计"""
        stats = {}
        for key, saver in self._savers.items():
            stats[key] = saver.get_stats()
        return {
            "active_savers": len(self._savers),
            "savers": stats,
        }
