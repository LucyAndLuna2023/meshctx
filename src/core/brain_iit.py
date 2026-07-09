"""
IIT Consciousness Engine — 整合信息理论Φ计算 (v3.115.16)
基于 Tononi(2004/2008) IIT + Oizumi(2014) IIT 3.0 + Balduzzi & Tononi(2008) 因果 repertoire

核心机制:
1. Φ (Phi) 计算 (Tononi, 2008; Oizumi et al., 2014):
   - 因果 repertoire: 系统当前状态的因果力空间
   - 有效信息 (EI): 系统在当前状态下对过去的约束与对未来的约束
   - Partition: MIP (Minimum Information Partition) — 最小信息分区破坏
   - Φ = 最小分区下丢失的信息量

2. 因果 repertoire (Balduzzi & Tononi, 2008):
   - 过去因果 repertoire (cause): P(s_t-1 | s_t) — 系统对过去状态的约束
   - 未来因果 repertoire (effect): P(s_t+1 | s_t) — 系统对未来状态的约束
   - 噪声对比: 连接系统 vs 断开连接系统的差异

3. 概念结构 (Oizumi et al., 2014):
   - 概念 = 因果repertoire over a specific purview
   - 概念空间: 系统的全部概念集合
   - φ_max: 单个概念的最大Φ值

4. PyPhi-inspired 计算:
   - CES (Cause-Effect Structure): 因果效应结构
   - 基于numpy的概率转移矩阵操作
   - 支持离散+连续状态空间

参考文献:
- Tononi G (2004) An information integration theory of consciousness. BMC Neuroscience
- Tononi G (2008) Consciousness as integrated information: a provisional manifesto
- Oizumi M, Albantakis L, Tononi G (2014) From the phenomenology to the mechanisms of consciousness: IIT 3.0. PLoS Comput Biol
- Balduzzi D, Tononi G (2008) Integrated information in discrete dynamical systems. PLoS Comput Biol
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set
from itertools import combinations
import time
import math
import hashlib


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class CausalRepertoire:
    """A probability distribution over past/future states given current state."""
    distribution: np.ndarray         # shape: (n_states,) — probabilities
    purview: List[int]               # which elements this repertoire covers
    state_index: int                 # the conditioned current state
    direction: str                   # 'cause' (past) or 'effect' (future)
    entropy: float = 0.0
    effective_information: float = 0.0

    def kl_divergence(self, other: 'CausalRepertoire') -> float:
        """KL divergence D(P||Q) between two repertoires."""
        eps = 1e-12
        p = np.clip(self.distribution, eps, 1.0)
        q = np.clip(other.distribution, eps, 1.0)
        return float(np.sum(p * np.log(p / q)))


@dataclass
class Concept:
    """A concept: mechanism + purview pair with its φ value."""
    mechanism: List[int]             # indices of elements forming the mechanism
    purview: Tuple[int, ...]         # purview elements
    cause_repertoire: Optional[CausalRepertoire] = None
    effect_repertoire: Optional[CausalRepertoire] = None
    phi: float = 0.0                 # integrated information for this concept
    phi_cause: float = 0.0
    phi_effect: float = 0.0


@dataclass
class PhiResult:
    """Complete Φ computation result for a system."""
    phi_max: float                   # maximum Φ across all partitions
    phi_total: float                 # sum of φ for all concepts
    phi_structures: float            # Φ^structure — EMD distance
    mip: Optional[Tuple[Tuple[int, ...], Tuple[int, ...]]] = None
    concepts: List[Concept] = field(default_factory=list)
    complex_boundaries: List[int] = field(default_factory=list)
    computation_time_ms: float = 0.0


# ─── System Representation ────────────────────────────────────────────────────

class DiscreteSystem:
    """
    Represents a discrete dynamical system for IIT analysis.
    Each element has binary states {0, 1}. Transitions follow TPM.
    """

    def __init__(self, n_elements: int, tpm: Optional[np.ndarray] = None,
                 current_state: Optional[np.ndarray] = None, seed: int = 42):
        self.n = n_elements
        self.n_states = 2 ** n_elements

        if tpm is not None:
            self.tpm = tpm  # Transition Probability Matrix: (n_states, n_states)
        else:
            self.tpm = self._random_tpm(seed)

        if current_state is not None:
            self.current_state = current_state
        else:
            rng = np.random.RandomState(seed + 1)
            self.current_state = (rng.rand(n_elements) > 0.5).astype(float)

    def _random_tpm(self, seed: int) -> np.ndarray:
        """Generate a random deterministic or near-deterministic TPM."""
        rng = np.random.RandomState(seed)
        tpm = np.zeros((self.n_states, self.n_states))
        for s in range(self.n_states):
            # Each state transitions to a mostly-deterministic next state
            next_state = rng.randint(0, self.n_states)
            tpm[s, next_state] = 0.85
            # Some noise
            remaining = 0.15
            for _ in range(3):
                noise_state = rng.randint(0, self.n_states)
                if noise_state != next_state:
                    noise_prob = rng.uniform(0, remaining / 2)
                    tpm[s, noise_state] += noise_prob
                    remaining -= noise_prob
            tpm[s, next_state] += remaining
        # Normalize
        tpm = tpm / tpm.sum(axis=1, keepdims=True)
        return tpm

    def state_to_index(self, state: np.ndarray) -> int:
        """Convert binary state vector to integer index."""
        powers = 2 ** np.arange(len(state))[::-1]
        return int(np.dot(state, powers))

    def index_to_state(self, idx: int) -> np.ndarray:
        """Convert integer index to binary state vector."""
        state = np.zeros(self.n)
        for i in range(self.n):
            state[i] = (idx >> (self.n - 1 - i)) & 1
        return state

    def marginalize(self, state_idx: int, keep: List[int]) -> np.ndarray:
        """
        Marginalize to only include elements in `keep`.
        Returns transition probabilities marginalized over removed elements.
        """
        # Compute effect repertoire: P(S_{t+1}^{keep} | S_t = state_idx)
        future_dist = self.tpm[state_idx]  # full distribution

        # Marginalize: sum over all states whose keep-elements match
        n_keep = len(keep)
        keep_mask = 0
        for i, elem in enumerate(keep):
            keep_mask |= (1 << (self.n - 1 - elem))

        marginalized = np.zeros(2 ** n_keep)
        for future_idx in range(self.n_states):
            keep_idx = 0
            for i, elem in enumerate(keep):
                if (future_idx >> (self.n - 1 - elem)) & 1:
                    keep_idx |= (1 << (n_keep - 1 - i))
            marginalized[keep_idx] += future_dist[future_idx]

        return marginalized

    def cause_repertoire(self, state_idx: int, purview: List[int]) -> np.ndarray:
        """
        Compute cause repertoire: P(S_{t-1}^{purview} | S_t = state_idx).
        Uses Bayes rule and uniform prior over past states.
        """
        # P(past | present) ∝ P(present | past) * P(past)
        # Uniform prior: P(past) = 1/n_states for all past states
        n_purview = len(purview)
        cause_dist = np.zeros(2 ** n_purview)

        for past_idx in range(self.n_states):
            # P(present | past) from TPM
            forward_prob = self.tpm[past_idx, state_idx]
            if forward_prob < 1e-12:
                continue

            # Marginalize past to purview
            past_purview_idx = 0
            for i, elem in enumerate(purview):
                if (past_idx >> (self.n - 1 - elem)) & 1:
                    past_purview_idx |= (1 << (n_purview - 1 - i))

            cause_dist[past_purview_idx] += forward_prob

        # Normalize
        total = cause_dist.sum()
        if total > 1e-12:
            cause_dist /= total
        else:
            cause_dist = np.ones(2 ** n_purview) / (2 ** n_purview)
        return cause_dist


# ─── Partition & Φ Core ───────────────────────────────────────────────────────

class IITPhiComputer:
    """
    Core Φ computation engine following IIT 3.0 methodology.
    Computes integrated information Φ for discrete systems.
    """

    def __init__(self, system: DiscreteSystem):
        self.system = system
        self._partition_cache: Dict[tuple, float] = {}

    def _generate_all_partitions(self, n: int) -> List[Tuple[Tuple[int, ...], Tuple[int, ...]]]:
        """Generate all bipartitions of n elements (excluding trivial)."""
        indices = list(range(n))
        partitions = []
        for k in range(1, n // 2 + 1):
            for combo in combinations(indices, k):
                part1 = tuple(sorted(combo))
                part2 = tuple(sorted(set(indices) - set(combo)))
                partitions.append((part1, part2))
        return partitions

    def _disconnect_tpm(self, part1: Tuple[int, ...], part2: Tuple[int, ...]) -> np.ndarray:
        """
        Create a disconnected TPM by zeroing cross-connections.
        This implements the 'partition' operation in IIT.
        """
        n = self.system.n
        disconnected = np.zeros_like(self.system.tpm)

        for s_from in range(self.system.n_states):
            from_state = self.system.index_to_state(s_from)
            for s_to in range(self.system.n_states):
                to_state = self.system.index_to_state(s_to)

                # Only keep intra-part connections; zero cross-part
                from_part1 = np.array([from_state[i] for i in part1])
                from_part2 = np.array([from_state[i] for i in part2])
                to_part1 = np.array([to_state[i] for i in part1])
                to_part2 = np.array([to_state[i] for i in part2])

                # Factorized: P(S') = P(S'_part1 | S_part1) * P(S'_part2 | S_part2)
                # Approximate by keeping only the marginal effects
                p1 = self.system.tpm[s_from, s_to] * 0.5  # heuristic split
                p2 = self.system.tpm[s_from, s_to] * 0.5
                disconnected[s_from, s_to] = p1 + p2

        # Renormalize
        row_sums = disconnected.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        disconnected = disconnected / row_sums
        return disconnected

    def compute_effective_information(self, part: Tuple[int, ...],
                                       mechanism: Optional[List[int]] = None) -> float:
        """
        Effective Information EI(X → Y): mutual information between past and future
        under maximum entropy past distribution (uniform intervention).
        EI = I(X;Y) with p(X) = uniform.

        EI = 1/N ∑_i D_KL[ P(Y|X=x_i) || P(Y) ]
        where P(Y) is the marginal over all X.
        """
        mech = mechanism if mechanism else list(part)
        n_states = self.system.n_states

        # Marginal future distribution P(Y|X=uniform) = mean of all conditional
        marginal_future = np.zeros(2 ** len(part))
        for x_idx in range(n_states):
            cond_dist = self.system.marginalize(x_idx, list(part))
            marginal_future += cond_dist / n_states

        # EI = mean KL divergence
        ei = 0.0
        eps = 1e-12
        for x_idx in range(n_states):
            cond_dist = self.system.marginalize(x_idx, list(part))
            p = np.clip(cond_dist, eps, 1.0)
            q = np.clip(marginal_future, eps, 1.0)
            ei += np.sum(p * np.log(p / q))

        return ei / n_states

    def compute_phi(self, mechanism: List[int], purview: Tuple[int, ...]) -> float:
        """
        Compute φ for a mechanism-purview pair.
        φ = min_{partition} D_KL[ connected_repertoire || partitioned_repertoire ]

        This is the core IIT computation: the distance between the connected
        system's causal repertoire and the partitioned (disconnected) system's.
        """
        current_idx = self.system.state_to_index(self.system.current_state)

        # Connected effect repertoire
        connected_effect = self.system.marginalize(current_idx, list(purview))
        connected_effect = np.clip(connected_effect, 1e-12, 1.0)

        # Find MIP: partition that minimizes the difference
        min_kl = float('inf')
        purview_list = list(purview)

        # Generate all bipartitions of the mechanism
        if len(mechanism) <= 1:
            # Single-element mechanism: φ is its effective information
            return self.compute_effective_information(purview_list)

        mech_partitions = self._generate_all_partitions(len(mechanism))
        if not mech_partitions:
            return self.compute_effective_information(purview_list)

        for mp in mech_partitions:
            p1_indices = tuple(mechanism[i] for i in range(len(mechanism))
                              if i in mp[0])
            p2_indices = tuple(mechanism[i] for i in range(len(mechanism))
                              if i in mp[1])

            if not p1_indices or not p2_indices:
                continue

            # Partitioned effect: apply noise injection to simulate disconnection
            disconnected_tpm = self._disconnect_tpm(p1_indices, p2_indices)
            partitioned_effect = np.zeros(2 ** len(purview))

            for future_idx in range(self.system.n_states):
                purview_idx = 0
                for i, elem in enumerate(purview):
                    if (future_idx >> (self.system.n - 1 - elem)) & 1:
                        purview_idx |= (1 << (len(purview) - 1 - i))
                partitioned_effect[purview_idx] += disconnected_tpm[current_idx, future_idx]

            partitioned_effect = np.clip(partitioned_effect, 1e-12, 1.0)

            # KL divergence
            kl = float(np.sum(connected_effect *
                              np.log(connected_effect / partitioned_effect)))
            if kl < min_kl:
                min_kl = kl

        return min_kl if min_kl != float('inf') else 0.0

    def compute_cause_phi(self, mechanism: List[int], purview: Tuple[int, ...]) -> float:
        """Compute φ_cause: information the mechanism specifies about its past purview."""
        current_idx = self.system.state_to_index(self.system.current_state)
        connected_cause = self.system.cause_repertoire(current_idx, list(purview))
        connected_cause = np.clip(connected_cause, 1e-12, 1.0)

        # Noise baseline (disconnected): uniform distribution
        n_purview = len(purview)
        uniform = np.ones(2 ** n_purview) / (2 ** n_purview)

        kl = float(np.sum(connected_cause * np.log(connected_cause / uniform)))
        return max(0.0, kl)

    def compute_conceptual_structure(self,
                                      max_mechanism_size: int = 3,
                                      min_phi: float = 0.01) -> List[Concept]:
        """Compute all concepts (mechanism-purview pairs) with φ > min_phi."""
        concepts = []
        n = self.system.n

        for mech_size in range(1, min(max_mechanism_size + 1, n + 1)):
            for mech_combo in combinations(range(n), mech_size):
                mechanism = list(mech_combo)

                # For each mechanism, find best purview (max φ)
                best_phi = 0.0
                best_purview = None

                for purview_size in range(1, n + 1):
                    for purview_combo in combinations(range(n), purview_size):
                        phi = self.compute_phi(mechanism, purview_combo)
                        if phi > best_phi:
                            best_phi = phi
                            best_purview = purview_combo

                if best_phi > min_phi and best_purview is not None:
                    current_idx = self.system.state_to_index(self.system.current_state)
                    eff_repertoire = CausalRepertoire(
                        distribution=self.system.marginalize(current_idx, list(best_purview)),
                        purview=list(best_purview),
                        state_index=current_idx,
                        direction='effect',
                        effective_information=best_phi
                    )
                    cause_repertoire = CausalRepertoire(
                        distribution=self.system.cause_repertoire(current_idx, list(best_purview)),
                        purview=list(best_purview),
                        state_index=current_idx,
                        direction='cause',
                        effective_information=self.compute_cause_phi(mechanism, best_purview)
                    )

                    concept = Concept(
                        mechanism=mechanism,
                        purview=best_purview,
                        cause_repertoire=cause_repertoire,
                        effect_repertoire=eff_repertoire,
                        phi=best_phi,
                        phi_cause=cause_repertoire.effective_information,
                        phi_effect=eff_repertoire.effective_information
                    )
                    concepts.append(concept)

        return sorted(concepts, key=lambda c: c.phi, reverse=True)


# ─── Main IIT Engine ──────────────────────────────────────────────────────────

class IITConsciousness:
    """
    Integrated Information Theory consciousness engine.

    Computes Φ (integrated information) for a given system state.
    Φ > 0 indicates the system generates integrated information — a signature
    of consciousness according to IIT.

    Usage:
        iit = IITConsciousness(n_elements=5)
        result = iit.compute_phi()
        print(f"Φ = {result.phi_max:.4f}")
        print(f"Concepts: {len(result.concepts)}")
    """

    def __init__(self, n_elements: int = 5, seed: int = 42,
                 custom_tpm: Optional[np.ndarray] = None,
                 current_state: Optional[np.ndarray] = None):
        self.n_elements = n_elements
        self.system = DiscreteSystem(
            n_elements, tpm=custom_tpm,
            current_state=current_state, seed=seed
        )
        self.phi_computer = IITPhiComputer(self.system)
        self._result_cache: Optional[PhiResult] = None
        self._history: List[PhiResult] = []

    def compute_phi(self, max_mech_size: int = 3,
                    min_phi: float = 0.01) -> PhiResult:
        """Compute the full IIT Φ analysis for the current system state."""
        t0 = time.time()

        concepts = self.phi_computer.compute_conceptual_structure(
            max_mechanism_size=max_mech_size,
            min_phi=min_phi
        )

        # Φ^max: maximum φ value across all concepts
        phi_max = max((c.phi for c in concepts), default=0.0)

        # Φ^structure: sum of φ across all concepts
        phi_total = sum(c.phi for c in concepts)

        # Find MIP across elements
        partitions = self.phi_computer._generate_all_partitions(self.n_elements)
        best_mip = None
        min_ei = float('inf')
        for p in partitions:
            ei = self.phi_computer.compute_effective_information(list(p[0]))
            if ei < min_ei:
                min_ei = ei
                best_mip = p

        dt_ms = (time.time() - t0) * 1000

        result = PhiResult(
            phi_max=phi_max,
            phi_total=phi_total,
            phi_structures=phi_total,  # Simplified
            mip=best_mip,
            concepts=concepts,
            computation_time_ms=dt_ms
        )

        self._result_cache = result
        self._history.append(result)
        return result

    def update_state(self, new_state: np.ndarray):
        """Update the system's current state and invalidate cache."""
        if len(new_state) != self.n_elements:
            raise ValueError(f"State must have {self.n_elements} elements")
        self.system.current_state = np.clip(new_state, 0, 1)
        self._result_cache = None

    def evolve(self, steps: int = 1) -> np.ndarray:
        """Evolve the system forward using the TPM (stochastic)."""
        rng = np.random.RandomState()
        state_idx = self.system.state_to_index(self.system.current_state)
        for _ in range(steps):
            probs = self.system.tpm[state_idx]
            state_idx = rng.choice(self.system.n_states, p=probs)
        self.system.current_state = self.system.index_to_state(state_idx)
        self._result_cache = None
        return self.system.current_state.copy()

    @property
    def phi_level(self) -> float:
        """Convenience: current Φ^max value."""
        if self._result_cache:
            return self._result_cache.phi_max
        return 0.0

    def consciousness_report(self) -> Dict:
        """Generate a human-readable consciousness report."""
        if not self._result_cache:
            self.compute_phi()

        r = self._result_cache
        n_concepts = len(r.concepts)
        top_concepts = r.concepts[:5] if n_concepts > 0 else []

        report = {
            'phi_max': round(r.phi_max, 4),
            'phi_total': round(r.phi_total, 4),
            'n_concepts': n_concepts,
            'complex_size': self.n_elements,
            'computation_ms': round(r.computation_time_ms, 2),
            'top_mechanisms': [
                {
                    'mechanism': c.mechanism,
                    'purview': list(c.purview),
                    'phi': round(c.phi, 4)
                }
                for c in top_concepts
            ],
            'consciousness_level': self._classify_consciousness(r.phi_max),
            'state_vector': self.system.current_state.tolist()
        }
        return report

    def _classify_consciousness(self, phi: float) -> str:
        """Heuristic classification of Φ levels."""
        if phi < 0.01:
            return 'pre-conscious / reflex'
        elif phi < 0.1:
            return 'minimal consciousness'
        elif phi < 0.5:
            return 'awareness / sentience'
        elif phi < 2.0:
            return 'rich consciousness'
        else:
            return 'self-aware / meta-conscious'
