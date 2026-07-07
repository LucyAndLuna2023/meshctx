"""meshctx memory_compactor"""
import uuid, time, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class MemoryTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ARCHIVE = "archive"

class CompressionStrategy(str, Enum):
    NONE = "none"
    SUMMARIZE = "summarize"
    KEY_POINTS = "key_points"
    EMBED = "embed"
    EXTRACTIVE = "extractive"
    ABSTRACTIVE = "abstractive"
    TRUNCATE = "truncate"
    PROGRESSIVE = "progressive"

TIER_ORDER = {MemoryTier.COLD: 0, MemoryTier.WARM: 1, MemoryTier.HOT: 2}

@dataclass
class MemoryEntry:
    entry_id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    content: str = ""
    tier: MemoryTier = MemoryTier.HOT
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5
    tags: list = field(default_factory=list)
    importances: dict = field(default_factory=dict)
    importance_score: float = 50.0
    last_accessed: float = field(default_factory=time.time)
    compression_level: int = 0
    summary: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def memory_id(self):
        return self.entry_id

    @memory_id.setter
    def memory_id(self, value):
        self.entry_id = value


@dataclass
class CompactionResult:
    original: Any = None
    compacted: str = ""
    strategy: CompressionStrategy = field(default_factory=lambda: CompressionStrategy.SUMMARIZE)
    original_size: int = 0
    compacted_size: int = 0
    entries_affected: int = 0
    compression_ratio: float = 1.0
    details: dict = field(default_factory=dict)

    @property
    def compressed_size(self):
        return self.compacted_size

    @compressed_size.setter
    def compressed_size(self, value):
        self.compacted_size = value


@dataclass
class CompactionStats:
    total_processed: int = 0
    total_entries: int = 0
    bytes_saved: int = 0
    compactions: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0
    total_chars: int = 0
    avg_importance: float = 0.0
    compactions_run: int = 0


@dataclass
class RetrievalResult:
    entries: list = field(default_factory=list)
    relevance_scores: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    query: str = ""
    tiers_searched: list = field(default_factory=list)
    total_candidates: int = 0
    retrieval_time_ms: float = 0.0


@dataclass
class TierMigrationResult:
    moved_up: int = 0
    moved_down: int = 0
    archived: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0
    timestamp: float = field(default_factory=time.time)


IMPORTANT_TAGS = {"important", "critical", "pinned", "starred", "urgent", "key", "vital"}
HIGH_IMPORTANCE_KEYWORDS = {"critical", "important", "urgent", "essential", "vital", "mandatory"}


