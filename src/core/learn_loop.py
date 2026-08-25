"""
OODA Learn闭环 — 学习阶段实现（开源真实版）
将任务执行结果反馈给策略选择系统

核心机制:
1. 结果记录 → 策略信念更新 (belief update)
2. 连续成功 → 习惯缓存 (habit cache)
3. 连续失败 → 策略切换建议 (strategy shift suggestion)
4. 与ActiveInference + FreeEnergy接口对接 (观测/反馈数据生成)

接入点: AgentLoopPlugin的Learn阶段

纯 Python stdlib 实现（threading / collections / time / logging），
不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.learn_loop")


class LearnLoop:
    """OODA Learn阶段处理器

    状态:
      beliefs  — {task_type: {strategy: {strength, successes, failures,
                                         consecutive_successes, consecutive_failures, ...}}}
      habits   — {task_type: {"strategy": ..., "count": n, "formed_at": ...}}
      history  — 最近一次执行结果记录 (deque, 有上限)

    线程安全: 所有写入经过 self._lock。
    """

    ERROR_STRATEGY_MAP = {
        'knowledge_gap': 'explore_random',
        'tool_error': 'safe_path',
        'timeout': 'defer_decision',
        'resource_exhausted': 'safe_path',
        'validation_error': 'balanced',
        'network_error': 'defer_decision',
    }
    FALLBACK_STRATEGIES = ['explore_random', 'balanced', 'safe_path', 'defer_decision', 'meta']

    # 连续失败达到该次数即判定策略"卡住"，触发切换建议
    STRATEGY_STUCK_FAILURES = 3

    def __init__(self, habit_threshold: int = 10):
        if habit_threshold <= 0:
            raise ValueError("habit_threshold must be a positive integer")
        self.habit_threshold: int = int(habit_threshold)
        self.beliefs: Dict[str, Dict[str, dict]] = {}
        self.habits: Dict[str, dict] = {}
        self.history: List[dict] = []
        self._history_max = 1000
        self._lock = threading.RLock()
        self._created_at = time.time()

    # ── 结果记录 ──────────────────────────────────────────
    def record_outcome(self, task_type: str, success: bool, quality: float,
                       strategy_used: str, duration: float,
                       error_type: Optional[str] = None) -> Dict:
        """记录一次任务执行结果并更新策略信念。

        返回:
          {
            "belief_updated": bool,
            "strength": float,
            "task_type": str,
            "strategy_used": str,
            "success": bool,
            "quality": float,
            "habit": bool,          # 本次记录后是否形成/已存在习惯
            "strategy_shift": bool, # 是否因连续失败触发切换建议
          }
        """
        quality = max(0.0, min(1.0, float(quality or 0.0)))
        duration = max(0.0, float(duration or 0.0))
        with self._lock:
            task_beliefs = self.beliefs.setdefault(task_type, {})
            belief = task_beliefs.setdefault(strategy_used, {
                "strength": 0.5,
                "successes": 0,
                "failures": 0,
                "consecutive_successes": 0,
                "consecutive_failures": 0,
                "total_duration": 0.0,
                "last_outcome": None,
                "first_used": time.time(),
                "last_used": time.time(),
            })

            if success:
                # 成功强化: 基础增量 + 质量加权
                belief["strength"] = min(1.0, belief["strength"] + 0.1 + quality * 0.05)
                belief["successes"] += 1
                belief["consecutive_successes"] += 1
                belief["consecutive_failures"] = 0
                belief["last_outcome"] = "success"
            else:
                # 失败惩罚: 强度减半
                belief["strength"] = max(0.0, belief["strength"] * 0.5)
                belief["failures"] += 1
                belief["consecutive_failures"] += 1
                belief["consecutive_successes"] = 0
                belief["last_outcome"] = "failure"
            belief["total_duration"] += duration
            belief["last_used"] = time.time()

            # 错误类型 → 记录建议策略（供切换参考）
            if not success and error_type:
                suggested = self.ERROR_STRATEGY_MAP.get(error_type)
                if suggested:
                    belief.setdefault("suggested_error_strategies", []).append(suggested)

            # 习惯形成: 连续成功达到阈值
            formed = belief["consecutive_successes"] >= self.habit_threshold
            if formed:
                prev = self.habits.get(task_type)
                count = belief["consecutive_successes"]
                if prev and prev.get("strategy") == strategy_used:
                    prev["count"] = count
                    prev["last_reinforced"] = time.time()
                else:
                    self.habits[task_type] = {
                        "strategy": strategy_used,
                        "count": count,
                        "formed_at": time.time(),
                        "last_reinforced": time.time(),
                    }

            # 策略切换建议: 同一策略连续失败达到阈值
            shift = (not success) and belief["consecutive_failures"] >= self.STRATEGY_STUCK_FAILURES

            record = {
                "task_type": task_type,
                "strategy": strategy_used,
                "success": bool(success),
                "quality": quality,
                "duration": duration,
                "error_type": error_type,
                "timestamp": time.time(),
            }
            self.history.append(record)
            if len(self.history) > self._history_max:
                self.history = self.history[-self._history_max:]

            return {
                "belief_updated": True,
                "strength": belief["strength"],
                "task_type": task_type,
                "strategy_used": strategy_used,
                "success": bool(success),
                "quality": quality,
                "habit": task_type in self.habits,
                "strategy_shift": shift,
            }

    # ── 习惯查询 ──────────────────────────────────────────
    def is_habit(self, task_type: str) -> bool:
        """检查某个任务类型是否已形成习惯"""
        with self._lock:
            return task_type in self.habits

    def get_habit_strategy(self, task_type: str) -> Optional[str]:
        """获取习惯策略"""
        with self._lock:
            habit = self.habits.get(task_type)
            if habit is None:
                return None
            return habit.get("strategy")

    # ── 策略建议 ──────────────────────────────────────────
    def suggest_strategy(self, task_type: str) -> str:
        """基于历史数据推荐策略

        优先级:
          1. 已形成习惯 → 习惯策略
          2. 信念中 strength 最高的策略（若其连续失败≥阈值则切换）
          3. 无历史 → FALLBACK_STRATEGIES[0]
        """
        with self._lock:
            habit = self.habits.get(task_type)
            if habit is not None:
                return habit.get("strategy", self.FALLBACK_STRATEGIES[0])

            task_beliefs = self.beliefs.get(task_type)
            if not task_beliefs:
                return self.FALLBACK_STRATEGIES[0]

            best = max(task_beliefs.items(), key=lambda kv: kv[1].get("strength", 0.0))
            best_strategy, best_data = best
            if best_data.get("consecutive_failures", 0) >= self.STRATEGY_STUCK_FAILURES:
                return self._get_fallback(best_strategy)
            return best_strategy

    def _get_fallback(self, current: str) -> str:
        """获取不同于当前的备用策略"""
        for strategy in self.FALLBACK_STRATEGIES:
            if strategy != current:
                return strategy
        return current

    # ── 统计与外部接口 ────────────────────────────────────
    def get_stats(self) -> Dict:
        """返回学习统计"""
        with self._lock:
            total = len(self.history)
            successes = sum(1 for h in self.history if h["success"])
            strategy_count = sum(len(b) for b in self.beliefs.values())
            return {
                "task_types": len(self.beliefs),
                "strategies": strategy_count,
                "habits": len(self.habits),
                "total_outcomes": total,
                "success_rate": round(successes / total, 4) if total else 0.0,
                "history_size": total,
                "habit_threshold": self.habit_threshold,
                "beliefs": {
                    task: {
                        strat: {
                            "strength": round(data.get("strength", 0.0), 4),
                            "successes": data.get("successes", 0),
                            "failures": data.get("failures", 0),
                        }
                        for strat, data in strategies.items()
                    }
                    for task, strategies in self.beliefs.items()
                },
            }

    def to_free_energy_observation(self, task_type: str) -> Dict:
        """生成供FreeEnergy.perceive()使用的观测数据

        观测携带该任务类型的策略信念分布与习惯状态,
        供自由能最小化模块计算预期自由能/惊喜度。
        """
        with self._lock:
            task_beliefs = self.beliefs.get(task_type, {})
            belief_list = [
                {
                    "strategy": strat,
                    "strength": round(data.get("strength", 0.0), 4),
                    "successes": data.get("successes", 0),
                    "failures": data.get("failures", 0),
                }
                for strat, data in sorted(task_beliefs.items(),
                                          key=lambda kv: -kv[1].get("strength", 0.0))
            ]
            habit = self.habits.get(task_type)
            max_strength = max((b.get("strength", 0.0) for b in task_beliefs.values()), default=0.0)
            return {
                "observation_type": "learn_loop",
                "task_type": task_type,
                "beliefs": belief_list,
                "habit": habit,
                "expected_free_energy": round(1.0 - max_strength, 4),
                "timestamp": time.time(),
            }

    def to_active_inference_feedback(self, task_type: str, strategy: str) -> Dict:
        """生成供ActiveInference.learn_from_outcome()使用的反馈

        反馈给出该策略的信念强度与成败计数，供其更新策略先验。
        """
        with self._lock:
            belief = self.beliefs.get(task_type, {}).get(strategy)
            if belief is None:
                return {
                    "task_type": task_type,
                    "strategy": strategy,
                    "strength": 0.5,
                    "successes": 0,
                    "failures": 0,
                    "available": False,
                }
            return {
                "task_type": task_type,
                "strategy": strategy,
                "strength": round(belief.get("strength", 0.0), 4),
                "successes": belief.get("successes", 0),
                "failures": belief.get("failures", 0),
                "available": True,
                "timestamp": time.time(),
            }


__all__ = ["LearnLoop"]
