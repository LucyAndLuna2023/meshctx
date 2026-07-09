"""
Mirror Neurons — Intention Inference & Empathy Engine (v3.115.16)
基于 Rizzolatti(1996) 镜像神经元发现 + Gallese(2004) 具身模拟 + Iacoboni(2005) 意图理解

核心机制:
1. 镜像神经元系统 (Rizzolatti et al., 1996; Gallese et al., 1996):
   - F5区(腹侧前运动皮层): 动作执行+观察时均激活
   - 顶下小叶(PF/PFG): 体感-运动整合, 动作理解
   - 严格一致(Strictly Congruent): 完全相同动作才激活 (~30%)
   - 广义一致(Broadly Congruent): 相似目标动作激活 (~60%)

2. 意图推断 (Iacoboni et al., 2005; Fogassi et al., 2005):
   - 动作链编码: 镜像神经元编码动作序列, 非独立动作
   - 上下文调制: 相同抓握动作, 不同上下文→不同意图解读
   - 前-后时间编码: 动作准备阶段已有镜像激活

3. 具身模拟理论 (Gallese & Goldman, 1998; Gallese, 2005):
   - 理解他人=内在地模拟他人动作/情感
   - "如你是我"(as if you were me) 机制
   - 前运动→顶叶→STS→边缘系统(脑岛/杏仁核) 全通路

4. 共情建模 (Singer et al., 2004; Carr et al., 2003):
   - 前岛叶(AIC) + 前扣带回(ACC): 疼痛共情
   - 动作镜像→情感镜像: 渐进的层次处理
   - 自我/他人区分: 防止过度共情

参考文献:
- Rizzolatti G et al. (1996) Premotor cortex and the recognition of motor actions
- Gallese V, Goldman A (1998) Mirror neurons and the simulation theory of mind-reading
- Iacoboni M et al. (2005) Grasping the intentions of others
- Fogassi L et al. (2005) Parietal lobe: from action organization to intention understanding
- Singer T et al. (2004) Empathy for pain involves the affective but not sensory components
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set
import time
import math
import hashlib


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ActionObservation:
    """An observed action from another agent."""
    action_type: str              # "grasp", "reach", "push", "communicate", etc.
    target_object: str = ""
    kinematics: np.ndarray = field(default_factory=lambda: np.zeros(8))
    context: str = ""
    agent_id: str = "unknown"
    timestamp: float = field(default_factory=time.time)


@dataclass
class MirrorResponse:
    """Output of mirror neuron processing."""
    observed_action: str
    inferred_intention: str
    intention_confidence: float
    motor_simulation: np.ndarray      # simulated motor plan
    empathy_response: float           # 0-1
    emotional_resonance: float        # -1 to +1
    self_other_distinction: float     # 0=merged, 1=clearly distinct
    prediction_next_action: str
    action_understanding_confidence: float


@dataclass
class MirrorNeuron:
    """A single mirror neuron in F5 or PF."""
    preferred_action: str
    preferred_target: str = ""
    is_strictly_congruent: bool = False
    activation_threshold: float = 0.3
    baseline_rate: float = 0.1
    context_sensitivity: float = 0.5
    chain_position: int = 0       # position in action chain (0=first)


# ─── Action Encoding ─────────────────────────────────────────────────────────
# Kinematic features → distributed mirror neuron representation.

class ActionEncoder:
    """
    Encode observed actions into feature vectors for mirror neuron processing.

    Features encoded:
    - Kinematic: velocity profile, acceleration, jerk, trajectory
    - Effector: hand, mouth, foot
    - Object interaction: presence/absence of target, grip type
    - Temporal: duration, rhythm, phase
    """

    # Action taxonomy based on Rizzolatti's F5 classification
    ACTION_TYPES = [
        "grasp", "hold", "tear", "reach", "push", "pull",
        "manipulate", "release", "bring_to_mouth", "communicate",
        "observe", "approach", "avoid", "attack", "defend",
        "give", "take", "point", "gesture", "express",
    ]

    # Kinematic feature dimensions
    KINEMATIC_DIM = 16

    def __init__(self, feature_dim: int = 64):
        self.feature_dim = feature_dim
        # Action semantic embeddings (fixed random projections for stability)
        rng = np.random.RandomState(42)
        self.action_embeddings: Dict[str, np.ndarray] = {}
        for action in self.ACTION_TYPES:
            vec = rng.randn(feature_dim // 4) * 0.1
            self.action_embeddings[action] = vec / (np.linalg.norm(vec) + 1e-8)

        # Object embeddings
        self.object_embeddings: Dict[str, np.ndarray] = {}

    def _get_object_embedding(self, obj_name: str) -> np.ndarray:
        """Get or create an embedding for an object."""
        if obj_name not in self.object_embeddings:
            h = int(hashlib.sha256(obj_name.encode()).hexdigest(), 16)
            rng = np.random.RandomState(h % (2**31))
            vec = rng.randn(self.feature_dim // 8) * 0.1
            self.object_embeddings[obj_name] = vec / (np.linalg.norm(vec) + 1e-8)
        return self.object_embeddings[obj_name]

    def encode(self, observation: ActionObservation) -> np.ndarray:
        """
        Encode an action observation into a distributed feature vector.
        """
        features = np.zeros(self.feature_dim)

        # 1. Action type embedding (first quarter)
        offset = 0
        size = self.feature_dim // 4
        if observation.action_type in self.action_embeddings:
            features[offset:offset + size] = self.action_embeddings[observation.action_type]

        # 2. Target object embedding (second quarter)
        offset = size
        if observation.target_object:
            obj_emb = self._get_object_embedding(observation.target_object)
            actual = min(size, len(obj_emb))
            features[offset:offset + actual] = obj_emb[:actual]

        # 3. Kinematic features (third quarter)
        offset = 2 * size
        kin = observation.kinematics
        if len(kin) > 0:
            actual = min(size, len(kin))
            features[offset:offset + actual] = np.tanh(kin[:actual])

        # 4. Context encoding (fourth quarter)
        offset = 3 * size
        if observation.context:
            # Hash context to features
            h = int(hashlib.sha256(observation.context.encode()).hexdigest(), 16)
            rng = np.random.RandomState(h % (2**31))
            ctx_features = rng.randn(size) * 0.1
            features[offset:offset + size] = ctx_features / (np.linalg.norm(ctx_features) + 1e-8)

        # Normalize
        norm = np.linalg.norm(features)
        if norm > 0:
            features /= norm

        return features


# ─── F5 Mirror Neuron Pool ───────────────────────────────────────────────────
# Ventral premotor cortex F5: the original mirror neuron region.

class F5MirrorPool:
    """
    F5 ventral premotor mirror neuron population.

    Rizzolatti et al. (1996): F5 neurons fire both when:
    1. Monkey executes a goal-directed action (grasping, holding, etc.)
    2. Monkey observes another performing the same action

    Two classes:
    - Strictly congruent (~30%): only fire for identical action
    - Broadly congruent (~60%): fire for actions with same goal

    Key property: F5 encodes action GOALS, not just movements.
    """

    def __init__(self, n_neurons: int = 128, action_types: Optional[List[str]] = None):
        self.n_neurons = n_neurons
        self.action_types = action_types or ActionEncoder.ACTION_TYPES

        # Create mirror neuron population
        self.neurons: List[MirrorNeuron] = []
        rng = np.random.RandomState(88)

        for i in range(n_neurons):
            action = self.action_types[i % len(self.action_types)]
            strictly = rng.random() < 0.3  # ~30% strictly congruent
            self.neurons.append(MirrorNeuron(
                preferred_action=action,
                preferred_target="" if strictly else "*",
                is_strictly_congruent=strictly,
                activation_threshold=0.2 + rng.random() * 0.3,
                baseline_rate=rng.random() * 0.15,
                context_sensitivity=rng.random() * 0.8,
                chain_position=i % 4,
            ))

        # Action chain templates: typical sequences
        self.action_chains: Dict[str, List[str]] = {
            "grasp": ["reach", "grasp", "hold", "release"],
            "eat": ["reach", "grasp", "bring_to_mouth", "release"],
            "give": ["reach", "grasp", "give", "release"],
            "attack": ["approach", "attack", "avoid"],
            "communicate": ["gesture", "point", "express"],
        }

    def activate(self, observation: ActionObservation,
                 encoded_features: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Activate F5 mirror neurons in response to observed action.

        Returns: (activation_vector, population_response)
        """
        activations = np.zeros(self.n_neurons)

        for i, neuron in enumerate(self.neurons):
            # Base activation: action type match
            action_match = 0.0
            if neuron.preferred_action == observation.action_type:
                action_match = 1.0
            elif not neuron.is_strictly_congruent:
                # Broadly congruent: partial activation for related actions
                action_match = self._action_similarity(
                    observation.action_type, neuron.preferred_action
                )

            # Target object match
            target_match = 1.0
            if neuron.preferred_target and neuron.is_strictly_congruent:
                target_match = 1.0 if neuron.preferred_target == observation.target_object else 0.2

            # Context modulation
            context_factor = 1.0
            if observation.context and neuron.context_sensitivity > 0.3:
                ctx_hash = hash(observation.context) % 1000
                context_factor = 0.7 + 0.3 * ((ctx_hash / 1000.0) * 2 - 1) * neuron.context_sensitivity

            # Kinematic similarity (correlation with encoded features)
            # Use neuron-specific random projection
            rng = np.random.RandomState(i * 7 + 13)
            neuron_projection = rng.randn(len(encoded_features))
            proj = float(np.dot(neuron_projection, encoded_features))
            kin_match = 0.5 + 0.5 * np.tanh(proj * 3.0)

            # Combined activation
            activation = (
                0.45 * action_match +
                0.20 * target_match +
                0.15 * context_factor +
                0.20 * kin_match
            )

            # Threshold
            if activation > neuron.activation_threshold:
                activations[i] = activation
            else:
                activations[i] = neuron.baseline_rate

        # Population response (mean activation above baseline)
        population_response = float(np.mean(activations > 0.3))

        return activations, population_response

    def _action_similarity(self, action1: str, action2: str) -> float:
        """Compute similarity between two action types."""
        if action1 == action2:
            return 1.0

        # Manual similarity dictionary based on action semantics
        similar_pairs = {
            ("grasp", "hold"): 0.8,
            ("grasp", "manipulate"): 0.7,
            ("reach", "grasp"): 0.6,
            ("push", "pull"): 0.5,
            ("give", "take"): 0.6,
            ("approach", "reach"): 0.5,
            ("communicate", "express"): 0.7,
            ("gesture", "point"): 0.8,
            ("attack", "defend"): 0.6,
            ("bring_to_mouth", "grasp"): 0.4,
        }
        key = (action1, action2)
        if key in similar_pairs:
            return similar_pairs[key]
        rev_key = (action2, action1)
        return similar_pairs.get(rev_key, 0.1)

    def predict_next_action(self, current_action: str,
                            context: str = "") -> Tuple[str, float]:
        """
        Predict next action in a chain based on F5 action chain encoding.

        Fogassi et al. (2005): PF/PFG mirror neurons encode action chains.
        The observation of action A primes the motor system for action B.
        """
        # Find matching chain
        best_chain = None
        for chain_name, chain_actions in self.action_chains.items():
            if current_action in chain_actions:
                idx = chain_actions.index(current_action)
                if idx + 1 < len(chain_actions):
                    best_chain = (chain_actions, idx, chain_name)
                    break

        if best_chain is None:
            # No chain found; use generic successor
            for chain_name, chain_actions in self.action_chains.items():
                if len(chain_actions) > 0 and current_action[0] == chain_actions[0][0]:
                    best_chain = (chain_actions, -1, chain_name)
                    break

        if best_chain:
            chain_actions, idx, chain_name = best_chain
            if idx >= 0 and idx + 1 < len(chain_actions):
                next_action = chain_actions[idx + 1]
                confidence = 0.85 - 0.1 * idx  # early steps more predictable
                return next_action, confidence
            elif idx < 0:
                next_action = chain_actions[0]
                return next_action, 0.3

        return "unknown", 0.1


