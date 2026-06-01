"""
meshctx v3.108 — Memory Compactor (记忆压缩器)

Advanced memory management with:
  1. 智能摘要压缩 — Multi-strategy intelligent summarization
  2. 重要性评分 — Multi-factor importance scoring with decay
  3. 分层存储(hot/warm/cold) — Automatic tiered storage migration
  4. 检索优化 — Importance-weighted retrieval with caching
"""

import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections import defaultdict, deque, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.memory_compactor")


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class MemoryTier(Enum):
    """记忆层级"""
    HOT = "hot"        # 热记忆: 频繁访问, 高重要性
    WARM = "warm"      # 温记忆: 中等访问, 中等重要性
    COLD = "cold"      # 冷记忆: 很少访问, 低重要性


class CompressionStrategy(Enum):
    """压缩策略"""
    EXTRACTIVE = "extractive"          # 提取关键词句
    ABSTRACTIVE = "abstractive"        # 生成式摘要
    PROGRESSIVE = "progressive"        # 渐进式多层压缩
    MERGE = "merge"                    # 合并相似记忆
    TRUNCATE = "truncate"              # 截断长内容


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """单个记忆条目"""
    memory_id: str = ""
    content: str = ""
    summary: str = ""                          # 压缩后的摘要
    importance_score: float = 50.0             # 重要性评分 (0-100)
    tier: str = MemoryTier.HOT.value           # 当前层级
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    compression_level: int = 0                 # 压缩级别 (0=原始, 1=轻量, 2=中等, 3=深度)
    parent_ids: List[str] = field(default_factory=list)  # 合并来源
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(
                self.content.encode()
            ).hexdigest()[:16]

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_accessed

    @property
    def is_compressed(self) -> bool:
        return self.compression_level > 0


@dataclass
class CompactionResult:
    """压缩操作结果"""
    strategy: str = ""
    original_size: int = 0                     # 原始字符数
    compressed_size: int = 0                   # 压缩后字符数
    compression_ratio: float = 0.0             # 压缩比
    before_score: float = 0.0
    after_score: float = 0.0
    entries_affected: int = 0
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TierMigrationResult:
    """层级迁移结果"""
    hot_to_warm: int = 0
    warm_to_cold: int = 0
    cold_to_warm: int = 0
    warm_to_hot: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RetrievalResult:
    """检索结果"""
    query: str = ""
    entries: List[MemoryEntry] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)  # memory_id → relevance
    total_candidates: int = 0
    retrieval_time_ms: float = 0.0
    tiers_searched: List[str] = field(default_factory=list)


@dataclass
class CompactionStats:
    """压缩统计"""
    total_entries: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0
    total_chars: int = 0
    total_compressed_chars: int = 0
    avg_importance: float = 0.0
    compactions_run: int = 0
    last_compaction: float = 0.0


# ═══════════════════════════════════════════════════════════
# Memory Compactor Engine
# ═══════════════════════════════════════════════════════════

