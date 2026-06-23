"""
v3.50 Feedback Loop Engine — 测试
覆盖: 记录/画像/分析/自适应/重试判断/超时优化/完整管道
"""
import pytest
import time
from src.core.feedback_loop import (
    FeedbackLoopEngine, ExecutionRecord, ActionProfile,
    AdaptiveConfig, AutonomousPipeline, FeedbackPhase,
    get_feedback_engine,
)


class TestExecutionRecord:
    """执行记录"""

    def test_create(self):
        r = ExecutionRecord(action_name="test", status="success")
        assert r.action_name == "test"
        assert r.status == "success"
        assert r.error_type == ""  # default, set by record() not constructor

    def test_error_classification_timeout(self):
        r = ExecutionRecord(action_name="slow", status="failed",
                           error_type="TIMEOUT")
        assert r.error_type == "TIMEOUT"


class TestActionProfile:
    """操作画像"""

    def test_success_rate(self):
        p = ActionProfile(name="test")
        p.total = 10
        p.success = 8
        p.failed = 2
        assert p.success_rate == 0.8

    def test_success_rate_empty(self):
        p = ActionProfile(name="empty")
        assert p.success_rate == 1.0

    def test_is_reliable(self):
        p = ActionProfile(name="reliable")
        p.total = 5
        p.success = 5
        p.consecutive_failure = 0
        assert p.is_reliable

    def test_is_not_reliable(self):
        p = ActionProfile(name="unreliable")
        p.total = 5
        p.success = 2
        p.consecutive_failure = 1
        assert not p.is_reliable

    def test_not_reliable_insufficient_data(self):
        p = ActionProfile(name="new")
        p.total = 1
        p.success = 1
        assert not p.is_reliable  # Need >= 3 samples