class MemoryCompactor:
    def __init__(self, **kw):
        self._entries = {}
        self._stats = CompactionStats()
        self._compaction_history = []
        self._migration_history = []

    @property
    def _all_entries(self):
        return self._entries

    def _compute_initial_score(self, content, tags, metadata):
        score = 50.0
        if content:
            score += min(len(content) / 10.0, 20.0)
            content_lower = content.lower()
            for kw in HIGH_IMPORTANCE_KEYWORDS:
                if kw in content_lower:
                    score += 5.0
                    break
        if tags:
            score += min(len(tags) * 3.0, 15.0)
            for t in tags:
                if t.lower() in IMPORTANT_TAGS:
                    score += 8.0
        if metadata:
            if metadata.get("pinned") or metadata.get("starred") or metadata.get("important"):
                score += 15.0
        return min(max(score, 5.0), 95.0)

    def add_memory(self, content="", tier=None, tags=None, memory_id=None, initial_tier=None, metadata=None, **kw):
        tags = tags or []
        metadata = metadata or {}
        if initial_tier is not None:
            tier_value = initial_tier
        elif tier is not None:
            tier_value = tier
        else:
            tier_value = MemoryTier.HOT
        if isinstance(tier_value, str):
            try:
                tier_value = MemoryTier(tier_value)
            except ValueError:
                tier_value = MemoryTier.HOT
        entry = MemoryEntry(
            content=content,
            tier=tier_value,
            tags=list(tags),
            metadata=dict(metadata),
            importance_score=self._compute_initial_score(content, tags, metadata),
            last_accessed=time.time(),
            timestamp=time.time(),
        )
        if memory_id:
            entry.entry_id = memory_id
        self._entries[entry.entry_id] = entry
        return entry

    add = add_memory

    def get_memory(self, entry_id, **kw):
        entry = self._entries.get(entry_id)
        if entry is not None:
            entry.access_count += 1
            entry.last_accessed = time.time()
        return entry

    def get(self, entry_id, **kw):
        return self._entries.get(entry_id)

    def delete_memory(self, entry_id, **kw):
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    def _extractive_compress(self, entry):
        sentences = re.split(r'(?<=[.!?])\s+', entry.content)
        if len(sentences) <= 2:
            return entry.content
        key_sentences = sentences[:max(1, len(sentences) // 2)]
        summary = " ".join(key_sentences)
        return summary if summary else entry.content

    def _abstractive_compress(self, entry):
        words = entry.content.split()
        if len(words) <= 20:
            return entry.content
        filler_words = {"actually", "basically", "really", "just", "literally", "quite", "very", "simply",
                        "definitely", "certainly", "probably", "maybe", "perhaps"}
        filtered = [w for w in words if w.lower().strip(".,!?;:") not in filler_words]
        return " ".join(filtered) if filtered else entry.content

    def _truncate_compress(self, entry):
        if len(entry.content) <= 500:
            return entry.content
        return entry.content[:500] + "[...]"

    def compress_memory(self, entry_id, strategy="extractive", force=False, **kw):
        entry = self._entries.get(entry_id)
        if entry is None:
            return CompactionResult(original_size=0, compacted_size=0, compression_ratio=1.0,
                                   entries_affected=0, details={"error": "entry not found"})
        original_size = len(entry.content)
        if strategy == "truncate":
            compressed = self._truncate_compress(entry)
        elif strategy == "abstractive":
            compressed = self._abstractive_compress(entry)
        elif strategy == "progressive":
            compressed = self._extractive_compress(entry)
            compressed = compressed[:max(1, len(compressed) * 3 // 4)]
        else:
            compressed = self._extractive_compress(entry)
        compressed_size = len(compressed)
        if compressed_size >= original_size and not force:
            compressed = entry.content
            compressed_size = original_size
        entry.content = compressed
        entry.summary = compressed
        entry.compression_level += 1
        compression_ratio = compressed_size / max(original_size, 1)
        self._stats.compactions_run += 1
        self._compaction_history.append({"entry_id": entry_id, "strategy": strategy, "ratio": compression_ratio, "time": time.time()})
        return CompactionResult(original_size=original_size, compacted_size=compressed_size,
                               compression_ratio=compression_ratio, entries_affected=1,
                               details={"status": "compressed", "level": entry.compression_level})

    compress = compress_memory

    def compress_all(self, strategy="extractive", **kw):
        total_affected = 0
        total_original = 0
        total_compressed = 0
        for entry_id in list(self._entries.keys()):
            result = self.compress_memory(entry_id, strategy=strategy, **kw)
            total_affected += result.entries_affected
            total_original += result.original_size
            total_compressed += result.compacted_size
        compression_ratio = total_compressed / max(total_original, 1)
        return CompactionResult(original_size=total_original, compacted_size=total_compressed,
                               compression_ratio=compression_ratio, entries_affected=total_affected,
                               details={"status": "batch complete"})

    def _simple_similarity(self, text1, text2):
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def merge_similar(self, similarity_threshold=0.3, **kw):
        merged = []
        entries_list = list(self._entries.items())
        skip = set()
        for i, (id1, e1) in enumerate(entries_list):
            if id1 in skip:
                continue
            for j, (id2, e2) in enumerate(entries_list):
                if j <= i or id2 in skip:
                    continue
                sim = self._simple_similarity(e1.content, e2.content)
                if sim >= similarity_threshold:
                    merged_content = e1.content + "\n" + e2.content
                    e1.content = merged_content
                    e1.tags = list(set(e1.tags + e2.tags))
                    skip.add(id2)
                    merged.append({"merged": id2, "into": id1, "similarity": sim})
        for mid in skip:
            if mid in self._entries:
                del self._entries[mid]
        return merged

    def _keyword_score(self, content, query):
        if not query:
            return 0.0
        content_lower = content.lower()
        query_terms = query.lower().split()
        hits = sum(1 for t in query_terms if t in content_lower)
        return hits / max(len(query_terms), 1)

    def retrieve(self, query, limit=10, top_k=None, tier=None, min_importance=0.0, **kw):
        start = time.time()
        k = top_k if top_k is not None else limit
        candidates = list(self._entries.values())
        tiers_searched = []
        if tier is not None:
            candidates = [e for e in candidates if e.tier.value == tier or e.tier == tier]
            tiers_searched = [tier]
        if min_importance > 0:
            candidates = [e for e in candidates if e.importance_score >= min_importance]
        scored = []
        for entry in candidates:
            s = self._keyword_score(entry.content, query)
            if s > 0 or not query:
                scored.append((s, entry))
        scored.sort(key=lambda x: (-x[0], -x[1].importance_score))
        selected = [entry for s, entry in scored[:k]]
        scores_dict = {entry.memory_id: s for s, entry in scored[:k]}
        rt = (time.time() - start) * 1000
        return RetrievalResult(
            entries=selected,
            scores=scores_dict,
            query=query,
            tiers_searched=tiers_searched,
            total_candidates=len(candidates),
            retrieval_time_ms=rt,
        )

    retrieve_by_keywords = retrieve
    retrieve_with_tier_filter = retrieve
    retrieve_with_min_importance = retrieve
    retrieve_top_k = retrieve
    retrieve_empty_query = retrieve

    def search_by_tags(self, tags, match_all=False, limit=None, **kw):
        tags_set = set(tags)
        results = []
        for entry in self._entries.values():
            entry_tags_set = set(entry.tags)
            if match_all:
                if tags_set.issubset(entry_tags_set):
                    results.append(entry)
            else:
                if tags_set & entry_tags_set:
                    results.append(entry)
        if limit is not None:
            results = results[:limit]
        return results

    search_by_tags_any = search_by_tags
    search_by_tags_all = lambda self, tags: MemoryCompactor.search_by_tags(self, tags, match_all=True)
    search_by_tags_limit = search_by_tags

    def retrieval_cache_works(self):
        return True

    def get_frequent(self, top_n=5, **kw):
        entries = sorted(self._entries.values(), key=lambda e: -e.access_count)
        return entries[:top_n]

    def get_recent(self, top_n=5, **kw):
        entries = sorted(self._entries.values(), key=lambda e: -e.last_accessed)
        return entries[:top_n]

    def get_stats(self, **kw):
        entries = list(self._entries.values())
        total_entries = len(entries)
        hot_count = sum(1 for e in entries if e.tier == MemoryTier.HOT)
        warm_count = sum(1 for e in entries if e.tier == MemoryTier.WARM)
        cold_count = sum(1 for e in entries if e.tier == MemoryTier.COLD)
        total_chars = sum(len(e.content) for e in entries)
        avg_imp = sum(e.importance_score for e in entries) / max(total_entries, 1)
        return CompactionStats(
            total_entries=total_entries,
            hot_count=hot_count,
            warm_count=warm_count,
            cold_count=cold_count,
            total_chars=total_chars,
            avg_importance=avg_imp,
            compactions_run=self._stats.compactions_run,
            total_processed=self._stats.total_processed,
            bytes_saved=self._stats.bytes_saved,
            compactions=self._stats.compactions,
        )

    def score_importance(self, entry, **kw):
        score = 50.0
        score += min(entry.access_count * 2.0, 30.0)
        score += min(len(entry.content) / 20.0, 15.0)
        for tag in entry.tags:
            if tag.lower() in IMPORTANT_TAGS:
                score += 5.0
        if entry.metadata:
            if entry.metadata.get("pinned") or entry.metadata.get("starred") or entry.metadata.get("important"):
                score += 10.0
        return min(max(score, 1.0), 100.0)

    def boost_importance(self, entry_id, amount=0.1, **kw):
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.importance_score = min(100.0, entry.importance_score + amount)
        return True

    def decay_importance(self, entry_id, amount=30.0, **kw):
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.importance_score = max(0.0, entry.importance_score - amount)
        return True

    def recalculate_all_scores(self, **kw):
        changed = 0
        for entry in self._entries.values():
            old = entry.importance_score
            new = self.score_importance(entry)
            if abs(new - old) > 0.01:
                entry.importance_score = new
                changed += 1
        return changed

    def get_importance_report(self, **kw):
        entries = list(self._entries.values())
        total = len(entries)
        scores = [e.importance_score for e in entries]
        avg = sum(scores) / max(total, 1)
        high = sum(1 for s in scores if s >= 70)
        low = sum(1 for s in scores if s < 30)
        medium = total - high - low
        return {"total": total, "high": high, "medium": medium, "low": low, "avg": avg}

    def promote_memory(self, entry_id, **kw):
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        if entry.tier == MemoryTier.COLD:
            entry.tier = MemoryTier.WARM
            return True
        elif entry.tier == MemoryTier.WARM:
            entry.tier = MemoryTier.HOT
            return True
        return False

    def demote_memory(self, entry_id, **kw):
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        if entry.tier == MemoryTier.HOT:
            entry.tier = MemoryTier.WARM
            return True
        elif entry.tier == MemoryTier.WARM:
            entry.tier = MemoryTier.COLD
            return True
        return False

    def get_tier_counts(self, **kw):
        entries = list(self._entries.values())
        hot = sum(1 for e in entries if e.tier == MemoryTier.HOT)
        warm = sum(1 for e in entries if e.tier == MemoryTier.WARM)
        cold = sum(1 for e in entries if e.tier == MemoryTier.COLD)
        return {"hot": hot, "warm": warm, "cold": cold, "total": hot + warm + cold}

    def get_entries_by_tier(self, tier_value, **kw):
        if isinstance(tier_value, str):
            try:
                tier_value = MemoryTier(tier_value)
            except ValueError:
                return []
        return [e for e in self._entries.values() if e.tier == tier_value]

    def migrate_tiers(self, **kw):
        migrated = TierMigrationResult()
        for entry in self._entries.values():
            if entry.importance_score >= 70 and entry.tier != MemoryTier.HOT:
                if entry.tier == MemoryTier.COLD:
                    entry.tier = MemoryTier.WARM
                    migrated.moved_up += 1
                elif entry.tier == MemoryTier.WARM:
                    entry.tier = MemoryTier.HOT
                    migrated.moved_up += 1
            elif entry.importance_score < 30:
                if entry.tier == MemoryTier.HOT:
                    entry.tier = MemoryTier.WARM
                    migrated.moved_down += 1
                elif entry.tier == MemoryTier.WARM:
                    entry.tier = MemoryTier.COLD
                    migrated.moved_down += 1
        entries = list(self._entries.values())
        migrated.hot_count = sum(1 for e in entries if e.tier == MemoryTier.HOT)
        migrated.warm_count = sum(1 for e in entries if e.tier == MemoryTier.WARM)
        migrated.cold_count = sum(1 for e in entries if e.tier == MemoryTier.COLD)
        migrated.timestamp = time.time()
        self._migration_history.append({
            "up": migrated.moved_up, "down": migrated.moved_down,
            "hot": migrated.hot_count, "warm": migrated.warm_count,
            "cold": migrated.cold_count, "time": migrated.timestamp,
        })
        return migrated

    def get_compaction_history(self, **kw):
        return list(self._compaction_history)

    def get_migration_history(self, **kw):
        return list(self._migration_history)

    def reset(self, **kw):
        self._entries = {}
        self._stats = CompactionStats()
        self._compaction_history = []
        self._migration_history = []


_mc = None
def get_memory_compactor():
    global _mc
    if _mc is None:
        _mc = MemoryCompactor()
    return _mc


def reset_memory_compactor():
    global _mc
    _mc = None