# ─── Parietal Mirror (PF/PFG) ────────────────────────────────────────────────
# Inferior parietal lobule: somatosensory-motor integration for action understanding.

class ParietalMirror:
    """
    Inferior parietal lobule (PF/PFG) — action understanding via somatosensory-motor loop.

    Fogassi et al. (2005): PF/PFG neurons encode action chains.
    They activate differently based on the ACTION GOAL, even for identical movements.

    Example: grasping food → chain for "eating"
             grasping object → chain for "placing"
    Same grasp, different PF/PFG activation → different intention inferred.
    """

    def __init__(self, n_neurons: int = 64):
        self.n_neurons = n_neurons

        # Goal templates (action → intention)
        self.goal_templates: Dict[str, List[Tuple[str, float]]] = {
            "grasp": [("eat", 0.35), ("place", 0.30), ("give", 0.20), ("use", 0.15)],
            "reach": [("grasp", 0.40), ("touch", 0.30), ("point", 0.20), ("explore", 0.10)],
            "bring_to_mouth": [("eat", 0.70), ("drink", 0.20), ("taste", 0.10)],
            "push": [("move", 0.45), ("remove", 0.30), ("open", 0.15), ("close", 0.10)],
            "give": [("transfer", 0.50), ("share", 0.30), ("show", 0.20)],
            "attack": [("defeat", 0.40), ("intimidate", 0.35), ("defend", 0.25)],
            "express": [("communicate", 0.55), ("request", 0.25), ("emote", 0.20)],
        }

        # Context-specific intention priors
        self.context_priors: Dict[str, Dict[str, float]] = {}

    def infer_intention(self, observation: ActionObservation,
                        f5_activation: np.ndarray) -> Tuple[str, float]:
        """
        Infer intention from observed action + context.
        PF/PFG integrates F5 motor representation with contextual cues.
        """
        action = observation.action_type
        context = observation.context

        # Base intention distribution from goal templates
        intentions: Dict[str, float] = {}
        if action in self.goal_templates:
            for intention, prior in self.goal_templates[action]:
                intentions[intention] = prior

        if not intentions:
            intentions["unknown"] = 1.0

        # Context modulation
        if context:
            ctx_key = f"{context}_{action}"
            if ctx_key in self.context_priors:
                for intention, boost in self.context_priors[ctx_key].items():
                    if intention in intentions:
                        intentions[intention] *= (1.0 + boost)

        # F5 activation sharpens the posterior
        if len(f5_activation) > 0:
            # Stronger F5 activation = more confident inference
            f5_strength = float(np.mean(f5_activation[f5_activation > 0.3])) if np.any(f5_activation > 0.3) else 0.3

            # Modulate intention confidence by F5 strength
            for intention in intentions:
                intentions[intention] *= (0.5 + 0.5 * f5_strength * 2.0)

        # Normalize
        total = sum(intentions.values())
        if total > 0:
            for k in intentions:
                intentions[k] /= total

        # Return best intention
        best_intention = max(intentions, key=intentions.get)
        best_confidence = intentions[best_intention]

        return best_intention, best_confidence

    def learn_context_intention(self, context: str, action: str,
                                 intention: str, reinforcement: float = 1.0):
        """Learn context→intention associations through experience."""
        ctx_key = f"{context}_{action}"
        if ctx_key not in self.context_priors:
            self.context_priors[ctx_key] = {}
        current = self.context_priors[ctx_key].get(intention, 0.0)
        self.context_priors[ctx_key][intention] = current + 0.1 * reinforcement