class MemoryCompactor:
    """
    v3.108 记忆压缩器

    四大核心功能:
      1. 智能摘要压缩 — 多策略压缩引擎（提取/抽象/渐进/合并/截断）
      2. 重要性评分 — 多因子评分（访问频率+新近度+内容长度+标签权重+时间衰减）
      3. 分层存储(hot/warm/cold) — 自动迁移+手动升降级+阈值配置
      4. 检索优化 — 重要性加权排序+分片缓存+关键词预索引
    """

    # ── Tier thresholds ────────────────────────────────────
    DEFAULT_HOT_THRESHOLD_HOURS = 1.0           # hot: accessed within 1 hour
    DEFAULT_WARM_THRESHOLD_HOURS = 24.0         # warm: accessed within 24 hours
    DEFAULT_HOT_IMPORTANCE_MIN = 70.0           # hot: importance >= 70
    DEFAULT_WARM_IMPORTANCE_MIN = 30.0          # warm: importance >= 30

    # ── Importance weights ─────────────────────────────────
    WEIGHT_ACCESS_FREQ = 0.30
    WEIGHT_RECENCY = 0.25
    WEIGHT_CONTENT_LENGTH = 0.15
    WEIGHT_TAG_RELEVANCE = 0.15
    WEIGHT_META_BOOST = 0.10
    WEIGHT_DECAY = 0.05

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # Primary storage: tiered stores
        self._hot_store: Dict[str, MemoryEntry] = OrderedDict()
        self._warm_store: Dict[str, MemoryEntry] = OrderedDict()
        self._cold_store: Dict[str, MemoryEntry] = OrderedDict()
        self._all_entries: Dict[str, MemoryEntry] = {}  # master index

        # Retrieval cache (LRU)
        self._retrieval_cache: OrderedDict = OrderedDict()
        self._max_cache_size = self.config.get("cache_size", 128)

        # Keyword index for fast lookup
        self._keyword_index: Dict[str, Set[str]] = defaultdict(set)

        # Compaction history
        self._compaction_history: List[CompactionResult] = []
        self._migration_history: List[TierMigrationResult] = []
        self._compaction_count: int = 0
        self._last_compaction: float = 0.0

        # Configurable thresholds
        self.hot_threshold_hours = self.config.get(
            "hot_threshold_hours", self.DEFAULT_HOT_THRESHOLD_HOURS
        )
        self.warm_threshold_hours = self.config.get(
            "warm_threshold_hours", self.DEFAULT_WARM_THRESHOLD_HOURS
        )
        self.hot_importance_min = self.config.get(
            "hot_importance_min", self.DEFAULT_HOT_IMPORTANCE_MIN
        )
        self.warm_importance_min = self.config.get(
            "warm_importance_min", self.DEFAULT_WARM_IMPORTANCE_MIN
        )

        # Decay half-life (seconds) — importance halves after this
        self.decay_half_life = self.config.get("decay_half_life", 86400 * 7)  # 7 days

    # ══════════════════════════════════════════════════════
    # 1. Smart Summary Compression
    # ══════════════════════════════════════════════════════

    def _extractive_compress(self, content: str, ratio: float = 0.3) -> str:
        """提取式压缩: 保留最重要的句子"""
        sentences = re.split(r'(?<=[.!?。！？\n])\s*', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

        if len(sentences) <= 2:
            return content

        # Score each sentence by keywords and position
        scored = []
        for i, sent in enumerate(sentences):
            score = 0.0
            # Position weight: first/last sentences more important
            if i == 0:
                score += 3.0
            elif i == len(sentences) - 1:
                score += 2.0
            # Length weight: medium sentences preferred
            words = len(sent.split())
            if 5 <= words <= 30:
                score += 2.0
            # Capitalization weight
            if sent and sent[0].isupper():
                score += 1.0
            # Keyword weight
            keywords = ["important", "key", "critical", "main", "核心", "关键",
                        "summary", "conclusion", "result", "therefore"]
            for kw in keywords:
                if kw.lower() in sent.lower():
                    score += 2.0
            scored.append((sent, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        keep_count = max(1, int(len(sentences) * ratio))
        kept = [s for s, _ in scored[:keep_count]]

        # Preserve original order
        kept_sorted = sorted(kept, key=lambda s: content.index(s) if s in content else 99999)
        return " ".join(kept_sorted)

    def _abstractive_compress(self, content: str, max_length: int = 200) -> str:
        """抽象式压缩: 生成简洁摘要（启发式）"""
        # 1. Remove filler words
        filler_patterns = [
            r'\b(actually|basically|literally|really|very|quite|rather|just|simply)\b',
            r'\b(嗯|啊|嘛|吧|呢|了|的|得|地)\b',
        ]
        compressed = content
        for pattern in filler_patterns:
            compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)

        # 2. Collapse whitespace
        compressed = re.sub(r'\s+', ' ', compressed).strip()

        # 3. Truncate to max_length
        if len(compressed) > max_length:
            # Try to break at sentence boundary
            break_point = compressed.rfind('.', 0, max_length)
            if break_point == -1:
                break_point = compressed.rfind(' ', 0, max_length)
            if break_point > max_length * 0.5:
                compressed = compressed[:break_point + 1]
            else:
                compressed = compressed[:max_length] + "..."

        # 4. Add structural markers
        if len(compressed) > 50 and "\n" not in compressed:
            # Add a tl;dr style prefix for long content
            pass

        return compressed.strip()

    def _progressive_compress(self, entry: MemoryEntry) -> MemoryEntry:
        """渐进式压缩: 根据压缩级别逐级加深"""
        if entry.compression_level >= 3:
            return entry  # Already at max compression

        new_level = entry.compression_level + 1
        ratios = {1: 0.6, 2: 0.3, 3: 0.15}

        compressed = self._extractive_compress(
            entry.summary or entry.content,
            ratio=ratios.get(new_level, 0.3),
        )

        entry.summary = compressed
        entry.compression_level = new_level
        return entry

    def _merge_compress(
        self, entries: List[MemoryEntry]
    ) -> Optional[MemoryEntry]:
        """合并压缩: 将相似记忆合并为一个"""
        if len(entries) < 2:
            return None

        # Use the most recent entry as base
        entries.sort(key=lambda e: e.created_at, reverse=True)
        base = entries[0]

        combined_content = " | ".join(
            e.summary or e.content for e in entries
        )
        summary = self._extractive_compress(combined_content, ratio=0.4)

        merged = MemoryEntry(
            memory_id=self._make_id("merged"),
            content=combined_content,
            summary=summary,
            importance_score=max(e.importance_score for e in entries),
            tier=base.tier,
            created_at=base.created_at,
            last_accessed=max(e.last_accessed for e in entries),
            access_count=sum(e.access_count for e in entries),
            tags=list(set(t for e in entries for t in e.tags)),
            metadata={"merged_from": [e.memory_id for e in entries]},
            compression_level=max(e.compression_level for e in entries) + 1,
            parent_ids=[e.memory_id for e in entries],
        )
        return merged

    def _truncate_compress(self, content: str, max_chars: int = 500) -> str:
        """截断压缩: 直接截断长内容"""
        if len(content) <= max_chars:
            return content
        # Find clean break point
        truncated = content[:max_chars]
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        break_at = max(last_period, last_newline)
        if break_at > max_chars * 0.6:
            return content[:break_at + 1] + " [...]"
        return truncated + " [...]"

    def compress_memory(
        self,
        memory_id: str,
        strategy: Optional[str] = None,
        force: bool = False,
    ) -> CompactionResult:
        """
        压缩单条记忆

        Args:
            memory_id: 记忆ID
            strategy: 压缩策略 (None=自动选择最佳策略)
            force: 是否强制压缩（即使已压缩过）

        Returns:
            CompactionResult
        """
        start_time = time.time()
        entry = self._all_entries.get(memory_id)
        if entry is None:
            return CompactionResult(
                strategy=strategy or "none",
                original_size=0,
                compressed_size=0,
                details={"error": "Memory not found"},
            )

        content = entry.summary or entry.content
        original_size = len(content)

        if entry.is_compressed and not force:
            return CompactionResult(
                strategy="skip",
                original_size=original_size,
                compressed_size=original_size,
                compression_ratio=1.0,
                details={"reason": "Already compressed"},
            )

        # Auto-select strategy
        if strategy is None:
            if entry.compression_level == 0:
                strategy = CompressionStrategy.EXTRACTIVE.value
            elif entry.compression_level == 1:
                strategy = CompressionStrategy.ABSTRACTIVE.value
            else:
                strategy = CompressionStrategy.PROGRESSIVE.value

        # Apply strategy
        if strategy == CompressionStrategy.EXTRACTIVE.value:
            compressed = self._extractive_compress(content)
        elif strategy == CompressionStrategy.ABSTRACTIVE.value:
            compressed = self._abstractive_compress(content)
        elif strategy == CompressionStrategy.PROGRESSIVE.value:
            compressed = self._progressive_compress(entry).summary
        elif strategy == CompressionStrategy.TRUNCATE.value:
            compressed = self._truncate_compress(content)
        else:
            compressed = content

        compressed_size = len(compressed)
        ratio = compressed_size / max(original_size, 1)

        # Update entry
        entry.summary = compressed
        entry.compression_level = min(entry.compression_level + 1, 3)
        entry.metadata["last_compression_strategy"] = strategy
        entry.metadata["last_compressed_at"] = time.time()

        result = CompactionResult(
            strategy=strategy,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_ratio=round(ratio, 3),
            before_score=entry.importance_score,
            after_score=self.score_importance(entry),
            entries_affected=1,
            duration_ms=round((time.time() - start_time) * 1000, 2),
            details={"memory_id": memory_id, "new_level": entry.compression_level},
        )

        self._compaction_history.append(result)
        self._compaction_count += 1
        self._last_compaction = time.time()

        return result

    def compress_all(
        self,
        strategy: Optional[str] = None,
        tier: Optional[str] = None,
        min_age_hours: float = 0,
    ) -> CompactionResult:
        """批量压缩记忆"""
        start_time = time.time()
        entries = self._get_entries_by_tier(tier) if tier else list(
            self._all_entries.values()
        )

        # Filter by age
        now = time.time()
        candidates = [
            e for e in entries
            if (now - e.created_at) / 3600 >= min_age_hours
        ]

        total_original = 0
        total_compressed = 0
        affected = 0

        for entry in candidates:
            content = entry.summary or entry.content
            original_size = len(content)

            if strategy == CompressionStrategy.EXTRACTIVE.value:
                compressed = self._extractive_compress(content)
            elif strategy == CompressionStrategy.ABSTRACTIVE.value:
                compressed = self._abstractive_compress(content)
            elif strategy == CompressionStrategy.TRUNCATE.value:
                compressed = self._truncate_compress(content)
            else:
                # Auto: progressive
                self._progressive_compress(entry)
                compressed = entry.summary

            total_original += original_size
            total_compressed += len(compressed)
            entry.summary = compressed
            entry.compression_level = min(entry.compression_level + 1, 3)
            affected += 1

        ratio = total_compressed / max(total_original, 1)
        result = CompactionResult(
            strategy=strategy or "progressive",
            original_size=total_original,
            compressed_size=total_compressed,
            compression_ratio=round(ratio, 3),
            entries_affected=affected,
            duration_ms=round((time.time() - start_time) * 1000, 2),
        )

        self._compaction_history.append(result)
        self._compaction_count += 1
        self._last_compaction = time.time()

        return result

    def merge_similar(
        self, similarity_threshold: float = 0.7
    ) -> List[MemoryEntry]:
        """合并相似记忆"""
        merged_list = []
        entries = list(self._all_entries.values())
        processed: Set[str] = set()

        for i, e1 in enumerate(entries):
            if e1.memory_id in processed:
                continue
            group = [e1]
            for j, e2 in enumerate(entries):
                if j <= i or e2.memory_id in processed:
                    continue
                sim = self._compute_similarity(e1, e2)
                if sim >= similarity_threshold:
                    group.append(e2)
                    processed.add(e2.memory_id)

            if len(group) >= 2:
                merged = self._merge_compress(group)
                if merged:
                    # Remove originals
                    for e in group:
                        self._remove_from_stores(e.memory_id)
                    # Add merged
                    self._add_to_stores(merged)
                    merged_list.append(merged)
                    processed.add(e1.memory_id)

        return merged_list

    def _compute_similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        """计算两条记忆的相似度 (Jaccard on keywords)"""
        def get_keywords(entry: MemoryEntry) -> Set[str]:
            text = (entry.summary or entry.content).lower()
            words = set(re.findall(r'\b\w{3,}\b', text))
            # Add tags
            words.update(t.lower() for t in entry.tags)
            return words

        kw_a = get_keywords(a)
        kw_b = get_keywords(b)

        if not kw_a or not kw_b:
            return 0.0

        intersection = len(kw_a & kw_b)
        union = len(kw_a | kw_b)
        return intersection / union if union > 0 else 0.0

    # ══════════════════════════════════════════════════════
    # 2. Importance Scoring
    # ══════════════════════════════════════════════════════

    def score_importance(self, entry: MemoryEntry) -> float:
        """
        多因子重要性评分 (0-100)

        因子:
        - 访问频率 (30%): log-scaled access count
        - 新近度 (25%): exponential decay from last_accessed
        - 内容长度 (15%): optimal length bonus
        - 标签权重 (15%): tag count and specificity
        - 元数据加成 (10%): pinned, starred, etc.
        - 时间衰减 (5%): age-based decay
        """
        now = time.time()
        score = 0.0

        # 1. Access frequency (log-scaled)
        if entry.access_count > 0:
            freq_score = min(1.0, math.log2(entry.access_count + 1) / 10.0)
            score += freq_score * self.WEIGHT_ACCESS_FREQ * 100

        # 2. Recency (exponential decay)
        idle_hours = (now - entry.last_accessed) / 3600
        recency_score = math.exp(-idle_hours / max(self.hot_threshold_hours * 2, 1))
        score += recency_score * self.WEIGHT_RECENCY * 100

        # 3. Content length
        length = len(entry.content)
        if 100 <= length <= 5000:
            length_score = 0.8
        elif 50 <= length <= 10000:
            length_score = 0.5
        elif length < 50:
            length_score = 0.2
        else:
            length_score = 0.3
        score += length_score * self.WEIGHT_CONTENT_LENGTH * 100

        # 4. Tags
        if entry.tags:
            tag_score = min(1.0, len(entry.tags) / 10.0)
            score += tag_score * self.WEIGHT_TAG_RELEVANCE * 100

        # 5. Metadata boost
        meta_boost = 0.0
        if entry.metadata.get("pinned"):
            meta_boost += 0.5
        if entry.metadata.get("starred"):
            meta_boost += 0.3
        if entry.metadata.get("important"):
            meta_boost += 0.2
        score += meta_boost * self.WEIGHT_META_BOOST * 100

        # 6. Time decay (half-life)
        age_hours = (now - entry.created_at) / 3600
        decay = math.pow(0.5, age_hours / (self.decay_half_life / 3600))
        score -= (1 - decay) * self.WEIGHT_DECAY * 100

        return max(0.0, min(100.0, round(score, 1)))

    def recalculate_all_scores(self) -> int:
        """重新计算所有记忆的重要性评分"""
        count = 0
        for entry in self._all_entries.values():
            old_score = entry.importance_score
            new_score = self.score_importance(entry)
            if abs(old_score - new_score) > 0.1:
                entry.importance_score = new_score
                count += 1
        return count

    def boost_importance(self, memory_id: str, amount: float = 10.0) -> bool:
        """手动提升重要性"""
        entry = self._all_entries.get(memory_id)
        if entry is None:
            return False
        entry.importance_score = min(100.0, entry.importance_score + amount)
        entry.metadata["boosted"] = True
        return True

    def decay_importance(self, memory_id: str, amount: float = 5.0) -> bool:
        """手动衰减重要性"""
        entry = self._all_entries.get(memory_id)
        if entry is None:
            return False
        entry.importance_score = max(0.0, entry.importance_score - amount)
        return True

    def get_importance_report(self) -> Dict[str, Any]:
        """获取重要性分布报告"""
        scores = [e.importance_score for e in self._all_entries.values()]
        if not scores:
            return {"avg": 0, "min": 0, "max": 0, "high": 0, "medium": 0, "low": 0}

        high = sum(1 for s in scores if s >= 70)
        medium = sum(1 for s in scores if 30 <= s < 70)
        low = sum(1 for s in scores if s < 30)

        return {
            "avg": round(sum(scores) / len(scores), 1),
            "min": round(min(scores), 1),
            "max": round(max(scores), 1),
            "total": len(scores),
            "high": high,
            "medium": medium,
            "low": low,
        }

    # ══════════════════════════════════════════════════════
    # 3. Tiered Storage (hot/warm/cold)
    # ══════════════════════════════════════════════════════

    def _determine_tier(self, entry: MemoryEntry) -> str:
        """根据访问时间和重要性判断层级"""
        now = time.time()
        idle_hours = (now - entry.last_accessed) / 3600

        if idle_hours <= self.hot_threshold_hours and entry.importance_score >= self.hot_importance_min:
            return MemoryTier.HOT.value
        elif idle_hours <= self.warm_threshold_hours and entry.importance_score >= self.warm_importance_min:
            return MemoryTier.WARM.value
        else:
            return MemoryTier.COLD.value

    def _get_store(self, tier: str) -> Dict[str, MemoryEntry]:
        """获取指定层级的存储"""
        stores = {
            MemoryTier.HOT.value: self._hot_store,
            MemoryTier.WARM.value: self._warm_store,
            MemoryTier.COLD.value: self._cold_store,
        }
        return stores.get(tier, self._cold_store)

    def _add_to_stores(self, entry: MemoryEntry):
        """添加到所有存储索引"""
        self._all_entries[entry.memory_id] = entry
        store = self._get_store(entry.tier)
        store[entry.memory_id] = entry
        self._index_keywords(entry)

    def _remove_from_stores(self, memory_id: str):
        """从所有存储索引移除"""
        entry = self._all_entries.pop(memory_id, None)
        if entry:
            store = self._get_store(entry.tier)
            store.pop(memory_id, None)
        # Also check other stores
        for store in [self._hot_store, self._warm_store, self._cold_store]:
            store.pop(memory_id, None)
        self._deindex_keywords(memory_id)

    def add_memory(
        self,
        content: str,
        memory_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        initial_tier: Optional[str] = None,
    ) -> MemoryEntry:
        """
        添加新记忆

        Args:
            content: 记忆内容
            memory_id: 自定义ID (None=自动生成)
            tags: 标签列表
            metadata: 元数据
            initial_tier: 初始层级 (None=自动判断)

        Returns:
            MemoryEntry
        """
        entry = MemoryEntry(
            memory_id=memory_id or self._make_id("mem"),
            content=content,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Score importance
        entry.importance_score = self.score_importance(entry)

        # Determine tier
        entry.tier = initial_tier or self._determine_tier(entry)

        self._add_to_stores(entry)
        return entry

    def get_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        """获取记忆（含访问记录）"""
        entry = self._all_entries.get(memory_id)
        if entry:
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._update_retrieval_cache(memory_id, entry)
        return entry

    def migrate_tiers(self) -> TierMigrationResult:
        """
        自动层级迁移

        根据访问时间和重要性自动升降级记忆
        """
        result = TierMigrationResult()

        for entry in list(self._all_entries.values()):
            old_tier = entry.tier
            new_tier = self._determine_tier(entry)

            if old_tier != new_tier:
                # Remove from old store
                old_store = self._get_store(old_tier)
                old_store.pop(entry.memory_id, None)

                # Add to new store
                entry.tier = new_tier
                new_store = self._get_store(new_tier)
                new_store[entry.memory_id] = entry

                # Track migration
                if old_tier == MemoryTier.HOT.value and new_tier == MemoryTier.WARM.value:
                    result.hot_to_warm += 1
                elif old_tier == MemoryTier.WARM.value and new_tier == MemoryTier.COLD.value:
                    result.warm_to_cold += 1
                elif old_tier == MemoryTier.COLD.value and new_tier == MemoryTier.WARM.value:
                    result.cold_to_warm += 1
                elif old_tier == MemoryTier.WARM.value and new_tier == MemoryTier.HOT.value:
                    result.warm_to_hot += 1

        result.hot_count = len(self._hot_store)
        result.warm_count = len(self._warm_store)
        result.cold_count = len(self._cold_store)
        result.timestamp = time.time()

        self._migration_history.append(result)
        return result

    def promote_memory(self, memory_id: str) -> bool:
        """手动提升记忆层级 (最高到hot)"""
        entry = self._all_entries.get(memory_id)
        if entry is None:
            return False

        tiers = [MemoryTier.COLD.value, MemoryTier.WARM.value, MemoryTier.HOT.value]
        current_idx = tiers.index(entry.tier) if entry.tier in tiers else 0
        if current_idx >= len(tiers) - 1:
            return False

        old_store = self._get_store(entry.tier)
        old_store.pop(entry.memory_id, None)

        entry.tier = tiers[current_idx + 1]
        new_store = self._get_store(entry.tier)
        new_store[entry.memory_id] = entry

        # Also boost importance
        entry.importance_score = min(100.0, entry.importance_score + 15.0)
        return True

    def demote_memory(self, memory_id: str) -> bool:
        """手动降级记忆层级 (最低到cold)"""
        entry = self._all_entries.get(memory_id)
        if entry is None:
            return False

        tiers = [MemoryTier.COLD.value, MemoryTier.WARM.value, MemoryTier.HOT.value]
        current_idx = tiers.index(entry.tier) if entry.tier in tiers else 2
        if current_idx <= 0:
            return False

        old_store = self._get_store(entry.tier)
        old_store.pop(entry.memory_id, None)

        entry.tier = tiers[current_idx - 1]
        new_store = self._get_store(entry.tier)
        new_store[entry.memory_id] = entry

        entry.importance_score = max(0.0, entry.importance_score - 15.0)
        return True

    def get_tier_counts(self) -> Dict[str, int]:
        """获取各层级统计"""
        return {
            "hot": len(self._hot_store),
            "warm": len(self._warm_store),
            "cold": len(self._cold_store),
            "total": len(self._all_entries),
        }

    def get_entries_by_tier(
        self, tier: str, limit: int = 100
    ) -> List[MemoryEntry]:
        """按层级获取记忆列表"""
        store = self._get_store(tier)
        entries = list(store.values())
        entries.sort(key=lambda e: e.importance_score, reverse=True)
        return entries[:limit]

    def _get_entries_by_tier(self, tier: Optional[str]) -> List[MemoryEntry]:
        """内部方法: 获取指定层级的所有条目"""
        if tier is None:
            return list(self._all_entries.values())
        store = self._get_store(tier)
        return list(store.values())

    # ══════════════════════════════════════════════════════
    # 4. Retrieval Optimization
    # ══════════════════════════════════════════════════════

    def _index_keywords(self, entry: MemoryEntry):
        """为条目建立关键词索引"""
        text = (entry.content + " " + (entry.summary or "")).lower()
        words = set(re.findall(r'\b[a-zA-Z0-9_\u4e00-\u9fff]{2,}\b', text))
        for word in words:
            self._keyword_index[word].add(entry.memory_id)

    def _deindex_keywords(self, memory_id: str):
        """从关键词索引移除条目"""
        for word, ids in list(self._keyword_index.items()):
            ids.discard(memory_id)
            if not ids:
                del self._keyword_index[word]

    def _update_retrieval_cache(self, memory_id: str, entry: MemoryEntry):
        """更新检索缓存 (LRU)"""
        if memory_id in self._retrieval_cache:
            del self._retrieval_cache[memory_id]
        self._retrieval_cache[memory_id] = entry
        while len(self._retrieval_cache) > self._max_cache_size:
            self._retrieval_cache.popitem(last=False)

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        tier: Optional[str] = None,
        min_importance: float = 0,
        use_cache: bool = True,
    ) -> RetrievalResult:
        """
        检索记忆

        支持:
        - 关键词匹配 + 重要性加权排序
        - 按层级过滤
        - LRU缓存加速
        - 最低重要性阈值

        Args:
            query: 检索查询
            top_k: 返回条数
            tier: 限定层级 (None=所有层级)
            min_importance: 最低重要性阈值
            use_cache: 是否使用缓存

        Returns:
            RetrievalResult
        """
        start_time = time.time()

        # Try cache first
        if use_cache and query in self._retrieval_cache:
            entry = self._retrieval_cache[query]
            if self._tier_match(entry, tier) and entry.importance_score >= min_importance:
                return RetrievalResult(
                    query=query,
                    entries=[entry],
                    scores={entry.memory_id: 1.0},
                    total_candidates=1,
                    retrieval_time_ms=round((time.time() - start_time) * 1000, 2),
                    tiers_searched=[entry.tier] if tier is None else [tier],
                )

        # Keyword matching
        query_words = set(re.findall(
            r'\b[a-zA-Z0-9_\u4e00-\u9fff]{2,}\b', query.lower()
        ))

        candidates: Dict[str, float] = {}
        tiers_searched: Set[str] = set()

        for word in query_words:
            matched_ids = self._keyword_index.get(word, set())
            for mid in matched_ids:
                entry = self._all_entries.get(mid)
                if entry is None:
                    continue
                if tier and entry.tier != tier:
                    continue
                if entry.importance_score < min_importance:
                    continue
                tiers_searched.add(entry.tier)
                # Multiple matches boost score
                candidates[mid] = candidates.get(mid, 0.0) + 1.0

        # Fallback: search all entries by tier
        if not candidates:
            entries = self._get_entries_by_tier(tier)
            for entry in entries:
                if entry.importance_score < min_importance:
                    continue
                # Simple substring match
                text = (entry.content + " " + (entry.summary or "")).lower()
                match_score = 0.0
                for word in query_words:
                    if word in text:
                        match_score += 0.5
                if match_score > 0:
                    candidates[entry.memory_id] = match_score
                    tiers_searched.add(entry.tier)

        # Score: keyword_match * importance_weight
        scored = []
        for mid, kw_score in candidates.items():
            entry = self._all_entries.get(mid)
            if entry is None:
                continue
            # Combine keyword match with importance
            importance_weight = entry.importance_score / 100.0
            combined_score = kw_score * 0.6 + importance_weight * 0.4
            scored.append((mid, combined_score, entry))

        # Sort by combined score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]

        entries = []
        scores = {}
        for mid, score, entry in top:
            entries.append(entry)
            scores[mid] = round(score, 3)
            # Update cache
            if use_cache:
                self._update_retrieval_cache(mid, entry)

        return RetrievalResult(
            query=query,
            entries=entries,
            scores=scores,
            total_candidates=len(candidates),
            retrieval_time_ms=round((time.time() - start_time) * 1000, 2),
            tiers_searched=list(tiers_searched),
        )

    def search_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        limit: int = 20,
    ) -> List[MemoryEntry]:
        """按标签检索"""
        results = []
        for entry in self._all_entries.values():
            entry_tags_lower = [t.lower() for t in entry.tags]
            if match_all:
                if all(t.lower() in entry_tags_lower for t in tags):
                    results.append(entry)
            else:
                if any(t.lower() in entry_tags_lower for t in tags):
                    results.append(entry)

        results.sort(key=lambda e: e.importance_score, reverse=True)
        return results[:limit]

    def _tier_match(self, entry: MemoryEntry, tier: Optional[str]) -> bool:
        """检查是否匹配层级过滤"""
        if tier is None:
            return True
        return entry.tier == tier

    def get_frequent(self, top_n: int = 10) -> List[MemoryEntry]:
        """获取最频繁访问的记忆"""
        entries = list(self._all_entries.values())
        entries.sort(key=lambda e: e.access_count, reverse=True)
        return entries[:top_n]

    def get_recent(self, top_n: int = 10) -> List[MemoryEntry]:
        """获取最近访问的记忆"""
        entries = list(self._all_entries.values())
        entries.sort(key=lambda e: e.last_accessed, reverse=True)
        return entries[:top_n]

    # ══════════════════════════════════════════════════════
    # 5. Maintenance & Stats
    # ══════════════════════════════════════════════════════

    def get_stats(self) -> CompactionStats:
        """获取压缩统计"""
        scores = [e.importance_score for e in self._all_entries.values()]
        total_chars = sum(len(e.content) for e in self._all_entries.values())
        compressed_chars = sum(
            len(e.summary) for e in self._all_entries.values() if e.summary
        )
        return CompactionStats(
            total_entries=len(self._all_entries),
            hot_count=len(self._hot_store),
            warm_count=len(self._warm_store),
            cold_count=len(self._cold_store),
            total_chars=total_chars,
            total_compressed_chars=compressed_chars,
            avg_importance=round(sum(scores) / max(len(scores), 1), 1),
            compactions_run=self._compaction_count,
            last_compaction=self._last_compaction,
        )

    def get_compaction_history(
        self, limit: int = 20
    ) -> List[CompactionResult]:
        """获取压缩历史"""
        return self._compaction_history[-limit:]

    def get_migration_history(
        self, limit: int = 10
    ) -> List[TierMigrationResult]:
        """获取迁移历史"""
        return self._migration_history[-limit:]

    def reset(self):
        """重置所有数据"""
        self._hot_store.clear()
        self._warm_store.clear()
        self._cold_store.clear()
        self._all_entries.clear()
        self._retrieval_cache.clear()
        self._keyword_index.clear()
        self._compaction_history.clear()
        self._migration_history.clear()
        self._compaction_count = 0
        self._last_compaction = 0.0

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        if memory_id not in self._all_entries:
            return False
        self._remove_from_stores(memory_id)
        self._retrieval_cache.pop(memory_id, None)
        return True

    @staticmethod
    def _make_id(prefix: str = "mem") -> str:
        """生成唯一ID"""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_memory_compactor_instance: Optional[MemoryCompactor] = None


def get_memory_compactor(config: Optional[Dict] = None) -> MemoryCompactor:
    """获取MemoryCompactor单例"""
    global _memory_compactor_instance
    if _memory_compactor_instance is None:
        _memory_compactor_instance = MemoryCompactor(config=config)
    return _memory_compactor_instance


def reset_memory_compactor():
    """重置MemoryCompactor单例"""
    global _memory_compactor_instance
    if _memory_compactor_instance is not None:
        _memory_compactor_instance.reset()
    _memory_compactor_instance = None
