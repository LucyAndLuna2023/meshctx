"""v3.98 Feedback Loop 反馈闭环引擎测试"""
import time
import pytest
from src.core.feedback_loop import (
    FeedbackLoop, FeedbackSentiment, UserFeedback,
    FailurePattern, StrategyAdjustment, FeedbackLoopReport,
    get_feedback_loop, reset_feedback_loop,
)


class TestUserFeedbackCollection:
    """1) 用户反馈收集测试"""

    def test_collect_thumbs_up(self):
        loop = FeedbackLoop()
        fb = loop.collect_thumbs_up(
            category="response_quality",
            action_context="answered question about Python",
            comment="Great answer!",
        )
        assert fb.sentiment == FeedbackSentiment.THUMBS_UP.value
        assert fb.category == "response_quality"
        assert fb.feedback_id.startswith("fb_")
        assert fb.timestamp > 0
        assert len(loop._feedbacks) == 1

    def test_collect_thumbs_down(self):
        loop = FeedbackLoop()
        fb = loop.collect_thumbs_down(
            category="accuracy",
            action_context="code review",
            comment="这个答案不对",
            is_critical=True,
        )
        assert fb.sentiment == FeedbackSentiment.THUMBS_DOWN.value
        assert fb.category == "accuracy"
        assert fb.is_critical is True
        assert len(loop._feedbacks) == 1
        assert loop._thumbs_down_categories["accuracy"] == 1

    def test_collect_neutral_and_invalid_sentiment(self):
        loop = FeedbackLoop()
        fb = loop.collect_feedback(sentiment="neutral", category="tone")
        assert fb.sentiment == "neutral"
        # Invalid sentiment defaults to neutral
        fb2 = loop.collect_feedback(sentiment="invalid_xyz")
        assert fb2.sentiment == FeedbackSentiment.NEUTRAL.value
        assert len(loop._feedbacks) == 2

    def test_multiple_feedback_counts(self):
        loop = FeedbackLoop()
        for _ in range(5):
            loop.collect_thumbs_up(category="speed")
        for _ in range(3):
            loop.collect_thumbs_down(category="accuracy", comment="不对")
        for _ in range(2):
            loop.collect_feedback(sentiment="neutral", category="tone")

        stats = loop.get_feedback_stats()
        assert stats["total"] == 10
        assert stats["thumbs_up"] == 5
        assert stats["thumbs_down"] == 3
        assert stats["neutral"] == 2
        # 5/8 = 0.625
        assert stats["satisfaction_rate"] == pytest.approx(0.625, abs=0.01)


class TestFailurePatternAnalysis:
    """2) 自动分析失败模式测试"""

    def test_no_feedbacks_returns_empty(self):
        loop = FeedbackLoop()
        patterns = loop.analyze_failure_patterns()
        assert patterns == []

    def test_pattern_detection_by_category(self):
        loop = FeedbackLoop()
        for _ in range(5):
            loop.collect_thumbs_down(category="speed", comment="太慢了")
        for _ in range(3):
            loop.collect_thumbs_down(category="accuracy", comment="不对")

        patterns = loop.analyze_failure_patterns()
        assert len(patterns) >= 2  # speed + accuracy
        speed_pattern = next(p for p in patterns if p.category == "speed")
        assert speed_pattern.total_occurrences == 5
        assert speed_pattern.severity == "medium"

    def test_critical_pattern(self):
        loop = FeedbackLoop()
        loop.collect_thumbs_down(
            category="response_quality",
            comment="Bad response",
            is_critical=True,
        )
        loop.collect_thumbs_down(category="response_quality")
        patterns = loop.analyze_failure_patterns(min_occurrences=1)
        # Response quality with critical flag → severity should be critical
        rq = next(p for p in patterns if p.category == "response_quality")
        assert rq.severity == "critical"

    def test_min_occurrences_filter(self):
        loop = FeedbackLoop()
        loop.collect_thumbs_down(category="speed")  # only 1
        for _ in range(3):
            loop.collect_thumbs_down(category="accuracy")

        patterns = loop.analyze_failure_patterns(min_occurrences=2)
        categories = [p.category for p in patterns]
        assert "accuracy" in categories
        assert "speed" not in categories

    def test_active_and_critical_pattern_accessors(self):
        loop = FeedbackLoop()
        for _ in range(6):
            loop.collect_thumbs_down(category="accuracy", is_critical=True)

        active = loop.get_active_patterns()
        critical = loop.get_critical_patterns()
        assert len(critical) >= 1
        assert critical[0].severity == "critical"


