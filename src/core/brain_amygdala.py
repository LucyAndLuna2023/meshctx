"""
Amygdala Salience Tagger — 杏仁核显著性标记器 (v3.115.16)
基于 LeDoux(1996) 双通路恐惧条件化 + McGaugh(2004) 记忆巩固情绪调控

核心机制:
1. 双通路威胁检测 (LeDoux, 1996):
   - Fast Subcortical: 丘脑→外侧杏仁核(LA) 直接通路, ~12ms, 粗糙但快速
   - Slow Cortical: 丘脑→感觉皮层→LA, ~30-40ms, 精细分析
   - LA整合两通路信号 → 中央杏仁核(CeA)输出恐惧反应

2. 情绪调控记忆巩固 (McGaugh, 2004):
   - 基底外侧杏仁核(BLA)→海马体投射
   - 去甲肾上腺素/糖皮质激素调控LTP
   - 高唤醒度 → 更强记忆巩固信号

3. 新颖性检测 + 习惯化 (Groves & Thompson, 1970):
   - 双过程理论: 习惯化(递减) + 敏感化(递增)
   - 刺激特异性衰减 + 去习惯化

参考文献:
- LeDoux JE (1996) The Emotional Brain
- McGaugh JL (2004) The amygdala modulates the consolidation of memories
- Groves PM, Thompson RF (1970) Habituation: A dual-process theory
- Davis M, Whalen PJ (2001) The amygdala: vigilance and emotion
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set
import time
import math
import hashlib


# ─── Threat Lexicon & Semantic Embeddings ───────────────────────────────────
# LeDoux: amygdala responds to innate + learned threat cues
_THREAT_WORDS: Set[str] = {
    "danger", "kill", "attack", "threat", "weapon", "bomb", "fire",
    "murder", "death", "die", "dead", "hurt", "pain", "war", "blood",
    "gun", "knife", "stab", "shoot", "explode", "terror", "panic",
    "emergency", "warning", "critical", "fatal", "severe", "violence",
    "assault", "hostage", "hostile", "intruder", "predator", "venom",
    "poison", "toxic", "hazard", "collapse", "crash", "scream",
    "help!", "run!", "flee", "hide", "escape", "survive",
}

_SAFETY_WORDS: Set[str] = {
    "safe", "peace", "calm", "relax", "gentle", "warm", "love",
    "happy", "joy", "comfort", "secure", "protected", "friend",
    "kind", "soft", "quiet", "serene", "tranquil", "harmony",
}

# Word-level threat embeddings: coarse vector representations for fast pathway
# Each word → 16-dim embedding. Fast pathway uses cosine similarity to threat prototype.
def _build_threat_prototype(dim: int = 16, seed: int = 42) -> np.ndarray:
    """Build a prototypical 'threat' vector in embedding space."""
    rng = np.random.RandomState(seed)
    return rng.randn(dim)


_THREAT_PROTOTYPE = _build_threat_prototype(16)
_SAFETY_PROTOTYPE = np.random.RandomState(43).randn(16)


def _tokenize(text: str) -> List[str]:
    """Simple tokenization: lowercase, split on non-alpha, filter short tokens."""
    import re
    tokens = re.findall(r'[a-z!?]+', text.lower())
    # Normalize: strip trailing punctuation for matching, but keep it for embedding
    return [t for t in tokens if len(t) > 1]


def _normalize_token(token: str) -> str:
    """Strip trailing punctuation for threat-word matching."""
    return token.rstrip('!?.,;:')


def _word_embedding(word: str, dim: int = 16) -> np.ndarray:
    """Deterministic pseudo-embedding via hash → random projection (fixed seed)."""
    h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
    rng = np.random.RandomState(h % (2**31))
    vec = rng.randn(dim)
    return vec / (np.linalg.norm(vec) + 1e-8)


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ThreatSignal:
    """Output of threat detection — the amygdala's assessment."""
    fast_score: float          # fast subcortical pathway (0-1)
    slow_score: float          # slow cortical pathway (0-1)
    integrated_score: float    # LA-integrated score (0-1)
    fear_response: float       # CeA output: physiological response magnitude
    valence: float             # -1 (negative) to +1 (positive)
    arousal: float             # 0 (calm) to 1 (highly aroused)
    novelty: float             # 0 (familiar) to 1 (completely novel)
    habituation_level: float   # 0 (no habituation) to 1 (fully habituated)
    is_threat: bool            # binary threat classification
    modulation_signal: float   # BLA→hippocampus consolidation modulation (0-1)


