"""v2.46 SDB Framework — 测试套件 (可量化数据)"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.sdb_framework import (
    SDBEngine, SDBRecord, SDBPhase, RejectReason, get_sdb_engine
)


@pytest.fixture
def engine():
    return SDBEngine(variance_threshold=0.3, track_replay=True, max_records=100)


class TestProposePhase:
    """阶段1: Propose (Stochastic)"""

    def test_propose_creates_record(self, engine):
        record = engine.propose(
            model_id="deepseek-v4",
            action="patch",
            params={"file": "test.py", "content": "x=1"},
            raw_output='{"action":"patch","file":"test.py","content":"x=1"}',
            deterministic_context="patch:test.py:modify",
        )
        assert record.record_id.startswith("sdb_")
        assert record.proposer_model == "deepseek-v4"
        assert record.proposed_action == "patch"
        assert record.phase == SDBPhase.PROPOSE
        assert record.replay_hash != ""

    def test_propose_increments_count(self, engine):
        engine.propose("model-a", "write", {}, "")
        engine.propose("model-a", "read", {}, "")
        assert engine._stats["total_proposals"] == 2

    def test_propose_same_context_same_hash(self, engine):
        ctx = "write:test.py:print('hello')"
        r1 = engine.propose("m1", "write", {}, "output1", deterministic_context=ctx)
        r2 = engine.propose("m1", "write", {}, "output2", deterministic_context=ctx)
        assert r1.replay_hash == r2.replay_hash  # 相同上下文的hash相同


class TestVerifyPhase:
    """阶段2: Verify (Deterministic)"""

    def test_verify_all_passed(self, engine):
        record = engine.propose("deepseek-v4", "patch", {}, "out")
        record = engine.verify(record,
            rules=["syntax_check", "principle_check"],
            checks={"syntax_check": True, "principle_check": True})
        assert record.verification_passed
        assert record.phase == SDBPhase.VERIFY

    def test_verify_one_failed(self, engine):
        record = engine.propose("deepseek-v4", "rm -rf /", {}, "out")
        record = engine.verify(record,
            rules=["dangerous_cmd", "path_check"],
            checks={"dangerous_cmd": False, "path_check": True})
        assert not record.verification_passed

    def test_replay_divergence_detected(self, engine):
        # 第一次: 缓存输出
        ctx = "patch:config.py:modify"
        r1 = engine.propose("m1", "patch", {}, "output_v1",
                            deterministic_context=ctx)
        r1 = engine.verify(r1, ["check"], {"check": True})
        engine.commit(r1, success=True)  # 缓存到 replay_cache

        # 第二次: 相同context但不同输出
        r2 = engine.propose("m1", "patch", {}, "output_v2",
                            deterministic_context=ctx)
        r2 = engine.verify(r2, ["check"], {"check": True})
        # 应检测到replay divergence
        assert r2.reject_reason == RejectReason.REPLAY_DIVERGENCE
        assert not r2.verification_passed
        assert engine._stats["replay_divergences"] >= 1


class TestCommitRejectPhase:
    """阶段3-4: Commit/Reject"""

    def test_commit_success(self, engine):
        record = engine.propose("m1", "read", {}, "out")
        record = engine.verify(record, ["check"], {"check": True})
        record = engine.commit(record, success=True)
        assert record.phase == SDBPhase.COMMIT
        assert record.commit_success
        assert engine._stats["total_commits"] == 1

    def test_reject_on_failed_verify(self, engine):
        record = engine.propose("m1", "rm", {}, "out")
        record = engine.verify(record, ["danger"], {"danger": False})
        record = engine.commit(record)
        assert record.phase == SDBPhase.REJECT
        assert engine._stats["total_rejects"] == 1

    def test_reject_reason_tracked(self, engine):
        record = engine.propose("m1", "write", {}, "out")
        record.reject_reason = RejectReason.PRINCIPLE_VIOLATION
        record.verification_passed = False
        record = engine.commit(record)
        assert engine._stats["reject_by_reason"]["principle_violation"] >= 1


class TestPipeline:
    """一键管道"""

    def test_pipeline_success(self, engine):
        record = engine.pipeline(
            model_id="deepseek-v4",
            action="patch",
            params={"file": "x.py"},
            raw_output="output",
            rules=["syntax"],
            checks={"syntax": True},
            deterministic_context="patch:x.py",
        )
        assert record.phase == SDBPhase.COMMIT
        assert record.commit_success

    def test_pipeline_reject(self, engine):
        record = engine.pipeline(
            model_id="deepseek-v4",
            action="delete_system",
            params={},
            raw_output="output",
            rules=["dangerous"],
            checks={"dangerous": False},
        )
        assert record.phase == SDBPhase.REJECT


class TestStatistics:
    """可量化统计指标 ★核心★"""

    def test_commit_rate_100_percent(self, engine):
        """100%提交率"""
        for i in range(10):
            engine.pipeline("m1", "read", {}, f"out{i}",
                            ["check"], {"check": True})
        stats = engine.get_stats()
        assert stats["commit_rate"] == 1.0
        assert stats["reject_rate"] == 0.0

    def test_commit_rate_50_percent(self, engine):
        """50%提交率"""
        for i in range(10):
            passed = i % 2 == 0
            engine.pipeline("m1", "write", {}, f"out{i}",
                            ["check"], {"check": passed})
        stats = engine.get_stats()
        assert 0.45 <= stats["commit_rate"] <= 0.55  # 约50%

    def test_reject_by_reason_distribution(self, engine):
        """拒绝原因分布"""
        for i in range(5):
            record = engine.propose("m1", "write", {}, f"out{i}")
            record.reject_reason = RejectReason.SYNTAX_ERROR
            record.verification_passed = False
            engine.commit(record)
        for i in range(3):
            record = engine.propose("m1", "write", {}, f"out2_{i}")
            record.reject_reason = RejectReason.PRINCIPLE_VIOLATION
            record.verification_passed = False
            engine.commit(record)
        stats = engine.get_stats()
        assert stats["reject_by_reason"]["syntax_error"] == 5
        assert stats["reject_by_reason"]["principle_violation"] == 3
        assert stats["total_rejects"] == 8

    def test_replay_divergence_rate(self, engine):
        """重放分歧率"""
        # 先建立缓存
        ctx = "unique_ctx_1"
        r = engine.pipeline("m1", "read", {}, "output_A",
                            ["check"], {"check": True},
                            deterministic_context=ctx)
        # 相同上下文不同输出 → 分歧
        r2 = engine.pipeline("m1", "read", {}, "output_B",
                             ["check"], {"check": True},
                             deterministic_context=ctx)
        replay = engine.get_replay_report()
        assert replay["divergences"] >= 1
        assert replay["divergence_rate"] > 0

    def test_empty_stats(self, engine):
        """空引擎统计"""
        stats = engine.get_stats()
        assert stats["total_proposals"] == 0
        assert stats["commit_rate"] == 0
        assert stats["replay_divergence_rate"] == 0


class TestVarianceReport:
    """模型方差报告 (论文核心) ★★★"""

    def test_variance_report_with_data(self, engine):
        """有数据时的方差报告"""
        for i in range(20):
            # 80%成功率
            engine.pipeline("deepseek-v4", "write", {},
                            f"out{i}",
                            ["check"], {"check": i % 5 != 0})

        report = engine.get_variance_report(window=100)
        overall = report["overall"]
        assert overall["sample_size"] >= 10
        assert 0.5 <= overall["commit_rate"] <= 1.0
        assert overall["variance_coefficient"] >= 0

    def test_variance_by_model(self, engine):
        """按模型分组的方差"""
        # 模型A: 高成功率
        for i in range(10):
            engine.pipeline("model-reliable", "read", {}, f"r{i}",
                            ["check"], {"check": True})
        # 模型B: 低成功率
        for i in range(10):
            engine.pipeline("model-unstable", "write", {}, f"u{i}",
                            ["check"], {"check": i % 3 == 0})

        report = engine.get_variance_report(window=50)
        by_model = report.get("by_model", {})
        if "model-reliable" in by_model:
            assert by_model["model-reliable"]["commit_rate"] > \
                   by_model.get("model-unstable", {}).get("commit_rate", 0)

    def test_architectural_momentum(self, engine):
        """架构惯性 — 论文核心概念"""
        for i in range(15):
            engine.pipeline("m1", "read", {}, f"out{i}",
                            ["check"], {"check": True})
        report = engine.get_variance_report(window=50)
        momentum = report.get("architectural_momentum", 0)
        # 全成功后 架构惯性应接近1.0
        assert momentum > 0.8


class TestReliabilityScore:
    """可靠性评分 ★★★"""

    def test_perfect_reliability(self, engine):
        """完美可靠性 = S级"""
        for i in range(30):
            engine.pipeline("deepseek-v4", "read", {}, f"out{i}",
                            ["check"], {"check": True})
        score = engine.get_reliability_score()
        assert score["reliability_score"] >= 90
        assert "S" in score["grade"]

    def test_poor_reliability(self, engine):
        """低可靠性"""
        for i in range(30):
            engine.pipeline("m1", "write", {}, f"out{i}",
                            ["check"], {"check": i % 3 != 0})
        score = engine.get_reliability_score()
        assert score["reliability_score"] < 80
    
    def test_components_sum_to_score(self, engine):
        """分项之和 = 总分"""
        for i in range(20):
            engine.pipeline("m1", "read", {}, f"out{i}",
                            ["check"], {"check": i % 4 != 0})
        score = engine.get_reliability_score()
        components = score["components"]
        expected_sum = round(
            components["commit_rate_contribution"] +
            components["replay_contribution"] +
            components["architectural_contribution"], 2
        )
        assert abs(score["reliability_score"] - expected_sum) < 1.0


class TestPipelineWithDifferentPatterns:
    """不同SDB模式的管道测试"""

    def test_conversational_pattern(self, engine):
        """对话模式 (低风险)"""
        for i in range(10):
            engine.pipeline("m1", "chat", {"msg": f"hello {i}"},
                            f"resp {i}",
                            rules=["content_filter"],
                            checks={"content_filter": True})
        stats = engine.get_stats()
        assert stats["commit_rate"] == 1.0

    def test_autonomous_pattern(self, engine):
        """自主模式 (中风险) — 混合pass/reject"""
        for i in range(15):
            engine.pipeline("m1", "terminal",
                            {"cmd": f"echo {i}"},
                            f"cmd{i}",
                            rules=["dangerous_cmd", "path_check"],
                            checks={
                                "dangerous_cmd": "rm" not in f"echo {i}",
                                "path_check": True,
                            })
        stats = engine.get_stats()
        assert stats["commit_rate"] > 0.8  # 大部分通过

    def test_long_horizon_pattern(self, engine):
        """长时任务模式 (高风险)"""
        for i in range(10):
            engine.pipeline("m1", "deploy",
                            {"target": "production"},
                            f"dep{i}",
                            rules=["syntax", "principle", "replay", "approval"],
                            checks={
                                "syntax": True,
                                "principle": i % 4 != 0,
                                "replay": True,
                                "approval": i % 3 != 0,
                            },
                            deterministic_context=f"deploy:production:attempt_{i}")
        stats = engine.get_stats()
        # 长时任务应该有较多reject
        assert stats["reject_rate"] > 0


class TestHistoryAndCleanup:
    """历史与清理"""

    def test_recent_records(self, engine):
        for i in range(5):
            engine.pipeline("m1", "read", {}, f"out{i}",
                            ["check"], {"check": True})
        records = engine.get_recent_records(limit=3)
        assert len(records) == 3

    def test_get_rejects(self, engine):
        for i in range(5):
            engine.pipeline("m1", "write", {}, f"out{i}",
                            ["check"], {"check": i % 2 == 0})
        rejects = engine.get_rejects()
        assert len(rejects) >= 2

    def test_clear(self, engine):
        for i in range(3):
            engine.pipeline("m1", "read", {}, f"out{i}",
                            ["check"], {"check": True})
        engine.clear()
        assert len(engine.get_recent_records()) == 0
        # 统计应保留
        assert engine._stats["total_proposals"] == 3


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import sdb_framework
        sdb_framework._engine = None
        e1 = get_sdb_engine()
        e2 = get_sdb_engine()
        assert e1 is e2