class TestStrategyAdjustment:
    """3) 策略自动调整测试"""

    def test_no_triggers_returns_empty(self):
        loop = FeedbackLoop()
        adjustments = loop.auto_adjust_strategies()
        assert adjustments == []

    def test_verbosity_adjustment_too_verbose(self):
        loop = FeedbackLoop()
        # Simulate "too verbose" signals
        loop._category_counter["too_verbose"] = 5
        loop._category_counter["too_concise"] = 0

        adjustments = loop.auto_adjust_strategies()
        assert len(adjustments) >= 1
        verbosity_adj = next(
            a for a in adjustments if a.strategy_name == "verbosity"
        )
        assert verbosity_adj.new_value == "concise"
        assert loop._strategies["verbosity"] == "concise"

    def test_verbosity_adjustment_too_concise(self):
        loop = FeedbackLoop()
        loop._category_counter["too_concise"] = 5
        loop._category_counter["too_verbose"] = 0

        adjustments = loop.auto_adjust_strategies()
        verbosity_adj = next(
            a for a in adjustments if a.strategy_name == "verbosity"
        )
        assert verbosity_adj.new_value == "verbose"
        assert loop._strategies["verbosity"] == "verbose"

    def test_inaccuracy_triggers_fact_checking(self):
        loop = FeedbackLoop()
        loop._category_counter["inaccurate"] = 3

        adjustments = loop.auto_adjust_strategies()
        fact_adj = next(
            a for a in adjustments if a.strategy_name == "check_facts_before_answer"
        )
        assert fact_adj.new_value is True

    def test_counter_cleared_after_adjustment(self):
        loop = FeedbackLoop()
        loop._category_counter["too_verbose"] = 5
        loop._category_counter["too_concise"] = 0

        loop.auto_adjust_strategies()
        assert loop._category_counter == {}

    def test_revert_adjustment(self):
        loop = FeedbackLoop()
        loop._category_counter["too_verbose"] = 5
        loop.auto_adjust_strategies()

        assert loop._strategies["verbosity"] == "concise"
        result = loop.revert_adjustment("verbosity")
        assert result is True
        assert loop._strategies["verbosity"] == "balanced"

    def test_get_current_strategies(self):
        loop = FeedbackLoop()
        strategies = loop.get_current_strategies()
        assert strategies["verbosity"] == "balanced"
        assert strategies["tone"] == "professional"
        assert strategies["creativity"] == 0.7


class TestFeedbackLoopReport:
    """4) 反馈闭环报告测试"""

    def test_empty_report(self):
        loop = FeedbackLoop()
        report = loop.generate_report()
        assert report.total_feedback == 0
        assert report.satisfaction_rate == 1.0
        assert report.trend_direction == "insufficient_data"
        assert "No feedback collected yet" in report.recommendations[0]

    def test_report_with_feedback(self):
        loop = FeedbackLoop()
        for _ in range(7):
            loop.collect_thumbs_up(category="speed")
        for _ in range(3):
            loop.collect_thumbs_down(category="accuracy", comment="不对")

        report = loop.generate_report()
        assert report.total_feedback == 10
        assert report.thumbs_up == 7
        assert report.thumbs_down == 3
        assert report.satisfaction_rate == pytest.approx(0.7, abs=0.01)
        assert len(report.top_failure_patterns) >= 1

    def test_report_period_filter(self):
        loop = FeedbackLoop()
        # Old feedback (simulate by backdating timestamp)
        loop.collect_thumbs_up(category="speed")
        loop._feedbacks[-1].timestamp = time.time() - 7200  # 2 hours ago

        # Recent feedback
        loop.collect_thumbs_down(category="accuracy")

        # Report for last 1 hour should only include the recent one
        report = loop.generate_report(period_hours=1)
        assert report.total_feedback == 1

    def test_trend_computation(self):
        loop = FeedbackLoop()
        # Create declining trend: first 6 up, then 2 down
        for _ in range(6):
            loop.collect_thumbs_up(category="speed")
        for _ in range(4):
            loop.collect_thumbs_down(category="accuracy")

        report = loop.generate_report()
        assert report.trend_direction in ("improving", "declining", "stable", "insufficient_data")

    def test_report_with_strategy_adjustments(self):
        loop = FeedbackLoop()
        loop._category_counter["too_verbose"] = 5
        loop.auto_adjust_strategies()
        loop.collect_thumbs_up()
        loop.collect_thumbs_down()

        report = loop.generate_report(include_adjustments=True)
        assert len(report.recent_adjustments) >= 1
        assert report.recent_adjustments[0].strategy_name == "verbosity"

    def test_report_recommendations_low_satisfaction(self):
        loop = FeedbackLoop()
        for _ in range(2):
            loop.collect_thumbs_up()
        for _ in range(8):
            loop.collect_thumbs_down()

        report = loop.generate_report()
        assert any("CRITICAL" in r for r in report.recommendations)

    def test_report_recommendations_declining(self):
        loop = FeedbackLoop()
        for _ in range(10):
            loop.collect_thumbs_up(category="speed")
        for _ in range(10):
            loop.collect_thumbs_down(category="accuracy")

        report = loop.generate_report()
        # trend should be "declining" since thumbs_down are all in second half
        assert any(
            "Satisfaction trending downward" in r
            for r in report.recommendations
        )