# ─── Motor Simulation ────────────────────────────────────────────────────────
# Gallese & Goldman (1998): understanding = internally simulating.

class MotorSimulator:
    """
    Motor simulation engine — "as if you were doing it yourself."

    Gallese & Goldman (1998): when we observe an action, we covertly simulate
    the motor plan in our own motor system. This simulation is what gives us
    understanding of the action.

    Key: simulation must be inhibited from reaching execution (otherwise
    we'd actually perform observed actions). Subthreshold activation only.
    """

    def __init__(self, motor_dim: int = 12):
        self.motor_dim = motor_dim

        # Motor primitives
        self.motor_primitives: Dict[str, np.ndarray] = {}
        rng = np.random.RandomState(55)
        for action in ActionEncoder.ACTION_TYPES:
            self.motor_primitives[action] = rng.randn(motor_dim) * 0.5

        # Current simulation state
        self._simulated_plan: np.ndarray = np.zeros(motor_dim)
        self._simulation_strength: float = 0.0

        # Inhibition gate: prevents motor execution
        self.inhibition_gate: float = 0.8

    def simulate(self, action_type: str, intensity: float = 1.0,
                 kinematics: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Generate a simulated motor plan for the observed action.
        This is SUBSHRESHOLD — inhibited from actual execution.
        """
        base_plan = self.motor_primitives.get(
            action_type,
            np.random.RandomState(hash(action_type) % (2**31)).randn(self.motor_dim) * 0.5
        )

        # Blend with observed kinematics if available
        if kinematics is not None and len(kinematics) > 0:
            kin_padded = np.pad(kinematics[:min(len(kinematics), self.motor_dim)],
                               (0, max(0, self.motor_dim - len(kinematics))))
            # Weighted blend: more kinematics → more faithful simulation
            blend_weight = min(0.6, 0.1 + 0.3 * len(kinematics) / self.motor_dim)
            base_plan = (1.0 - blend_weight) * base_plan + blend_weight * kin_padded

        # Scale by intensity
        simulated = base_plan * intensity * (1.0 - self.inhibition_gate)

        self._simulated_plan = simulated
        self._simulation_strength = float(np.linalg.norm(simulated))

        return simulated

    def get_simulation_strength(self) -> float:
        """How strongly the motor system is simulating (0-1)."""
        return min(1.0, self._simulation_strength / 2.0)


# ─── Empathy Engine ──────────────────────────────────────────────────────────
# Singer et al. (2004): empathy for pain involves AIC + ACC.
# Carr et al. (2003): action mirroring → emotion mirroring via insula.

class EmpathyEngine:
    """
    Empathy engine — from action mirroring to emotional resonance.

    Singer et al. (2004): observing pain in others activates:
    - Anterior Insula (AIC): interoceptive resonance
    - Anterior Cingulate (ACC): affective component

    Carr et al. (2003): hierarchy of mirroring:
    Action mirroring (F5/PF) → Emotion mirroring (Insula) → Empathy (ACC/PFC)
    """

    # Emotion-action associations (from embodied cognition research)
    ACTION_EMOTION_MAP: Dict[str, Tuple[str, float]] = {
        "attack": ("anger", 0.8),
        "defend": ("fear", 0.7),
        "avoid": ("fear", 0.6),
        "approach": ("interest", 0.5),
        "give": ("warmth", 0.6),
        "take": ("desire", 0.5),
        "grasp": ("desire", 0.3),
        "express": ("various", 0.6),
        "communicate": ("various", 0.5),
        "bring_to_mouth": ("desire", 0.5),
        "hold": ("comfort", 0.4),
        "release": ("relief", 0.3),
    }

    def __init__(self):
        self.emotional_resonance: float = 0.0
        self._resonance_history: deque = deque(maxlen=50)
        self._empathy_threshold: float = 0.2

        # Self-other distinction (prevents over-empathy)
        self.self_other_boundary: float = 0.7
        self._self_state: np.ndarray = np.zeros(8)  # own emotional state

    def compute_emotional_resonance(self, action: str,
                                     motor_simulation_strength: float) -> float:
        """
        Compute emotional resonance from observed action + motor simulation.

        Carr et al. (2003): the stronger the motor simulation, the stronger
        the emotional resonance. Action representation → Insula → Emotion.
        """
        if action in self.ACTION_EMOTION_MAP:
            _, base_intensity = self.ACTION_EMOTION_MAP[action]
        else:
            base_intensity = 0.2

        # Emotional resonance = base * motor simulation strength * (1 - self/other boundary)
        resonance = base_intensity * motor_simulation_strength * (1.0 - self.self_other_boundary * 0.5)
        resonance = np.clip(resonance, 0.0, 1.0)

        self.emotional_resonance = 0.8 * self.emotional_resonance + 0.2 * resonance
        self._resonance_history.append(self.emotional_resonance)

        return self.emotional_resonance

    def compute_empathy(self, observed_emotion: str = "",
                        own_emotion: str = "",
                        motor_strength: float = 0.5) -> float:
        """
        Compute empathy score (0-1).

        Empathy = emotional resonance * self-other distinction factor.
        Healthy empathy: resonance with clear self-other boundary.
        Over-empathy (emotional contagion): resonance without boundary.
        """
        # Base from motor resonance
        base_empathy = self.emotional_resonance

        # Emotion congruence boost
        if observed_emotion and own_emotion:
            if observed_emotion == own_emotion:
                congruence = 1.0
            else:
                # Some emotions are related
                related = {
                    ("anger", "fear"): 0.4,
                    ("sadness", "fear"): 0.3,
                    ("joy", "interest"): 0.5,
                }
                congruence = related.get((observed_emotion, own_emotion),
                                         related.get((own_emotion, observed_emotion), 0.1))
            base_empathy *= (1.0 + congruence * 0.5)

        # Self-other boundary: healthy empathy preserves distinction
        empathy = base_empathy * self.self_other_boundary * motor_strength

        return float(np.clip(empathy, 0.0, 1.0))

    def adjust_self_other_boundary(self, delta: float):
        """Adjust self-other distinction boundary."""
        self.self_other_boundary = np.clip(self.self_other_boundary + delta, 0.1, 1.0)

    def get_empathy_stats(self) -> dict:
        return {
            "emotional_resonance": round(self.emotional_resonance, 3),
            "self_other_boundary": round(self.self_other_boundary, 3),
            "mean_resonance": round(float(np.mean(self._resonance_history))
                                    if self._resonance_history else 0.0, 3),
        }


# ─── Complete MirrorNeurons ──────────────────────────────────────────────────

class MirrorNeurons:
    """
    Complete mirror neuron system for intention inference + empathy.

    Pipeline:
    Action Observation → Action Encoder → F5 Mirror Pool (action recognition)
        → Parietal Mirror (intention inference + action chain)
        → Motor Simulator (covert motor simulation)
        → Empathy Engine (emotional resonance)
        → MirrorResponse

    Key features:
    - ~80-150ms mirror response latency (matches EEG mu-rhythm suppression)
    - Strictly + Broadly congruent mirror neurons
    - Action chain prediction (what happens next)
    - Motor simulation at subthreshold level
    - Emotional resonance → empathy computation
    - Self-other distinction to prevent over-empathy
    """

    def __init__(self, n_f5_neurons: int = 128, n_parietal_neurons: int = 64):
        self.encoder = ActionEncoder()
        self.f5 = F5MirrorPool(n_neurons=n_f5_neurons)
        self.parietal = ParietalMirror(n_neurons=n_parietal_neurons)
        self.simulator = MotorSimulator()
        self.empathy = EmpathyEngine()

        # State
        self.last_observation: Optional[ActionObservation] = None
        self.last_response: Optional[MirrorResponse] = None
        self.observation_count: int = 0
        self.intention_history: deque = deque(maxlen=50)

    def observe(self, action_type: str,
                target_object: str = "",
                kinematics: Optional[np.ndarray] = None,
                context: str = "",
                agent_id: str = "unknown") -> MirrorResponse:
        """
        Observe an action and generate mirror response.

        Args:
            action_type: type of action observed
            target_object: object being acted upon
            kinematics: kinematic features (velocity, trajectory, etc.)
            context: contextual information
            agent_id: identifier of the observed agent
        """
        self.observation_count += 1

        # Build observation
        obs = ActionObservation(
            action_type=action_type,
            target_object=target_object,
            kinematics=kinematics if kinematics is not None else np.zeros(8),
            context=context,
            agent_id=agent_id,
        )
        self.last_observation = obs

        # 1. Encode observation
        encoded = self.encoder.encode(obs)

        # 2. F5 mirror activation
        f5_activations, f5_population = self.f5.activate(obs, encoded)

        # 3. Parietal mirror: intention inference
        intention, intention_confidence = self.parietal.infer_intention(
            obs, f5_activations
        )
        self.intention_history.append((intention, intention_confidence))

        # 4. Action chain prediction
        next_action, next_confidence = self.f5.predict_next_action(
            action_type, context
        )

        # 5. Motor simulation
        motor_plan = self.simulator.simulate(
            action_type,
            intensity=f5_population,
            kinematics=kinematics,
        )
        sim_strength = self.simulator.get_simulation_strength()

        # 6. Emotional resonance + empathy
        emotional_resonance = self.empathy.compute_emotional_resonance(
            action_type, sim_strength
        )
        empathy_score = self.empathy.compute_empathy(
            observed_emotion=self._action_to_emotion(action_type),
            motor_strength=sim_strength,
        )

        # 7. Self-other distinction
        self_other = self.empathy.self_other_boundary

        # Action understanding confidence (based on F5 activation)
        understanding_conf = f5_population * 0.7 + intention_confidence * 0.3

        response = MirrorResponse(
            observed_action=action_type,
            inferred_intention=intention,
            intention_confidence=round(intention_confidence, 3),
            motor_simulation=motor_plan,
            empathy_response=round(empathy_score, 3),
            emotional_resonance=round(emotional_resonance, 3),
            self_other_distinction=round(self_other, 3),
            prediction_next_action=next_action,
            action_understanding_confidence=round(understanding_conf, 3),
        )

        self.last_response = response
        return response

    def _action_to_emotion(self, action: str) -> str:
        """Map action to associated emotion."""
        if action in EmpathyEngine.ACTION_EMOTION_MAP:
            return EmpathyEngine.ACTION_EMOTION_MAP[action][0]
        return "neutral"

    def learn_from_feedback(self, correct_intention: str,
                            reinforcement: float = 1.0):
        """Learn from feedback about correct intention interpretation."""
        if self.last_observation:
            self.parietal.learn_context_intention(
                self.last_observation.context,
                self.last_observation.action_type,
                correct_intention,
                reinforcement,
            )

    def set_empathy_boundary(self, boundary: float):
        """Set self-other distinction boundary (0=merged, 1=distinct)."""
        self.empathy.self_other_boundary = np.clip(boundary, 0.1, 1.0)

    def get_stats(self) -> dict:
        """Return diagnostic statistics."""
        return {
            "observation_count": self.observation_count,
            "f5_population_size": self.f5.n_neurons,
            "n_strictly_congruent": sum(
                1 for n in self.f5.neurons if n.is_strictly_congruent
            ),
            "n_broadly_congruent": sum(
                1 for n in self.f5.neurons if not n.is_strictly_congruent
            ),
            "motor_simulation_strength": round(self.simulator.get_simulation_strength(), 3),
            "inhibition_gate": round(self.simulator.inhibition_gate, 3),
            **self.empathy.get_empathy_stats(),
            "recent_intentions": list(self.intention_history)[-5:],
        }

    def reset(self):
        """Reset all state."""
        self.simulator = MotorSimulator()
        self.empathy = EmpathyEngine()
        self.last_observation = None
        self.last_response = None
        self.intention_history.clear()
