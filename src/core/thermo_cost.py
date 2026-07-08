"""meshctx thermo_cost — Thermodynamic Cost Analysis (v2.82)

Based on Landauer's principle: minimum energy to erase one bit = kT ln(2).
Modern hardware is far from this theoretical limit — efficiency ratios > 1e10.
"""

import math
from dataclasses import dataclass, field
from typing import Any

# ── Physical constants ──────────────────────────────────────────────
k_B = 1.380649e-23          # Boltzmann constant (J/K)
T_ROOM = 300.0              # Room temperature (K)
LANDAUER_PER_BIT = k_B * T_ROOM * math.log(2)  # ≈ 2.87e-21 J/bit

# ── Hardware profiles ───────────────────────────────────────────────
# energy_per_token_j is a rough estimate for inference
HARDWARE_PROFILES: dict[str, dict[str, float]] = {
    "a100":   {"energy_per_token_j": 0.35, "tdp_w": 300},
    "h100":   {"energy_per_token_j": 0.25, "tdp_w": 350},
    "cpu":    {"energy_per_token_j": 5.0,  "tdp_w": 150},
    "tpu_v4": {"energy_per_token_j": 0.20, "tdp_w": 200},
}

# ── Power-source CO₂ intensity (g/J) ────────────────────────────────
POWER_SOURCE_CO2: dict[str, float] = {
    "renewable": 0.00001,
    "mixed":     0.00014,   # ≈ 0.5 kg/kWh
    "coal":      0.00030,
    "gas":       0.00015,
}


@dataclass
class CostResult:
    """Result of a single thermodynamic cost computation."""
    query: str
    input_tokens: int
    output_tokens: int
    tokens: int = 0
    bits_processed: int = 0
    landauer_energy_j: float = 0.0
    actual_energy_j: float = 0.0
    efficiency_ratio: float = 0.0
    co2_grams: float = 0.0
    hardware: str = ""
    power_source: str = ""


class ThermodynamicCostAnalyzer:
    """Analyze computational cost through the lens of thermodynamics.

    Parameters
    ----------
    hardware : str
        One of the keys in HARDWARE_PROFILES.
    power_source : str
        One of the keys in POWER_SOURCE_CO2.
    """

    def __init__(self, hardware: str = "a100", power_source: str = "mixed", **kw) -> None:
        if hardware not in HARDWARE_PROFILES:
            raise ValueError(f"Unknown hardware '{hardware}'. Choose from {list(HARDWARE_PROFILES)}")
        if power_source not in POWER_SOURCE_CO2:
            raise ValueError(f"Unknown power_source '{power_source}'. Choose from {list(POWER_SOURCE_CO2)}")

        self.hardware = hardware
        self.power_source = power_source
        self._profile = HARDWARE_PROFILES[hardware]
        self._co2_per_j = POWER_SOURCE_CO2[power_source]

        # Internal stats
        self._call_count: int = 0
        self._total_actual_j: float = 0.0
        self._total_landauer_j: float = 0.0

    # ── Core computation ────────────────────────────────────────────

    def compute_cost(self, query: str, input_tokens: int, output_tokens: int, **kw) -> CostResult:
        """Compute thermodynamic cost for a single query."""
        total_tokens = input_tokens + output_tokens
        bits = total_tokens * 16  # 16-bit token representation

        landauer = bits * LANDAUER_PER_BIT
        actual = total_tokens * self._profile["energy_per_token_j"]
        co2 = actual * self._co2_per_j

        # Guard against zero division
        ratio = actual / landauer if landauer > 0 else float("inf")

        self._call_count += 1
        self._total_actual_j += actual
        self._total_landauer_j += landauer

        return CostResult(
            query=query,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens=total_tokens,
            bits_processed=bits,
            landauer_energy_j=landauer,
            actual_energy_j=actual,
            efficiency_ratio=ratio,
            co2_grams=co2,
            hardware=self.hardware,
            power_source=self.power_source,
        )

    # ── Comparison ──────────────────────────────────────────────────

    def compare_models(self, tasks: list[dict[str, Any]], **kw) -> dict[str, Any]:
        """Compare energy cost across hardware profiles for a set of tasks.

        Returns a dict with ``best_config`` and ``efficiency_gap`` (> 1).
        """
        results: dict[str, float] = {}

        for hw_name, hw_profile in HARDWARE_PROFILES.items():
            total_j = 0.0
            for task in tasks:
                tokens = task.get("input_tokens", 0) + task.get("output_tokens", 0)
                total_j += tokens * hw_profile["energy_per_token_j"]
            results[hw_name] = total_j

        best = min(results, key=results.get)   # type: ignore[arg-type]
        worst = max(results, key=results.get)  # type: ignore[arg-type]
        gap = results[worst] / results[best] if results[best] > 0 else float("inf")

        return {
            "best_config": best,
            "efficiency_gap": gap,
            "energy_by_hardware": results,
        }

    # ── Helpers ─────────────────────────────────────────────────────

    def _energy_equivalent(self, joules: float, **kw) -> str:
        """Return a human-readable energy equivalent."""
        wh = joules / 3600.0  # watt-hours
        if wh < 0.001:
            return f"≈ {joules * 1000:.2f} mJ"
        elif wh < 1:
            return f"≈ {wh * 1000:.2f} mWh"
        else:
            return f"≈ {wh:.3f} Wh"

    def suggest_optimizations(self, **kw) -> list[str]:
        """Return a list of optimization tips to reduce energy cost."""
        return [
            "Use INT8/FP8 quantization to halve energy per token.",
            "Batch requests to maximise GPU utilization.",
            "Cache frequent queries to avoid recomputation.",
            "Use speculative decoding to reduce total token count.",
            "Shift workloads to renewable-energy time windows.",
            "Distil large models into smaller, efficient variants.",
        ]

    def get_stats(self, **kw) -> dict[str, Any]:
        """Return aggregate statistics about all computations so far."""
        avg_ratio = (
            self._total_actual_j / self._total_landauer_j
            if self._total_landauer_j > 0
            else float("inf")
        )
        return {
            "total_operations": self._call_count,
            "total_actual_joules": self._total_actual_j,
            "total_landauer_joules": self._total_landauer_j,
            "efficiency_vs_landauer": f"{avg_ratio:.2e}x",
            "energy_equivalent": self._energy_equivalent(self._total_actual_j),
        }

