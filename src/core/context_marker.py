"""Epigenetic Context Marker — 表观遗传语境标记 (phase-2, task 5).

对应理论：22 表观遗传与记忆（Miller & Sweatt 2007）。
对标：Mem0 语境感知裁剪 —— 不是"什么记忆重要"，而是"什么记忆对当前语境重要"。

类比表观遗传（不改 DNA 序列，只改表达）：
  - 语境标记 context_tags = 表观遗传修饰（甲基化/乙酰化）
    —— 不改变记忆内容本身，只改变检索/注入概率
  - 命中强化 = 甲基化 +（该语境下更容易被提取）
  - 未命中衰减 = 去甲基化 -（逐渐沉默）
  - 权重设上下限 + 定期衰减 → 防过拟合当前会话

检索公式（16KB 预算裁剪）：
    context_score = base_importance × 0.3 + ctx_match × 0.7
    （权重常量可被 CMA-ES 优化替换）

本模块核心函数为纯函数（不修改入参），便于测试与可回滚。
"""
from __future__ import annotations

import re
from typing import Iterable

# ── 常量（权重可被 CMA-ES 优化） ─────────────────────────────────
BASE_W = 0.3        # base importance 权重
CTX_W = 0.7         # 语境匹配权重
MARK_MIN = 0.05     # 标记权重下限（防过拟合，沉默但不消失）
MARK_MAX = 1.0      # 标记权重上限
DECAY = 0.05        # 定期衰减步长（未使用标记缓慢降低表达）

# 关键词 → 语境标记（启发式映射，覆盖常用话题）
_KEYWORD_TAGS: dict[str, str] = {
    "deploy": "task:deploy", "部署": "task:deploy",
    "release": "task:release", "上线": "task:release",
    "bug": "task:debug", "fix": "task:debug", "修": "task:debug",
    "test": "task:testing", "测试": "task:testing",
    "meeting": "task:meeting", "会议": "task:meeting",
    "budget": "topic:budget", "预算": "topic:budget",
    "plan": "topic:planning", "计划": "topic:planning",
    "style": "user_style:formal", "正式": "user_style:formal",
    "python": "tech:python", "redis": "tech:redis", "docker": "tech:docker",
    "fsrs": "tech:fsrs", "memory": "topic:memory", "记忆": "topic:memory",
}


def extract_context_markers(text: str | None = None, hint: str | None = None) -> dict:
    """从文本/意图 hint 提取语境标记 {tag: weight}（启发式，纯函数）。

    - hint：显式意图/任务标记（如 "deploy"），权重 1.0
    - text：关键词映射（中英），每命中一次权重 +1.0（封顶见调用方归一化）
    """
    tags: dict[str, float] = {}
    if hint:
        for h in re.split(r"[\s,，;；]+", hint.strip()):
            if h:
                tags[f"intent:{h}"] = 1.0
    if text:
        low = text.lower()
        for kw, tag in _KEYWORD_TAGS.items():
            if kw in low:
                tags[tag] = tags.get(tag, 0.0) + 1.0
    return tags


def merge_active_context(text: str | None = None, hint: str | None = None) -> dict:
    """当前会话语境标记合并（同一标记权重取 max，覆盖到 [0, MARK_MAX]）。"""
    tags = extract_context_markers(text=text, hint=hint)
    return {k: min(MARK_MAX, v) for k, v in tags.items()}


def context_match(item, active_context: dict) -> float:
    """item.context_tags 与当前语境的加权重合度（Jaccard 加权）。

    权重 = item 侧标记强度 × 语境侧强度，求和后除以 item 侧总和（归一化 0-1）。
    无任何标记 → 0.0。
    """
    if not active_context:
        return 0.0
    tags = getattr(item, "context_tags", None) or {}
    if not tags:
        return 0.0
    inter = 0.0
    total = 0.0
    for tag, w in tags.items():
        w = float(w)
        total += w
        if tag in active_context:
            inter += w * min(1.0, float(active_context[tag]))
    return inter / total if total > 0 else 0.0


def _base_score(item) -> float:
    """base importance：用 importance（稳定，不随时间抖动）。

    语境排序的 base 应与"到期紧迫度"解耦——紧迫度已由无 context 路径
    的 review_urgency 负责；语境路径聚焦"当前语境相关优先"。
    """
    return float(getattr(item, "importance", 0.5) or 0.5)


def context_score(item, active_context: dict, base_w: float = BASE_W, ctx_w: float = CTX_W) -> float:
    """context_score = base_importance × base_w + ctx_match × ctx_w。

    无 active_context → 退化为纯 base（向后兼容全局排序）。
    """
    if not active_context:
        return _base_score(item)
    return _base_score(item) * base_w + context_match(item, active_context) * ctx_w


def rank_by_context(
    items: Iterable,
    active_context: dict,
    base_w: float = BASE_W,
    ctx_w: float = CTX_W,
) -> list[tuple]:
    """按语境条件分数降序排序（非全局分数）。

    返回 [(item, score), ...]，供 retrieve() 在 16KB 预算下裁剪注入。
    """
    scored = [
        (it, context_score(it, active_context, base_w=base_w, ctx_w=ctx_w))
        for it in items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def update_markers(
    item,
    active_context: dict,
    hit: bool,
    delta: float = 0.1,
    decay: float = DECAY,
) -> dict:
    """标记更新（表观遗传类比，纯函数返回新 dict，不修改入参）。

    - 命中且语境标记在 item 上：该标记权重 + delta（甲基化，封顶 MARK_MAX）
    - 未命中：item 上所有与语境相关的标记 - decay（去甲基化，下限 MARK_MIN）
    返回更新后的 context_tags 副本。
    """
    tags = dict(getattr(item, "context_tags", None) or {})
    if not active_context:
        return tags
    if hit:
        for tag in active_context:
            if tag in tags:
                tags[tag] = min(MARK_MAX, tags[tag] + delta)
    else:
        for tag in active_context:
            if tag in tags:
                tags[tag] = max(MARK_MIN, tags[tag] - decay)
    return tags


def auto_tag_item(item) -> dict:
    """从记忆元数据自动打语境标记（入库钩子用）。

    从 value/content 关键词 + source/project_id 生成初始 context_tags。
    返回新 dict（不修改入参）。
    """
    tags: dict[str, float] = {}
    text = str(getattr(item, "value", "") or getattr(item, "content", "") or "")
    extracted = extract_context_markers(text=text)
    for k, v in extracted.items():
        tags[k] = max(tags.get(k, 0.0), v)
    src = str(getattr(item, "source", "") or "").strip()
    if src:
        tags[f"source:{src}"] = 1.0
    pid = str(getattr(item, "project_id", "") or "").strip()
    if pid:
        tags[f"project:{pid}"] = 1.0
    return {k: min(MARK_MAX, v) for k, v in tags.items()}


__all__ = [
    "BASE_W", "CTX_W", "MARK_MIN", "MARK_MAX", "DECAY",
    "extract_context_markers", "merge_active_context", "context_match",
    "context_score", "rank_by_context", "update_markers", "auto_tag_item",
]
