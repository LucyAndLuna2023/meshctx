"""
OODA Learn闭环 — 学习阶段实现
将任务执行结果反馈给策略选择系统

核心机制:
1. 结果记录 → 策略信念更新
2. 连续成功 → 习惯缓存
3. 连续失败 → 策略切换建议
4. 与ActiveInference + FreeEnergy接口对接

接入点: AgentLoopPlugin的Learn阶段
"""
import time
from typing import Dict, Optional, List
from collections import defaultdict


class LearnLoop:
    """
    OODA Learn阶段处理器

    接受任务执行结果 → 更新内部模型 → 影响未来决策
    """

    # 错误类型 → 推荐策略映射
    ERROR_STRATEGY_MAP = {
        "knowledge_gap": "explore_random",
        "tool_error": "safe_path",
        "timeout": "defer_decision",
        "resource_exhausted": "safe_path",
        "validation_error": "balanced",
        "network_error": "defer_decision",
    }

    # 备用策略池（当前策略不可用时轮换）
    FALLBACK_STRATEGIES = [
        "explore_random",
        "balanced",
        "safe_path",
        "defer_decision",
        "meta",
    ]

    def __init__(self, habit_threshold: int = 10):
        self.habit_threshold = habit_threshold

        # 任务类型 → 策略 → 成功/失败计数
        self.strategy_stats: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: {"success": 0, "fail": 0}
        )

        # 习惯缓存: task_type → {"strategy": str, "count": int, "last_used": float}
        self.habits: Dict[str, Dict] = {}

        # 连续失败计数
        self._consecutive_fails: Dict[str, int] = defaultdict(int)

        # 最近结果（用于趋势分析）
        self.recent_results: List[Dict] = []

    # ── 核心: 记录结果 → 更新信念 ──────────────────

    def record_outcome(
        self,
        task_type: str,
        success: bool,
        quality: float,
        strategy_used: str,
        duration: float,
        error_type: Optional[str] = None,
    ) -> Dict:
        """
        记录一次任务执行结果

        返回: {"belief_updated": bool, "strength": float, "habit_formed": bool, ...}
        """
        strength = quality if success else max(0.05, min(0.25, 1.0 - quality))

        # 更新策略统计
        stats = self.strategy_stats[(task_type, strategy_used)]
        if success:
            stats["success"] += 1
        else:
            stats["fail"] += 1

        # 更新连续失败计数
        if success:
            self._consecutive_fails[(task_type, strategy_used)] = 0
        else:
            self._consecutive_fails[(task_type, strategy_used)] += 1

        # 检查习惯形成
        habit_formed = False
        if success and quality > 0.7:
            habit = self.habits.get(task_type, {"strategy": strategy_used, "count": 0, "last_used": 0})
            habit["count"] += 1
            habit["last_used"] = time.time()
            habit["strategy"] = strategy_used
            self.habits[task_type] = habit

            if habit["count"] >= self.habit_threshold:
                habit_formed = True

        # 记录最近结果
        self.recent_results.append({
            "task_type": task_type,
            "success": success,
            "quality": quality,
            "strategy": strategy_used,
            "duration": duration,
            "error_type": error_type,
            "timestamp": time.time(),
        })

        # 只保留最近200条
        if len(self.recent_results) > 200:
            self.recent_results = self.recent_results[-100:]

        return {
            "belief_updated": True,
            "strength": round(strength, 3),
            "habit_formed": habit_formed,
            "consecutive_fails": self._consecutive_fails[(task_type, strategy_used)],
        }

    # ── 习惯管理 ──────────────────────────────────

    def is_habit(self, task_type: str) -> bool:
        """检查某个任务类型是否已形成习惯"""
        habit = self.habits.get(task_type)
        if not habit:
            return False
        return habit["count"] >= self.habit_threshold

    def get_habit_strategy(self, task_type: str) -> Optional[str]:
        """获取习惯策略"""
        habit = self.habits.get(task_type)
        if not habit or habit["count"] < self.habit_threshold:
            return None
        return habit["strategy"]

    # ── 策略建议 ──────────────────────────────────

    def suggest_strategy(self, task_type: str) -> str:
        """
        基于历史数据推荐策略

        优先级: 习惯 > 最优历史策略 > 均衡策略
        """
        # 1. 检查习惯
        habit = self.get_habit_strategy(task_type)
        if habit:
            return habit

        # 2. 找最优历史策略
        best_strategy = None
        best_ratio = -1.0

        for (tt, strategy), stats in self.strategy_stats.items():
            if tt != task_type:
                continue
            total = stats["success"] + stats["fail"]
            if total == 0:
                continue
            ratio = stats["success"] / total
            if ratio > best_ratio:
                best_ratio = ratio
                best_strategy = strategy

        if best_strategy and best_ratio > 0.5:
            return best_strategy

        # 3. 检查连续失败 → 切换策略
        for (tt, strategy), fails in self._consecutive_fails.items():
            if tt == task_type and fails >= 3:
                return self._get_fallback(strategy)

        return "balanced"

    def _get_fallback(self, current: str) -> str:
        """获取不同于当前的备用策略"""
        for s in self.FALLBACK_STRATEGIES:
            if s != current:
                return s
        return "balanced"

    # ── 统计查询 ──────────────────────────────────

    def get_stats(self) -> Dict:
        """返回学习统计"""
        total_success = sum(1 for r in self.recent_results if r["success"])
        total_fail = len(self.recent_results) - total_success
        total = len(self.recent_results)

        return {
            "total_outcomes": total,
            "success_rate": round(total_success / max(1, total), 3),
            "habits_formed": sum(1 for h in self.habits.values() if h["count"] >= self.habit_threshold),
            "active_strategies": list(set(
                s for (_, s), _ in self.strategy_stats.items()
            )),
            "recent_success_rate": round(
                sum(1 for r in self.recent_results[-20:] if r["success"]) / max(1, min(20, len(self.recent_results))), 3
            ),
        }

    # ── 集成接口: 对接ActiveInference和FreeEnergy ──

    def to_free_energy_observation(self, task_type: str) -> Dict:
        """
        生成供FreeEnergy.perceive()使用的观测数据
        """
        stats = self.get_stats()
        return {
            "outcome": 1 if stats["success_rate"] > 0.5 else 0,
            "duration": sum(r["duration"] for r in self.recent_results[-10:]) / max(1, len(self.recent_results[-10:])),
            "success": stats["success_rate"] > 0.5,
            "task_type": task_type,
        }

    def to_active_inference_feedback(self, task_type: str, strategy: str) -> Dict:
        """
        生成供ActiveInference.learn_from_outcome()使用的反馈
        """
        fails = self._consecutive_fails.get((task_type, strategy), 0)
        stats = self.strategy_stats.get((task_type, strategy), {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]

        return {
            "policy_name": strategy,
            "success": stats["success"] > stats["fail"],
            "duration": 1.0,  # placeholder, 实际应从context获取
            "consecutive_fails": fails,
            "success_ratio": stats["success"] / max(1, total),
            "sample_count": total,
        }
