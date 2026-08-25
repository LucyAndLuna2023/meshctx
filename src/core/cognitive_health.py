"""
认知衰减监控 — CognitiveHealthMonitor
对抗长时间Agent运行的认知衰减

监控维度:
- 自由能趋势(上升→惊讶增加→衰减)
- 决策置信度趋势(下降→决策疲劳)
- 输出重复率(上升→思维僵化)
- 综合健康评分(0-100)
- 告警级别(normal/warning/critical)
- 新会话建议

接入点: OODA循环中定期调用，主循环的Orient阶段

真实开源实现（2026-08 批次B 审计）：纯 stdlib，无 stub 代理。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.cognitive_health")


class CognitiveHealthMonitor:
    """认知健康监控器 — 主动检测Agent衰减"""

    SCORE_WARNING = 60.0
    SCORE_CRITICAL = 40.0
    NEW_SESSION_THRESHOLD = 30.0

    # 评分权重
    _W_FE = 30.0      # 自由能健康度权重
    _W_CONF = 35.0    # 置信度健康度权重
    _W_REP = 35.0     # 重复率权重
    # 趋势归一化基准（slope 绝对值 / 基准 → [0,1]）
    _TREND_BASE = 0.05
    # 诊断问题阈值
    _FE_AVG_BAD = 0.55
    _FE_TREND_BAD = 0.05
    _CONF_AVG_BAD = 0.45
    _CONF_TREND_BAD = -0.05
    _REPEAT_BAD = 0.35

    def __init__(self, history_size: int = 50, max_score_history: int = 20, enable_alerts: bool = True):
        self.history_size = max(1, int(history_size))
        self.max_score_history = max(1, int(max_score_history))
        self.enable_alerts = bool(enable_alerts)
        self.free_energy_history: deque = deque(maxlen=self.history_size)
        self.confidence_history: deque = deque(maxlen=self.history_size)
        self.output_history: deque = deque(maxlen=self.history_size * 4)
        self.score_history: deque = deque(maxlen=self.max_score_history)
        self.events: List[Dict[str, Any]] = []
        self.score = 100.0
        self.alert_level = "normal"
        self._low_score_streak = 0
        self._lock = threading.RLock()
        self._log_event("init", {"score": self.score})

    # ── 记录 ──────────────────────────────────────────────
    def record_free_energy(self, f_value: float):
        """记录一次自由能值 (0-1, 越高越惊讶→越不健康)"""
        with self._lock:
            self.free_energy_history.append(float(f_value))
            self._log_event("free_energy", {"value": float(f_value)})

    def record_confidence(self, confidence: float):
        """记录一次决策置信度 (0-1, 越高越好)"""
        with self._lock:
            self.confidence_history.append(float(confidence))
            self._log_event("confidence", {"value": float(confidence)})

    def record_output(self, text: str):
        """记录输出内容（用于检测重复）"""
        with self._lock:
            self.output_history.append(str(text))

    # ── 趋势计算 ──────────────────────────────────────────
    @staticmethod
    def _linear_slope(values) -> float:
        """对序列做最小二乘线性回归，返回单位步长斜率。"""
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(values) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, values))
        var = sum((x - mx) ** 2 for x in xs)
        return (cov / var) if var > 0 else 0.0

    def get_free_energy_trend(self) -> float:
        """自由能趋势: 正数=自由能上升(衰减中), 负数=改善"""
        with self._lock:
            return self._linear_slope(list(self.free_energy_history))

    def get_confidence_trend(self) -> float:
        """置信度趋势: 正数=改善, 负数=衰减"""
        with self._lock:
            return self._linear_slope(list(self.confidence_history))

    def get_repeat_ratio(self) -> float:
        """输出重复率 (0-1)：非唯一输出占比。无输出时返回 0。"""
        with self._lock:
            outputs = list(self.output_history)
            if not outputs:
                return 0.0
            unique = len(set(outputs))
            return (len(outputs) - unique) / len(outputs)

    # ── 评分 ──────────────────────────────────────────────
    @staticmethod
    def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    def compute_score(self) -> float:
        """计算综合健康评分 (0-100)"""
        with self._lock:
            fe_hist = list(self.free_energy_history)
            conf_hist = list(self.confidence_history)

            # 无任何观测 → 无衰减证据，评分保持满分
            if not fe_hist and not conf_hist:
                return 100.0

            fe_avg = sum(fe_hist) / len(fe_hist) if fe_hist else 0.3
            fe_trend = self._linear_slope(fe_hist)
            fe_trend_norm = self._clamp(fe_trend / self._TREND_BASE, -1.0, 1.0)
            fe_pen = self._clamp(
                0.6 * fe_avg + 0.4 * max(0.0, fe_trend_norm)
            )

            conf_avg = sum(conf_hist) / len(conf_hist) if conf_hist else 0.7
            conf_trend = self._linear_slope(conf_hist)
            conf_trend_norm = self._clamp(conf_trend / self._TREND_BASE, -1.0, 1.0)
            conf_pen = self._clamp(
                0.5 * (1.0 - conf_avg) + 0.5 * max(0.0, -conf_trend_norm)
            )

            rep_pen = self._clamp(self.get_repeat_ratio())

            score = (
                100.0
                - self._W_FE * fe_pen
                - self._W_CONF * conf_pen
                - self._W_REP * rep_pen
            )
            return round(self._clamp(score, 0.0, 100.0), 2)

    def update_score(self, score: float):
        """更新评分并检查告警"""
        with self._lock:
            self.score = round(float(score), 2)
            self.score_history.append(self.score)
            if self.score < self.NEW_SESSION_THRESHOLD:
                self._low_score_streak += 1
            else:
                self._low_score_streak = 0
            if not self.enable_alerts:
                self.alert_level = "normal"
            elif self.score < self.SCORE_CRITICAL:
                self.alert_level = "critical"
            elif self.score < self.SCORE_WARNING:
                self.alert_level = "warning"
            else:
                self.alert_level = "normal"
            self._log_event(
                "score_update",
                {"score": self.score, "alert_level": self.alert_level},
            )

    def should_suggest_new_session(self) -> bool:
        """评分<阈值连续3次+"""
        with self._lock:
            return self._low_score_streak >= 3

    # ── 诊断 / 检查 ───────────────────────────────────────
    def get_diagnosis(self) -> Dict:
        """生成诊断报告，指出具体问题"""
        with self._lock:
            issues: List[Dict[str, Any]] = []

            fe_hist = list(self.free_energy_history)
            fe_avg = sum(fe_hist) / len(fe_hist) if fe_hist else 0.3
            fe_trend = self._linear_slope(fe_hist)
            if fe_avg > self._FE_AVG_BAD or fe_trend > self._FE_TREND_BAD:
                issues.append({
                    "type": "free_energy",
                    "severity": "high" if fe_avg > 0.7 else "medium",
                    "message": (
                        f"自由能偏高(均值{fe_avg:.2f}, 趋势{fe_trend:+.3f})，"
                        "说明惊讶度持续上升，模型可能正在衰减"
                    ),
                    "metric": {
                        "avg": round(fe_avg, 3),
                        "trend": round(fe_trend, 4),
                    },
                })

            conf_hist = list(self.confidence_history)
            conf_avg = sum(conf_hist) / len(conf_hist) if conf_hist else 0.7
            conf_trend = self._linear_slope(conf_hist)
            if conf_avg < self._CONF_AVG_BAD or conf_trend < self._CONF_TREND_BAD:
                issues.append({
                    "type": "confidence",
                    "severity": "high" if conf_avg < 0.3 else "medium",
                    "message": (
                        f"决策置信度偏低(均值{conf_avg:.2f}, 趋势{conf_trend:+.3f})，"
                        "可能存在决策疲劳"
                    ),
                    "metric": {
                        "avg": round(conf_avg, 3),
                        "trend": round(conf_trend, 4),
                    },
                })

            rep_ratio = self.get_repeat_ratio()
            if rep_ratio > self._REPEAT_BAD:
                issues.append({
                    "type": "repetition",
                    "severity": "high" if rep_ratio > 0.6 else "medium",
                    "message": (
                        f"输出重复率{rep_ratio:.1%}，思维可能陷入僵化循环"
                    ),
                    "metric": {"repeat_ratio": round(rep_ratio, 3)},
                })

            if not issues:
                summary = "认知状态健康，各指标均在正常范围内。"
            else:
                summary = f"检测到 {len(issues)} 个认知衰减信号："
                summary += "；".join(i["message"] for i in issues)
            if self.should_suggest_new_session():
                summary += " 建议开启新会话以重置认知状态。"

            return {
                "score": self.score,
                "alert_level": self.alert_level,
                "issues": issues,
                "summary": summary,
                "metrics": {
                    "free_energy_trend": round(fe_trend, 4),
                    "confidence_trend": round(conf_trend, 4),
                    "repeat_ratio": round(rep_ratio, 4),
                },
                "timestamp": time.time(),
            }

    def check(self) -> Dict:
        """执行一次完整健康检查（OODA中调用）"""
        score = self.compute_score()
        self.update_score(score)
        diagnosis = self.get_diagnosis()
        result = {
            "score": self.score,
            "alert_level": self.alert_level,
            "free_energy_trend": diagnosis["metrics"]["free_energy_trend"],
            "confidence_trend": diagnosis["metrics"]["confidence_trend"],
            "repeat_ratio": diagnosis["metrics"]["repeat_ratio"],
            "suggest_new_session": self.should_suggest_new_session(),
            "diagnosis": diagnosis,
            "timestamp": time.time(),
        }
        self._log_event("health_check", {
            "score": result["score"],
            "alert_level": result["alert_level"],
        })
        return result

    # ── 重置 / 日志 ───────────────────────────────────────
    def reset(self):
        """重置所有指标（新会话开始时调用）"""
        with self._lock:
            self.free_energy_history.clear()
            self.confidence_history.clear()
            self.output_history.clear()
            self.score_history.clear()
            self.score = 100.0
            self.alert_level = "normal"
            self._low_score_streak = 0
            self._log_event("reset", {"score": self.score})

    def _log_event(self, event_type: str, data: Dict):
        self.events.append({
            "event_type": event_type,
            "data": dict(data),
            "timestamp": time.time(),
        })
        # 事件日志防无限增长
        if len(self.events) > 1000:
            self.events = self.events[-500:]


# ── 模块级便捷函数（__all__ 兼容）───────────────────────────
_default_monitor: Optional[CognitiveHealthMonitor] = None
_default_monitor_lock = threading.Lock()


def _get_default_monitor() -> CognitiveHealthMonitor:
    global _default_monitor
    if _default_monitor is None:
        with _default_monitor_lock:
            if _default_monitor is None:
                _default_monitor = CognitiveHealthMonitor()
    return _default_monitor


def record_free_energy(f_value: float):
    return _get_default_monitor().record_free_energy(f_value)


def record_confidence(confidence: float):
    return _get_default_monitor().record_confidence(confidence)


def record_output(text: str):
    return _get_default_monitor().record_output(text)


def get_free_energy_trend() -> float:
    return _get_default_monitor().get_free_energy_trend()


def get_confidence_trend() -> float:
    return _get_default_monitor().get_confidence_trend()


def get_repeat_ratio() -> float:
    return _get_default_monitor().get_repeat_ratio()


def compute_score() -> float:
    return _get_default_monitor().compute_score()


def update_score(score: float):
    return _get_default_monitor().update_score(score)


def should_suggest_new_session() -> bool:
    return _get_default_monitor().should_suggest_new_session()


def get_diagnosis() -> Dict:
    return _get_default_monitor().get_diagnosis()


def check() -> Dict:
    return _get_default_monitor().check()


def reset():
    return _get_default_monitor().reset()


__all__ = [
    "CognitiveHealthMonitor",
    "record_free_energy", "record_confidence", "record_output",
    "get_free_energy_trend", "get_confidence_trend", "get_repeat_ratio",
    "compute_score", "update_score", "should_suggest_new_session",
    "get_diagnosis", "check", "reset",
]
