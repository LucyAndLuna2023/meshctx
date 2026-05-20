"""
MeshCtx Human-Like Memory — Pattern-Based Associative Memory
==============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

A fundamentally different approach to AI memory, modeling human cognitive
mechanisms rather than key-value storage.

Core mechanisms:
1. Pattern Chunking — Compress raw data into meaningful "memory chunks"
   (like a Go player recognizing "Chinese opening" from 50 moves)
2. Emotional Salience — Weight memories by emotional intensity,
   not just recency (trauma > routine)
3. Hippocampal Replay — During idle time, replay memories at high speed
   to consolidate patterns and discover connections
4. Memory Reconsolidation — Every recall updates the memory with new context,
   enabling continuous learning
5. Associative Spreading Activation — Memories activate related memories
   through weighted links (smell → place → person → conversation)
6. Productive Forgetting — Forget details, keep patterns. Forgetting is a
   feature that extracts the gist.

Inspiration:
- Go professionals: Pattern recognition of board positions as "shapes"
- Memory champions: Method of loci + spaced repetition + chunking
- Neuroscience: Hippocampal replay, reconsolidation, predictive coding

License: Proprietary Core. ALL RIGHTS RESERVED.
         Contact: license@meshctx.com
"""
import time
import math
import hashlib
import threading
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Set
from enum import Enum


# ── Core Types ──────────────────────────────────────────────


class EmotionIntensity(Enum):
    """Emotional salience — directly affects memory retention strength."""
    NEUTRAL = 0      # Routine interaction
    INTERESTING = 1  # Worth remembering
    IMPORTANT = 2    # Significant information
    SURPRISING = 3   # Unexpected discovery
    FRUSTRATING = 4  # Error/failure experience
    CRITICAL = 5     # User explicitly corrected / strong emotion


@dataclass
class MemoryChunk:
    """A compressed, pattern-based memory unit.

    Unlike raw message storage, a MemoryChunk captures the *meaning* —
    the pattern, not the data. Like a Go player remembering "the 3-3
    invasion pattern" rather than individual stone placements.
    """
    id: str = ""
    pattern: str = ""           # The extracted pattern/gist
    emotion: EmotionIntensity = EmotionIntensity.NEUTRAL
    importance: float = 0.5  # 0-1, decays unless reinforced
    created_at: float = field(default_factory=time.time)
    last_recalled: float = field(default_factory=time.time)
    recall_count: int = 0
    strength: float = 1.0    # Current memory strength (decays, reconsolidates)
    # Association network — linked memory chunk IDs with weights
    associations: Dict[str, float] = field(default_factory=dict)
    # Context tags for state-dependent retrieval
    context_tags: Set[str] = field(default_factory=set)
    # The raw source (kept for reconsolidation)
    raw_source: str = ""
    raw_source_hash: str = ""

    def decay_strength(self, elapsed_hours: float):
        """Ebbinghaus-like decay, modified by emotional intensity.

        Critical/emotional memories decay MUCH slower.
        Neutral memories decay at normal Ebbinghaus rate.
        """
        # Emotion bonus: higher = slower decay
        emotion_bonus = {
            EmotionIntensity.NEUTRAL: 1,
            EmotionIntensity.INTERESTING: 3,
            EmotionIntensity.IMPORTANT: 10,
            EmotionIntensity.SURPRISING: 20,
            EmotionIntensity.FRUSTRATING: 50,
            EmotionIntensity.CRITICAL: 200,  # Almost never forget
        }[self.emotion]

        # R = e^(-t / (S * emotion_bonus))
        # S=24h base, scaled by emotion_bonus
        base_decay = math.exp(-elapsed_hours / (24 * emotion_bonus))
        recall_bonus = min(0.3, self.recall_count * 0.02)
        self.strength = max(0.02, base_decay * self.strength + recall_bonus)

    def reconsolidate(self, new_context: str, new_emotion: EmotionIntensity = None):
        """Reconsolidation: updating a memory on recall.

        Every time you remember something, the memory becomes plastic
        and incorporates new information. This is how human learning works.
        """
        # Update pattern with new context
        if new_context and new_context != self.raw_source:
            # Merge: keep the gist, update details
            words_old = set(self.pattern.split())
            words_new = set(new_context.split())
            new_words = words_new - words_old
            if new_words:
                self.pattern = self.pattern + " | " + " ".join(
                    list(new_words)[:5])

        # Update emotion (never downgrade)
        if new_emotion and new_emotion.value > self.emotion.value:
            self.emotion = new_emotion

        # Strengthen
        self.strength = min(1.0, self.strength + 0.1)
        self.recall_count += 1
        self.last_recalled = time.time()

    def pattern_signature(self) -> str:
        """Generate a compact signature for pattern matching."""
        words = sorted(set(self.pattern.lower().split()))
        return hashlib.md5(" ".join(words[:10]).encode()).hexdigest()[:12]


