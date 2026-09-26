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


# ── Phase 1 深化: registry 接线 + 降级链 + token 计量 ──────────

_L2_SIGNATURES = ("opus", "gpt-4o", "gpt-4.1", "claude", "gemini-2.5-pro", "deepseek-v4-pro", "o1", "o3")


def resolve_models(registry=None) -> Dict[str, str]:
    """从 model_registry 解析三级实际可用模型 (含降级链):

    L0 = provider=ollama 的已配置条目 (本地零 token)
    L1 = registry 默认模型 (云中档主力)
    L2 = 已配置条目中匹配旗舰签名的第一个
    降级: L0 缺→用 L1; L1 缺→用 L2; 全缺→空串 (调用方决定禁用/直连)。
    """
    env_models = {t: os.environ.get(f"MESHCTX_{t}_MODEL", "") for t in TIERS}
    models = {t: "" for t in TIERS}
    try:
        if registry is None:
            from src.model_registry import get_registry
            registry = get_registry()
        entries = getattr(registry, "_entries", {}) or {}
        default = getattr(registry, "_default", "") or ""
        # L0: ollama 条目
        for mid, info in entries.items():
            if info.get("provider") == "ollama":
                models["L0"] = mid
                break
        # L1: registry 默认
        if default:
            models["L1"] = default
        # L2: 旗舰签名
        for mid in entries:
            low = mid.lower()
            if any(s in low for s in _L2_SIGNATURES):
                models["L2"] = mid
                break
    except Exception:
        pass
    # 合成: env 显式指定 > registry 解析
    for t in TIERS:
        models[t] = env_models.get(t) or models.get(t) or ""
    # 降级链 (仅对未显式指定的档位)
    for t in TIERS:
        if models[t]:
            break
    for t in reversed(TIERS):
        if models[t]:
            top = models[t]
    if not models["L0"]:
        models["L0"] = models["L1"] or models["L2"] or ""
    if not models["L1"]:
        models["L1"] = models["L2"] or ""
    return models


class CascadeUsage:
    """per-tier token 计量器 (看板数据源)。

    saved_tokens = 反事实估算: L0 处理的量若走 L2 的等效成本,
    按 L0:L2 价差倍率 (默认 50x) 折算 — 看板展示"节省"。
    """

    L0_SAVING_FACTOR = int(os.environ.get("MESHCTX_L0_SAVING_FACTOR", "50"))

    def __init__(self):
        self._by_tier: Dict[str, Dict[str, int]] = {t: {"calls": 0, "tokens": 0} for t in TIERS}

    def record(self, tier: str, tokens: int) -> None:
        if tier in self._by_tier and tokens >= 0:
            self._by_tier[tier]["calls"] += 1
            self._by_tier[tier]["tokens"] += tokens

    def report(self) -> Dict[str, Any]:
        total = sum(v["tokens"] for v in self._by_tier.values())
        l0_tokens = self._by_tier["L0"]["tokens"]
        return {"by_tier": {k: dict(v) for k, v in self._by_tier.items()},
                "total_tokens": total,
                "saved_tokens_estimate": l0_tokens * self.L0_SAVING_FACTOR}


_usage = CascadeUsage()


def record_usage(tier: str, tokens: int) -> None:
    """模块级计量入口 (chat 端点接线用)。"""
    _usage.record(tier, tokens)


def usage_report() -> Dict[str, Any]:
    return _usage.report()


# ── Phase 1 收尾: chat 端点接线 ────────────────────────────────

_TOOLS_RE = re.compile(
    r"文件|执行|运行|命令|搜索|搜索|查看|读取|打开|终端|shell|terminal|"
    r"file|run|exec|search|browse|command|script|部署|安装|删除|写入", re.I)


def needs_tools(text: str) -> bool:
    """消息是否隐含工具/执行意图 (简单规则; 误判安全: 误判 True→至少 L1)."""
    return bool(text) and bool(_TOOLS_RE.search(text))


def pick_model_for_message(message: str, requested_model: str = "",
                           registry=None, cascade_on: bool = None) -> Dict[str, object]:
    """chat 端点模型选择入口 (v6.1 接线, 安全设计):

    · 用户显式指定模型 (下拉选择) → 原样返回, 级联不介入
    · MESHCTX_CASCADE=0 → 回落 registry 默认 (旧行为)
    · 级联开启 → 分级 (needs_tools 决定工具下限) + resolve_models 降级链
      (无本地模型时 L0 降级 L1=默认 → 行为与旧版完全等价, 零风险)
    """
    if requested_model and str(requested_model).strip():
        return {"tier": "user", "model": requested_model,
                "reason": "用户显式指定, 级联不介入"}
    if cascade_on is None:
        cascade_on = os.environ.get("MESHCTX_CASCADE", "1") not in ("0", "false", "no")
    if not cascade_on:
        return {"tier": "default", "model": "",
                "reason": "级联关闭 → 调用方回落 registry 默认 (旧行为等价)"}
    needs = needs_tools(message or "")
    tier = classify_task(message or "", has_tools=needs)
    models = resolve_models(registry)
    model = models.get(tier) or models.get("L1") or models.get("L2") or ""
    return {"tier": tier, "model": model,
            "reason": _reason(tier, message or "", needs) if cascade_on else "级联关闭, 默认模型"}
