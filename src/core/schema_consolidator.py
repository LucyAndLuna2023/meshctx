"""Schema Consolidator — 图式化三层收敛管线 (phase-2, task 4).

对标 Mem0 consolidate：把零散情景记忆收敛为可复用的语义/核心层。

设计（MeshCtx 第二阶段实施计划 任务④，对应理论：图式 Schank & Abelson 1977
+ 加工深度 Craik & Lockhart 1972）：

    原始记忆流
       │  情景层 Episodic（保留原始事件，短期）
       ▼
    schema 抽取器（启发式主题 + 摘要）
       │  语义层 Semantic（事实/规律去重合并，"10 条会议 → 1 条结论"）
       ▼
    核心层 Core（高频语义模式 → 原则/偏好/习惯）

规则：
  - 触发：同主题记忆 ≥ 3 条 → 后台合并为 1 条语义摘要（原始保留在情景层并降权）
  - 去重：embedding 相似度 > 0.85 + 同实体 → 视为重复，按"最新 + 最详细"保留
  - 降权：合并后情景层条目 importance 减半、FSRS stability 继承语义层（不重新学习）

本模块为纯函数、零外部依赖（不调用 LLM），便于单元测试与可回滚。
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Iterable

# ── 三层 schema 标签 ────────────────────────────────────────────
SCHEMA_EPISODIC = "episodic"   # 情景层：原始事件
SCHEMA_SEMANTIC = "semantic"   # 语义层：事实/规律（去重合并后）
SCHEMA_CORE = "core"           # 核心层：原则/偏好/习惯（高频语义模式）

# ── 默认参数 ────────────────────────────────────────────────────
DEFAULT_SIM_THRESHOLD = 0.85   # 相似度 ≥ 阈值 + 同主题 → 去重
DEFAULT_GROUP_MIN = 3          # 同主题 ≥ N 条 → 触发合并
DEFAULT_CORE_MIN_FREQ = 2      # 同主题语义层 ≥ N 次 → 提升为核心层
MAX_IMPORTANCE = 1.0

_STOPWORDS = {
    "的", "了", "是", "在", "我", "们", "你", "他", "她", "它", "这", "那",
    "有", "和", "就", "不", "人", "都", "一", "一个", "也", "很", "会", "要",
    "the", "a", "an", "and", "or", "is", "are", "was", "to", "of", "in",
    "for", "on", "with", "that", "this", "it", "we", "you", "they",
}


# ── 主题抽取（启发式，零依赖） ──────────────────────────────────
def extract_theme(item) -> str:
    """从单条记忆提取主题键。

    优先级：① entities 中首个实体 → "entity:<名>"
            ② value/content 高频 token（≥2 字符）→ "topic:<词>"
    无可用信息 → "topic:general"
    P3-2: 输出前经同义词归一化（周会/会议/例会 → meeting 组），
    避免同主题变体分到不同组导致收敛效率下降。
    """
    get = item.get if isinstance(item, dict) else lambda k, d=None: getattr(item, k, d)
    entities = list(get("entities", None) or [])
    if entities:
        name = str(entities[0]).strip()
        if name:
            return _normalize_theme(f"entity:{name[:48]}")

    text = str(get("value", "") or get("content", "") or "")
    tokens = _tokenize(text)
    if tokens:
        top_word, cnt = tokens[0]
        return _normalize_theme(f"topic:{top_word[:48]}")
    return "topic:general"


# ── P3-2 同义词归一化（002 审计建议） ──────────────────────────
# 同主题变体（中英常用业务词）→ 规范键，使 '周会/会议/例会' 收敛到同一组。
SYNONYM_CANON = {
    # 会议
    "周会": "meeting", "例会": "meeting", "会议": "meeting", "早会": "meeting",
    "meeting": "meeting", "standup": "meeting",
    # 发布/部署
    "部署": "release", "发布": "release", "上线": "release", "灰度": "release",
    "release": "release", "deploy": "release",
    # 预算
    "预算": "budget", "预算审批": "budget", "budget": "budget",
    # 用户
    "用户": "user", "客户": "user", "user": "user", "customer": "user",
    # 测试
    "测试": "testing", "回归": "testing", "test": "testing",
    # 文档
    "文档": "doc", "doc": "doc", "documentation": "doc",
    # 招聘
    "招聘": "hiring", "面试": "hiring", "hiring": "hiring", "interview": "hiring",
    # 代码
    "代码": "code", "code": "code",
}


def _normalize_theme(theme: str) -> str:
    """主题键同义词归一化：'entity:周会' → 'entity:meeting'；'topic:发布新版' → 'topic:release'。"""
    prefix, _, stem = theme.partition(":")
    s = stem.strip().lower()
    if s in SYNONYM_CANON:
        return f"{prefix}:{SYNONYM_CANON[s]}"
    # 包含匹配（token 片段含同义词，如 '发布新版' 含 '发布'）→ 取首个命中规范键
    for k, canon in SYNONYM_CANON.items():
        if k and k in s:
            return f"{prefix}:{canon}"
    return theme


def _tokenize(text: str) -> list[tuple[str, int]]:
    """高频 token 抽取（中英混合，≥2 字符，过滤停用词/纯数字）。"""
    # 中文：2-4 字词；英文：字母数字词
    zh_tokens = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    en_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]{1,20}", text.lower())
    tokens = [t for t in zh_tokens + en_tokens if t not in _STOPWORDS]
    if not tokens:
        return []
    return Counter(tokens).most_common(10)


def _is_text_duplicate(a: str, b: str) -> bool:
    """文本近重复判定：互为子串包含（a in b or b in a）。

    与 embedding 语义相似不同，这仅在字面层面判"几乎同一句话"，
    避免把同主题不同要点（"主题A点0" vs "主题A点1"）误判为重复。
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a


