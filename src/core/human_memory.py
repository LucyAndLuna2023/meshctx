"""meshctx human_memory — 仿人类记忆引擎 v2.40

模拟人类记忆特性:
- 情感衰减: 情绪强度影响记忆持久度
- 模式重巩固: 回忆时强化记忆
- 上下文关联: 基于标签和关联网络检索
- 扩散激活: 关联记忆在 recall 时传播
"""
import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


# ── Emotion Intensity ────────────────────────────

class EmotionIntensity(Enum):
    """情绪强度 — 越高越不容易遗忘"""
    NEUTRAL = 0
    INTERESTING = 1
    IMPORTANT = 2
    CRITICAL = 5


# ── Memory Chunk ─────────────────────────────────

@dataclass
class MemoryChunk:
    """单个记忆块"""
    id: str
    pattern: str
    emotion: EmotionIntensity = EmotionIntensity.NEUTRAL
    strength: float = 1.0
    recall_count: int = 0
    importance: float = 0.0
    context_tags: Set[str] = field(default_factory=set)
    associations: Dict[str, float] = field(default_factory=dict)
    _created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if self.importance == 0.0:
            self._update_importance()

    def _update_importance(self):
        """根据情绪计算重要性"""
        mapping = {
            EmotionIntensity.NEUTRAL: 0.1,
            EmotionIntensity.INTERESTING: 0.4,
            EmotionIntensity.IMPORTANT: 0.7,
            EmotionIntensity.CRITICAL: 1.0,
        }
        self.importance = mapping.get(self.emotion, 0.1)

    def decay_strength(self, hours: float):
        """随时间衰减 — CRITICAL(5)几乎不衰减"""
        decay_rate = 0.24 / (1 + self.emotion.value)
        self.strength *= (1 - decay_rate) ** (hours / 24)
        self.strength = max(0.01, min(1.0, self.strength))

    def reconsolidate(self, context: str,
                       new_emotion: Optional[EmotionIntensity] = None):
        """重巩固 — 回忆时更新上下文，永远不降级情绪"""
        if new_emotion is not None and new_emotion.value > self.emotion.value:
            self.emotion = new_emotion
            self._update_importance()
        self.strength = min(1.0, self.strength * 1.15)
        self.recall_count += 1

    def pattern_signature(self) -> str:
        """模式签名 — 用于去重"""
        words = re.findall(r'\w+', self.pattern.lower())
        words.sort()
        return hashlib.md5(" ".join(words).encode()).hexdigest()


# ── Pattern Extraction ──────────────────────────

def _extract_pattern(text: str) -> str:
    """从文本提取关键模式"""
    words = re.findall(r'\w+', text.lower())
    noise = {'the', 'a', 'an', 'is', 'of', 'in', 'to', 'for', 'and', 'or',
             'but', 'with', 'on', 'at', 'by', 'that', 'this'}
    meaningful = [w for w in words if w not in noise and len(w) > 2]
    if meaningful:
        return " ".join(meaningful[:8])
    return " ".join(words[:5])  # fallback


# ── Human-Like Memory Engine ─────────────────────

