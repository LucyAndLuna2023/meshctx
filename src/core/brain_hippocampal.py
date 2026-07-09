"""
Hippocampal Replay — 海马体记忆回放引擎 (v3.115.16)
基于Buzsáki(2015) Sharp-Wave Ripples + Hopfield(1982)吸引子网络 + McClelland(1995)互补学习系统

核心机制:
1. 模式分离 (Dentate Gyrus) — 高维稀疏编码, 防记忆干扰
2. 模式完成 (CA3) — Hopfield-style 吸引子, 部分线索→完整回忆
3. SWR触发回放 — 锐波涟漪事件驱动离线巩固
4. 时间序列学习 — 前后突触时序依赖可塑性
5. 情绪调控巩固 — 杏仁核→海马调节记忆强度

参考文献:
- Buzsáki G. (2015) Hippocampal sharp wave-ripple: A cognitive biomarker
- Hopfield JJ (1982) Neural networks and physical systems with emergent collective computational abilities
- McClelland JL et al. (1995) Why there are complementary learning systems in the hippocampus and neocortex
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import time
import math


@dataclass
class MemoryPattern:
    """A sparse distributed representation of an episodic memory."""
    id: str
    pattern: np.ndarray          # high-dim sparse binary vector
    context: str                  # textual description
    emotional_valence: float = 0.0
    emotional_arousal: float = 0.0
    timestamp: float = field(default_factory=time.time)
    replay_count: int = 0
    consolidation_level: float = 0.0  # 0.0 (hippocampal) → 1.0 (neocortical)
    strength: float = 1.0
    
    def __hash__(self):
        return hash(self.id)


class PatternSeparator:
    """DG-inspired pattern separation — sparse high-dimensional encoding."""
    
    def __init__(self, input_dim: int = 64, output_dim: int = 512, sparsity: float = 0.1):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.sparsity = sparsity
        # Random projection matrix (fixed, not learned — like DG granule cells)
        rng = np.random.RandomState(42)
        self.projection = rng.randn(output_dim, input_dim) / np.sqrt(input_dim)
        self.threshold = np.percentile(
            self.projection @ np.ones(input_dim), 
            100 * (1 - sparsity)
        )
    
    def separate(self, input_pattern: np.ndarray) -> np.ndarray:
        """Project to sparse high-dim representation — pattern separation."""
        if len(input_pattern) < self.input_dim:
            input_pattern = np.pad(input_pattern, (0, self.input_dim - len(input_pattern)))
        elif len(input_pattern) > self.input_dim:
            input_pattern = input_pattern[:self.input_dim]
        
        activation = self.projection @ input_pattern
        # Winner-take-all sparsity: only top k% fire
        threshold = np.percentile(np.abs(activation), 100 * (1 - self.sparsity))
        output = (np.abs(activation) > threshold).astype(float)
        output *= np.sign(activation)
        return output


class PatternCompleter:
    """CA3-inspired Hopfield attractor network for pattern completion."""
    
    def __init__(self, pattern_dim: int = 512):
        self.dim = pattern_dim
        self.weights = np.zeros((pattern_dim, pattern_dim))
        self.stored_patterns: List[np.ndarray] = []
    
    def store(self, pattern: np.ndarray):
        """Hebbian storage: Δw_ij = x_i * x_j"""
        if len(pattern) < self.dim:
            pattern = np.pad(pattern, (0, self.dim - len(pattern)))
        p = pattern[:self.dim]
        self.weights += np.outer(p, p)
        np.fill_diagonal(self.weights, 0)  # no self-connections
        self.stored_patterns.append(p)
    
    def recall(self, partial: np.ndarray, iterations: int = 5) -> Tuple[np.ndarray, float]:
        """Hopfield dynamics: s_i = sign(Σ w_ij * s_j)"""
        if len(partial) < self.dim:
            partial = np.pad(partial, (0, self.dim - len(partial)))
        state = partial[:self.dim].copy()
        
        for _ in range(iterations):
            # Asynchronous update
            for i in range(self.dim):
                net_input = np.dot(self.weights[i], state)
                state[i] = np.tanh(net_input / 100.0)
        
        # Compute similarity with stored patterns
        similarities = []
        for stored in self.stored_patterns:
            sim = np.dot(state, stored) / (np.linalg.norm(state) * np.linalg.norm(stored) + 1e-8)
            similarities.append(sim)
        
        best_idx = int(np.argmax(similarities))
        return self.stored_patterns[best_idx], float(similarities[best_idx])


class HippocampalReplay:
    """
    Complete hippocampal replay system implementing:
    - DG pattern separation → CA3 pattern completion → SWR replay → consolidation
    """
    
    def __init__(self, max_recent: int = 200, swr_threshold: float = 0.3):
        self.separator = PatternSeparator()
        self.completer = PatternCompleter()
        self.recent: deque = deque(maxlen=max_recent)
        self.consolidated: List[MemoryPattern] = []
        
        # SWR detection state
        self._swr_probability = 0.0
        self.swr_threshold = swr_threshold
        self._idle_accumulator = 0.0
        
        # Stats
        self._total_encodes = 0
        self._total_replays = 0
        self._last_swr_time = time.time()
    
    def _text_to_pattern(self, text: str) -> np.ndarray:
        """Convert text to a fixed-dimension pattern using character n-gram hashing."""
        dim = 64
        pattern = np.zeros(dim)
        text = text.lower()
        for i in range(len(text)):
            # Character bigrams as features
            if i + 1 < len(text):
                h = hash(text[i:i+2]) % dim
                pattern[h] += 1.0
            # Single chars too
            h = hash(text[i]) % dim
            pattern[h] += 1.0
        # Normalize
        norm = np.linalg.norm(pattern)
        if norm > 0:
            pattern /= norm
        return pattern
    
    def encode(self, content: str, emotional_valence: float = 0.0,
               emotional_arousal: float = 0.0) -> MemoryPattern:
        """Encode an episodic memory through DG→CA3 pathway."""
        self._total_encodes += 1
        
        # DG: Pattern separation
        raw = self._text_to_pattern(content)
        sparse = self.separator.separate(raw)
        
        # CA3: Store in attractor network
        self.completer.store(sparse)
        
        # Create memory trace
        import uuid
        trace = MemoryPattern(
            id=str(uuid.uuid4())[:12],
            pattern=sparse,
            context=content,
            emotional_valence=emotional_valence,
            emotional_arousal=emotional_arousal,
        )
        self.recent.append(trace)
        
        # Emotion modulates consolidation rate
        emotional_intensity = abs(emotional_valence) * emotional_arousal
        trace.consolidation_level = min(0.3, emotional_intensity * 0.5)
        
        return trace
    
    def detect_swr(self, idle_duration: float) -> bool:
        """Detect Sharp-Wave Ripple event — triggers replay during rest."""
        # SWR probability increases with idle time and number of recent memories
        self._idle_accumulator += idle_duration
        
        recent_ratio = min(1.0, len(self.recent) / 20.0)
        idle_factor = min(1.0, self._idle_accumulator / 60.0)
        
        self._swr_probability = recent_ratio * idle_factor
        self._swr_probability *= 1.0 + 0.1 * np.random.randn()  # noise
        
        if self._swr_probability > self.swr_threshold:
            self._idle_accumulator = 0.0
            self._last_swr_time = time.time()
            return True
        return False
    
    def replay_swr(self, n_replays: int = 3) -> List[Tuple[MemoryPattern, float]]:
        """SWR-triggered replay: reactivate memories with temporal compression."""
        self._total_replays += 1
        if not self.recent:
            return []
        
        results = []
        
        # Select memories for replay (emotion-biased sampling)
        weights = []
        for t in self.recent:
            w = abs(t.emotional_valence) * 0.6 + t.emotional_arousal * 0.3 + 0.1
            weights.append(w)
        weights = np.array(weights) / sum(weights)
        
        indices = np.random.choice(len(self.recent), 
                                    size=min(n_replays, len(self.recent)),
                                    p=weights, replace=False)
        
        for idx in sorted(indices):
            trace = self.recent[idx]
            # CA3: Pattern completion — partial cue → full recall
            noise = np.random.randn(len(trace.pattern)) * 0.1
            partial = trace.pattern + noise
            recalled, similarity = self.completer.recall(partial)
            
            trace.replay_count += 1
            trace.strength = min(2.0, trace.strength + 0.05 * similarity)
            
            # Consolidation: repeated replay → neocortical transfer
            trace.consolidation_level += 0.02 * similarity
            trace.consolidation_level = min(1.0, trace.consolidation_level)
            
            results.append((trace, similarity))
        
        return results
    
    def consolidate(self, threshold: float = 0.8) -> List[MemoryPattern]:
        """Move fully consolidated memories to long-term storage."""
        moved = []
        remaining = deque(maxlen=self.recent.maxlen)
        for t in self.recent:
            if t.consolidation_level >= threshold:
                self.consolidated.append(t)
                moved.append(t)
            else:
                remaining.append(t)
        self.recent = remaining
        return moved
    
    def recall(self, cue: str, top_k: int = 5) -> List[Tuple[MemoryPattern, float]]:
        """Recall memories matching a cue — searches recent + consolidated."""
        cue_pattern = self._text_to_pattern(cue)
        sparse_cue = self.separator.separate(cue_pattern)
        
        # Try pattern completion
        completed, _ = self.completer.recall(sparse_cue)
        
        # Score all memories by similarity to completed pattern
        scored = []
        all_memories = list(self.recent) + self.consolidated
        for m in all_memories:
            sim = np.dot(completed, m.pattern) / (
                np.linalg.norm(completed) * np.linalg.norm(m.pattern) + 1e-8
            )
            # Boost by strength and emotional significance
            score = sim * m.strength * (1.0 + abs(m.emotional_valence) * 0.5)
            scored.append((score, m))
        
        scored.sort(key=lambda x: -x[0])
        return [(m, s) for s, m in scored[:top_k]]
    
    def decay_recent(self, rate: float = 0.005):
        """Apply Ebbinghaus forgetting curve to recent memories."""
        survivors = deque(maxlen=self.recent.maxlen)
        for t in self.recent:
            t.strength = max(0.05, t.strength - rate)
            if t.strength > 0.05 or t.consolidation_level > 0.5:
                survivors.append(t)
        self.recent = survivors
    
    def stats(self) -> dict:
        return {
            "recent_memories": len(self.recent),
            "consolidated_memories": len(self.consolidated),
            "total_encodes": self._total_encodes,
            "total_replays": self._total_replays,
            "swr_probability": round(self._swr_probability, 3),
            "avg_strength": float(np.mean([t.strength for t in self.recent])) if self.recent else 0.0,
            "avg_consolidation": float(np.mean([t.consolidation_level for t in self.recent])) if self.recent else 0.0,
            "separator_dim": f"{self.separator.input_dim}→{self.separator.output_dim}",
            "completer_patterns": len(self.completer.stored_patterns),
        }
