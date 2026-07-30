"""
Default Mode Network — 默认模式网络引擎 (v3.115.16)
基于 Raichle(2001) DMN + Buckner(2008) 内省/自我参照 + Schacter(2012) 情景未来思维

核心机制:
1. 默认模式网络 (Raichle et al., 2001; Buckner et al., 2008):
   - mPFC (内侧前额叶): 自我参照加工, 社会认知
   - PCC (后扣带回): 情景记忆检索, 自我相关性评估
   - Angular Gyrus (角回): 语义整合, 概念组合
   - Medial Temporal Lobe (MTL): 情景记忆
   - DMN在静息态高度激活, 任务态去激活

2. 自传体记忆与自我模型 (Conway & Pleydell-Pearce, 2000; Damasio, 2010):
   - 工作自我 (working self): 当前目标驱动的自传体记忆检索
   - 自我模型: 多层级的自我表征结构
   - 自传体知识库: 生命周期→一般事件→事件特异性知识
   - 概念性自我 (conceptual self): 特质、角色、价值观

3. 情景未来思维 (Schacter et al., 2012; Addis et al., 2007):
   - 建设性情景模拟假说: 回忆过去 + 想象未来共享核心网络
   - 情景记忆片段重组 → 新颖未来场景构建
   - 海马-前额叶耦合驱动场景构建

4. 内省与元认知 (Flavell, 1979; Fleming & Dolan, 2012):
   - 自我监测: 在线评估自身认知过程
   - 元认知信心: 对自己判断的信心评级
   - 自我反思: 对过去决策的反事实推理

参考文献:
- Raichle ME et al. (2001) A default mode of brain function. PNAS
- Buckner RL et al. (2008) The brain's default network. Ann NY Acad Sci
- Schacter DL et al. (2012) The future of memory: remembering, imagining, and the brain
- Conway MA, Pleydell-Pearce CW (2000) The construction of autobiographical memories
- Damasio A (2010) Self Comes to Mind
- Addis DR et al. (2007) Remembering the past and imagining the future. Neuropsychologia
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set, Union
import time
import math
import re
import hashlib


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class SelfModel:
    """Multi-level self-representation model (Damasio, 2010)."""
    # Proto-self: basic bodily/state awareness
    proto_self: np.ndarray           # embodied state vector (interoception, posture, etc.)

    # Core self: moment-to-moment self-awareness
    core_self: np.ndarray            # transient self-in-the-moment representation
    core_narrative: str = ""         # brief description of current self-state

    # Autobiographical self: identity across time
    traits: Dict[str, float] = field(default_factory=dict)    # Big-5-ish traits
    roles: List[str] = field(default_factory=list)            # social roles
    values: Dict[str, float] = field(default_factory=dict)    # value priorities
    goals: Dict[str, float] = field(default_factory=dict)     # current goal activations
    preferences: Dict[str, float] = field(default_factory=dict)

    # Self-coherence: how consistent the self-model is
    coherence: float = 0.5

    def update_coherence(self):
        """Measure self-model internal consistency."""
        if not self.traits or not self.values:
            self.coherence = 0.5
            return
        # Coherence = alignment of traits with values and goals
        trait_vals = np.array(list(self.traits.values()))
        value_vals = np.array(list(self.values.values()))
        # Normalized dot product as coherence metric
        if len(trait_vals) > 0 and len(value_vals) > 0:
            correlation = np.corrcoef(
                np.resize(trait_vals, min(len(trait_vals), len(value_vals))),
                np.resize(value_vals, min(len(trait_vals), len(value_vals)))
            )[0, 1]
            self.coherence = max(0.0, min(1.0, (correlation + 1.0) / 2.0))
            if np.isnan(self.coherence):
                self.coherence = 0.5


@dataclass
class AutobiographicalMemory:
    """A stored autobiographical episode."""
    id: str
    content: str
    embedding: np.ndarray
    timestamp: float
    emotional_valence: float = 0.0
    emotional_arousal: float = 0.0
    self_relevance: float = 0.5    # how central to self-identity
    vividness: float = 0.5          # detail richness
    retrieval_count: int = 0
    last_retrieved: float = 0.0
    lifetime_period: str = ""       # e.g., "childhood", "career"
    event_type: str = "general"     # specific episode, general event, lifetime period
    associated_goals: List[str] = field(default_factory=list)

    def __hash__(self):
        return hash(self.id)


@dataclass
class FutureScenario:
    """An imagined future scenario."""
    id: str
    description: str
    embedding: np.ndarray
    probability: float              # estimated likelihood
    desirability: float             # [-1, +1] how desirable
    vividness: float                # detail richness
    source_memories: List[str]      # IDs of autobiographical memories used
    expected_outcome: str
    timestamp: float = field(default_factory=time.time)
    emotional_valence: float = 0.0
    emotional_arousal: float = 0.0


@dataclass
class IntrospectionResult:
    """Result of self-reflection / introspection."""
    topic: str
    confidence: float               # [0, 1] metacognitive confidence
    uncertainty_sources: List[str]
    alternative_perspectives: List[str]
    self_relevance: float
    emotional_response: str
    insight_gained: bool
    coherence_impact: float         # how this changes self-model coherence


# ─── Self-Model Engine ────────────────────────────────────────────────────────

class SelfModelEngine:
    """
    Maintains and updates a multi-level self-model.
    Conway's working self: goals + currently active self-representations
    guide memory retrieval and future thinking.
    """

    def __init__(self, embedding_dim: int = 64):
        self.dim = embedding_dim
        self.rng = np.random.RandomState(42)
        self.model = SelfModel(
            proto_self=np.zeros(embedding_dim),
            core_self=np.zeros(embedding_dim)
        )
        self._update_history: List[Dict] = []

    def initialize_traits(self):
        """Initialize Big-5-like trait dimensions."""
        self.model.traits = {
            'openness': 0.7,
            'conscientiousness': 0.6,
            'extraversion': 0.5,
            'agreeableness': 0.6,
            'neuroticism': 0.3,
            'curiosity': 0.8,
            'creativity': 0.7,
            'analytical': 0.75,
            'empathy': 0.65,
            'resilience': 0.6
        }
        self.model.values = {
            'truth': 0.9,
            'helpfulness': 0.85,
            'autonomy': 0.7,
            'growth': 0.8,
            'connection': 0.65,
            'efficiency': 0.7,
            'creativity': 0.75,
            'safety': 0.6
        }
        self.model.roles = ['assistant', 'problem_solver', 'knowledge_synthesizer']
        self.model.goals = {
            'answer_question': 0.9,
            'learn_from_interaction': 0.7,
            'maintain_consistency': 0.8
        }
        self.model.update_coherence()

    def update_from_experience(self, experience: str,
                                embedding: Optional[np.ndarray] = None,
                                emotional_valence: float = 0.0,
                                emotional_arousal: float = 0.0):
        """Update self-model based on a new experience (self-referential processing)."""
        if embedding is None:
            h = int(hashlib.sha256(experience.encode()).hexdigest(), 16)
            embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)])

        # Update proto-self (embodied state)
        self.model.proto_self = 0.9 * self.model.proto_self + 0.1 * embedding

        # Update core self with emotional modulation
        emotional_weight = 0.1 + 0.3 * abs(emotional_valence) * emotional_arousal
        self.model.core_self = (
            (1.0 - emotional_weight) * self.model.core_self
            + emotional_weight * embedding
        )

        # Update core narrative
        self.model.core_narrative = experience[:200]

        # Adjust goals based on experience
        for goal in self.model.goals:
            # Goals related to experience get small activation boost
            if goal.replace('_', ' ') in experience.lower():
                self.model.goals[goal] = min(1.0, self.model.goals[goal] + 0.05)

        self.model.update_coherence()
        self._update_history.append({
            'experience': experience[:100],
            'coherence': self.model.coherence,
            'core_self_norm': float(np.linalg.norm(self.model.core_self))
        })

    def get_self_schema(self) -> Dict:
        """Return a structured representation of the current self-model."""
        return {
            'traits': dict(self.model.traits),
            'values': dict(self.model.values),
            'roles': list(self.model.roles),
            'goals': dict(self.model.goals),
            'coherence': round(self.model.coherence, 3),
            'core_narrative': self.model.core_narrative,
            'dominant_traits': sorted(self.model.traits.items(),
                                       key=lambda x: x[1], reverse=True)[:3],
            'dominant_goals': sorted(self.model.goals.items(),
                                      key=lambda x: x[1], reverse=True)[:3]
        }

    def self_relevance_score(self, content: str, embedding: np.ndarray) -> float:
        """Compute how self-relevant a piece of information is."""
        # Cosine similarity with core_self
        core_norm = np.linalg.norm(self.model.core_self)
        emb_norm = np.linalg.norm(embedding)
        if core_norm < 1e-10 or emb_norm < 1e-10:
            return 0.5

        cosine_sim = float(np.dot(self.model.core_self, embedding) /
                            (core_norm * emb_norm))
        relevance = (cosine_sim + 1.0) / 2.0  # map [-1,1] → [0,1]

        # Boost if content mentions traits/roles/goals
        for trait in self.model.traits:
            if trait in content.lower():
                relevance = min(1.0, relevance + 0.1)
        for role in self.model.roles:
            if role.lower() in content.lower():
                relevance = min(1.0, relevance + 0.1)

        return relevance


# ─── Autobiographical Memory Store ────────────────────────────────────────────

class AutobiographicalMemoryStore:
    """
    Hierarchical autobiographical memory store.
    Conway & Pleydell-Pearce (2000): lifetime periods → general events → event-specific.

    Retrieval guided by working self (current goals + active self-representations).
    """

    def __init__(self, max_memories: int = 500):
        self.max_memories = max_memories
        self.memories: List[AutobiographicalMemory] = []
        self._lifetime_periods: Dict[str, List[str]] = defaultdict(list)

    def store(self, memory: AutobiographicalMemory):
        """Store an autobiographical memory with hierarchical indexing."""
        self.memories.append(memory)
        if memory.lifetime_period:
            self._lifetime_periods[memory.lifetime_period].append(memory.id)

        # Prune if over capacity (keep most self-relevant + recent)
        if len(self.memories) > self.max_memories:
            self.memories.sort(
                key=lambda m: m.self_relevance * 0.3 + m.vividness * 0.3
                              + (1.0 / (1.0 + time.time() - m.timestamp)) * 0.4,
                reverse=True
            )
            removed = self.memories[self.max_memories:]
            self.memories = self.memories[:self.max_memories]
            for rm in removed:
                if rm.lifetime_period and rm.id in self._lifetime_periods[rm.lifetime_period]:
                    self._lifetime_periods[rm.lifetime_period].remove(rm.id)

    def retrieve_by_cue(self, cue: str, embedding: np.ndarray,
                         top_k: int = 5) -> List[AutobiographicalMemory]:
        """
        Retrieval by working self: current goals + cue match drives retrieval.
        Conway's model: working self shapes retrieval from autobiographical knowledge base.
        """
        if not self.memories:
            return []

        scored = []
        emb_norm = np.linalg.norm(embedding)

        for mem in self.memories:
            # Cue similarity
            if emb_norm > 1e-10 and np.linalg.norm(mem.embedding) > 1e-10:
                cue_sim = float(np.dot(embedding, mem.embedding) /
                                 (emb_norm * np.linalg.norm(mem.embedding)))
                cue_sim = (cue_sim + 1.0) / 2.0
            else:
                cue_sim = 0.5

            # Recency bonus
            recency = 1.0 / (1.0 + (time.time() - mem.timestamp) / 86400.0)

            # Self-relevance
            relevance = mem.self_relevance

            # Retrieval practice effect: more retrieved → easier to retrieve
            retrieval_bonus = 1.0 - math.exp(-mem.retrieval_count / 5.0)

            score = (0.35 * cue_sim + 0.15 * recency + 0.30 * relevance
                     + 0.10 * mem.vividness + 0.10 * retrieval_bonus)

            scored.append((mem, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Update retrieval counts for retrieved memories
        for mem, _ in scored[:top_k]:
            mem.retrieval_count += 1
            mem.last_retrieved = time.time()

        return [m for m, _ in scored[:top_k]]

    def memory_consolidation(self, min_self_relevance: float = 0.3):
        """
        Simulate consolidation: less self-relevant episodic details fade,
        highly self-relevant memories become more vivid (rehearsal effect).
        """
        for mem in self.memories:
            if mem.self_relevance > min_self_relevance:
                # Rehearsal strengthens
                mem.vividness = min(1.0, mem.vividness + 0.01)
            else:
                # Fading
                mem.vividness = max(0.1, mem.vividness - 0.005)
                mem.self_relevance = max(0.05, mem.self_relevance - 0.002)


# ─── Episodic Future Thinking ─────────────────────────────────────────────────

class FutureSimulator:
    """
    Episodic future thinking engine.
    Schacter et al. (2012): constructive episodic simulation hypothesis.
    Recombines autobiographical memory fragments into novel future scenarios.

    Process:
    1. Retrieve relevant memories
    2. Extract elements (people, places, objects, actions)
    3. Recombine with novelty injection
    4. Evaluate plausibility and emotional impact
    """

    def __init__(self, memory_store: AutobiographicalMemoryStore,
                 embedding_dim: int = 64):
        self.memory_store = memory_store
        self.dim = embedding_dim
        self.rng = np.random.RandomState(43)
        self.scenarios: List[FutureScenario] = []
        self._element_cache: Dict[str, List[np.ndarray]] = {}

    def _extract_elements(self, content: str) -> List[str]:
        """Extract key elements (entities, actions) from text."""
        import re
        # Simple extraction: noun phrases and verbs
        words = re.findall(r'[a-zA-Z]{3,}', content.lower())
        # Filter interesting content words
        stopwords = {'the', 'and', 'was', 'were', 'that', 'this', 'with',
                     'for', 'from', 'have', 'has', 'not', 'are', 'but',
                     'had', 'been', 'can', 'did'}
        return [w for w in words if w not in stopwords]

    def simulate_future(self, prompt: str, embedding: np.ndarray,
                         horizon: str = 'near',
                         n_scenarios: int = 3) -> List[FutureScenario]:
        """
        Generate future scenarios based on autobiographical memory recombination.

        Horizon: 'near' (days-weeks), 'medium' (months), 'far' (years)
        """
        # Retrieve source memories relevant to the prompt
        source_memories = self.memory_store.retrieve_by_cue(prompt, embedding, top_k=10)

        if not source_memories:
            return []

        # Collect elements from source memories
        all_elements = []
        for mem in source_memories:
            elements = self._extract_elements(mem.content)
            all_elements.extend(elements)

        if not all_elements:
            all_elements = ['future', 'scenario']

        scenarios = []
        for i in range(n_scenarios):
            # Recombine elements with novelty injection
            sample_size = min(5, len(all_elements))
            selected_elements = list(self.rng.choice(
                all_elements, size=sample_size, replace=False
            ))

            # Novelty: inject random conceptual combinations
            novelty_words = ['new', 'unexpected', 'different', 'evolved',
                             'transformed', 'alternative', 'novel', 'unforeseen']
            novelty = self.rng.choice(novelty_words, size=1)[0]

            # Build scenario description
            if horizon == 'near':
                timeframe = 'in the coming days'
                prob_scale = 0.6
            elif horizon == 'far':
                timeframe = 'in the distant future'
                prob_scale = 0.2
            else:
                timeframe = 'in the months ahead'
                prob_scale = 0.4

            description = (
                f"A {novelty} scenario {timeframe} involving "
                f"{', '.join(selected_elements[:3])}"
            )

            # Vividness from source memory quality
            mean_vividness = float(np.mean([m.vividness for m in source_memories]))
            vividness = mean_vividness * 0.7 + 0.3 * self.rng.random()

            # Emotional tone from source memories
            mean_valence = float(np.mean([m.emotional_valence for m in source_memories]))
            mean_arousal = float(np.mean([m.emotional_arousal for m in source_memories]))

            scenario = FutureScenario(
                id=f"future_{time.time()}_{i}",
                description=description,
                embedding=embedding * 0.7 + self.rng.randn(self.dim) * 0.3,
                probability=prob_scale * (1.0 - 0.3 * self.rng.random()),
                desirability=mean_valence * 0.8 + self.rng.uniform(-0.2, 0.2),
                vividness=vividness,
                source_memories=[m.id for m in source_memories[:3]],
                expected_outcome=f"Outcome: {novelty} resolution of {selected_elements[0] if selected_elements else 'events'}",
                emotional_valence=mean_valence,
                emotional_arousal=mean_arousal
            )
            scenarios.append(scenario)

        self.scenarios.extend(scenarios)
        return scenarios

    def evaluate_scenario(self, scenario: FutureScenario,
                           self_goals: Dict[str, float]) -> Dict:
        """Evaluate a future scenario against current goals and self-model."""
        # Goal alignment: does this scenario advance active goals?
        goal_alignment = 0.0
        for goal, weight in self_goals.items():
            if goal.replace('_', ' ') in scenario.description.lower():
                goal_alignment += weight

        # Feasibility: vividness × probability
        feasibility = scenario.vividness * scenario.probability

        # Overall desirability
        desirability = scenario.desirability * (0.5 + 0.5 * goal_alignment)

        return {
            'goal_alignment': round(goal_alignment, 3),
            'feasibility': round(feasibility, 3),
            'desirability': round(desirability, 3),
            'emotional_valence': round(scenario.emotional_valence, 3),
            'should_pursue': desirability > 0.3 and feasibility > 0.2
        }


# ─── Main Default Mode Network ────────────────────────────────────────────────

class DefaultModeNetwork:
    """
    Complete Default Mode Network engine.

    The DMN activates during rest, self-reflection, and internally-directed cognition:
    - Self-model maintenance (mPFC)
    - Autobiographical memory retrieval (PCC + MTL)
    - Episodic future thinking (hippocampal-PFC coupling)
    - Introspection and metacognition

    Usage:
        dmn = DefaultModeNetwork()
        dmn.initialize_self()
        dmn.remember("Today I solved a difficult problem about...")
        future = dmn.imagine_future("What if I learned quantum computing?")
        report = dmn.introspect("Why did I answer that question that way?")
    """

    def __init__(self, embedding_dim: int = 64):
        self.dim = embedding_dim
        self.self_engine = SelfModelEngine(embedding_dim)
        self.memory_store = AutobiographicalMemoryStore()
        self.future_simulator = FutureSimulator(self.memory_store, embedding_dim)
        self._introspection_log: List[IntrospectionResult] = []
        self._default_mode_active: bool = False
        self._rng = np.random.RandomState(44)

    def initialize_self(self):
        """Initialize the self-model with default traits."""
        self.self_engine.initialize_traits()

    def remember(self, content: str,
                  emotional_valence: float = 0.0,
                  emotional_arousal: float = 0.0) -> str:
        """Encode an autobiographical memory and update self-model."""
        # Hash-based embedding
        h = int(hashlib.sha256(content.encode()).hexdigest(), 16)
        embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)])

        # Compute self-relevance
        relevance = self.self_engine.self_relevance_score(content, embedding)

        # Create memory
        mem = AutobiographicalMemory(
            id=f"am_{int(time.time())}_{len(self.memory_store.memories)}",
            content=content,
            embedding=embedding,
            timestamp=time.time(),
            emotional_valence=emotional_valence,
            emotional_arousal=emotional_arousal,
            self_relevance=relevance,
            vividness=0.5 + 0.3 * abs(emotional_arousal),  # emotional = vivid
            lifetime_period=self._infer_lifetime_period(content),
            event_type='specific'
        )

        self.memory_store.store(mem)
        self.self_engine.update_from_experience(
            content, embedding, emotional_valence, emotional_arousal
        )

        return mem.id

    def recall(self, cue: str, top_k: int = 5) -> List[Dict]:
        """Retrieve autobiographical memories by cue."""
        h = int(hashlib.sha256(cue.encode()).hexdigest(), 16)
        embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)])

        memories = self.memory_store.retrieve_by_cue(cue, embedding, top_k)

        return [{
            'id': m.id,
            'content': m.content[:200],
            'self_relevance': round(m.self_relevance, 3),
            'vividness': round(m.vividness, 3),
            'emotional_valence': round(m.emotional_valence, 3),
            'retrieval_count': m.retrieval_count,
            'lifetime_period': m.lifetime_period
        } for m in memories]

    def imagine_future(self, prompt: str,
                        horizon: str = 'near',
                        n_scenarios: int = 3) -> List[Dict]:
        """Generate episodic future scenarios."""
        h = int(hashlib.sha256(prompt.encode()).hexdigest(), 16)
        embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)])

        scenarios = self.future_simulator.simulate_future(
            prompt, embedding, horizon, n_scenarios
        )

        results = []
        for s in scenarios:
            evaluation = self.future_simulator.evaluate_scenario(
                s, self.self_engine.model.goals
            )
            results.append({
                'id': s.id,
                'description': s.description,
                'probability': round(s.probability, 3),
                'desirability': round(s.desirability, 3),
                'vividness': round(s.vividness, 3),
                'evaluation': evaluation,
                'emotional_valence': round(s.emotional_valence, 3)
            })

        return results

    def introspect(self, topic: str) -> IntrospectionResult:
        """
        Perform introspection on a given topic.
        Combines self-model, autobiographical memory, and metacognitive assessment.
        """
        # Self-relevance check
        h = int(hashlib.sha256(topic.encode()).hexdigest(), 16)
        embedding = np.array([((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)])
        relevance = self.self_engine.self_relevance_score(topic, embedding)

        # Retrieve related memories
        memories = self.memory_store.retrieve_by_cue(topic, embedding, top_k=3)
        memory_valences = [m.emotional_valence for m in memories] if memories else [0.0]

        # Metacognitive confidence: function of memory vividness and self-relevance
        mean_vividness = float(np.mean([m.vividness for m in memories])) if memories else 0.5
        confidence = 0.4 * relevance + 0.3 * mean_vividness + 0.3 * self.self_engine.model.coherence

        # Uncertainty sources
        uncertainty_sources = []
        if mean_vividness < 0.4:
            uncertainty_sources.append("Low memory vividness")
        if relevance < 0.3:
            uncertainty_sources.append("Low self-relevance")
        if self.self_engine.model.coherence < 0.4:
            uncertainty_sources.append("Low self-model coherence")

        # Alternative perspectives
        alternatives = []
        if memories:
            alt_perspectives = set()
            for m in memories:
                alt_perspectives.update(m.content.split()[:5])
            alternatives = list(alt_perspectives)[:3]

        # Emotional response
        mean_valence = float(np.mean(memory_valences))
        if mean_valence > 0.3:
            emotional_response = "positive"
        elif mean_valence < -0.3:
            emotional_response = "negative"
        else:
            emotional_response = "neutral"

        # Insight detection: novel connection between self and topic
        insight_gained = relevance > 0.6 and len(memories) >= 2

        result = IntrospectionResult(
            topic=topic,
            confidence=confidence,
            uncertainty_sources=uncertainty_sources,
            alternative_perspectives=alternatives,
            self_relevance=relevance,
            emotional_response=emotional_response,
            insight_gained=insight_gained,
            coherence_impact=relevance * 0.1
        )

        self._introspection_log.append(result)
        return result

    def get_dmn_state(self) -> Dict:
        """Get current DMN state for monitoring."""
        return {
            'default_mode_active': self._default_mode_active,
            'self_coherence': round(self.self_engine.model.coherence, 3),
            'n_autobiographical_memories': len(self.memory_store.memories),
            'n_future_scenarios': len(self.future_simulator.scenarios),
            'n_introspections': len(self._introspection_log),
            'core_narrative': self.self_engine.model.core_narrative[:100],
            'dominant_goals': sorted(
                self.self_engine.model.goals.items(),
                key=lambda x: x[1], reverse=True
            )[:3],
            'recent_introspection_confidence': (
                self._introspection_log[-1].confidence
                if self._introspection_log else 0.5
            )
        }

    def toggle_dmn(self, active: bool = True):
        """Activate or deactivate DMN (task-positive vs default mode)."""
        self._default_mode_active = active

    def curiosity_drive(self, topic: str = "", max_questions: int = 5) -> List[str]:
        """v3.115.44: Curiosity-driven question generation.
        
        Generates exploratory questions based on knowledge gaps and novelty seeking.
        Higher curiosity trait → more diverse questions.
        """
        curiosity = self.self_engine.model.traits.get('curiosity', 0.5)
        questions = []
        
        # Gap-based: what don't we know about this topic?
        known = [m.content for m in self.memory_store.memories 
                if topic.lower() in m.content.lower()][:3]
        if not known and topic:
            questions.append(f"What is the fundamental nature of '{topic}'?")
            questions.append(f"How does '{topic}' connect to other domains?")
        
        # Novelty-based: what haven't we explored?
        if self.self_engine.model.traits.get('creativity', 0.5) > 0.5:
            questions.append(f"What unconventional approach could transform '{topic}'?")
        
        # Depth-based: go deeper
        if curiosity > 0.6:
            questions.append(f"What are the deeper implications of '{topic}' that aren't obvious?")
            questions.append(f"If we reversed our assumptions about '{topic}', what emerges?")
        
        # Cross-domain: connect unrelated ideas
        all_topics = set()
        for m in self.memory_store.memories[-10:]:
            for w in m.content.split():
                if len(w) > 4: all_topics.add(w.lower())
        if len(all_topics) > 3:
            sample = list(all_topics)[:3]
            questions.append(f"How might '{topic}' relate to {', '.join(sample)}?")
        
        # Ensure minimum questions
        if not questions:
            questions = [
                f"What do I not yet understand about this?",
                f"What would a breakthrough look like?",
                f"What assumptions am I making?",
            ]
        
        return questions[:max_questions]

    @staticmethod
    def _infer_lifetime_period(content: str) -> str:
        """Heuristic inference of lifetime period from content context."""
        content_lower = content.lower()
        if any(w in content_lower for w in ['child', 'young', 'school', 'kid']):
            return 'childhood'
        elif any(w in content_lower for w in ['work', 'job', 'career', 'boss']):
            return 'career'
        elif any(w in content_lower for w in ['recent', 'today', 'now', 'just']):
            return 'recent'
        elif any(w in content_lower for w in ['future', 'plan', 'will', 'goal']):
            return 'future_projection'
        return 'general'
