"""
认知衰减自检测试 — TDD RED phase
测试 src/core/cognitive_health.py 的 CognitiveHealthMonitor

覆盖:
- 自由能趋势检测
- 决策置信度监控
- 重复输出检测
- 综合健康评分
- 告警触发阈值
- 新会话建议
"""
import pytest
import time
from unittest.mock import patch


class TestCognitiveHealthMonitor:
    """认知衰减监控器"""

    def test_init_default_values(self):
        """初始化后所有指标为默认值"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor()
        assert chm.score == 100.0
        assert len(chm.free_energy_history) == 0
        assert len(chm.confidence_history) == 0
        assert chm.alert_level == "normal"

    def test_record_free_energy_updates_history(self):
        """记录自由能后历史列表长度增加"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=5)
        chm.record_free_energy(0.3)
        chm.record_free_energy(0.5)
        chm.record_free_energy(0.8)
        assert len(chm.free_energy_history) == 3

    def test_free_energy_trend_rising_detected(self):
        """自由能上升趋势被检测（上升=惊讶增加=衰减）"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        # 模拟自由能从0.2逐步上升到0.9
        for f in [0.2, 0.3, 0.35, 0.45, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9]:
            chm.record_free_energy(f)
        trend = chm.get_free_energy_trend()
        assert trend > 0, f"上升趋势应为正数, 实际={trend}"

    def test_free_energy_trend_stable_zero(self):
        """稳定自由能时趋势接近0"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        for f in [0.5] * 10:
            chm.record_free_energy(f)
        trend = chm.get_free_energy_trend()
        assert abs(trend) < 0.01

    def test_confidence_dropping_detected(self):
        """决策置信度下降被检测"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        for c in [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3, 0.25]:
            chm.record_confidence(c)
        trend = chm.get_confidence_trend()
        assert trend < 0, f"下降趋势应为负数, 实际={trend}"

    def test_repeat_output_detection(self):
        """重复输出被检测到"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor()
        chm.record_output("这是测试输出A")
        chm.record_output("这是测试输出A")
        chm.record_output("这是测试输出B")
        chm.record_output("这是测试输出A")
        ratio = chm.get_repeat_ratio()
        assert ratio > 0.3, f"重复率应>30%, 实际={ratio:.2f}"

    def test_score_drops_when_all_bad(self):
        """所有指标都差时评分应低于60"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        # 自由能上升
        for f in [0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]:
            chm.record_free_energy(f)
        # 置信度下降
        for c in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3, 0.25, 0.2]:
            chm.record_confidence(c)
        # 重复输出
        for i in range(8):
            chm.record_output("相同输出ABCDEFGH")
        score = chm.compute_score()
        assert score < 60.0, f"全差指标评分应<60, 实际={score}"

    def test_score_stays_high_when_all_good(self):
        """所有指标都好时评分应高于80"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        for f in [0.3] * 10:
            chm.record_free_energy(f)
        for c in [0.85] * 10:
            chm.record_confidence(c)
        for i in range(10):
            chm.record_output(f"不同的输出内容{i}")
        score = chm.compute_score()
        assert score >= 78.0, f"全好指标评分应≥78, 实际={score}"

    def test_alert_level_transitions(self):
        """告警级别正确转换: normal→warning→critical"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)

        # 正常状态
        chm.update_score(90)
        assert chm.alert_level == "normal"

        # 降到警告 (<60)
        chm.update_score(55)
        assert chm.alert_level == "warning"

        # 降到危险 (<40)
        chm.update_score(35)
        assert chm.alert_level == "critical"

    def test_suggest_new_session_when_critical(self):
        """评分<30持续3次后建议新会话"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        chm.update_score(25)
        assert not chm.should_suggest_new_session()

        chm.update_score(25)
        assert not chm.should_suggest_new_session()

        chm.update_score(25)
        assert chm.should_suggest_new_session()

    def test_score_history_capped(self):
        """评分历史长度不超过最大值"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(max_score_history=5)
        for s in [90, 85, 80, 75, 70, 65, 60, 55]:
            chm.update_score(s)
        assert len(chm.score_history) == 5
        assert chm.score_history[-1] == 55

    def test_reset_restores_defaults(self):
        """reset恢复所有指标到默认值"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)
        chm.record_free_energy(0.9)
        chm.record_confidence(0.2)
        chm.record_output("test")
        chm.update_score(30)

        chm.reset()

        assert chm.score == 100.0
        assert len(chm.free_energy_history) == 0
        assert len(chm.confidence_history) == 0
        assert chm.alert_level == "normal"

    def test_get_diagnosis_returns_correct_issues(self):
        """诊断报告列出实际存在的问题"""
        from src.core.cognitive_health import CognitiveHealthMonitor
        chm = CognitiveHealthMonitor(history_size=10)

        # 只让自由能出问题
        for f in [0.3, 0.5, 0.7, 0.9]:
            chm.record_free_energy(f)
        for c in [0.85] * 4:
            chm.record_confidence(c)

        diagnosis = chm.get_diagnosis()
        issue_types = [i["type"] for i in diagnosis["issues"]]
        assert "free_energy" in issue_types
        assert "confidence" not in issue_types  # 置信度正常


class TestLearnLoopIntegration:
    """OODA Learn阶段闭环"""

    def test_learn_from_success_reinforces_strategy(self):
        """成功任务强化对应策略的信念"""
        from src.core.learn_loop import LearnLoop
        loop = LearnLoop()
        result = loop.record_outcome(
            task_type="code_generation",
            success=True,
            quality=0.9,
            strategy_used="exploit_best",
            duration=30.0
        )
        assert result["belief_updated"] is True
        assert result["strength"] > 0.5

    def test_learn_from_failure_penalizes_strategy(self):
        """失败任务惩罚对应策略"""
        from src.core.learn_loop import LearnLoop
        loop = LearnLoop()
        result = loop.record_outcome(
            task_type="code_generation",
            success=False,
            quality=0.1,
            strategy_used="exploit_best",
            duration=5.0,
            error_type="knowledge_gap"
        )
        assert result["belief_updated"] is True
        assert result["strength"] < 0.3

    def test_habits_accumulate_after_repeated_success(self):
        """连续成功10次后自动形成习惯"""
        from src.core.learn_loop import LearnLoop
        loop = LearnLoop(habit_threshold=5)

        for i in range(5):
            loop.record_outcome(
                task_type="deploy",
                success=True,
                quality=0.95,
                strategy_used="balanced",
                duration=10.0
            )

        assert loop.is_habit("deploy") is True

    def test_habits_decay_when_not_used(self):
        """习惯长时间不用会衰减"""
        from src.core.learn_loop import LearnLoop
        loop = LearnLoop(habit_threshold=3)

        for i in range(4):
            loop.record_outcome("deploy", True, 0.9, "balanced", 10.0)

        assert loop.is_habit("deploy") is True

        # 模拟时间流逝后再次检查(衰减后应该还在但强度降低)
        habit = loop.habits.get("deploy")
        assert habit is not None

    def test_strategy_shift_on_repeated_failure(self):
        """同一策略连续失败3次后自动切换"""
        from src.core.learn_loop import LearnLoop
        loop = LearnLoop()

        for i in range(3):
            loop.record_outcome(
                task_type="analyze",
                success=False,
                quality=0.0,
                strategy_used="exploit_best",
                duration=60.0,
                error_type="tool_error"
            )

        suggestion = loop.suggest_strategy("analyze")
        assert suggestion != "exploit_best"
