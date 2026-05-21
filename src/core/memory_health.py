"""Memory Health Dashboard — v2.64
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
直接解决行业P0痛点: "AI agent memory is garbage"

展示:
1. 当前记忆状态: 总数/压缩比/遗忘曲线
2. SDM向量空间: 维度/利用率/碰撞率
3. 情绪加权: 关键记忆vs普通记忆衰减对比
4. 海马回放: 最近巩固统计
5. 联想网络: 激活扩散路径可视化数据
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MemoryStats:
    """记忆统计快照"""
    total_memories: int = 0
    compressed_memories: int = 0
    compression_ratio: float = 0.0  # 压缩比 (压缩前/压缩后)
    sdm_dimension: int = 1000
    sdm_utilization: float = 0.0  # SDM空间利用率
    sdm_collision_rate: float = 0.0
    critical_memories: int = 0  # 关键记忆数
    neutral_memories: int = 0
    critical_decay_hours: float = 0.0  # 关键记忆半衰期
    neutral_decay_hours: float = 0.0
    replay_cycles: int = 0  # 海马回放次数
    recent_consolidations: int = 0
    associative_edges: int = 0  # 联想网络边数
    avg_recall_latency_ms: float = 0.0
    total_tokens_saved: int = 0  # 通过压缩节省的token


class MemoryHealthDashboard:
    """记忆健康仪表盘"""

    def __init__(self):
        self._stats_history: List[MemoryStats] = []
        self._last_snapshot_time: float = 0.0

    def collect_stats(self) -> MemoryStats:
        """收集当前记忆统计数据"""
        stats = MemoryStats()

        # 1. 从突破记忆模块获取数据
        try:
            from .breakthrough_memory import get_breakthrough_memory
            bm = get_breakthrough_memory()
            metrics = bm.get_breakthrough_metrics()

            sdm_data = metrics.get("sdm", {})
            fractal_data = metrics.get("fractal", {})

            stats.sdm_dimension = sdm_data.get("dimension", 1000)
            stats.sdm_utilization = sdm_data.get("utilization", 0.0)
            stats.compression_ratio = fractal_data.get("ratio", 1.0)

            # 估算记忆数
            total = sdm_data.get("patterns_stored", 0)
            stats.total_memories = total
            stats.compressed_memories = int(total / max(1, stats.compression_ratio))

            # Token节省
            stats.total_tokens_saved = total * max(0, stats.compression_ratio - 1)

        except ImportError:
            pass

        # 2. 从人脑记忆模块获取情绪/衰减数据
        try:
            from .human_memory import get_human_memory
            hm = get_human_memory()
            health = hm.get_health_report() if hasattr(hm, 'get_health_report') else {}

            stats.critical_memories = health.get("critical_count", 0)
            stats.neutral_memories = health.get("neutral_count", 0)
            stats.critical_decay_hours = health.get("critical_decay_hours", 720.0)
            stats.neutral_decay_hours = health.get("neutral_decay_hours", 3.6)

            # 回放统计
            replay = health.get("replay", {})
            stats.replay_cycles = replay.get("total_cycles", 0)
            stats.recent_consolidations = replay.get("recent", 0)

            # 联想网络
            assoc = health.get("associative", {})
            stats.associative_edges = assoc.get("edges", 0)

        except ImportError:
            pass

        # 3. 保存历史
        self._stats_history.append(stats)
        if len(self._stats_history) > 100:
            self._stats_history = self._stats_history[-100:]
        self._last_snapshot_time = time.time()

        return stats

    def get_health_score(self) -> Dict[str, Any]:
        """计算记忆健康评分 (0-100)"""
        stats = self.collect_stats()

        scores = {}

        # 1. 容量评分: 有记忆即得分
        if stats.total_memories > 0:
            scores["容量"] = min(100, stats.total_memories)
        else:
            scores["容量"] = 10

        # 2. 压缩评分: 压缩比越高越好
        if stats.compression_ratio >= 100:
            scores["压缩效率"] = 100
        elif stats.compression_ratio >= 10:
            scores["压缩效率"] = 80
        elif stats.compression_ratio > 1:
            scores["压缩效率"] = 50
        else:
            scores["压缩效率"] = 20

        # 3. 情绪保护评分: 关键记忆衰减越慢越好
        if stats.critical_decay_hours > 500:
            scores["情绪保护"] = 100
        elif stats.critical_decay_hours > 100:
            scores["情绪保护"] = 70
        else:
            scores["情绪保护"] = 30

        # 4. 巩固评分: 有回放=健康
        if stats.replay_cycles > 0:
            scores["记忆巩固"] = min(100, stats.replay_cycles * 10)
        else:
            scores["记忆巩固"] = 0

        # 5. 关联评分
        if stats.associative_edges > 100:
            scores["联想网络"] = 100
        elif stats.associative_edges > 10:
            scores["联想网络"] = 60
        else:
            scores["联想网络"] = stats.associative_edges

        overall = sum(scores.values()) / max(1, len(scores))

        return {
            "overall_score": round(overall, 1),
            "dimension_scores": scores,
            "stats": {
                "total_memories": stats.total_memories,
                "compression_ratio": f"{stats.compression_ratio:.1f}:1",
                "tokens_saved": stats.total_tokens_saved,
                "sdm_dimension": stats.sdm_dimension,
                "critical_vs_neutral": (
                    f"{stats.critical_memories}:{stats.neutral_memories}"
                ),
                "decay_advantage": (
                    f"关键记忆衰减慢{stats.critical_decay_hours/ max(0.01, stats.neutral_decay_hours):.0f}x"
                ),
                "replay_cycles": stats.replay_cycles,
                "associative_edges": stats.associative_edges,
            },
            "timestamp": time.time(),
        }

    def get_health_trend(self) -> Dict:
        """获取健康趋势"""
        if len(self._stats_history) < 2:
            return {"trend": "stable", "data_points": len(self._stats_history)}

        recent = self._stats_history[-10:]
        comp_ratios = [s.compression_ratio for s in recent]
        mem_counts = [s.total_memories for s in recent]

        comp_trend = "improving" if len(set(comp_ratios)) > 1 and \
            comp_ratios[-1] >= comp_ratios[0] else \
            "declining" if comp_ratios[-1] < comp_ratios[0] * 0.8 else "stable"

        mem_trend = "growing" if mem_counts[-1] > mem_counts[0] else \
            "shrinking" if mem_counts[-1] < mem_counts[0] else "stable"

        return {
            "compression": {"trend": comp_trend, "current": round(comp_ratios[-1], 1)},
            "memory_count": {"trend": mem_trend, "current": mem_counts[-1]},
            "data_points": len(recent),
        }

    def get_forgetting_curve_data(self) -> List[Dict]:
        """遗忘曲线数据点（用于绘图）"""
        try:
            from .human_memory import get_human_memory
            hm = get_human_memory()
            curve = hm.get_forgetting_curve() if hasattr(hm, 'get_forgetting_curve') else []
            return curve[:50]  # 最多50个数据点
        except ImportError:
            return []


# 单例
_dashboard: Optional[MemoryHealthDashboard] = None


def get_memory_health() -> MemoryHealthDashboard:
    global _dashboard
    if _dashboard is None:
        _dashboard = MemoryHealthDashboard()
    return _dashboard
