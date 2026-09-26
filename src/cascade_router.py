# -*- coding: utf-8 -*-
"""meshctx SMA Phase 1 — 级联路由器 (Cascade Router, v7 方向).

目标 (用户定稿 2026-09-22): 开源弱模型 + meshctx ≈ 强模型效果;
本地预处理省 token; 本地小模型处理大任务。

三级模型梯度:
  L0 本地小模型 (Ollama qwen3 等) — 摘要/分类/格式化/改写/简单问答, 零 API token
  L1 云中档 (deepseek-flash 等已配置主力) — 常规对话/代码
  L2 旗舰 (opus/gpt 级) — 复杂推理/架构

本模块 (Phase 1) 为纯规则分级器 + 路由决策; LLM 分类器与置信度升级
(Phase 2 验证器联动) 在后续版本接入。显式用户指定永远优先。

守门: tests/test_cascade_router.py
"""
import os
import re
from typing import Dict, Optional

TIERS = ("L0", "L1", "L2")

# 默认模型解析 (运行时从 model_registry 解析; 此处只声明梯度语义)
DEFAULT_MODELS = {
    "L0": os.environ.get("MESHCTX_L0_MODEL", "ollama:qwen3"),
    "L1": os.environ.get("MESHCTX_L1_MODEL", ""),
    "L2": os.environ.get("MESHCTX_L2_MODEL", ""),
}

import os  # noqa: E402  (DEFAULT_MODELS 之后保持集中可读)

# ── L0 信号: 短小/机械/格式化 ──────────────────────────────
_L0_PATTERNS = [
    re.compile(r"^(?:hi|hello|你好|嗨|在吗|thanks|谢谢|ok|好的)[\s!!！.。？?]*$", re.I),
    re.compile(r"^(?:翻译|translate|总结|summarize|摘要|改写|润色|格式化|classify|分类)\b", re.I),
]
_L0_MAX_CHARS = 500  # 超长直接排除 L0

# ── L2 信号: 复杂推理/架构/多文件/深度分析 ─────────────────
_L2_PATTERNS = [
    re.compile(r"架构|architecture|系统设计|system design|重构|refactor", re.I),
    re.compile(r"为什么|why|根因|root cause|推导|prove|证明|权衡|trade-?off", re.I),
    re.compile(r"多文件|跨模块|codebase|全面审查|深度分析|in depth", re.I),
    re.compile(r"规划|roadmap|战略|strategy|对比分析", re.I),
]
_L2_MIN_CHARS = 800  # 长文分析倾向 L2

# ── L1 信号 (默认档): 显式任务词 ────────────────────────────
_L1_PATTERNS = re.compile(r"写|实现|implement|fix|修|bug|脚本|script|函数|function|api", re.I)


def classify_task(text: str, has_tools: bool = False) -> str:
    """规则分级器 → "L0" | "L1" | "L2"。

    优先级: L2 信号 > L0 信号 > L1 默认。
    has_tools=True (需要工具循环/多步执行) 时不低于 L1。
    """
    if not text or not text.strip():
        return "L1"
    t = text.strip()
    n = len(t)

    for p in _L2_PATTERNS:
        if p.search(t):
            return "L2"
    if n >= _L2_MIN_CHARS:
        return "L2"

    if has_tools:
        return "L1"  # 工具任务至少 L1 (L0 工具循环可靠性不足, Phase 2 再放开)

    for p in _L0_PATTERNS:
        if p.search(t):
            return "L0"
    if n <= _L0_MAX_CHARS and not _L1_PATTERNS.search(t):
        return "L0"
    return "L1"


def route(task_text: str, has_tools: bool = False,
          models: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """路由决策: 分级 + 模型解析 + 理由。显式指定 (models) 永远优先。"""
    tier = classify_task(task_text, has_tools=has_tools)
    m = {**DEFAULT_MODELS, **(models or {})}
    return {
        "tier": tier,
        "model": m.get(tier) or "",
        "reason": _reason(tier, task_text, has_tools),
    }


def _reason(tier: str, text: str, has_tools: bool) -> str:
    if tier == "L2":
        return "复杂/长文/架构信号 → 旗舰"
    if tier == "L0":
        return "短小机械任务 → 本地小模型 (零 API token)"
    if has_tools:
        return "工具循环任务 → 中档起步"
    return "常规任务 → 中档"


def should_escalate(fail_count: int, validation_failed: bool = False) -> bool:
    """升级触发 (Phase 2 验证器联动入口): 失败≥2 或校验失败即升级一档。"""
    return fail_count >= 2 or bool(validation_failed)
