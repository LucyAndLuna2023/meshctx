"""
Emotional Consolidation Engine — 情绪记忆巩固系统 (v3.115.16)
基于 McGaugh(2000/2004) 情绪记忆调控 + Walker & Stickgold(2004) 睡眠依赖巩固 + Kensinger(2009) 情绪记忆偏向

核心机制:
1. Valence/Arousal 双维度标记 (Kensinger & Corkin, 2003; Kensinger, 2009):
   - 效价 (Valence): [-1, +1] 否定到肯定
   - 唤醒度 (Arousal): [0, 1] 平静到高度激动
   - 双过程: 高唤醒→杏仁核依赖的自动编码; 低唤醒→前额叶依赖的控制编码

2. 睡眠依赖巩固 (Walker & Stickgold, 2004; Diekelmann & Born, 2010):
   - SWS (慢波睡眠): 海马→新皮层系统巩固, 低频振荡(<1Hz)驱动重放
   - REM: 突触可塑性巩固, θ节律(4-8Hz)促进情绪记忆
   - 双阶段假说: SWS重复激活 + REM突触巩固
   - 情感标签优先: 高唤醒记忆在睡眠中优先巩固

3. 去甲肾上腺素/糖皮质激素调控 (McGaugh, 2000; Roozendaal et al., 2009):
   - 基底外侧杏仁核(BLA)→海马体投射
   - 情绪唤醒→NE释放→cAMP/PKA→CREB→蛋白质合成→LTP增强
   - 倒U型剂量-反应曲线

4. 情绪记忆偏向编码 (Kensinger, 2009; Christianson, 1992):
   - 情绪增强效应(EME): 情绪项目的记忆优于中性项目
   - 中心/周边权衡: 中心情绪细节增强, 周边背景细节削弱

参考文献:
- McGaugh JL (2000) Memory — a century of consolidation. Science
- McGaugh JL (2004) The amygdala modulates the consolidation of memories
- Walker MP, Stickgold R (2004) Sleep-dependent learning and memory consolidation
- Diekelmann S, Born J (2010) The memory function of sleep. Nat Rev Neurosci
- Kensinger EA (2009) Remembering the details: Effects of emotion
- Roozendaal B et al. (2009) The hippocampus mediates glucocorticoid-induced memory
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set, Callable
import time
import math
import hashlib


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class EmotionalTag:
    """Valence/arousal tag attached to a memory or experience."""
    valence: float               # [-1, +1] negative → positive
    arousal: float               # [0, 1] calm → intense
    dominance: float = 0.5       # [0, 1] submissive → dominant
    novelty: float = 0.0         # [0, 1] familiarity → novelty
    intensity: float = 0.0       # [0, 1] combined emotional intensity
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"

    def __post_init__(self):
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(0.0, min(1.0, self.arousal))
        # Intensity = arousal * (1.0 + |valence|)/2 → high arousal + extreme valence = high intensity
        self.intensity = self.arousal * (1.0 + abs(self.valence)) / 2.0


@dataclass
class EmotionalEmotionalMemoryItem:
    """A memory item tagged for emotional consolidation."""
    id: str
    content: str
    embedding: np.ndarray              # vector representation
    emotional_tag: EmotionalTag
    strength: float = 1.0              # raw memory strength
    consolidation_level: float = 0.0   # 0.0 (hippocampal) → 1.0 (neocortical)
    consolidation_count: int = 0       # number of consolidation cycles
    sleep_cycles: int = 0              # sleep cycles experienced
    rem_consolidated: bool = False
    sws_consolidated: bool = False
    timestamp: float = field(default_factory=time.time)
    priority_score: float = 0.0        # computed consolidation priority

    def __hash__(self):
        return hash(self.id)

    def compute_priority(self) -> float:
        """
        Consolidation priority = arousal * novelty * (1 - consolidation_level).
        High-arousal novel items that haven't been fully consolidated get priority.
        """
        self.priority_score = (
            self.emotional_tag.arousal
            * self.emotional_tag.novelty
            * (1.0 - self.consolidation_level)
            * self.strength
        )
        return self.priority_score


# ─── Valence / Arousal Detector ───────────────────────────────────────────────

class ValenceArousalDetector:
    """
    Emotion detection using lexicon-based valence/arousal mapping.
    NRC-VAD inspired: words mapped to VAD (Valence-Arousal-Dominance) space.
    """

    # Compact NRC-VAD-inspired lexicon (valence, arousal, dominance)
    _VAD_LEXICON: Dict[str, Tuple[float, float, float]] = {
        # High valence + high arousal
        "exciting": (0.85, 0.78, 0.70), "thrilling": (0.82, 0.85, 0.65),
        "wonderful": (0.92, 0.65, 0.72), "amazing": (0.90, 0.70, 0.68),
        "love": (0.95, 0.72, 0.65), "happy": (0.88, 0.62, 0.70),
        "joy": (0.91, 0.68, 0.67), "elated": (0.87, 0.71, 0.75),
        "victory": (0.83, 0.73, 0.82), "triumph": (0.84, 0.75, 0.85),
        # High valence + low arousal
        "peaceful": (0.82, 0.18, 0.55), "calm": (0.75, 0.12, 0.58),
        "serene": (0.80, 0.15, 0.52), "content": (0.72, 0.22, 0.60),
        "relaxed": (0.76, 0.16, 0.57), "gentle": (0.70, 0.20, 0.50),
        "comfortable": (0.74, 0.21, 0.62), "satisfied": (0.71, 0.25, 0.63),
        # Low valence + high arousal
        "terrified": (-0.93, 0.88, 0.15), "horrified": (-0.90, 0.82, 0.18),
        "furious": (-0.85, 0.80, 0.55), "enraged": (-0.88, 0.85, 0.52),
        "panic": (-0.82, 0.84, 0.20), "desperate": (-0.78, 0.75, 0.28),
        "angry": (-0.75, 0.68, 0.58), "hate": (-0.90, 0.65, 0.45),
        "rage": (-0.80, 0.78, 0.60), "scared": (-0.72, 0.70, 0.25),
        # Low valence + low arousal
        "sad": (-0.65, 0.30, 0.30), "depressed": (-0.75, 0.28, 0.20),
        "lonely": (-0.68, 0.32, 0.25), "gloomy": (-0.62, 0.27, 0.28),
        "bored": (-0.40, 0.18, 0.35), "tired": (-0.35, 0.20, 0.32),
        "hopeless": (-0.80, 0.33, 0.15), "miserable": (-0.78, 0.38, 0.18),
        # Dominance variations
        "powerful": (0.60, 0.62, 0.90), "weak": (-0.45, 0.38, 0.10),
        "confident": (0.75, 0.52, 0.82), "helpless": (-0.72, 0.55, 0.08),
        "brave": (0.65, 0.58, 0.78), "fearful": (-0.68, 0.62, 0.15),
        # Additional common words
        "anxious": (-0.55, 0.60, 0.22), "nervous": (-0.48, 0.55, 0.28),
        "worried": (-0.50, 0.48, 0.30), "stressed": (-0.60, 0.58, 0.25),
        "surprised": (0.40, 0.62, 0.35), "shocked": (-0.45, 0.75, 0.20),
        "disgusted": (-0.78, 0.52, 0.40), "proud": (0.78, 0.55, 0.78),
        "grateful": (0.82, 0.42, 0.55), "thankful": (0.80, 0.38, 0.52),
        "curious": (0.55, 0.48, 0.55), "interested": (0.60, 0.42, 0.58),
        "confused": (-0.35, 0.45, 0.25), "uncertain": (-0.30, 0.38, 0.30),
        "determined": (0.62, 0.58, 0.75), "motivated": (0.68, 0.55, 0.72),
        "hopeful": (0.65, 0.42, 0.52), "optimistic": (0.70, 0.45, 0.55),
        "pessimistic": (-0.42, 0.38, 0.32), "doubtful": (-0.35, 0.32, 0.35),
        "guilty": (-0.62, 0.45, 0.28), "ashamed": (-0.65, 0.48, 0.22),
        "jealous": (-0.55, 0.55, 0.30), "envious": (-0.45, 0.48, 0.32),
        "trust": (0.62, 0.28, 0.55), "betrayed": (-0.78, 0.58, 0.18),
    }

    def tag_text(self, text: str) -> EmotionalTag:
        """Detect valence and arousal from text using lexicon lookup."""
        import re
        tokens = re.findall(r'[a-z]+', text.lower())

        valences = []
        arousals = []
        dominances = []

        for token in tokens:
            if token in self._VAD_LEXICON:
                v, a, d = self._VAD_LEXICON[token]
                valences.append(v)
                arousals.append(a)
                dominances.append(d)

        if not valences:
            # Default neutral
            return EmotionalTag(valence=0.0, arousal=0.3, dominance=0.5)

        # Weighted mean: longer tokens get slightly more weight
        mean_valence = float(np.mean(valences))
        mean_arousal = float(np.mean(arousals))
        mean_dominance = float(np.mean(dominances))

        return EmotionalTag(
            valence=mean_valence,
            arousal=mean_arousal,
            dominance=mean_dominance,
            novelty=abs(mean_valence) * mean_arousal  # extreme + arousing = novel
        )

    def tag_embedding(self, embedding: np.ndarray) -> EmotionalTag:
        """Fallback: derive emotional tag from embedding vector properties."""
        # Heuristic: embedding norm ≈ arousal; first PC direction ≈ valence
        norm = float(np.linalg.norm(embedding))
        arousal = min(1.0, norm / max(1.0, np.sqrt(len(embedding))))

        # Pseudo-valence from weighted sum (positive bias from random init)
        raw_valence = float(np.mean(embedding)) * 2.0
        valence = max(-1.0, min(1.0, raw_valence))

        return EmotionalTag(valence=valence, arousal=arousal, dominance=0.5)


# ─── Noradrenergic Consolidation Model ────────────────────────────────────────

class NoradrenergicModulator:
    """
    Models the effect of norepinephrine (NE) on memory consolidation.
    McGaugh (2000): BLA NE release enhances hippocampal LTP consolidation.

    Key dynamics:
    - NE concentration follows an inverted-U dose-response on memory strength
    - Peak consolidation occurs at moderate NE levels
    - BLA lesion abolishes emotional memory enhancement
    """

    def __init__(self, baseline_ne: float = 0.1, peak_ne: float = 0.7):
        self.baseline_ne = baseline_ne
        self.peak_ne = peak_ne
        self.current_ne = baseline_ne
        self._ne_history: deque = deque(maxlen=100)

    def ne_from_arousal(self, arousal: float) -> float:
        """Map arousal [0,1] → NE concentration [0,1]."""
        # Sigmoidal: low arousal→baseline, high arousal→saturation
        k = 8.0  # steepness
        mid = 0.45
        return self.baseline_ne + (self.peak_ne - self.baseline_ne) / (1.0 + math.exp(-k * (arousal - mid)))

    def consolidation_gain(self, ne_level: float) -> float:
        """
        Inverted-U dose-response: consolidation gain from NE level.
        Yerkes-Dodson-like: optimal at ~0.6-0.7 NE, drop-off at extremes.
        """
        # Gaussian centered at optimal NE
        optimal_ne = 0.62
        sigma = 0.25
        gain = math.exp(-((ne_level - optimal_ne) ** 2) / (2 * sigma ** 2))
        # Floor at baseline consolidation rate
        return max(0.05, gain)

    def update_ne(self, emotional_intensity: float):
        """Update current NE level based on emotional intensity."""
        target = self.ne_from_arousal(emotional_intensity)
        # Slow dynamics: NE takes time to rise and fall
        tau = 0.3
        self.current_ne += tau * (target - self.current_ne)
        self._ne_history.append(self.current_ne)


# ─── Sleep Consolidation Engine ───────────────────────────────────────────────

class SleepConsolidator:
    """
    Sleep-dependent memory consolidation model.
    Walker & Stickgold (2004): SWS + REM stages perform complementary consolidation.

    SWS (Slow-Wave Sleep):
    - <1 Hz slow oscillations drive hippocampal replay
    - Spindle events (12-15Hz) couple with slow oscillations for neocortical transfer
    - Selective reactivation of memories tagged for consolidation

    REM:
    - Theta (4-8Hz) promotes synaptic plasticity
    - Emotional memory strengthening via amygdala-hippocampal coupling
    - Creative association formation
    """

    def __init__(self,
                 sws_duration_minutes: float = 90.0,
                 rem_duration_minutes: float = 70.0,
                 n_cycles: int = 4):
        self.sws_duration = sws_duration_minutes
        self.rem_duration = rem_duration_minutes
        self.n_cycles = n_cycles
        self.spindle_rate: float = 8.0       # spindles per minute during SWS
        self.theta_power: float = 0.5         # theta power during REM
        self._sleep_history: List[Dict] = []

    def consolidate_sws(self, memories: List[EmotionalEmotionalMemoryItem],
                         consolidation_rate: float = 0.05) -> List[EmotionalEmotionalMemoryItem]:
        """
        SWS consolidation: hippocampal → neocortical transfer.
        Prioritizes high-arousal tagged memories.
        Selective replay: each spindle event picks top-k memories for reactivation.
        """
        if not memories:
            return memories

        n_spindles = int(self.sws_duration * self.spindle_rate / 60.0)
        reactivations_per_spindle = min(5, len(memories))

        for _ in range(n_spindles):
            # Sort by priority and pick top for reactivation
            for m in memories:
                m.compute_priority()

            sorted_mems = sorted(memories, key=lambda m: m.priority_score, reverse=True)
            reactivated = sorted_mems[:reactivations_per_spindle]

            for mem in reactivated:
                # Consolidation: move from hippocampal (0) → neocortical (1)
                # Rate modulated by emotional arousal (McGaugh effect)
                arousal_boost = 1.0 + mem.emotional_tag.arousal
                increment = consolidation_rate * arousal_boost * mem.priority_score
                mem.consolidation_level = min(1.0, mem.consolidation_level + increment)
                mem.consolidation_count += 1

            mem.sws_consolidated = True

        self._sleep_history.append({
            'stage': 'SWS', 'duration_min': self.sws_duration,
            'n_spindles': n_spindles, 'memories_consolidated': len(memories)
        })
        return memories

    def consolidate_rem(self, memories: List[EmotionalEmotionalMemoryItem],
                         plasticity_rate: float = 0.03) -> List[EmotionalEmotionalMemoryItem]:
        """
        REM consolidation: synaptic plasticity strengthening.
        Emotional memories get extra strengthening.
        Theta oscillations drive associative binding.
        """
        if not memories:
            return memories

        # Theta cycles during REM
        theta_freq = 6.0  # Hz
        n_theta_cycles = int(self.rem_duration * 60 * theta_freq / 60.0)

        for _ in range(n_theta_cycles // 10):  # batch per ~10 theta cycles
            for mem in memories:
                mem.compute_priority()

                # REM selectively strengthens emotional memories (Walker & Stickgold)
                emotional_component = abs(mem.emotional_tag.valence) * mem.emotional_tag.arousal
                rem_boost = 1.0 + 2.0 * emotional_component

                # Synaptic consolidation: strengthen the memory trace
                delta = plasticity_rate * rem_boost * self.theta_power * mem.priority_score
                mem.strength = min(3.0, mem.strength + delta)
                mem.rem_consolidated = True
                mem.sleep_cycles += 1

        self._sleep_history.append({
            'stage': 'REM', 'duration_min': self.rem_duration,
            'theta_cycles': n_theta_cycles, 'memories_strengthened': len(memories)
        })
        return memories

    def sleep_cycle(self, memories: List[EmotionalEmotionalMemoryItem],
                    consolidation_rate: float = 0.05,
                    plasticity_rate: float = 0.03) -> List[EmotionalEmotionalMemoryItem]:
        """Run one full sleep cycle: SWS → REM."""
        for cycle in range(self.n_cycles):
            # Early cycles: more SWS; later cycles: more REM (Born et al., 2006)
            sws_factor = 1.0 - 0.2 * cycle  # SWS declines across cycles
            rem_factor = 1.0 + 0.15 * cycle  # REM increases across cycles

            old_sws = self.sws_duration
            old_rem = self.rem_duration
            self.sws_duration = old_sws * sws_factor
            self.rem_duration = old_rem * rem_factor

            memories = self.consolidate_sws(memories, consolidation_rate)
            memories = self.consolidate_rem(memories, plasticity_rate)

            self.sws_duration = old_sws
            self.rem_duration = old_rem

        return memories


# ─── Main Emotional Consolidation Engine ──────────────────────────────────────

class EmotionalConsolidation:
    """
    Complete emotional memory consolidation system.
    Integrates:
    - Valence/arousal detection (Kensinger, 2009)
    - Noradrenergic modulation (McGaugh, 2000)
    - Sleep-dependent consolidation (Walker & Stickgold, 2004)
    """

    def __init__(self):
        self.detector = ValenceArousalDetector()
        self.ne_modulator = NoradrenergicModulator()
        self.sleep_consolidator = SleepConsolidator()
        self.memories: List[EmotionalEmotionalMemoryItem] = []
        self._tag_history: List[EmotionalTag] = []
        self._consolidation_epoch: int = 0
        self._rng = np.random.RandomState(42)

    def tag_experience(self, content: str,
                        embedding: Optional[np.ndarray] = None) -> EmotionalMemoryItem:
        """Tag a new experience with emotional metadata and register it."""
        tag = self.detector.tag_text(content)

        if embedding is None:
            # Hash-based pseudo-embedding
            h = int(hashlib.sha256(content.encode()).hexdigest(), 16)
            embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(16)])

        mem_id = hashlib.sha256(
            f"{content}:{time.time()}:{len(self.memories)}".encode()
        ).hexdigest()[:12]

        item = EmotionalEmotionalMemoryItem(
            id=mem_id,
            content=content,
            embedding=embedding,
            emotional_tag=tag
        )
        item.compute_priority()

        self.memories.append(item)
        self._tag_history.append(tag)

        # Noradrenergic modulation on encoding
        self.ne_modulator.update_ne(tag.arousal)
        ne_level = self.ne_modulator.current_ne
        gain = self.ne_modulator.consolidation_gain(ne_level)
        item.strength *= gain

        return item

    def consolidate(self, consolidation_rate: float = 0.05,
                    plasticity_rate: float = 0.03) -> Dict:
        """
        Run one consolidation epoch (daytime + sleep).

        Daytime: noradrenergic modulation maintains high-arousal memory traces
        Sleep: SWS + REM cycles consolidate memories
        """
        self._consolidation_epoch += 1

        # Daytime: NE-modulated trace maintenance
        for mem in self.memories:
            ne_gain = self.ne_modulator.consolidation_gain(
                self.ne_modulator.ne_from_arousal(mem.emotional_tag.arousal)
            )
            # Emotional memories decay slower
            decay = 0.001 * (1.0 - ne_gain * mem.emotional_tag.intensity)
            mem.strength = max(0.01, mem.strength - decay)

        # Sleep consolidation
        self.memories = self.sleep_consolidator.sleep_cycle(
            self.memories, consolidation_rate, plasticity_rate
        )

        # Compute stats
        return {
            'epoch': self._consolidation_epoch,
            'n_memories': len(self.memories),
            'consolidated': sum(1 for m in self.memories if m.consolidation_level > 0.5),
            'fully_consolidated': sum(1 for m in self.memories if m.consolidation_level > 0.95),
            'mean_strength': float(np.mean([m.strength for m in self.memories])),
            'mean_consolidation': float(np.mean([m.consolidation_level for m in self.memories])),
            'current_ne': round(self.ne_modulator.current_ne, 3),
            'sleep_cycles_completed': self._consolidation_epoch
        }

    def query_emotional_state(self) -> Dict:
        """Get current emotional state of the system."""
        if not self._tag_history:
            return {'valence': 0.0, 'arousal': 0.0, 'dominance': 0.5,
                    'mood_label': 'neutral'}

        # Weighted by recency (more recent = more influential)
        recent = list(self._tag_history)[-20:]
        weights = np.exp(np.linspace(-2, 0, len(recent)))
        weights /= weights.sum()

        mean_v = float(np.average([t.valence for t in recent], weights=weights))
        mean_a = float(np.average([t.arousal for t in recent], weights=weights))
        mean_d = float(np.average([t.dominance for t in recent], weights=weights))

        return {
            'valence': round(mean_v, 3),
            'arousal': round(mean_a, 3),
            'dominance': round(mean_d, 3),
            'mood_label': self._classify_mood(mean_v, mean_a)
        }

    @staticmethod
    def _classify_mood(valence: float, arousal: float) -> str:
        """Classify mood quadrant from valence-arousal space (Russell's circumplex)."""
        if valence > 0.2 and arousal > 0.5:
            return 'excited / elated'
        elif valence > 0.2 and arousal <= 0.5:
            return 'calm / content'
        elif valence <= -0.2 and arousal > 0.5:
            return 'distressed / anxious'
        elif valence <= -0.2 and arousal <= 0.5:
            return 'depressed / bored'
        elif abs(valence) <= 0.2 and arousal > 0.5:
            return 'alert / surprised'
        elif abs(valence) <= 0.2 and arousal <= 0.5:
            return 'neutral'
        return 'neutral'

    def get_priority_queue(self, top_k: int = 10) -> List[EmotionalEmotionalMemoryItem]:
        """Return top-k memories by consolidation priority."""
        for m in self.memories:
            m.compute_priority()
        return sorted(self.memories, key=lambda m: m.priority_score, reverse=True)[:top_k]