class TestFeedbackEngine:
    """反馈引擎"""

    def test_init(self):
        engine = FeedbackLoopEngine()
        assert len(engine._records) == 0
        assert len(engine._profiles) == 0

    def test_record_success(self):
        engine = FeedbackLoopEngine()
        result = {"name": "echo", "command": "echo hello", "risk": 0,
                   "status": "success", "exit_code": 0, "output": "hello", "error": "",
                   "duration_ms": 100}
        record = engine.record(result)
        assert record.action_name == "echo"
        assert record.status == "success"
        assert record.error_type == "NONE"
        assert len(engine._records) == 1

    def test_record_failure(self):
        engine = FeedbackLoopEngine()
        result = {"name": "fail", "command": "exit 1", "risk": 1,
                   "status": "failed", "exit_code": 1, "output": "", "error": "command failed",
                   "duration_ms": 50}
        record = engine.record(result)
        assert record.status == "failed"
        assert record.error_type != "NONE"

    def test_record_timeout(self):
        engine = FeedbackLoopEngine()
        result = {"name": "slow", "command": "sleep", "risk": 0,
                   "status": "failed", "exit_code": -1, "output": "", 
                   "error": "TIMEOUT after 30s", "duration_ms": 30000}
        record = engine.record(result)
        assert record.error_type == "TIMEOUT"

    def test_profile_update(self):
        engine = FeedbackLoopEngine()
        for i in range(5):
            engine.record({"name": "echo", "command": "echo", "risk": 0,
                          "status": "success", "exit_code": 0, "output": "ok",
                          "error": "", "duration_ms": 100})
        
        profile = engine._profiles.get("echo")
        assert profile is not None
        assert profile.total == 5
        assert profile.success == 5
        assert profile.success_rate == 1.0
        assert profile.is_reliable

    def test_profile_consecutive_tracking(self):
        engine = FeedbackLoopEngine()
        # 3 success, 2 fail
        for status in ["success", "success", "failed", "failed", "success"]:
            engine.record({"name": "mixed", "command": "cmd", "risk": 0,
                          "status": status, "exit_code": 0 if status == "success" else 1,
                          "output": "", "error": "", "duration_ms": 50})
        
        profile = engine._profiles["mixed"]
        assert profile.consecutive_success == 1  # Last was success
        assert profile.total == 5
        assert profile.success == 3
        assert profile.failed == 2

    def test_analyze_empty(self):
        engine = FeedbackLoopEngine()
        result = engine.analyze()
        assert result["status"] == "no_data"

    def test_analyze_with_data(self):
        engine = FeedbackLoopEngine()
        for i in range(10):
            engine.record({"name": "test", "command": "cmd", "risk": 0,
                          "status": "success" if i < 8 else "failed",
                          "exit_code": 0 if i < 8 else 1,
                          "output": "", "error": "", "duration_ms": 50})
        
        analysis = engine.analyze()
        assert analysis["total_records"] == 10
        assert "80.0%" in analysis["success_rate"]

    def test_adapt(self):
        engine = FeedbackLoopEngine()
        for i in range(5):
            engine.record({"name": "echo", "command": "echo", "risk": 0,
                          "status": "success", "exit_code": 0,
                          "output": "", "error": "", "duration_ms": 50})
        
        result = engine.adapt()
        assert "changes" in result
        assert "current" in result

    def test_should_retry(self):
        engine = FeedbackLoopEngine()
        engine.record({"name": "flakey", "command": "cmd", "risk": 0,
                       "status": "failed", "exit_code": 1,
                       "output": "", "error": "", "duration_ms": 50})
        
        # 刚失败→不应立即重试(cooldown)
        should, delay = engine.should_retry("flakey")
        assert not should  # cooldown active

    def test_get_optimal_timeout(self):
        engine = FeedbackLoopEngine()
        for i in range(3):
            engine.record({"name": "test", "command": "cmd", "risk": 0,
                          "status": "success", "exit_code": 0,
                          "output": "", "error": "", "duration_ms": 5000})
        
        timeout = engine.get_optimal_timeout("test")
        assert 10 <= timeout <= 120

    def test_get_optimal_timeout_new_action(self):
        engine = FeedbackLoopEngine()
        timeout = engine.get_optimal_timeout("never_seen")
        assert timeout == 30  # default

    def test_generate_report(self):
        engine = FeedbackLoopEngine()
        for i in range(10):
            engine.record({"name": "echo", "command": "echo", "risk": 0,
                          "status": "success" if i < 9 else "failed",
                          "exit_code": 0 if i < 9 else 1,
                          "output": "ok", "error": "", "duration_ms": 50})
        
        report = engine.generate_report()
        assert "analysis" in report
        assert "recommendations" in report
        assert "top_actions" in report
        assert len(report["top_actions"]) > 0

    def test_recommendations_reliable(self):
        engine = FeedbackLoopEngine()
        for i in range(5):
            engine.record({"name": "echo", "command": "echo", "risk": 0,
                          "status": "success", "exit_code": 0,
                          "output": "", "error": "", "duration_ms": 50})
        
        report = engine.generate_report()
        recommendations = report["recommendations"]
        assert any("Auto-approve" in r for r in recommendations)

    def test_get_stats(self):
        engine = FeedbackLoopEngine()
        engine.record({"name": "test", "command": "cmd", "risk": 0,
                       "status": "success", "exit_code": 0,
                       "output": "", "error": "", "duration_ms": 50})
        
        stats = engine.get_stats()
        assert stats["total_records"] == 1
        assert "config" in stats

    def test_record_batch(self):
        engine = FeedbackLoopEngine()
        results = [
            {"name": "a", "command": "a", "status": "success", "exit_code": 0, "risk": 0, "output": "", "error": "", "duration_ms": 10},
            {"name": "b", "command": "b", "status": "failed", "exit_code": 1, "risk": 1, "output": "", "error": "err", "duration_ms": 20},
            {"name": "a", "command": "a", "status": "success", "exit_code": 0, "risk": 0, "output": "", "error": "", "duration_ms": 15},
        ]
        for r in results:
            engine.record(r)
        
        assert len(engine._records) == 3
        assert len(engine._profiles) == 2
        assert engine._profiles["a"].total == 2
        assert engine._profiles["b"].total == 1

    def test_singleton(self):
        e1 = get_feedback_engine()
        e2 = get_feedback_engine()
        assert e1 is e2


class TestAdaptiveConfig:
    """自适应配置"""

    def test_defaults(self):
        config = AdaptiveConfig()
        assert config.default_timeout == 30
        assert config.max_retries == 2

    def test_adapt_reliable(self):
        config = AdaptiveConfig()
        profiles = {
            "a": ActionProfile(name="a", total=5, success=5, failed=0),
            "b": ActionProfile(name="b", total=5, success=5, failed=0),
        }
        old = config.auto_approve_threshold
        config.adapt_from_profile(profiles)
        assert config.auto_approve_threshold <= old

    def test_adapt_problematic(self):
        config = AdaptiveConfig()
        profiles = {
            "c": ActionProfile(name="c", total=5, success=1, failed=4, 
                              consecutive_failure=3, timeout_count=4),
        }
        config.adapt_from_profile(profiles)
        # 高失败→应提高门槛
        assert config.auto_approve_threshold >= 0.8


class TestAutonomousPipeline:
    """完整管道测试"""

    @pytest.mark.asyncio
    async def test_cycle_no_observer(self):
        pipeline = AutonomousPipeline()
        result = await pipeline.cycle()
        assert result["nudges"] == 0
        assert result["actions"] == 0

    def test_record_from_dict(self):
        engine = FeedbackLoopEngine()
        # Simulate action engine result
        result = {"name": "test_action", "command": "echo test", "risk": 0,
                   "status": "success", "exit_code": 0, 
                   "output": "test", "error": "", "duration_ms": 150}
        engine.record(result)
        assert len(engine._records) == 1
        profile = engine._profiles["test_action"]
        assert profile.total == 1
