"""Thermodynamic Computation Cost — v2.82
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Landauer原理 (1961): 每个不可逆计算消耗kT ln2能量

核心:
- 每个bit的删除 = kT ln2 ≈ 2.9e-21 J (室温)
- 计算不可逆性 = 信息丢失 → 能量消耗
- 用这个物理下限衡量每个操作的"真实成本"
- Beyond token cost → physical energy cost
"""
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

# 物理常数
K_BOLTZMANN = 1.380649e-23  # J/K
T_ROOM = 293.15             # K (20°C)
LANDAUER_LIMIT = K_BOLTZMANN * T_ROOM * math.log(2)  # ~2.9e-21 J/bit


@dataclass
class ComputationCost:
    """计算成本"""
    operation: str
    bits_processed: int = 0
    landauer_energy_j: float = 0.0  # 理论下限
    actual_energy_j: float = 0.0    # 实际估算
    efficiency_ratio: float = 0.0   # 实际/理论
    tokens: int = 0
    co2_grams: float = 0.0          # 碳排放估算


class ThermodynamicCostAnalyzer:
    """热力学成本分析器"""

    # 实际能耗估算 (Joule per token — 基于GPU TDP)
    _ENERGY_PER_TOKEN = {
        "h100": 3.0e-4,      # NVIDIA H100: ~700W, ~2M tok/s → 3.5e-4 J/tok
        "a100": 6.0e-4,      # A100: ~400W, ~700K tok/s → 5.7e-4
        "cpu":  1.0e-2,      # CPU推理: ~100W, ~10K tok/s → 1e-2
    }

    # 碳排放 (g CO2 per kWh, 取决于电网)
    _CO2_PER_KWH = {
        "renewable": 10,     # 可再生能源
        "mixed": 400,        # 混合电网
        "coal": 900,         # 煤电
    }

    def __init__(self, hardware: str = "a100",
                power_source: str = "mixed"):
        self.hardware = hardware
        self.power_source = power_source
        self._cost_history: List[ComputationCost] = []

    # ── Cost Computation ───────────────────────────────

    def compute_cost(self, operation: str,
                    input_tokens: int = 0,
                    output_tokens: int = 0,
                    bits_per_token: int = 16) -> ComputationCost:
        """计算操作的热力学成本"""
        total_tokens = input_tokens + output_tokens
        bits_processed = total_tokens * bits_per_token

        # 1. Landauer理论下限
        landauer_energy = bits_processed * LANDAUER_LIMIT

        # 2. 实际能耗估算
        energy_per_token = self._ENERGY_PER_TOKEN.get(
            self.hardware, self._ENERGY_PER_TOKEN["a100"]
        )
        actual_energy = total_tokens * energy_per_token

        # 3. 效率比 (实际/理论)
        efficiency = actual_energy / max(landauer_energy, 1e-30)

        # 4. 碳排放
        co2_per_kwh = self._CO2_PER_KWH.get(
            self.power_source, self._CO2_PER_KWH["mixed"]
        )
        kwh = actual_energy / 3.6e6  # J → kWh
        co2 = kwh * co2_per_kwh

        cost = ComputationCost(
            operation=operation,
            bits_processed=bits_processed,
            landauer_energy_j=landauer_energy,
            actual_energy_j=round(actual_energy, 9),
            efficiency_ratio=efficiency,
            tokens=total_tokens,
            co2_grams=round(co2, 6),
        )

        self._cost_history.append(cost)
        if len(self._cost_history) > 100:
            self._cost_history = self._cost_history[-100:]

        return cost

    # ── Comparative Analysis ────────────────────────────

    def compare_models(self, tasks: List[Dict]) -> Dict:
        """比较不同硬件+能源的成本"""
        results = []
        for hw in ["h100", "a100", "cpu"]:
            for ps in ["renewable", "mixed", "coal"]:
                self.hardware = hw
                self.power_source = ps
                total_j = 0
                total_co2 = 0
                for task in tasks:
                    cost = self.compute_cost(
                        task.get("name", "task"),
                        task.get("input_tokens", 0),
                        task.get("output_tokens", 0),
                    )
                    total_j += cost.actual_energy_j
                    total_co2 += cost.co2_grams
                results.append({
                    "hardware": hw,
                    "power": ps,
                    "energy_j": round(total_j, 6),
                    "co2_g": round(total_co2, 6),
                    "equivalent": self._energy_equivalent(total_j),
                })

        results.sort(key=lambda x: x["energy_j"])
        best = results[0]
        worst = results[-1]

        return {
            "best_config": f"{best['hardware']}+{best['power']}",
            "worst_config": f"{worst['hardware']}+{worst['power']}",
            "energy_range": f"{best['energy_j']} - {worst['energy_j']} J",
            "co2_range": f"{best['co2_g']} - {worst['co2_g']} g",
            "efficiency_gap": round(
                worst["energy_j"] / max(1e-10, best["energy_j"]), 1
            ),
            "all_configs": results,
        }

    def _energy_equivalent(self, joules: float) -> str:
        """能量等价物"""
        equivalents = [
            (1e6, "烧开1升水"),
            (1e3, "LED灯1小时"),
            (1e0, "心跳1次"),
            (1e-3, "蚂蚁爬1步"),
            (1e-6, "神经脉冲"),
        ]
        for threshold, desc in equivalents:
            if joules >= threshold:
                count = joules / threshold
                return f"≈ {count:.1f} x {desc}"
        return f"{joules:.2e} J"

    # ── Optimization Suggestions ────────────────────────

    def suggest_optimizations(self) -> List[str]:
        """基于热力学的优化建议"""
        suggestions = []

        # 检查当前配置效率
        if self.hardware == "cpu":
            suggestions.append(
                "💡 GPU推理比CPU能效高100x — 切换到H100/A100"
            )

        if self.power_source == "coal":
            suggestions.append(
                "🌱 煤电碳排放是可再生能源的90x — 切换到绿色电网"
            )

        # 通用建议
        suggestions.extend([
            "🔬 量化(INT8/INT4): 减少50-75% bits → Landauer成本成比例下降",
            "🔄 缓存复用: 避免重复计算 = 零能耗",
            "📉 小模型优先: BUDGET模型能效比EXPERT高1000x",
        ])

        return suggestions

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        if not self._cost_history:
            return {"total_operations": 0}

        total_j = sum(c.actual_energy_j for c in self._cost_history)
        total_co2 = sum(c.co2_grams for c in self._cost_history)
        total_bits = sum(c.bits_processed for c in self._cost_history)
        avg_efficiency = np.mean([c.efficiency_ratio for c in self._cost_history])

        return {
            "total_operations": len(self._cost_history),
            "total_energy_j": round(total_j, 6),
            "total_co2_g": round(total_co2, 6),
            "total_bits": total_bits,
            "landauer_limit_j": round(total_bits * LANDAUER_LIMIT, 12),
            "efficiency_vs_landauer": f"{avg_efficiency:.1e}x",
            "energy_equivalent": self._energy_equivalent(total_j),
            "optimizations": self.suggest_optimizations(),
        }


# 单例
_analyzer: Optional[ThermodynamicCostAnalyzer] = None


def get_thermo_analyzer() -> ThermodynamicCostAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ThermodynamicCostAnalyzer()
    return _analyzer