def _embedding_similarity(a, b) -> float:
    """向量余弦相似度（维度不一致按最短对齐）。"""
    ea = list(getattr(a, "embedding", None) or [])
    eb = list(getattr(b, "embedding", None) or [])
    if not ea or not eb:
        return 0.0
    n = min(len(ea), len(eb))
    ea, eb = ea[:n], eb[:n]
    dot = sum(x * y for x, y in zip(ea, eb))
    na = math.sqrt(sum(x * x for x in ea))
    nb = math.sqrt(sum(y * y for y in eb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ── 分组 ─────────────────────────────────────────────────────────
def group_by_theme(items: Iterable, group_min: int = DEFAULT_GROUP_MIN) -> dict[str, list]:
    """按主题分组，仅返回达到合并触发阈值（≥ group_min）的组。"""
    groups: dict[str, list] = {}
    for it in items:
        theme = extract_theme(it)
        groups.setdefault(theme, []).append(it)
    return {k: v for k, v in groups.items() if len(v) >= group_min}


# ── 去重（最新 + 最详细） ───────────────────────────────────────
def _informativeness(item) -> float:
    """信息量评分：内容长度 + 复习次数（去重时保留更详细/更被使用的）。"""
    text = str(getattr(item, "value", "") or getattr(item, "content", "") or "")
    return float(len(text)) + 50.0 * float(getattr(item, "review_count", 0) or 0)


def deduplicate(
    items: list,
    sim_threshold: float = DEFAULT_SIM_THRESHOLD,
) -> list:
    """同主题内去重：相似度 ≥ 阈值（embedding 优先，文本兜底）→ 合并为一条。

    保留策略：最新（last_reviewed/created_at 最大）+ 最详细（信息量最大）。
    返回去重后的新列表（不修改入参对象）。
    """
    kept: list = []
    for item in items:
        merged = False
        for ex in kept:
            sim = _embedding_similarity(ex, item)
            if sim >= sim_threshold:
                merged = True
            else:
                merged = _is_text_duplicate(
                    str(getattr(ex, "value", "") or getattr(ex, "content", "")),
                    str(getattr(item, "value", "") or getattr(item, "content", "")),
                )
            if merged:
                # 合并到信息量更大的一条（保留引用，后续降权用原 id）
                if _informativeness(item) > _informativeness(ex):
                    _absorb(ex, item)
                    kept[kept.index(ex)] = item
                else:
                    _absorb(item, ex)
                break
        if not merged:
            kept.append(item)
    return kept


def _absorb(keep, other) -> None:
    """把 other 的元信息并入 keep（importance 取并集、tags/entities 合并、复习数累加）。"""
    keep.importance = min(MAX_IMPORTANCE, float(keep.importance or 0) + float(other.importance or 0))
    keep.review_count = int(keep.review_count or 0) + int(other.review_count or 0)
    keep.lapses = int(keep.lapses or 0) + int(other.lapses or 0)
    keep.tags = _union(getattr(keep, "tags", None), getattr(other, "tags", None))
    keep.entities = _union(getattr(keep, "entities", None), getattr(other, "entities", None))
    rel = list(getattr(keep, "related_memory_ids", None) or [])
    for oid in (getattr(other, "related_memory_ids", None) or []):
        if oid not in rel:
            rel.append(oid)
    keep.related_memory_ids = rel


def _union(a, b) -> list:
    out = list(a or [])
    for x in (b or []):
        if x not in out:
            out.append(x)
    return out


# ── 语义层合并 ───────────────────────────────────────────────────
def merge_to_semantic(group: list) -> object:
    """把一组情景记忆合并为 1 条语义层摘要。

    摘要文本：主题 + 去重后的要点（取信息量最大的 2 条，去尾）。
    importance：组内最大（封顶 1.0）；stability：组内最大（不重新学习）。
    related_memory_ids：组内全部原 id（可回滚溯源）。
    """
    from .memory_hierarchy import MemoryItem

    theme = extract_theme(group[0])
    sorted_by_info = sorted(group, key=_informativeness, reverse=True)
    top = sorted_by_info[:2]

    points = []
    seen = set()
    for it in top:
        text = str(getattr(it, "value", "") or getattr(it, "content", "") or "").strip()
        key = text[:80]
        if text and key not in seen:
            seen.add(key)
            points.append(text)
    body = "；".join(points)
    if len(body) > 600:
        body = body[:597] + "…"

    semantic = MemoryItem(
        level=None,  # 沿用 store 默认层级逻辑，schema_layer 单独标注
        key=f"schema:{theme}",
        value=f"[{theme}] {body}" if body else f"[{theme}]",
        summary=f"语义层合并摘要（{len(group)} 条情景记忆收敛）",
        importance=min(MAX_IMPORTANCE, max(float(it.importance or 0) for it in group)),
        confidence=max(float(getattr(it, "confidence", 0) or 0) for it in group),
        tags=_union(None, [t for it in group for t in (getattr(it, "tags", None) or [])]),
        entities=_union(None, [e for it in group for e in (getattr(it, "entities", None) or [])]),
        related_memory_ids=[it.id for it in group],
        created_at=min(float(it.created_at or 0) for it in group),
    )
    semantic.schema_layer = SCHEMA_SEMANTIC
    # FSRS：继承组内最大 stability（不重新学习），difficulty 取均值
    semantic.stability = max(float(it.stability or 24.0) for it in group)
    semantic.difficulty = sum(float(it.difficulty or 5.0) for it in group) / len(group)
    semantic.next_review = max(float(it.next_review or 0) for it in group)
    semantic.last_reviewed = max(float(it.last_reviewed or 0) for it in group)
    return semantic


# ── 核心层提升 ───────────────────────────────────────────────────
def promote_to_core(
    semantic_items: list,
    min_freq: int = DEFAULT_CORE_MIN_FREQ,
) -> list:
    """高频语义模式 → 核心层原则/偏好/习惯（≥ min_freq 次同主题）。"""
    from .memory_hierarchy import MemoryItem

    freq: Counter = Counter(extract_theme(it) for it in semantic_items)
    out = []
    for theme, cnt in freq.items():
        if cnt < min_freq:
            continue
        members = [it for it in semantic_items if extract_theme(it) == theme]
        refs = [it.id for it in members]
        core = MemoryItem(
            key=f"core:{theme}",
            value=f"[原则] {theme}（由 {cnt} 条语义层记忆归纳）",
            summary=f"核心层原则：{theme} 高频出现 {cnt} 次",
            importance=min(MAX_IMPORTANCE, max(float(it.importance or 0) for it in members) + 0.1),
            tags=_union(None, [t for it in members for t in (getattr(it, "tags", None) or [])]),
            entities=_union(None, [e for it in members for e in (getattr(it, "entities", None) or [])]),
            related_memory_ids=refs,
        )
        core.schema_layer = SCHEMA_CORE
        core.stability = max(float(it.stability or 24.0) for it in members)
        out.append(core)
    return out


# ── 主入口（纯函数） ─────────────────────────────────────────────
def consolidate(
    items: list,
    sim_threshold: float = DEFAULT_SIM_THRESHOLD,
    group_min: int = DEFAULT_GROUP_MIN,
    core_min_freq: int = DEFAULT_CORE_MIN_FREQ,
) -> tuple[list, dict]:
    """图式化三层收敛主入口（纯函数，不修改入参对象）。

    流程：
      1. 按主题分组（≥ group_min 条才触发）
      2. 组内去重（相似度 ≥ sim_threshold）
      3. 每组 → 1 条语义层摘要
      4. 语义层高频主题 → 核心层原则
      5. 被合并的情景层条目 importance 减半（降权）

    返回：(新条目列表, stats)。新条目列表 = 情景层(降权副本) + 语义层 + 核心层。
    """
    import copy

    stats = {
        "grouped_themes": 0,
        "grouped_items": 0,
        "deduped": 0,
        "semantic_created": 0,
        "core_created": 0,
        "episodic_demoted": 0,
        "episodic_kept": 0,
        "semantic_kept": 0,
        "core_kept": 0,
    }

    episodic_in = [it for it in items if getattr(it, "schema_layer", SCHEMA_EPISODIC) != SCHEMA_SEMANTIC]
    semantic_in = [it for it in items if getattr(it, "schema_layer", SCHEMA_EPISODIC) == SCHEMA_SEMANTIC]

    groups = group_by_theme(episodic_in, group_min=group_min)
    stats["grouped_themes"] = len(groups)

    merged_ids: set[str] = set()
    semantic_created: list = []
    for theme, members in groups.items():
        stats["grouped_items"] += len(members)
        deduped = deduplicate(members, sim_threshold=sim_threshold)
        stats["deduped"] += len(members) - len(deduped)
        if len(deduped) >= group_min:
            sem = merge_to_semantic(deduped)
            semantic_created.append(sem)
            stats["semantic_created"] += 1
            merged_ids.update(it.id for it in members)

    core_created = promote_to_core(semantic_created + semantic_in, min_freq=core_min_freq)
    stats["core_created"] = len(core_created)

    # 情景层：被合并的降权（importance 减半）；未合并的保留
    episodic_out: list = []
    for it in episodic_in:
        new_it = copy.copy(it)
        if new_it.id in merged_ids:
            new_it.importance = max(0.05, float(new_it.importance or 0) * 0.5)
            stats["episodic_demoted"] += 1
        else:
            stats["episodic_kept"] += 1
        episodic_out.append(new_it)

    semantic_out: list = []
    for it in semantic_in:
        semantic_out.append(copy.copy(it))
    stats["semantic_kept"] = len(semantic_out)

    # 新增语义层若无同名主题旧条目，追加
    existing_keys = {it.key for it in semantic_out}
    for sem in semantic_created:
        if sem.key not in existing_keys:
            semantic_out.append(sem)
            existing_keys.add(sem.key)

    # 核心层：去重（同 key 保留新生成的，旧的核心条目保留）
    core_out = [copy.copy(it) for it in items if getattr(it, "schema_layer", None) == SCHEMA_CORE]
    stats["core_kept"] = len(core_out)
    core_keys = {it.key for it in core_out}
    for c in core_created:
        if c.key not in core_keys:
            core_out.append(c)
            core_keys.add(c.key)

    return episodic_out + semantic_out + core_out, stats


# ── Store 集成入口（非纯，操作 HierarchicalMemoryStore） ────────
def run_consolidation(store, **kw) -> dict:
    """对 store 执行一次收敛：取全部条目 → consolidate → 写回。

    写回策略：
      - 降权/保留的情景层：更新原条目字段（store 内就地）
      - 新增语义层/核心层：store.store() 落库
    返回 stats dict。
    """
    items = [it for _, it in store._all_items()]
    if not items:
        return {"skipped": True, "reason": "empty store"}
    new_items, stats = consolidate(items, **kw)
    # 情景层：原 id 已存在 → 更新字段；语义/核心：新增 → store
    for it in new_items:
        existing = store._items.get(it.id)
        if existing is not None:
            existing.importance = it.importance
            existing.stability = it.stability
            existing.difficulty = it.difficulty
            existing.next_review = it.next_review
            existing.last_reviewed = it.last_reviewed
            existing.review_count = it.review_count
            existing.lapses = it.lapses
            existing.tags = list(it.tags or [])
            existing.entities = list(it.entities or [])
            existing.related_memory_ids = list(it.related_memory_ids or [])
            existing.schema_layer = it.schema_layer
            existing.value = it.value
            existing.summary = it.summary
        else:
            store.store(it)
    stats["total_items_after"] = len(store._items)
    return stats


__all__ = [
    "SCHEMA_EPISODIC", "SCHEMA_SEMANTIC", "SCHEMA_CORE",
    "DEFAULT_SIM_THRESHOLD", "DEFAULT_GROUP_MIN", "DEFAULT_CORE_MIN_FREQ",
    "extract_theme", "group_by_theme", "deduplicate",
    "merge_to_semantic", "promote_to_core", "consolidate", "run_consolidation",
]