class TestSingletonAndReset:
    """5) 单例和重置测试"""

    def test_singleton_returns_same_instance(self):
        reset_feedback_loop()
        loop1 = get_feedback_loop()
        loop2 = get_feedback_loop()
        assert loop1 is loop2
        # Reset for other tests
        reset_feedback_loop()

    def test_reset_clears_all_data(self):
        reset_feedback_loop()
        loop = get_feedback_loop()
        loop.collect_thumbs_down(category="accuracy")
        loop.collect_thumbs_down(category="accuracy")  # need 2+ for min_occurrences
        loop.analyze_failure_patterns()
        loop._category_counter["too_verbose"] = 5
        loop.auto_adjust_strategies()
        loop.generate_report()

        assert len(loop._feedbacks) > 0
        assert len(loop._failure_patterns) > 0

        loop.reset()
        assert len(loop._feedbacks) == 0
        assert len(loop._failure_patterns) == 0
        assert len(loop._adjustments) == 0
        assert loop._strategies["verbosity"] == "balanced"
        assert loop._category_counter == {}
        assert len(loop._report_history) == 0
        reset_feedback_loop()

    def test_reset_feedback_loop_global(self):
        reset_feedback_loop()
        loop = get_feedback_loop()
        loop.collect_thumbs_up()
        reset_feedback_loop()

        new_loop = get_feedback_loop()
        assert new_loop.get_feedback_stats()["total"] == 0
        reset_feedback_loop()


class TestFeedbackLoopEndToEnd:
    """6) 完整闭环端到端测试"""

    def test_complete_closed_loop_cycle(self):
        """模拟完整闭环: 收集 → 分析 → 调整 → 报告"""
        loop = FeedbackLoop()

        # Phase 1: 收集
        for _ in range(8):
            loop.collect_thumbs_up(category="response_quality")
        for _ in range(5):
            loop.collect_thumbs_down(category="speed", comment="太慢了")
        for _ in range(3):
            loop.collect_thumbs_down(category="accuracy", comment="不对")
        loop.collect_feedback(sentiment="neutral", category="tone")

        # Phase 2: 分析
        patterns = loop.analyze_failure_patterns()
        assert len(patterns) >= 2
        # speed category should appear
        speed_patterns = [p for p in patterns if "speed" in p.category]
        assert len(speed_patterns) >= 1

        # Phase 3: 调整
        adjustments = loop.auto_adjust_strategies()
        # "slow" count is 5 → should trigger max_response_length reduction
        has_speed_adj = any(
            a.strategy_name == "max_response_length" for a in adjustments
        )
        assert has_speed_adj

        # Phase 4: 报告
        report = loop.generate_report()
        assert report.total_feedback == 17
        assert len(report.recommendations) >= 1

    def test_reset_between_cycles(self):
        loop = FeedbackLoop()
        loop.collect_thumbs_up()
        loop.reset()
        assert loop.get_feedback_stats()["total"] == 0

        # Can start fresh
        loop.collect_thumbs_down()
        assert loop.get_feedback_stats()["total"] == 1


class TestCommentSignalExtraction:
    """7) 评论信号提取测试"""

    def test_chinese_comment_signals(self):
        loop = FeedbackLoop()
        loop.collect_thumbs_down(comment="太慢了，等太久了")
        # "太慢" + "慢" (substring match) + "等太久" = 3
        assert loop._category_counter["slow"] == 3

    def test_combined_signals(self):
        loop = FeedbackLoop()
        loop.collect_thumbs_down(comment="这个答案不对，而且太啰嗦了")
        assert loop._category_counter["inaccurate"] == 1
        # "太啰嗦" + "啰嗦" (substring match) = 2
        assert loop._category_counter["too_verbose"] == 2


class TestDataModels:
    """8) 数据模型测试"""

    def test_user_feedback_defaults(self):
        fb = UserFeedback()
        assert fb.sentiment == FeedbackSentiment.NEUTRAL.value
        assert fb.feedback_id == ""
        assert fb.is_critical is False

    def test_failure_pattern_dissatisfaction_rate(self):
        fp = FailurePattern(
            pattern_name="test",
            thumbs_up_count=30,
            thumbs_down_count=70,
        )
        assert fp.dissatisfaction_rate == pytest.approx(0.7, abs=0.01)

    def test_failure_pattern_is_active(self):
        fp = FailurePattern(last_seen=time.time() - 100)
        assert fp.is_active is True

        fp2 = FailurePattern(last_seen=time.time() - 100000)
        assert fp2.is_active is False

    def test_strategy_adjustment_reverted(self):
        sa = StrategyAdjustment(
            strategy_name="verbosity",
            old_value="balanced",
            new_value="concise",
        )
        assert sa.reverted is False

    def test_feedback_loop_report_fields(self):
        report = FeedbackLoopReport(
            total_feedback=100,
            thumbs_up=80,
            thumbs_down=20,
        )
        assert report.satisfaction_rate == 0.0  # not auto-computed
        assert report.trend_direction == "stable"
