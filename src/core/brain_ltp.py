"""
LTP Enhancement — 长时程增强引擎 (v3.115.31)
基于 Bliss & Lømo(1973) 发现 + Malenka & Nicoll(1999) 分子机制

核心机制:
1. NMDA Receptor-Coincidence Detector (Nowak et al., 1984; Mayer et al., 1984):
   - 电压依赖性 Mg²⁺ 阻断
   - Ca²⁺ 通透性 — 突触后钙信号触发可塑性
   - GluN2A/GluN2B 亚基动力学差异

2. Calcium-Mediated Kinase Cascades (Malenka & Nicoll, 1999; Lisman et al., 2012):
   - CaMKII 自主磷酸化 → 持续活性 (Thr286)
   - PKA → CREB → 基因转录 → 蛋白合成
   - PKC → AMPA受体磷酸化 (Ser831)

3. AMPA Receptor Trafficking (Malinow & Malenka, 2002):
   - 早期LTP (E-LTP): AMPA受体磷酸化 + 突触外插入
   - 晚期LTP (L-LTP): 新蛋白合成 + 突触结构变化
   - 突触后致密区 (PSD) 重塑

4. Spike-Timing Dependence (Bi & Poo, 1998):
   - 与 STDP 互补: LTP处理化学信号, STDP处理时序信号
   - pre-before-post (Δt>0) → Ca²⁺ 超阈值 → LTP
   - post-before-pre (Δt<0) → Ca²⁺ 亚阈值 → LTD

参考文献:
- Bliss TVP, Lømo T (1973) Long-lasting potentiation of synaptic transmission. J Physiol
- Malenka RC, Nicoll RA (1999) Long-term potentiation — a decade of progress? Science
- Lisman J, Yasuda R, Raghavachari S (2012) Mechanisms of CaMKII action in LTP. Nat Rev Neurosci
- Malinow R, Malenka RC (2002) AMPA receptor trafficking and synaptic plasticity. Annu Rev Neurosci
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from collections import deque
import time
import math


# ─── Physical Constants ───────────────────────────────────────────────────────

@dataclass
class LTPConstants:
    """Biophysical constants for hippocampal CA1 LTP."""
    # NMDA receptor
    MG_BLOCK_V: float = -35.0       # mV — Mg²⁺ unblock threshold
    MG_BLOCK_SLOPE: float = 0.062    # mV⁻¹ — voltage sensitivity
    NMDA_TAU_RISE: float = 5.0       # ms — NMDA EPSC rise
    NMDA_TAU_DECAY: float = 50.0     # ms — NMDA EPSC decay

    # Calcium
    CA_REST: float = 50.0            # nM — resting Ca²⁺
    CA_THRESHOLD_LTP: float = 500.0  # nM — LTP induction threshold
    CA_THRESHOLD_LTD: float = 200.0  # nM — LTD induction threshold
    CA_TAU_DECAY: float = 50.0       # ms — Ca²⁺ clearance

    # CaMKII
    CAMKII_AUTOPHOS: float = 0.8     # autonomous activity fraction
    CAMKII_THR286_TAU: float = 60000 # ms — Thr286 dephosphorylation

    # AMPA trafficking
    AMPA_BASELINE: float = 1.0       # basal synaptic AMPA
    AMPA_PHOSPHO_BOOST: float = 1.5  # phosphorylation boost factor
    AMPA_INSERTION_RATE: float = 0.01 # /ms — new AMPAR insertion

    # Late LTP
    CREB_THRESHOLD: float = 0.7      # CaMKII→CREB activation threshold
    PROTEIN_SYNTHESIS_TAU: float = 1800000  # ms (30 min) — protein synthesis


# ─── Core Models ───────────────────────────────────────────────────────────────

@dataclass
class NMDARState:
    """NMDA receptor complex state."""
    voltage: float = -70.0           # postsynaptic membrane potential (mV)
    glutamate_bound: bool = False    # presynaptic glutamate release
    mg_block: float = 1.0            # 0=unblocked, 1=fully blocked
    open_prob: float = 0.0           # channel open probability
    ca_current: float = 0.0          # pA — Ca²⁺ current through NMDA


@dataclass
class SynapticState:
    """State of a single CA1 synapse undergoing LTP/LTD."""
    # AMPA receptor pool
    ampa_synaptic: float = 1.0       # AMPARs at PSD (normalized)
    ampa_phospho: float = 0.0        # phosphorylated AMPARs (Ser831)
    ampa_extrasynaptic: float = 0.0  # AMPARs in recycling pool

    # NMDA
    nmda: NMDARState = field(default_factory=NMDARState)

    # Calcium dynamics
    ca_concentration: float = 50.0    # nM — free cytosolic Ca²⁺
    ca_spike_count: int = 0          # number of suprathreshold events

    # CaMKII
    camkii_active: float = 0.0       # fraction of autonomous CaMKII
    camkii_total: float = 1.0        # total CaMKII pool

    # Plasticity state
    potentiation: float = 0.0        # LTP magnitude (normalized 0→1)
    late_phase: bool = False         # L-LTP engaged (protein synthesis)
    spine_volume: float = 1.0        # structural plasticity (normalized)

    # History
    stimulation_history: List[float] = field(default_factory=list)


class LTPEngine:
    """
    Long-Term Potentiation engine — NMDA-Ca²⁺-CaMKII-AMPA cascade.

    Usage:
        engine = LTPEngine()
        engine.stimulate(voltage=-60, frequency=100, duration=1000)  # 100Hz tetanus
        state = engine.get_synapse_state()
    """

    def __init__(self, synapse_id: str = "CA1-default"):
        self.id = synapse_id
        self.const = LTPConstants()
        self.synapse = SynapticState()
        self._time: float = 0.0
        self._last_stimulus: float = 0.0

    # ── NMDA Receptor Model ──────────────────────────────────────────────────

    def _nmda_mg_block(self, voltage: float) -> float:
        """Voltage-dependent Mg²⁺ block (Jahr & Stevens, 1990)."""
        return 1.0 / (1.0 + math.exp(-(voltage - self.const.MG_BLOCK_V) * self.const.MG_BLOCK_SLOPE))

    def _nmda_conductance(self, dt: float) -> float:
        """Dynamic NMDA conductance with rise and decay."""
        nmda = self.synapse.nmda
        if nmda.glutamate_bound:
            nmda.mg_block = self._nmda_mg_block(nmda.voltage)
            nmda.open_prob = min(1.0, nmda.open_prob + dt / self.const.NMDA_TAU_RISE)
        else:
            nmda.open_prob = max(0.0, nmda.open_prob - dt / self.const.NMDA_TAU_DECAY)

        return nmda.open_prob * (1.0 - nmda.mg_block)

    # ── Calcium Dynamics ──────────────────────────────────────────────────────

    def _calcium_dynamics(self, nmda_conductance: float, dt: float):
        """Ca²⁺ influx through NMDA + clearance (Helmchen et al., 1996)."""
        ca = self.synapse

        # Influx proportional to NMDA open probability
        ca_influx = nmda_conductance * 200.0  # pA → nM/ms

        # Decay back to resting
        ca_decay = (ca.ca_concentration - self.const.CA_REST) / self.const.CA_TAU_DECAY

        ca.ca_concentration += (ca_influx - ca_decay) * dt
        ca.ca_concentration = max(0.0, ca.ca_concentration)

    # ── CaMKII Activation ─────────────────────────────────────────────────────

    def _camkii_kinase(self, dt: float):
        """
        CaMKII holoenzyme activation model (Lisman et al., 2012).
        Ca²⁺/CaM binding → intersubunit autophosphorylation (Thr286) →
        autonomous activity → molecular switch.
        """
        ca = self.synapse

        if ca.ca_concentration > self.const.CA_THRESHOLD_LTP:
            # Ca²⁺ above threshold → CaMKII activation
            activation_rate = (ca.ca_concentration - self.const.CA_THRESHOLD_LTP) / 1000.0
            ca.camkii_active = min(1.0, ca.camkii_active + activation_rate * dt)

            # Check for late LTP trigger
            if ca.camkii_active > self.const.CREB_THRESHOLD and not ca.late_phase:
                ca.late_phase = True
                ca.spine_volume = 1.0  # prep for growth
        else:
            # Slow dephosphorylation of Thr286
            decay = ca.camkii_active / self.const.CAMKII_THR286_TAU
            ca.camkii_active = max(0.0, ca.camkii_active - decay * dt)

    # ── AMPA Receptor Trafficking ─────────────────────────────────────────────

    def _ampa_trafficking(self, dt: float):
        """
        AMPAR exocytosis/endocytosis (Malinow & Malenka, 2002).
        E-LTP: phosphorylation increases single-channel conductance.
        L-LTP: new AMPAR insertion + PSD growth.
        """
        syn = self.synapse
        camkii = syn.camkii_active

        # Phosphorylation: CaMKII → AMPAR Ser831 (Barria et al., 1997)
        phospho_target = camkii * syn.ampa_synaptic
        syn.ampa_phospho += (phospho_target - syn.ampa_phospho) * 0.1

        # Early LTP: effective AMPA conductance
        baseline = syn.ampa_synaptic
        phospho_boost = syn.ampa_phospho * (self.const.AMPA_PHOSPHO_BOOST - 1.0)
        effective_ampa = baseline + phospho_boost

        # Late LTP: new insertion + structural growth
        if syn.late_phase:
            insertion = self.const.AMPA_INSERTION_RATE * dt * camkii
            syn.ampa_synaptic += insertion
            syn.spine_volume += 0.001 * camkii * dt  # spine enlargement

        # Calculate potentiation level
        syn.potentiation = min(1.0, (effective_ampa - self.const.AMPA_BASELINE) /
                              (self.const.AMPA_PHOSPHO_BOOST + 1.0))

    # ── Public API ────────────────────────────────────────────────────────────

    def stimulate(self, voltage: float = -65.0, frequency: float = 100.0,
                  duration: float = 1000.0, dt: float = 1.0):
        """
        Apply a tetanic stimulation protocol.

        Parameters
        ----------
        voltage : float
            Postsynaptic holding potential (mV). -60mV enhances LTP via Mg²⁺ unblock.
        frequency : float
            Stimulation frequency (Hz). 100Hz = standard LTP tetanus.
        duration : float
            Total stimulation duration (ms).
        dt : float
            Integration timestep (ms).
        """
        steps = int(duration / dt)
        isi = 1000.0 / frequency  # inter-stimulus interval (ms)

        for step in range(steps):
            t = step * dt
            self._time += dt

            # Determine if stimulus occurs at this timestep
            stimulus_on = (t % isi) < dt

            # NMDA dynamics
            self.synapse.nmda.voltage = voltage
            self.synapse.nmda.glutamate_bound = stimulus_on
            g_nmda = self._nmda_conductance(dt)

            # Ca²⁺
            self._calcium_dynamics(g_nmda, dt)

            # CaMKII
            self._camkii_kinase(dt)

            # AMPA trafficking
            self._ampa_trafficking(dt)

            # Record
            if stimulus_on:
                self.synapse.stimulation_history.append(self.synapse.ca_concentration)
                if self.synapse.ca_concentration > self.const.CA_THRESHOLD_LTP:
                    self.synapse.ca_spike_count += 1
                self._last_stimulus = self._time

    def get_state(self) -> Dict:
        """Return current LTP state as a dict."""
        syn = self.synapse
        return {
            "synapse_id": self.id,
            "time_ms": self._time,
            "potentiation": round(syn.potentiation, 4),
            "late_phase": syn.late_phase,
            "ca_concentration_nM": round(syn.ca_concentration, 1),
            "camkii_active": round(syn.camkii_active, 4),
            "ampa_synaptic": round(syn.ampa_synaptic, 3),
            "ampa_phosphorylated": round(syn.ampa_phospho, 3),
            "spine_volume": round(syn.spine_volume, 3),
            "ca_spike_count": syn.ca_spike_count,
        }

    def is_potentiated(self) -> bool:
        """Has LTP been successfully induced?"""
        return self.synapse.potentiation > 0.3

    def reset(self):
        """Reset synapse to naive state."""
        self.synapse = SynapticState()
        self._time = 0.0


# ─── Multi-Synapse Ensemble ────────────────────────────────────────────────────

class LTPEnsemble:
    """
    Multi-synapse LTP simulation — models a population of CA1 synapses
    undergoing simultaneous potentiation (e.g., during learning).
    """

    def __init__(self, n_synapses: int = 100):
        self.synapses = [LTPEngine(f"CA1-{i:03d}") for i in range(n_synapses)]
        self.n_synapses = n_synapses

    def tetanize(self, voltage: float = -60.0, frequency: float = 100.0,
                 duration: float = 1000.0, p_stimulate: float = 0.5):
        """Tetanize a random subset of synapses (simulating sparse coding)."""
        for syn in self.synapses:
            if np.random.random() < p_stimulate:
                syn.stimulate(voltage=voltage, frequency=frequency, duration=duration)

    def get_ensemble_state(self) -> Dict:
        """Aggregate state across all synapses."""
        potentiated = sum(1 for s in self.synapses if s.is_potentiated())
        late_phase = sum(1 for s in self.synapses if s.synapse.late_phase)
        avg_pot = np.mean([s.synapse.potentiation for s in self.synapses])
        return {
            "total_synapses": self.n_synapses,
            "potentiated": potentiated,
            "late_phase_engaged": late_phase,
            "mean_potentiation": round(float(avg_pot), 4),
            "memory_strength": round(float(potentiated / self.n_synapses), 4),
        }

    def consolidate(self, cycles: int = 5):
        """Simulate memory consolidation via repeated reactivation."""
        for _ in range(cycles):
            for syn in self.synapses:
                if syn.is_potentiated():
                    # Reactivate potentiated synapses at lower frequency
                    syn.stimulate(voltage=-65, frequency=10, duration=500)