# ── Human-Like Memory System ─────────────────────────────────


class HumanLikeMemory:
    """Pattern-based associative memory modeled on human cognitive architecture.

    Key differences from traditional AI memory:
    1. Pattern chunking, not raw storage
    2. Emotional salience weighting
    3. Associative activation spreading
    4. Hippocampal replay during idle
    5. Memory reconsolidation on recall
    6. Productive forgetting (keep patterns, drop details)
    """

    def __init__(self, replay_interval: int = 300):
        """
        Args:
            replay_interval: Seconds between hippocampal replay cycles.
                            Default 300s (5 min). Set to 0 to disable.
        """
        self.chunks: Dict[str, MemoryChunk] = {}
        self.pattern_index: Dict[str, List[str]] = defaultdict(list)
        self.context_index: Dict[str, List[str]] = defaultdict(list)
        # Working memory (recent, not yet consolidated)
        self.working_memory: deque = deque(maxlen=50)
        # Stats
        self.total_chunks = 0
        self.total_recalls = 0
        self.replay_count = 0
        self.last_replay = time.time()

        # Background replay thread
        self._replay_interval = replay_interval
        self._replay_thread = None
        if replay_interval > 0:
            self._start_replay()

    # ── Encoding: Pattern Chunking ────────────────────────

    def encode(self, text: str, emotion: EmotionIntensity = EmotionIntensity.NEUTRAL,
               context_tags: Set[str] = None) -> MemoryChunk:
        """Encode raw text into a compressed memory chunk.

        Pattern extraction:
        1. Strip filler words (the, a, um, 的, 了, etc.)
        2. Extract key entities (names, numbers, technical terms)
        3. Generate pattern signature
        4. Create MemoryChunk with emotional weighting
        """
        # Extract pattern (gist) from text
        pattern = self._extract_pattern(text)

        # Check if this pattern already exists (pattern matching)
        sig = MemoryChunk(pattern=pattern).pattern_signature()
        similar = self._find_similar_patterns(sig)

        if similar:
            # Reconsolidate existing memory
            best = similar[0]
            chunk = self.chunks[best]
            chunk.reconsolidate(text, emotion)
            self._update_indexes(chunk, context_tags or set())
            return chunk

        # Create new memory chunk
        chunk_id = f"mem_{int(time.time())}_{len(self.chunks)}"
        chunk = MemoryChunk(
            id=chunk_id,
            pattern=pattern,
            emotion=emotion,
            importance=self._calc_importance(emotion),
            raw_source=text[:500],
            raw_source_hash=hashlib.md5(text.encode()).hexdigest()[:8],
            context_tags=context_tags or set(),
        )

        self.chunks[chunk_id] = chunk
        self.total_chunks += 1
        self._update_indexes(chunk, context_tags or set())
        self.working_memory.append(chunk_id)

        return chunk

    def _extract_pattern(self, text: str) -> str:
        """Extract the gist/pattern from raw text.

        Like a Go player seeing "Chinese opening" from 50 moves,
        we compress the text into its essential meaning.
        """
        # Remove filler words
        filler = {'the', 'a', 'an', 'is', 'was', 'are', 'were', 'be', 'been',
                  'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                  'would', 'could', 'should', 'may', 'might', 'shall', 'can',
                  'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                  'as', 'into', 'through', 'during', 'before', 'after',
                  '的', '了', '在', '是', '有', '和', '就', '不', '人', '都',
                  '也', '很', '到', '说', '要', '去', '你', '会', '着', '没',
                  '看', '好', '自己', '这', '他', '她', '它', '们', '那',
                  '我', '你', '他', '她', '它', '我们', '你们', '他们',
                  '这个', '那个', '什么', '怎么', '这样', '那样',
                  'um', 'uh', 'like', 'just', 'really', 'actually', 'basically',
                  '嗯', '啊', '哦', '呢', '吧', '吗', '嘛'}

        words = text.lower().split()
        key_words = [w for w in words if w not in filler and len(w) > 1]

        # Chunk into pattern — keep only meaningful words, limit length
        if len(key_words) > 30:
            # Take first 10 + middle 10 + last 10 for gist extraction
            pattern = " ".join(key_words[:10] + key_words[-10:])
        else:
            pattern = " ".join(key_words[:30])

        return pattern or text[:100]

    def _find_similar_patterns(self, signature: str) -> List[str]:
        """Find memory chunks with similar patterns."""
        candidates = self.pattern_index.get(signature[:8], [])
        if not candidates:
            return []
        # Score by pattern overlap
        scored = []
        for cid in candidates:
            if cid in self.chunks:
                chunk = self.chunks[cid]
                # Recent + strong = more likely match
                score = chunk.strength * (1.0 / max(1, (time.time() - chunk.created_at) / 86400))
                scored.append((score, cid))
        scored.sort(reverse=True)
        return [cid for _, cid in scored[:3] if _ > 0.3]

    def _calc_importance(self, emotion: EmotionIntensity) -> float:
        base = {
            EmotionIntensity.NEUTRAL: 0.3,
            EmotionIntensity.INTERESTING: 0.5,
            EmotionIntensity.IMPORTANT: 0.7,
            EmotionIntensity.SURPRISING: 0.8,
            EmotionIntensity.FRUSTRATING: 0.9,
            EmotionIntensity.CRITICAL: 1.0,
        }[emotion]
        return base

    def _update_indexes(self, chunk: MemoryChunk, context_tags: Set[str]):
        """Update pattern and context indexes."""
        sig = chunk.pattern_signature()
        if chunk.id not in self.pattern_index.get(sig[:8], []):
            self.pattern_index[sig[:8]].append(chunk.id)
        for tag in context_tags:
            if chunk.id not in self.context_index.get(tag, []):
                self.context_index[tag].append(chunk.id)

    # ── Retrieval: Associative Activation Spreading ──────

    def recall(self, query: str, context_tags: Set[str] = None,
               top_k: int = 10) -> List[MemoryChunk]:
        """Recall memories using associative spreading activation.

        Like smelling coffee → remembering Paris café → that conversation
        → the idea you had there.

        Activation spreads through:
        1. Direct pattern match → high activation
        2. Context overlap → medium activation
        3. Associative links → spreading activation (depth-limited)
        """
        self.total_recalls += 1
        query_pattern = self._extract_pattern(query)
        activated: Dict[str, float] = {}

        # Layer 1: Direct pattern match
        query_words = set(query_pattern.lower().split())
        for chunk_id, chunk in self.chunks.items():
            chunk_words = set(chunk.pattern.lower().split())
            overlap = len(query_words & chunk_words)
            if overlap > 0:
                # Jaccard-like similarity weighted by strength
                score = (overlap / max(len(query_words | chunk_words), 1)) * chunk.strength
                if score > 0.05:
                    activated[chunk_id] = score

        # Layer 2: Context boost
        if context_tags:
            for tag in context_tags:
                for chunk_id in self.context_index.get(tag, []):
                    if chunk_id in activated:
                        activated[chunk_id] *= 1.5  # Context match boost
                    elif chunk_id in self.chunks:
                        activated[chunk_id] = self.chunks[chunk_id].strength * 0.5

        # Layer 3: Spreading activation through associations (depth 2)
        new_activations = dict(activated)
        for _ in range(2):  # 2 hops
            next_wave = {}
            for chunk_id, act in new_activations.items():
                if chunk_id not in self.chunks:
                    continue
                chunk = self.chunks[chunk_id]
                for assoc_id, weight in chunk.associations.items():
                    if assoc_id in self.chunks and assoc_id not in activated:
                        spread = act * weight * 0.5  # 50% decay per hop
                        if spread > 0.05:
                            next_wave[assoc_id] = spread
            for cid, act in next_wave.items():
                activated[cid] = act
            new_activations = next_wave

        # Sort by activation, reconsolidate on recall
        results = []
        for chunk_id, score in sorted(activated.items(), key=lambda x: -x[1])[:top_k]:
            chunk = self.chunks[chunk_id]
            chunk.reconsolidate(query)
            results.append(chunk)

        return results

    def recall_by_emotion(self, min_intensity: EmotionIntensity = EmotionIntensity.IMPORTANT,
                          limit: int = 20) -> List[MemoryChunk]:
        """Recall memories by emotional intensity. Trauma > routine."""
        candidates = [c for c in self.chunks.values()
                     if c.emotion.value >= min_intensity.value]
        candidates.sort(key=lambda c: (c.emotion.value, c.importance, c.recall_count),
                       reverse=True)
        return candidates[:limit]

    def recall_by_context(self, context_tag: str, limit: int = 20) -> List[MemoryChunk]:
        """Context-dependent recall. Same context = better retrieval."""
        chunk_ids = self.context_index.get(context_tag, [])
        chunks = [self.chunks[cid] for cid in chunk_ids if cid in self.chunks]
        chunks.sort(key=lambda c: c.strength, reverse=True)
        return chunks[:limit]

    # ── Association Building ──────────────────────────────

    def build_associations(self, chunk_id: str, related_ids: List[str],
                           weights: List[float] = None):
        """Build associative links between memories.

        Like linking "Paris" → "coffee" → "conversation with Marie" →
        "startup idea". Each link has a weight.
        """
        if chunk_id not in self.chunks:
            return
        chunk = self.chunks[chunk_id]
        for i, rid in enumerate(related_ids):
            if rid not in self.chunks or rid == chunk_id:
                continue
            weight = weights[i] if weights else 0.5
            chunk.associations[rid] = max(
                chunk.associations.get(rid, 0), weight)
            # Bidirectional (weaker)
            other = self.chunks[rid]
            other.associations[chunk_id] = max(
                other.associations.get(chunk_id, 0), weight * 0.7)

    def auto_associate(self, max_links: int = 5):
        """Auto-discover associations between recent memories."""
        recent = sorted(self.chunks.values(),
                       key=lambda c: c.last_recalled, reverse=True)[:100]
        for i, chunk_a in enumerate(recent):
            words_a = set(chunk_a.pattern.lower().split())
            links = 0
            for chunk_b in recent[i+1:]:
                if links >= max_links:
                    break
                words_b = set(chunk_b.pattern.lower().split())
                overlap = len(words_a & words_b)
                if overlap >= 3:  # At least 3 shared significant words
                    weight = min(0.8, overlap / max(len(words_a | words_b), 1))
                    chunk_a.associations[chunk_b.id] = max(
                        chunk_a.associations.get(chunk_b.id, 0), weight)
                    chunk_b.associations[chunk_a.id] = max(
                        chunk_b.associations.get(chunk_a.id, 0), weight * 0.7)
                    links += 1

    # ── Hippocampal Replay ────────────────────────────────

    def _start_replay(self):
        """Start background hippocampal replay thread."""
        def replay_loop():
            while True:
                time.sleep(self._replay_interval)
                try:
                    self._hippocampal_replay()
                except Exception:
                    pass

        self._replay_thread = threading.Thread(target=replay_loop, daemon=True)
        self._replay_thread.start()

    def _hippocampal_replay(self):
        """Replay memories at high speed to consolidate patterns.

        Like the human hippocampus during sleep:
        1. Select high-importance recent memories
        2. Replay them at accelerated speed
        3. Discover cross-connections (insight generation)
        4. Strengthen consolidated patterns, weaken noise
        """
        self.replay_count += 1
        self.last_replay = time.time()
        now = time.time()

        # Select memories for replay: recent + emotionally salient
        candidates = []
        for chunk in self.chunks.values():
            age_hours = (now - chunk.created_at) / 3600
            # Prioritize: high emotion + recent + not yet consolidated
            replay_score = (chunk.emotion.value + 1) * chunk.importance
            if age_hours < 72:  # Recent bias
                replay_score *= 2.0
            if chunk.recall_count < 3:  # Not yet consolidated
                replay_score *= 3.0
            if replay_score > 2.0:
                candidates.append((replay_score, chunk))

        candidates.sort(reverse=True)

        # Replay top candidates
        replayed = 0
        for score, chunk in candidates[:50]:
            # Strengthen through replay
            chunk.strength = min(1.0, chunk.strength * 1.05)
            chunk.importance = min(1.0, chunk.importance * 1.02)
            replayed += 1

        # Auto-discover associations during replay
        if self.replay_count % 6 == 0:  # Every ~30 min
            self.auto_associate(max_links=3)

        # Productive forgetting: weaken low-importance, old, unrecalled
        for chunk in self.chunks.values():
            age_days = (now - chunk.created_at) / 86400
            if (age_days > 7 and chunk.recall_count == 0 and
                chunk.emotion == EmotionIntensity.NEUTRAL):
                chunk.strength *= 0.9  # Slow decay
            if chunk.strength < 0.05:
                # Memory is essentially forgotten (but pattern remains in index)
                pass

    def force_replay(self) -> Dict:
        """Manually trigger hippocampal replay. Returns stats."""
        before = self.total_chunks
        self._hippocampal_replay()
        return {
            "replay_count": self.replay_count,
            "chunks_before": before,
            "chunks_after": self.total_chunks,
            "strong_memories": sum(1 for c in self.chunks.values() if c.strength > 0.7),
            "weak_memories": sum(1 for c in self.chunks.values() if c.strength < 0.2),
        }

    # ── Memory Health & Diagnostics ───────────────────────

    def get_memory_stats(self) -> Dict:
        """Get comprehensive memory system diagnostics."""
        now = time.time()
        strong = sum(1 for c in self.chunks.values() if c.strength > 0.7)
        weak = sum(1 for c in self.chunks.values() if c.strength < 0.2)
        by_emotion = defaultdict(int)
        for c in self.chunks.values():
            by_emotion[c.emotion.name] += 1

        # Find most connected memory (hub node)
        most_connected = None
        max_connections = 0
        for c in self.chunks.values():
            if len(c.associations) > max_connections:
                max_connections = len(c.associations)
                most_connected = c.pattern[:80] if c.pattern else ""

        return {
            "total_chunks": self.total_chunks,
            "strong_memories": strong,
            "weak_memories": weak,
            "working_memory_size": len(self.working_memory),
            "total_recalls": self.total_recalls,
            "replay_count": self.replay_count,
            "last_replay_ago_s": round(now - self.last_replay, 1),
            "emotion_distribution": dict(by_emotion),
            "most_connected_memory": most_connected,
            "pattern_index_entries": len(self.pattern_index),
            "context_index_entries": sum(len(v) for v in self.context_index.values()),
            "avg_strength": round(
                sum(c.strength for c in self.chunks.values()) / max(len(self.chunks), 1), 2
            ),
        }

    # ── Persistence ────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "chunks": {
                cid: {
                    "id": c.id, "pattern": c.pattern,
                    "emotion": c.emotion.value, "importance": c.importance,
                    "created_at": c.created_at, "last_recalled": c.last_recalled,
                    "recall_count": c.recall_count, "strength": c.strength,
                    "associations": c.associations,
                    "context_tags": list(c.context_tags),
                    "raw_source": c.raw_source[:200],
                }
                for cid, c in self.chunks.items()
            },
            "stats": self.get_memory_stats(),
        }

    @classmethod
    def from_dict(cls, data: Dict, replay_interval: int = 300) -> "HumanLikeMemory":
        hm = cls(replay_interval=replay_interval)
        for cid, cd in data.get("chunks", {}).items():
            chunk = MemoryChunk(
                id=cd["id"], pattern=cd["pattern"],
                emotion=EmotionIntensity(cd.get("emotion", 0)),
                importance=cd.get("importance", 0.5),
                created_at=cd.get("created_at", time.time()),
                last_recalled=cd.get("last_recalled", time.time()),
                recall_count=cd.get("recall_count", 0),
                strength=cd.get("strength", 1.0),
                associations=cd.get("associations", {}),
                context_tags=set(cd.get("context_tags", [])),
                raw_source=cd.get("raw_source", ""),
            )
            hm.chunks[cid] = chunk
            hm._update_indexes(chunk, chunk.context_tags)
        hm.total_chunks = len(hm.chunks)
        return hm


# ── Singleton ───────────────────────────────────────────────

_global_human_memory: Optional[HumanLikeMemory] = None


def get_human_memory() -> HumanLikeMemory:
    global _global_human_memory
    if _global_human_memory is None:
        _global_human_memory = HumanLikeMemory(replay_interval=300)
    return _global_human_memory