@dataclass
class StimulusTrace:
    """Memory trace of a previously encountered stimulus (for habituation)."""
    stimulus_hash: str
    text: str
    valence: float
    arousal: float
    exposure_count: int = 1
    last_exposed: float = field(default_factory=time.time)
    habituation_rate: float = 0.0
    recovery_rate: float = 0.0


# ─── Fast Subcortical Pathway ────────────────────────────────────────────────
# LeDoux: thalamus → lateral amygdala, bypassing cortex. ~12ms latency.
# Detects crude threat features: specific keywords, basic acoustic patterns.

class FastSubcorticalPathway:
    """
    Thalamus → Lateral Amygdala direct projection.
    Rapid, coarse threat detection using keyword matching + shallow embeddings.
    """

    def __init__(self, dim: int = 16):
        self.dim = dim
        # Threat prototype learned through evolution/conditioning
        self.threat_prototype = _THREAT_PROTOTYPE.copy()
        # Learned threat associations (conditioned stimuli)
        self.conditioned_threats: Dict[str, float] = {}
        # Threshold for triggering
        self.threshold: float = 0.35

    def detect(self, text: str) -> Tuple[float, float, float]:
        """
        Fast threat detection.
        Returns: (threat_score, valence, arousal)
        Latency: ~12ms equivalent — O(n_tokens * dim)
        """
        tokens = _tokenize(text)
        if not tokens:
            return 0.0, 0.0, 0.0

        # 1. Keyword match: innate threat words (evolutionarily hardwired)
        normalized = [_normalize_token(t) for t in tokens]
        threat_keyword_count = sum(1 for t in normalized if t in _THREAT_WORDS)
        safety_keyword_count = sum(1 for t in normalized if t in _SAFETY_WORDS)

        keyword_threat = threat_keyword_count / max(len(tokens), 1)
        keyword_safety = safety_keyword_count / max(len(tokens), 1)

        # 2. Embedding similarity to threat prototype
        embeddings = np.array([_word_embedding(t, self.dim) for t in tokens])
        similarities = np.dot(embeddings, self.threat_prototype)
        k = max(1, len(tokens) // 3)
        top_k_sims = np.sort(similarities)[-k:]
        embedding_threat = float(np.tanh(np.mean(top_k_sims) * 2.0) * 0.5 + 0.5)

        # 3. Conditioned threat associations (learned fears)
        conditioned_score = 0.0
        for token in normalized:
            if token in self.conditioned_threats:
                conditioned_score = max(conditioned_score, self.conditioned_threats[token])

        # Integrate: keyword match dominates (innate), embedding refines, conditioned adds
        # Gate: embedding signal only contributes if there's also keyword or conditioned evidence
        has_lexical_evidence = keyword_threat > 0.0 or conditioned_score > 0.0
        embedding_weight = 0.30 if has_lexical_evidence else 0.12
        fast_score = (
            0.55 * keyword_threat +
            embedding_weight * embedding_threat +
            0.15 * conditioned_score
        )
        fast_score = min(fast_score, 1.0)

        # Valence: negative if threat detected
        valence = -fast_score * 1.2 + keyword_safety * 0.8
        valence = np.clip(valence, -1.0, 1.0)

        # Arousal: intensity of the signal
        arousal = fast_score * 0.9 + 0.1 * (1.0 - keyword_safety)

        return fast_score, valence, arousal

    def condition(self, stimulus: str, threat_level: float):
        """Condition a neutral stimulus to become a threat predictor (fear conditioning)."""
        tokens = _tokenize(stimulus)
        for t in tokens:
            nt = _normalize_token(t)
            old = self.conditioned_threats.get(nt, 0.0)
            # Rescorla-Wagner learning rule
            lr = 0.15
            self.conditioned_threats[nt] = old + lr * (threat_level - old)


# ─── Slow Cortical Pathway ───────────────────────────────────────────────────
# LeDoux: thalamus → sensory cortex → lateral amygdala. ~30-40ms latency.
# Finer-grained semantic analysis, context integration.

class SlowCorticalPathway:
    """
    Thalamus → Sensory Cortex → Lateral Amygdala.
    Slower, refined threat analysis with contextual/semantic processing.
    """

    def __init__(self, dim: int = 16):
        self.dim = dim
        self.threat_prototype = _THREAT_PROTOTYPE.copy()
        self.safety_prototype = _SAFETY_PROTOTYPE.copy()

        # Cortical semantic knowledge: broader threat associations
        self._semantic_field: Dict[str, np.ndarray] = {}

        # Build semantic threat field from the threat lexicon
        rng = np.random.RandomState(99)
        for word in _THREAT_WORDS:
            self._semantic_field[word] = rng.randn(dim) * 0.3 + self.threat_prototype * 0.7
        for word in _SAFETY_WORDS:
            self._semantic_field[word] = rng.randn(dim) * 0.3 + self.safety_prototype * 0.7

        # Context memory for integration across sentences
        self.context_buffer: deque = deque(maxlen=5)

    def detect(self, text: str) -> Tuple[float, float, float]:
        """
        Slow, cortical threat analysis.
        Considers: semantic similarity, contextual coherence, ambiguity resolution.
        Returns: (threat_score, valence, arousal)
        """
        tokens = _tokenize(text)
        if not tokens:
            return 0.0, 0.0, 0.0

        embeddings = np.array([_word_embedding(t, self.dim) for t in tokens])

        # 1. Semantic similarity analysis: each token vs threat/safety prototypes
        threat_sims = np.dot(embeddings, self.threat_prototype)
        safety_sims = np.dot(embeddings, self.safety_prototype)

        # 2. Weighted by word position: later words may resolve ambiguity
        n = len(tokens)
        if n > 1:
            position_weights = np.linspace(0.6, 1.4, n)  # later words weigh more
            position_weights /= position_weights.sum()
            weighted_threat = np.dot(threat_sims, position_weights)
            weighted_safety = np.dot(safety_sims, position_weights)
        else:
            weighted_threat = float(threat_sims[0])
            weighted_safety = float(safety_sims[0])

        # 3. Contextual integration: how does this text relate to recent context?
        context_boost = 0.0
        if self.context_buffer:
            context_embedding = np.mean([
                _word_embedding(w, self.dim)
                for ctx in self.context_buffer
                for w in _tokenize(ctx)
            ], axis=0) if any(_tokenize(ctx) for ctx in self.context_buffer) else np.zeros(self.dim)
            if np.linalg.norm(context_embedding) > 1e-8:
                text_embedding = np.mean(embeddings, axis=0)
                context_sim = float(np.dot(text_embedding, context_embedding) /
                                    (np.linalg.norm(text_embedding) * np.linalg.norm(context_embedding) + 1e-8))
                # If context was threatening, amplify the current threat assessment
                context_boost = np.tanh(context_sim) * 0.15

        # 4. Ambiguity penalty: conflicting signals reduce confidence
        threat_signal = np.tanh(weighted_threat * 1.8) * 0.5 + 0.5
        safety_signal = np.tanh(weighted_safety * 1.8) * 0.5 + 0.5
        ambiguity = 1.0 - abs(threat_signal - safety_signal)  # 1 when equally threat/safe

        slow_score = threat_signal * (1.0 - 0.3 * ambiguity) + context_boost
        slow_score = np.clip(slow_score, 0.0, 1.0)

        # Valence: refined by safety signal
        valence = -slow_score * 1.0 + safety_signal * 0.7
        valence = np.clip(valence, -1.0, 1.0)

        # Arousal: higher when less ambiguous (clear signal)
        clarity = 1.0 - ambiguity * 0.5
        arousal = slow_score * clarity + 0.05 * len(tokens)

        # Update context buffer
        self.context_buffer.append(text)

        return slow_score, valence, arousal


# ─── Lateral Amygdala Integrator ─────────────────────────────────────────────
# LA integrates fast subcortical (coarse, rapid) + slow cortical (refined) signals.

class LateralAmygdalaIntegrator:
    """
    Lateral Amygdala: convergence zone for both pathways.
    Integrates fast (subcortical) and slow (cortical) threat signals.
    Implements temporal coincidence detection: fast+slow co-activation → strong response.
    """

    def __init__(self, fast_weight: float = 0.45, slow_weight: float = 0.55):
        # Initial weights favor slow pathway slightly (more reliable)
        # But fast pathway can override if signal is very strong
        self.fast_weight = fast_weight
        self.slow_weight = slow_weight
        # Metaplasticity: adjust weights based on past accuracy
        self.fast_accuracy: deque = deque(maxlen=20)
        self.slow_accuracy: deque = deque(maxlen=20)

    def integrate(self, fast_score: float, fast_valence: float, fast_arousal: float,
                  slow_score: float, slow_valence: float, slow_arousal: float) -> Tuple[float, float, float]:
        """
        Integrate fast and slow pathway signals.
        Coincidence detection: if both pathways agree, amplify.
        Conflict resolution: if they disagree, trust slow pathway but let fast override if very strong.
        """
        # Base weighted integration
        integrated_score = self.fast_weight * fast_score + self.slow_weight * slow_score

        # Coincidence amplification (both pathways agree on threat)
        agreement = 1.0 - abs(fast_score - slow_score)  # 1 = perfect agreement
        coincidence_boost = agreement * 0.2 * min(fast_score, slow_score)
        integrated_score += coincidence_boost

        # Fast pathway override: if fast signal is extremely strong, it dominates
        # (evolutionary: snake-like object → react first, analyze later)
        if fast_score > 0.8:
            fast_override = (fast_score - 0.8) * 0.6
            integrated_score = max(integrated_score, fast_score - fast_override * 0.3)

        integrated_score = np.clip(integrated_score, 0.0, 1.0)

        # Integrated valence: blend, weighted by pathway confidence
        integrated_valence = self.fast_weight * fast_valence + self.slow_weight * slow_valence
        integrated_valence = np.clip(integrated_valence, -1.0, 1.0)

        # Integrated arousal: take the stronger signal (arousal is additive)
        integrated_arousal = max(fast_arousal, slow_arousal)

        # Metaplasticity: track which pathway contributed more
        contribution_ratio = fast_score / (slow_score + 1e-6)
        self.fast_accuracy.append(1.0 if contribution_ratio > 0.8 else 0.0)
        self.slow_accuracy.append(1.0 if contribution_ratio < 1.2 else 0.0)

        # Adjust weights slowly based on accuracy history
        if len(self.fast_accuracy) >= 10:
            fast_acc = np.mean(self.fast_accuracy)
            slow_acc = np.mean(self.slow_accuracy)
            total = fast_acc + slow_acc + 1e-6
            self.fast_weight = 0.3 + 0.4 * (fast_acc / total)
            self.slow_weight = 0.3 + 0.4 * (slow_acc / total)

        return integrated_score, integrated_valence, integrated_arousal


# ─── Central Amygdala Output ─────────────────────────────────────────────────
# CeA generates the fear/defense response: physiological, behavioral, endocrine.

class CentralAmygdalaResponse:
    """
    Central Amygdala: generates fear response output.
    Three response components:
    - Freezing/startle (behavioral)
    - Autonomic arousal (physiological)
    - HPA axis activation (endocrine/cortisol)
    """

    def __init__(self, response_threshold: float = 0.4):
        self.threshold = response_threshold
        # Response history for sensitization
        self.response_history: deque = deque(maxlen=10)

    def generate_response(self, integrated_score: float, integrated_arousal: float) -> float:
        """
        Generate CeA fear response magnitude.
        Includes sensitization: prior threat exposure lowers response threshold.
        """
        # Base response proportional to integrated threat score
        if integrated_score < self.threshold:
            base_response = 0.0
        else:
            # Sigmoid activation: sharp transition near threshold
            x = (integrated_score - self.threshold) / (1.0 - self.threshold)
            base_response = 1.0 / (1.0 + math.exp(-8.0 * (x - 0.3)))

        # Sensitization: recent high-threat experiences amplify current response
        sensitization = 0.0
        if self.response_history:
            recent_avg = np.mean(self.response_history)
            sensitization = recent_avg * 0.25  # up to 25% boost

        # Arousal modulates response intensity
        arousal_factor = 0.7 + 0.3 * integrated_arousal

        fear_response = (base_response + sensitization) * arousal_factor
        fear_response = np.clip(fear_response, 0.0, 1.0)

        # Record for sensitization
        self.response_history.append(fear_response)

        return fear_response

    def reset_sensitization(self):
        """Reset after a safety period."""
        self.response_history.clear()


# ─── Novelty Detection & Habituation ─────────────────────────────────────────
# Groves & Thompson (1970): Dual-process theory of habituation and sensitization.

class NoveltyHabituationSystem:
    """
    Novelty detection + habituation (Groves & Thompson, 1970).
    
    Two independent processes:
    1. Habituation (S-R pathway):递减 — decreased response to repeated stimuli
    2. Sensitization (state system):递增 — increased responsiveness after arousing stimuli
    
    Stimulus-specific habituation: each stimulus trace decays independently.
    """
    
    def __init__(self, 
                 habituation_rate: float = 0.12,
                 spontaneous_recovery_rate: float = 0.003,
                 novelty_threshold: float = 0.3,
                 trace_ttl: float = 300.0):  # 5 min before trace considered expired
        self.habituation_rate = habituation_rate
        self.recovery_rate = spontaneous_recovery_rate
        self.novelty_threshold = novelty_threshold
        self.trace_ttl = trace_ttl
        
        # Stimulus-specific memory traces
        self.traces: Dict[str, StimulusTrace] = {}
        
        # State sensitization (non-specific, global arousal boost)
        self.sensitization_level: float = 0.0
        self.sensitization_decay: float = 0.02  # per exposure
        
        # Orienting response tracking
        self.last_orienting: float = 0.0
        self.orienting_count: int = 0
        
    def _hash_stimulus(self, text: str) -> str:
        """Compute stimulus identity hash for recognition."""
        tokens = sorted(set(_tokenize(text)))
        combined = "|".join(tokens[:10])  # first 10 unique tokens
        return hashlib.md5(combined.encode()).hexdigest()[:12]
    
    def _recover_traces(self):
        """Recover habituation traces over time (spontaneous recovery)."""
        now = time.time()
        for shash, trace in list(self.traces.items()):
            elapsed = now - trace.last_exposed
            if elapsed > self.trace_ttl:
                del self.traces[shash]
            else:
                # Spontaneous recovery: habituation decays over time
                recovery = self.recovery_rate * elapsed
                trace.habituation_rate = max(0.0, trace.habituation_rate - recovery)
                
    def assess(self, text: str, current_arousal: float) -> Tuple[float, float]:
        """
        Assess novelty and habituation for a stimulus.
        Returns: (novelty_score, habituation_level)
        - novelty_score: 0 (familiar) → 1 (completely novel)
        - habituation_level: 0 (no habituation) → 1 (fully habituated)
        """
        self._recover_traces()
        
        shash = self._hash_stimulus(text)
        
        if shash not in self.traces:
            # Completely novel stimulus
            self.traces[shash] = StimulusTrace(
                stimulus_hash=shash,
                text=text,
                valence=0.0,
                arousal=current_arousal,
                exposure_count=1,
                habituation_rate=0.0,
            )
            novelty = 1.0
            habituation = 0.0
        else:
            trace = self.traces[shash]
            trace.exposure_count += 1
            trace.last_exposed = time.time()
            
            # Habituation grows with repeated exposure (negatively accelerated)
            # Formula: H(n) = 1 - exp(-rate * n)  — exponential approach to 1
            n = trace.exposure_count
            trace.habituation_rate = 1.0 - math.exp(-self.habituation_rate * n)
            
            habituation = trace.habituation_rate
            
            # Novelty is the inverse of habituation, but also decays with time
            time_factor = 0.0  # if just seen, no recovery
            novelty = (1.0 - habituation) * (1.0 + time_factor)
            novelty = np.clip(novelty, 0.0, 1.0)
        
        # State sensitization boost: novel stimuli after high-arousal events are MORE novel
        sensitization_boost = self.sensitization_level * 0.3
        novelty = min(1.0, novelty + sensitization_boost)
        
        # Decay sensitization (non-specific)
        self.sensitization_level *= (1.0 - self.sensitization_decay)
        
        # Boost sensitization from high arousal
        if current_arousal > 0.6:
            self.sensitization_level = min(1.0, self.sensitization_level + 0.15)
        
        # Track orienting response
        if novelty > self.novelty_threshold:
            self.last_orienting = novelty
            self.orienting_count += 1
            
        return novelty, habituation
    
    def get_habituation_summary(self) -> Dict:
        """Summary statistics for the habituation system."""
        return {
            "total_traces": len(self.traces),
            "mean_exposures": np.mean([t.exposure_count for t in self.traces.values()]) if self.traces else 0,
            "sensitization": self.sensitization_level,
            "orienting_count": self.orienting_count,
        }


# ─── BLA Memory Modulation ───────────────────────────────────────────────────
# McGaugh (2004): BLA modulates hippocampal memory consolidation via:
# 1. Norepinephrine release (emotional arousal)
# 2. Glucocorticoid enhancement (stress hormones)
# 3. Direct BLA→hippocampus projections strengthening LTP

class BLAMemoryModulator:
    """
    Basolateral Amygdala → Hippocampus memory modulation.
    Translates emotional salience into consolidation signals for the hippocampus.
    
    McGaugh's model: emotionally arousing events trigger hormonal + neural cascades
    that enhance memory consolidation. The BLA is the critical node.
    """
    
    def __init__(self):
        # Neuromodulator levels
        self.norepinephrine: float = 0.0      # 0-1, arousal-linked
        self.glucocorticoid: float = 0.0       # 0-1, stress-linked, slower
        self.acetylcholine: float = 0.05       # baseline attentional tone
        
        # Dynamics
        self.ne_decay: float = 0.08       # faster decay
        self.gc_decay: float = 0.02       # slower decay (hormonal)
        self.ne_rise: float = 0.6         # rapid release
        self.gc_rise: float = 0.15        # gradual release
        
        # Consolidation signal history
        self.modulation_history: deque = deque(maxlen=50)
        
    def update(self, integrated_score: float, arousal: float, 
               valence: float, fear_response: float):
        """
        Update neuromodulator levels based on emotional experience.
        Called on each stimulus processing cycle.
        """
        # Norepinephrine: fast, proportional to arousal + fear response
        ne_target = 0.6 * arousal + 0.4 * fear_response
        self.norepinephrine += self.ne_rise * (ne_target - self.norepinephrine)
        
        # Glucocorticoid: slower, proportional to integrated threat + sustained stress
        gc_target = 0.7 * integrated_score + 0.3 * self.glucocorticoid  # self-reinforcing
        self.glucocorticoid += self.gc_rise * (gc_target - self.glucocorticoid)
        
        # Acetylcholine: attentional component, novelty-driven (not implemented here, modulated externally)
        self.acetylcholine = np.clip(self.acetylcholine + 0.01 * arousal, 0.0, 1.0)
        
    def decay(self):
        """Time-based decay of neuromodulators (call periodically or per event)."""
        self.norepinephrine *= (1.0 - self.ne_decay)
        self.glucocorticoid *= (1.0 - self.gc_decay)
        self.acetylcholine *= 0.98
        
    def compute_modulation_signal(self) -> float:
        """
        Compute the BLA→hippocampus consolidation modulation signal.
        
        McGaugh: NE + GC interact synergistically. NE triggers initial consolidation,
        GC sustains it over time. Combined, they enhance LTP.
        
        Returns: modulation strength (0-1), to be used by hippocampus for memory weight.
        """
        # Interactive effect: NE × GC synergy (McGaugh & Roozendaal, 2002)
        # NE alone: moderate consolidation boost
        # GC alone: weak effect (needs NE for BLA activation)
        # NE + GC: strong synergistic boost
        ne_effect = self.norepinephrine * 0.6
        gc_effect = self.glucocorticoid * 0.4 * (0.3 + 0.7 * self.norepinephrine)  # gated by NE
        ach_effect = self.acetylcholine * 0.2  # attentional enhancement
        
        modulation = ne_effect + gc_effect + ach_effect
        
        # Emotional intensity gate: valence extremity amplifies modulation
        valence_intensity = abs(self._get_stored_valence())
        modulation *= (0.8 + 0.4 * valence_intensity)
        
        modulation = np.clip(modulation, 0.0, 1.0)
        
        self.modulation_history.append(modulation)
        return modulation
    
    def _get_stored_valence(self) -> float:
        """Get the current effective valence for modulation computation."""
        return np.mean([m for m in self.modulation_history]) if self.modulation_history else 0.0
    
    def get_state(self) -> Dict:
        """Return current neuromodulator state."""
        return {
            "norepinephrine": self.norepinephrine,
            "glucocorticoid": self.glucocorticoid,
            "acetylcholine": self.acetylcholine,
            "modulation": self.compute_modulation_signal() if self.modulation_history else 0.0,
        }


# ─── Main Amygdala Salience Tagger ───────────────────────────────────────────

class AmygdalaSalience:
    """
    Complete Amygdala Salience Tagger.
    
    Implements LeDoux's two-pathway fear conditioning +
    McGaugh's emotional memory consolidation modulation +
    Groves & Thompson's novelty/habituation dual-process theory.
    
    Usage:
        amygdala = AmygdalaSalience()
        result = amygdala.detect_threat("danger! run!")
        print(result)  # ThreatSignal with all components
    """
    
    def __init__(self,
                 fast_weight: float = 0.45,
                 slow_weight: float = 0.55,
                 threat_threshold: float = 0.4):
        # Two pathways
        self.fast_pathway = FastSubcorticalPathway()
        self.slow_pathway = SlowCorticalPathway()
        
        # Integration
        self.la_integrator = LateralAmygdalaIntegrator(fast_weight, slow_weight)
        self.cea_response = CentralAmygdalaResponse(threat_threshold)
        
        # Memory modulation
        self.bla_modulator = BLAMemoryModulator()
        
        # Novelty & habituation
        self.novelty_system = NoveltyHabituationSystem()
        
        # History
        self.detection_history: deque = deque(maxlen=100)
        
        # Threat threshold
        self.threat_threshold = threat_threshold
    
    def detect_threat(self, text: str) -> ThreatSignal:
        """
        Full threat detection pipeline.
        
        Pipeline:
        1. Fast subcortical pathway (thalamus→LA, ~12ms)
        2. Slow cortical pathway (thalamus→cortex→LA, ~30-40ms)
        3. LA integration (convergence + coincidence detection)
        4. CeA fear response generation
        5. Novelty/habituation assessment
        6. BLA modulation of memory consolidation
        
        Args:
            text: Input text to assess for threat
            
        Returns:
            ThreatSignal with all components
        """
        # Decay neuromodulators
        self.bla_modulator.decay()
        
        # Step 1: Fast subcortical pathway
        fast_score, fast_valence, fast_arousal = self.fast_pathway.detect(text)
        
        # Step 2: Slow cortical pathway
        slow_score, slow_valence, slow_arousal = self.slow_pathway.detect(text)
        
        # Step 3: LA Integration
        integrated_score, integrated_valence, integrated_arousal = self.la_integrator.integrate(
            fast_score, fast_valence, fast_arousal,
            slow_score, slow_valence, slow_arousal
        )
        
        # Step 4: CeA Fear Response
        fear_response = self.cea_response.generate_response(integrated_score, integrated_arousal)
        
        # Step 5: Novelty & Habituation
        novelty, habituation = self.novelty_system.assess(text, integrated_arousal)
        
        # Step 6: BLA Modulation (update + compute)
        self.bla_modulator.update(integrated_score, integrated_arousal, 
                                   integrated_valence, fear_response)
        modulation_signal = self.bla_modulator.compute_modulation_signal()
        
        # Binary threat classification (with hysteresis for stability)
        # Use a lower off-threshold to prevent flickering
        if self.detection_history:
            prev_threat = self.detection_history[-1].is_threat
            if prev_threat:
                off_threshold = self.threat_threshold * 0.6
            else:
                off_threshold = self.threat_threshold
        else:
            off_threshold = self.threat_threshold
        
        is_threat = integrated_score >= off_threshold
        
        # Build result
        signal = ThreatSignal(
            fast_score=round(fast_score, 4),
            slow_score=round(slow_score, 4),
            integrated_score=round(integrated_score, 4),
            fear_response=round(fear_response, 4),
            valence=round(integrated_valence, 4),
            arousal=round(integrated_arousal, 4),
            novelty=round(novelty, 4),
            habituation_level=round(habituation, 4),
            is_threat=is_threat,
            modulation_signal=round(modulation_signal, 4),
        )
        
        self.detection_history.append(signal)
        return signal
    
    def condition_fear(self, stimulus: str, threat_level: float = 0.8):
        """
        Condition a neutral stimulus to become a threat predictor.
        Implements classical fear conditioning (LeDoux).
        """
        self.fast_pathway.condition(stimulus, threat_level)
    
    def extinguish_fear(self, stimulus: str, trials: int = 5):
        """
        Extinguish a conditioned fear response.
        Repeated presentation without threat consequence → extinction learning.
        """
        for _ in range(trials):
            self.fast_pathway.condition(stimulus, 0.05)
    
    def get_state(self) -> Dict:
        """Comprehensive state report for metacognition."""
        neuromod = self.bla_modulator.get_state()
        hab_summary = self.novelty_system.get_habituation_summary()
        
        recent = list(self.detection_history)[-5:] if self.detection_history else []
        
        return {
            "neuromodulators": neuromod,
            "habituation": hab_summary,
            "pathway_weights": {
                "fast": round(self.la_integrator.fast_weight, 3),
                "slow": round(self.la_integrator.slow_weight, 3),
            },
            "recent_threats": [
                {
                    "score": s.integrated_score,
                    "is_threat": s.is_threat,
                    "fear_response": s.fear_response,
                    "novelty": s.novelty,
                }
                for s in recent
            ],
            "conditioned_fears": len(self.fast_pathway.conditioned_threats),
        }
    
    def reset(self):
        """Reset all internal state."""
        self.fast_pathway = FastSubcorticalPathway()
        self.slow_pathway = SlowCorticalPathway()
        self.la_integrator = LateralAmygdalaIntegrator()
        self.cea_response = CentralAmygdalaResponse(self.threat_threshold)
        self.bla_modulator = BLAMemoryModulator()
        self.novelty_system = NoveltyHabituationSystem()
        self.detection_history.clear()


# ─── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    amygdala = AmygdalaSalience()
    
    print("=" * 70)
    print("AMYGDALA SALIENCE TAGGER — Self-Test")
    print("=" * 70)
    
    tests = [
        "danger! run!",
        "I love this peaceful garden",
        "The bomb will explode in 5 minutes",
        "hello world, nice weather today",
        "help! someone is attacking me with a knife!",
        "Let's have a calm cup of tea",
        "danger!",
        "danger!",
        "danger!",
        "WARNING: critical system failure detected",
        "I am happy and safe at home",
    ]
    
    for text in tests:
        result = amygdala.detect_threat(text)
        flag = "⚠️  THREAT" if result.is_threat else "✅ SAFE"
        print(f"\nInput: {text!r}")
        print(f"  {flag}")
        print(f"  FastSub: {result.fast_score:.3f} | SlowCor: {result.slow_score:.3f} | Integ: {result.integrated_score:.3f}")
        print(f"  FearResp: {result.fear_response:.3f} | Valence: {result.valence:+.3f} | Arousal: {result.arousal:.3f}")
        print(f"  Novelty: {result.novelty:.3f} | Habituation: {result.habituation_level:.3f} | Modulation: {result.modulation_signal:.3f}")
    
    print("\n" + "=" * 70)
    print("STATE SUMMARY")
    print("=" * 70)
    state = amygdala.get_state()
    for k, v in state.items():
        print(f"  {k}: {v}")
    
    print("\n" + "=" * 70)
    print("FEAR CONDITIONING TEST")
    print("=" * 70)
    amygdala2 = AmygdalaSalience()
    print("\nBefore conditioning:")
    r = amygdala2.detect_threat("the blue circle")
    print(f"  'the blue circle' → threat={r.is_threat}, score={r.integrated_score:.3f}")
    
    amygdala2.condition_fear("blue circle", threat_level=0.85)
    print("\nAfter conditioning 'blue circle' as threat:")
    r = amygdala2.detect_threat("the blue circle")
    print(f"  'the blue circle' → threat={r.is_threat}, score={r.integrated_score:.3f}")
    
    print("\nExtinguishing...")
    amygdala2.extinguish_fear("blue circle", trials=8)
    r = amygdala2.detect_threat("the blue circle")
    print(f"  'the blue circle' → threat={r.is_threat}, score={r.integrated_score:.3f}")
    
    print("\n✅ All tests complete.")
