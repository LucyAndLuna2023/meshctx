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
"""
import time
import hashlib
from collections import deque
from typing import Dict, List, Tuple, Optional


class CognitiveHealthMonitor:
    """认知健康监控器 — 主动检测Agent衰减"""

    # 告警阈值
    SCORE_WARNING = 60.0       # 低于此进入警告
    SCORE_CRITICAL = 40.0      # 低于此进入危险
    NEW_SESSION_THRESHOLD = 30.0  # 低于此>3次建议新会话

    def __init__(
        self,
        history_size: int = 50,
        max_score_history: int = 20,
        enable_alerts: bool = True
    ):
        self.history_size = history_size
        self.max_score_history = max_score_history
        self.enable_alerts = enable_alerts

        # 自由能历史 (每个值: float 0-1)
        self.free_energy_history: deque = deque(maxlen=history_size)

        # 决策置信度历史 (每个值: float 0-1)
        self.confidence_history: deque = deque(maxlen=history_size)

        # 输出指纹历史 (用于检测重复)
        self.output_fingerprints: deque = deque(maxlen=history_size)

        # 综合评分历史
        self.score_history: deque = deque(maxlen=max_score_history)

        # 当前评分
        self.score: float = 100.0

        # 告警级别
        self.alert_level: str = "normal"  # normal, warning, critical

        # 连续低分计数器
        self._consecutive_low: int = 0

        # 上次检查时间
        self.last_check: float = time.time()

        # 事件记录
        self.events: List[Dict] = []

    # ── 数据记录 ──────────────────────────────────

    def record_free_energy(self, f_value: float):
        """记录一次自由能值 (0-1, 越高越惊讶→越不健康)"""
        self.free_energy_history.append(max(0.0, min(1.0, f_value)))

    def record_confidence(self, confidence: float):
        """记录一次决策置信度 (0-1, 越高越好)"""
        self.confidence_history.append(max(0.0, min(1.0, confidence)))

    def record_output(self, text: str):
        """记录输出内容（用于检测重复）"""
        fp = hashlib.md5(text[:200].encode()).hexdigest()
        self.output_fingerprints.append(fp)

    # ── 趋势分析 ──────────────────────────────────

    def get_free_energy_trend(self) -> float:
        """
        自由能趋势: 正数=自由能上升(衰减中), 负数=改善
        用简单线性回归估计
        """
        data = list(self.free_energy_history)
        if len(data) < 3:
            return 0.0

        n = len(data)
        x_mean = (n - 1) / 2.0
        y_mean = sum(data) / n

        num = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))

        if den == 0:
            return 0.0

        return num / den * n  # 缩放以反映整个历史窗口的变化

    def get_confidence_trend(self) -> float:
        """置信度趋势: 正数=改善, 负数=衰减"""
        data = list(self.confidence_history)
        if len(data) < 3:
            return 0.0

        n = len(data)
        x_mean = (n - 1) / 2.0
        y_mean = sum(data) / n

        num = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))

        if den == 0:
            return 0.0

        return num / den * n

    def get_repeat_ratio(self) -> float:
        """输出重复率 (0-1)"""
        if len(self.output_fingerprints) < 2:
            return 0.0

        total = len(self.output_fingerprints)
        unique = len(set(self.output_fingerprints))
        return 1.0 - (unique / total)

    # ── 综合评分 ──────────────────────────────────

    def compute_score(self) -> float:
        """
        计算综合健康评分 (0-100)

        指标权重:
        - 自由能趋势: 40% (最重要，上升=核心衰减信号)
        - 置信度趋势: 30%
        - 输出重复率: 20%
        - 自由能绝对值: 10%
        """
        # 1. 自由能趋势评分 (-0.5到+0.5, 映射到0-100)
        fe_trend = self.get_free_energy_trend()
        # 趋势>0.2=很差(<50), 趋势<0=好(>80)
        fe_trend_score = max(0, min(100, 80 - fe_trend * 200))

        # 2. 置信度趋势 (考虑绝对值和趋势)
        conf_trend = self.get_confidence_trend()
        conf_mean = (
            sum(self.confidence_history) / len(self.confidence_history)
            if self.confidence_history else 0.5
        )
        # 基础分来自绝对置信度 (0.5→30, 0.85→68, 1.0→80)
        conf_base = conf_mean * 80
        # 趋势加成
        conf_trend_bonus = conf_trend * 200
        conf_trend_score = max(0, min(100, conf_base + conf_trend_bonus))

        # 3. 重复率
        repeat = self.get_repeat_ratio()
        # 重复率>0.5=差(<40), 0=好(100)
        repeat_score = max(0, min(100, 100 - repeat * 120))

        # 4. 自由能绝对值
        fe_mean = (
            sum(self.free_energy_history) / len(self.free_energy_history)
            if self.free_energy_history else 0.3
        )
        fe_abs_score = max(0, min(100, 100 - fe_mean * 80))

        # 加权总分
        score = (
            fe_trend_score * 0.40 +
            conf_trend_score * 0.30 +
            repeat_score * 0.20 +
            fe_abs_score * 0.10
        )

        return round(score, 1)

    def update_score(self, score: float):
        """更新评分并检查告警"""
        self.score = score
        self.score_history.append(score)

        # 告警级别判断
        old_level = self.alert_level

        if score < self.NEW_SESSION_THRESHOLD:
            self._consecutive_low += 1
        else:
            self._consecutive_low = 0

        if score < self.SCORE_CRITICAL:
            self.alert_level = "critical"
        elif score < self.SCORE_WARNING:
            self.alert_level = "warning"
        else:
            self.alert_level = "normal"

        if old_level != self.alert_level:
            self._log_event(
                "alert_change",
                {"from": old_level, "to": self.alert_level, "score": score}
            )

    def should_suggest_new_session(self) -> bool:
        """评分<阈值连续3次+"""
        return self._consecutive_low >= 3

    # ── 诊断 ──────────────────────────────────────

    def get_diagnosis(self) -> Dict:
        """
        生成诊断报告，指出具体问题

        返回: {"issues": [...], "score": float, "alert": str}
        """
        issues = []

        fe_trend = self.get_free_energy_trend()
        if fe_trend > 0.1:
            issues.append({
                "type": "free_energy",
                "severity": "high" if fe_trend > 0.3 else "medium",
                "message": f"自由能上升趋势({fe_trend:.2f})，Agent正在经历更多惊讶",
                "suggestion": "考虑压缩上下文或减少并发任务"
            })

        conf_trend = self.get_confidence_trend()
        if conf_trend < -0.1:
            issues.append({
                "type": "confidence",
                "severity": "high" if conf_trend < -0.3 else "medium",
                "message": f"决策置信度下降({conf_trend:.2f})，可能出现决策疲劳",
                "suggestion": "考虑切换到更保守的策略或降低任务复杂度"
            })

        repeat = self.get_repeat_ratio()
        if repeat > 0.3:
            issues.append({
                "type": "repeat_output",
                "severity": "high" if repeat > 0.5 else "medium",
                "message": f"输出重复率{repeat:.1%}，思维可能陷入僵化循环",
                "suggestion": "增加随机性参数或切换探索模式"
            })

        return {
            "issues": issues,
            "score": self.score,
            "alert": self.alert_level,
            "free_energy_trend": round(fe_trend, 3),
            "confidence_trend": round(conf_trend, 3),
            "repeat_ratio": round(repeat, 3),
            "consecutive_low": self._consecutive_low,
            "suggest_new_session": self.should_suggest_new_session(),
        }

    # ── 生命周期 ──────────────────────────────────

    def check(self) -> Dict:
        """执行一次完整健康检查（OODA中调用）"""
        score = self.compute_score()
        self.update_score(score)
        self.last_check = time.time()

        diagnosis = self.get_diagnosis()
        if diagnosis["issues"]:
            self._log_event("health_check", diagnosis)

        return diagnosis

    def reset(self):
        """重置所有指标（新会话开始时调用）"""
        self.free_energy_history.clear()
        self.confidence_history.clear()
        self.output_fingerprints.clear()
        self.score_history.clear()
        self.score = 100.0
        self.alert_level = "normal"
        self._consecutive_low = 0
        self.last_check = time.time()

    # ── 内部 ──────────────────────────────────────

    def _log_event(self, event_type: str, data: Dict):
        self.events.append({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })
        # 只保留最近1000条
        if len(self.events) > 1000:
            self.events = self.events[-500:]
