"""v2.50 Unified Loop — 集成测试套件"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.unified_loop import (
    UnifiedLoopEngine, LoopPhase, LoopState, get_unified_loop
)


@pytest.fixture
def engine():
    """创建统一循环引擎"""
    return UnifiedLoopEngine(use_llm=False, use_sdb=True, auto_mode=False)


class TestLoopPhases:
    """OODA循环各阶段"""

    @pytest.mark.asyncio
    async def test_run_once_basic(self, engine):
        """基本的一次循环"""
        result = await engine.run_once("你好")
        assert result["iteration"] == 1
        assert "phases" in result
        assert "total_ms" in result

    @pytest.mark.asyncio
    async def test_run_once_chat_intent(self, engine):
        """对话意图 → chat动作"""
        result = await engine.run_once("今天天气怎么样")
        assert result["phases"]["decide"]["chosen_action"] == "chat"

    @pytest.mark.asyncio
    async def test_run_once_code_gen_intent(self, engine):
        """代码生成意图"""
        result = await engine.run_once("创建一个Python文件")
        assert result["phases"]["decide"]["chosen_action"] in ("write_file", "chat")

    @pytest.mark.asyncio
    async def test_run_once_analyze_intent(self, engine):
        """分析意图"""
        result = await engine.run_once("分析这段代码的性能")
        assert result["phases"]["decide"]["chosen_action"] in ("read_file", "search")

    @pytest.mark.asyncio
    async def test_phase_times_tracked(self, engine):
        """阶段耗时被追踪"""
        result = await engine.run_once("测试消息")
        assert "total_ms" in result
        assert result["total_ms"] >= 0
        assert "phase_times" in result
        for phase in ["observe", "orient", "decide", "act", "learn"]:
            assert phase in result["phase_times"]

    @pytest.mark.asyncio
    async def test_iteration_counter(self, engine):
        """迭代计数器"""
        for i in range(3):
            result = await engine.run_once(f"msg{i}")
            assert result["iteration"] == i + 1


class TestIntentClassification:
    """意图分类"""

    def test_classify_chat(self, engine):
        assert engine._classify_intent("你好") == "chat"
        assert engine._classify_intent("What's the weather?") == "chat"

    def test_classify_code_generation(self, engine):
        assert engine._classify_intent("写一个函数") == "code_generation"
        assert engine._classify_intent("创建配置文件") == "code_generation"
        assert engine._classify_intent("生成代码") == "code_generation"

    def test_classify_code_modification(self, engine):
        assert engine._classify_intent("修改这个bug") == "code_modification"
        assert engine._classify_intent("修复问题") == "code_modification"
        assert engine._classify_intent("改代码") == "code_modification"

    def test_classify_deployment(self, engine):
        assert engine._classify_intent("部署到服务器") == "deployment"

    def test_classify_search(self, engine):
        assert engine._classify_intent("搜索文件") == "search"
        assert engine._classify_intent("查找函数") == "search"

    def test_classify_analysis(self, engine):
        assert engine._classify_intent("分析性能") == "analysis"
        assert engine._classify_intent("检查代码质量") == "analysis"


class TestCandidateGeneration:
    """动作候选生成"""

    def test_generate_code_gen_candidates(self, engine):
        candidates = engine._generate_candidates({"intent": "code_generation"})
        assert len(candidates) >= 1
        assert candidates[0]["action"] in ("write_file", "chat")

    def test_generate_chat_candidates(self, engine):
        candidates = engine._generate_candidates({"intent": "chat"})
        assert len(candidates) == 1
        assert candidates[0]["action"] == "chat"

    def test_candidates_have_confidence(self, engine):
        for intent in ["code_generation", "code_modification", "deployment",
                       "analysis", "search", "chat"]:
            candidates = engine._generate_candidates({"intent": intent})
            assert sum(c["confidence"] for c in candidates) <= 1.1  # 概率接近1


class TestSDBIntegration:
    """SDB集成"""

    @pytest.mark.asyncio
    async def test_file_action_triggers_sdb(self, engine):
        """文件操作触发SDB检查"""
        # 模拟一个代码生成 → 执行
        engine._classify_intent = lambda t: "code_generation"
        result = await engine.run_once("写一个文件")
        act = result["phases"]["act"]
        if act["action"] in ("write_file", "patch"):
            assert act.get("sdb_checked")

    @pytest.mark.asyncio
    async def test_chat_action_skips_sdb(self, engine):
        """聊天动作跳过SDB"""
        result = await engine.run_once("你好")
        act = result["phases"]["act"]
        if act["action"] == "chat":
            assert not act.get("sdb_checked", False)


class TestBrainValidation:
    """脑状态验证集成"""

    @pytest.mark.asyncio
    async def test_brain_check_at_interval(self, engine):
        """每10次迭代脑状态检查"""
        for i in range(10):
            await engine.run_once(f"msg{i}")
        verify = engine._iteration_log[-1]["phases"].get("verify", {})
        assert verify.get("brain_check") is True or verify.get("brain_check") is False


class TestMetrics:
    """指标统计"""

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, engine):
        for _ in range(5):
            await engine.run_once("test")
        metrics = engine.get_metrics()
        assert metrics["total_iterations"] >= 5
        assert metrics["decisions_made"] >= 5

    @pytest.mark.asyncio
    async def test_metrics_phase_tracking(self, engine):
        await engine.run_once("test")
        metrics = engine.get_metrics()
        assert "current_phase" in metrics
        assert "actions_taken" in metrics

    @pytest.mark.asyncio
    async def test_history(self, engine):
        for i in range(3):
            await engine.run_once(f"msg{i}")
        history = engine.get_history()
        assert len(history) == 3
        assert history[0]["iteration"] == 1

    @pytest.mark.asyncio
    async def test_reset(self, engine):
        await engine.run_once("test")
        engine.reset()
        assert engine.state.iteration == 0
        assert engine._metrics["total_iterations"] == 0


class TestEdgeCases:
    """边界条件"""

    @pytest.mark.asyncio
    async def test_empty_input(self, engine):
        result = await engine.run_once("")
        assert result["iteration"] == 1

    @pytest.mark.asyncio
    async def test_very_long_input(self, engine):
        long_msg = "测试" * 1000
        result = await engine.run_once(long_msg)
        assert result["phases"]["observe"]["input_length"] > 1000

    @pytest.mark.asyncio
    async def test_special_chars(self, engine):
        result = await engine.run_once("🚀 Hello 世界 <script>alert(1)</script>")
        assert result["iteration"] == 1

    @pytest.mark.asyncio
    async def test_multiple_iterations_stable(self, engine):
        """多次迭代稳定"""
        for _ in range(20):
            result = await engine.run_once("test")
            assert result["total_ms"] >= 0


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import unified_loop
        unified_loop._engine = None
        e1 = get_unified_loop()
        e2 = get_unified_loop()
        assert e1 is e2
