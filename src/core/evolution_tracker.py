"""
MeshCtx v3.40 — Evolution Tracker (持续进化追踪器)

追踪meshctx每版的能力增长，生成进化曲线图。
自动记录: 模块数/测试数/能力维度分数/论文落地数

HN对标: DeepSWE benchmark (62↑) — 系统化评估Agent能力
"""
import time
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from collections import defaultdict


DATA_DIR = Path.home() / ".meshctx" / "evolution"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class VersionSnapshot:
    """版本快照"""
    version: str
    timestamp: float = field(default_factory=time.time)
    modules_count: int = 0
    tests_count: int = 0
    papers_landed: int = 0
    
    # 能力维度 0-100
    memory_score: float = 0
    safety_score: float = 0
    autonomy_score: float = 0
    reasoning_score: float = 0
    multimodal_score: float = 0
    performance_score: float = 0
    
    features: List[str] = field(default_factory=list)
    competitors_compared: List[str] = field(default_factory=list)


class EvolutionTracker:
    """进化追踪器 — 记录每次版本迭代的能力变化"""
    
    def __init__(self):
        self.history: List[VersionSnapshot] = []
        self._load()
    
    def _load(self):
        """从磁盘加载历史"""
        history_file = DATA_DIR / "history.json"
        if history_file.exists():
            with open(history_file) as f:
                data = json.load(f)
                for item in data:
                    snap = VersionSnapshot(**item)
                    self.history.append(snap)
    
    def _save(self):
        """保存到磁盘"""
        with open(DATA_DIR / "history.json", "w") as f:
            json.dump([s.__dict__ for s in self.history], f, indent=2, ensure_ascii=False)
    
    def snapshot(self, version: str, modules_count: int, tests_count: int,
                 papers: int = 0) -> VersionSnapshot:
        """创建当前版本快照"""
        # 从已有数据推算各维度分数
        snap = VersionSnapshot(
            version=version,
            modules_count=modules_count,
            tests_count=tests_count,
            papers_landed=papers,
            
            # 启发式计算各维度
            memory_score=min(100, 40 + papers * 8 + modules_count * 0.3),
            safety_score=min(100, 30 + modules_count * 0.5),
            autonomy_score=min(100, 20 + modules_count * 0.6),
            reasoning_score=min(100, 25 + papers * 10 + modules_count * 0.4),
            multimodal_score=min(100, 15 + modules_count * 0.2),
            performance_score=min(100, 50 + tests_count * 0.02),
        )
        
        self.history.append(snap)
        self._save()
        return snap
    
    def get_trend(self, dimension: str = "autonomy") -> Dict[str, Any]:
        """获取某维度的进化趋势"""
        if len(self.history) < 2:
            return {"trend": "initial", "versions": 1}
        
        scores = []
        versions = []
        for snap in self.history:
            versions.append(snap.version)
            scores.append(getattr(snap, f"{dimension}_score", 0))
        
        # 计算增长率
        growth = scores[-1] - scores[0]
        growth_rate = (scores[-1] / max(scores[0], 1) - 1) * 100
        
        # 每版本增量
        per_version = growth / max(len(self.history) - 1, 1)
        
        return {
            "dimension": dimension,
            "latest_score": scores[-1],
            "initial_score": scores[0],
            "total_growth": round(growth, 1),
            "growth_rate_pct": round(growth_rate, 1),
            "per_version_gain": round(per_version, 2),
            "versions": len(versions),
            "trajectory": [{"v": v, "s": s} for v, s in zip(versions, scores)],
        }
    
    def get_overall_health(self) -> Dict[str, Any]:
        """总体健康度"""
        if not self.history:
            return {"status": "no_data"}
        
        latest = self.history[-1]
        first = self.history[0]
        
        dimensions = ["memory", "safety", "autonomy", "reasoning", "multimodal", "performance"]
        scores = {}
        for d in dimensions:
            scores[d] = getattr(latest, f"{d}_score", 0)
        
        avg_score = sum(scores.values()) / len(scores)
        
        return {
            "version": latest.version,
            "modules": latest.modules_count,
            "tests": latest.tests_count,
            "papers": latest.papers_landed,
            "avg_capability_score": round(avg_score, 1),
            "total_versions_tracked": len(self.history),
            "first_version": first.version,
            "evolution_rating": self._evolution_rating(),
            "dimension_scores": scores,
        }
    
    def _evolution_rating(self) -> str:
        """进化评级"""
        if len(self.history) < 3:
            return "🌱 Seedling"
        
        # 计算所有维度平均增长率
        total_growth = 0
        for d in ["memory", "safety", "autonomy", "reasoning"]:
            trend = self.get_trend(d)
            total_growth += trend["growth_rate_pct"]
        
        avg_growth = total_growth / 4
        
        if avg_growth > 50: return "🚀 Hyper-Evolving"
        elif avg_growth > 25: return "📈 Rapidly Growing"
        elif avg_growth > 10: return "🌿 Steadily Improving"
        else: return "🌱 Seedling"
    
    def compare_versions(self, v1: str, v2: str) -> Dict[str, Any]:
        """对比两个版本"""
        snap1 = next((s for s in self.history if s.version == v1), None)
        snap2 = next((s for s in self.history if s.version == v2), None)
        
        if not snap1 or not snap2:
            return {"error": "version not found"}
        
        dimensions = ["memory", "safety", "autonomy", "reasoning", "multimodal", "performance"]
        diffs = {}
        for d in dimensions:
            diffs[d] = round(getattr(snap2, f"{d}_score") - getattr(snap1, f"{d}_score"), 1)
        
        return {
            "from": v1,
            "to": v2,
            "modules_gained": snap2.modules_count - snap1.modules_count,
            "tests_gained": snap2.tests_count - snap1.tests_count,
            "dimension_changes": diffs,
        }
    
    def predict_next_version(self) -> Dict[str, Any]:
        """预测下个版本的能力分数"""
        if len(self.history) < 2:
            return {"error": "need at least 2 snapshots"}
        
        predictions = {}
        for d in ["memory", "safety", "autonomy", "reasoning"]:
            trend = self.get_trend(d)
            predictions[d] = round(trend["latest_score"] + trend["per_version_gain"], 1)
        
        # 预测版本号
        latest_ver = self.history[-1].version
        parts = latest_ver.split(".")
        next_ver = f"{parts[0]}.{int(parts[1]) + 1}.0"
        
        return {
            "predicted_version": next_ver,
            "predicted_scores": predictions,
            "confidence": "medium" if len(self.history) > 5 else "low",
        }


# 单例
_tracker: Optional[EvolutionTracker] = None

def get_evolution_tracker() -> EvolutionTracker:
    global _tracker
    if _tracker is None:
        _tracker = EvolutionTracker()
    return _tracker