class HumanLikeMemory:
    """仿人类记忆引擎"""

    def __init__(self, replay_interval: int = 0):
        self.replay_interval = replay_interval
        self._chunks: OrderedDict[str, MemoryChunk] = OrderedDict()
        self._signatures: Dict[str, str] = {}  # sig → chunk_id

    @property
    def total_chunks(self) -> int:
        return len(self._chunks)

    def encode(self, text: str,
               emotion: Optional[EmotionIntensity] = None,
               context_tags: Optional[Set[str]] = None) -> MemoryChunk:
        """编码新记忆 — 自动去重，相同模式重巩固"""
        pattern = _extract_pattern(text)
        sig = MemoryChunk(id="", pattern=pattern).pattern_signature()

        # Dedup: same pattern signature → reconsolidate existing
        if sig in self._signatures:
            existing_id = self._signatures[sig]
            existing = self._chunks[existing_id]
            existing.reconsolidate(text, emotion)
            return existing

        chunk_id = f"mem_{len(self._chunks) + 1}"
        if emotion is None:
            # Auto-detect emotion from keywords
            if re.search(r'critical|urgent|!!!|p0|fatal', text, re.I):
                emotion = EmotionIntensity.CRITICAL
            elif re.search(r'important|key|essential', text, re.I):
                emotion = EmotionIntensity.IMPORTANT
            elif re.search(r'interesting|note|useful', text, re.I):
                emotion = EmotionIntensity.INTERESTING
            else:
                emotion = EmotionIntensity.NEUTRAL

        chunk = MemoryChunk(
            id=chunk_id,
            pattern=pattern,
            emotion=emotion,
            context_tags=context_tags or set(),
        )
        self._chunks[chunk_id] = chunk
        self._signatures[sig] = chunk_id
        return chunk

    def recall(self, query: str, limit: int = 10) -> List[MemoryChunk]:
        """回忆 — 基于关键词匹配 + 扩散激活"""
        query_words = set(re.findall(r'\w+', query.lower()))
        results: List[MemoryChunk] = []
        activated: Set[str] = set()

        for chunk in self._chunks.values():
            chunk_words = set(re.findall(r'\w+', chunk.pattern.lower()))
            overlap = len(query_words & chunk_words)
            score = overlap * chunk.strength

            if overlap > 0 or any(
                qw in chunk.pattern.lower() for qw in query_words
            ):
                results.append(chunk)
                activated.add(chunk.id)

        # Spreading activation: follow associations
        for chunk_id in list(activated):
            chunk = self._chunks.get(chunk_id)
            if not chunk:
                continue
            for assoc_id, weight in chunk.associations.items():
                if assoc_id not in activated and assoc_id in self._chunks:
                    assoc_chunk = self._chunks[assoc_id]
                    results.append(assoc_chunk)
                    activated.add(assoc_id)

        # Sort by strength
        results.sort(key=lambda c: c.strength, reverse=True)
        return results[:limit]

    def recall_by_emotion(self,
                           min_emotion: EmotionIntensity) -> List[MemoryChunk]:
        """按情绪强度召回"""
        return sorted(
            [c for c in self._chunks.values()
             if c.emotion.value >= min_emotion.value],
            key=lambda c: c.strength, reverse=True,
        )

    def recall_by_context(self, tag: str) -> List[MemoryChunk]:
        """按上下文标签召回"""
        return sorted(
            [c for c in self._chunks.values()
             if tag in c.context_tags],
            key=lambda c: c.strength, reverse=True,
        )

    def build_associations(self, chunk_id: str,
                            target_ids: List[str],
                            weights: List[float]):
        """建立记忆关联"""
        chunk = self._chunks.get(chunk_id)
        if not chunk:
            return
        for tid, w in zip(target_ids, weights):
            chunk.associations[tid] = w

    def force_replay(self) -> dict:
        """强制海马体重放 — 强化强记忆，遗忘弱记忆"""
        replay_count = 0
        strong = 0
        for chunk in self._chunks.values():
            if chunk.strength > 0.5:
                chunk.strength = min(1.0, chunk.strength * 1.05)
                strong += 1
            else:
                chunk.strength = max(0.01, chunk.strength * 0.95)
            replay_count += 1
        return {"replay_count": replay_count, "strong_memories": strong}

    def get_memory_stats(self) -> dict:
        """获取记忆统计"""
        if not self._chunks:
            return {
                "total_chunks": 0,
                "emotion_distribution": {},
                "avg_strength": 0.0,
            }
        dist = {}
        for chunk in self._chunks.values():
            name = chunk.emotion.name
            dist[name] = dist.get(name, 0) + 1
        avg = sum(c.strength for c in self._chunks.values()) / len(self._chunks)
        return {
            "total_chunks": self.total_chunks,
            "emotion_distribution": dist,
            "avg_strength": round(avg, 4),
        }

    def to_dict(self) -> dict:
        """序列化为字典"""
        chunks_data = []
        for chunk in self._chunks.values():
            chunks_data.append({
                "id": chunk.id,
                "pattern": chunk.pattern,
                "emotion": chunk.emotion.value,
                "strength": chunk.strength,
                "recall_count": chunk.recall_count,
                "importance": chunk.importance,
                "context_tags": list(chunk.context_tags),
                "associations": chunk.associations,
            })
        return {
            "replay_interval": self.replay_interval,
            "chunks": chunks_data,
        }

    @classmethod
    def from_dict(cls, data: dict, replay_interval: int = 0) -> "HumanLikeMemory":
        """从字典反序列化"""
        mem = cls(replay_interval=data.get("replay_interval", replay_interval))
        for cd in data.get("chunks", []):
            emotion = EmotionIntensity(cd["emotion"])
            chunk = MemoryChunk(
                id=cd["id"],
                pattern=cd["pattern"],
                emotion=emotion,
                strength=cd["strength"],
                recall_count=cd.get("recall_count", 0),
                importance=cd.get("importance", 0.0),
                context_tags=set(cd.get("context_tags", [])),
                associations=cd.get("associations", {}),
            )
            mem._chunks[chunk.id] = chunk
            mem._signatures[chunk.pattern_signature()] = chunk.id
        return mem


# ── Singleton ────────────────────────────────────

_human_memory_instance: Optional[HumanLikeMemory] = None


def get_human_memory() -> HumanLikeMemory:
    global _human_memory_instance
    if _human_memory_instance is None:
        _human_memory_instance = HumanLikeMemory()
    return _human_memory_instance


# ── Legacy stub support ──────────────────────────

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)
