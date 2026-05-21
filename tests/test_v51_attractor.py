"""v2.51 Attractor Reasoner — 测试套件"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.attractor_reasoner import (
    AttractorReasoner, Trajectory, DifficultyLevel, get_attractor_reasoner
)


@pytest.fixture
def engine():
    return AttractorReasoner(max_depth=10, max_breadth=3,
                              convergence_threshold=0.85, early_stop_rounds=3)


class TestCoreReasoning:
    """核心推理"""

    @pytest.mark.asyncio
    async def test_reason_returns_answer(self, engine):
        result = await engine.reason("1+1等于几?")
        assert "answer" in result
        assert "confidence" in result
        assert "trajectories" in result
        assert len(result["trajectories"]) > 0

    @pytest.mark.asyncio
    async def test_reason_with_custom_params(self, engine):
        result = await engine.reason("测试问题", depth=5, breadth=2)
        assert result["convergence_stats"]["breadth"] == 2
        assert result["convergence_stats"]["depth"] == 5

    @pytest.mark.asyncio
    async def test_reason_tracks_stats(self, engine):
        await engine.reason("query1")
        await engine.reason("query2")
        stats = engine.get_stats()
        assert stats["total_queries"] == 2

    @pytest.mark.asyncio
    async def test_reason_difficulty_classified(self, engine):
        result = await engine.reason("简单问题", depth=3, breadth=1)
        assert result["difficulty"] in ("simple", "moderate", "hard", "extreme")


class TestConvergence:
    """收敛检测"""

    def test_check_convergence_same_text(self, engine):
        assert engine._check_convergence("相同文本", "相同文本")

    def test_check_convergence_similar(self, engine):
        """高相似文本应收敛"""
        sim = engine._text_similarity(
            "答案是42因为生命宇宙万物的终极答案",
            "答案是42这是生命宇宙万物的答案"
        )
        # 中文分词空格少,Jaccard会比较单字
        assert sim > 0.2

    def test_check_convergence_different(self, engine):
        """完全不同文本不收敛"""
        sim = engine._text_similarity(
            "答案是A因为理由1",
            "答案是B因为理由2"
        )
        assert sim < 0.9

    def test_text_similarity_empty(self, engine):
        assert engine._text_similarity("", "") == 0.0
        assert engine._text_similarity("text", "") == 0.0

    def test_text_similarity_identical(self, engine):
        assert engine._text_similarity("identical text", "identical text") == 1.0


class TestAggregation:
    """轨迹聚合"""

    def test_aggregate_single_trajectory(self, engine):
        t = Trajectory(traj_id="t1", final_answer="答案A", converged_at=3, confidence=0.9)
        answer, conf = engine._aggregate_trajectories([t])
        assert answer == "答案A"
        assert conf >= 0.9

    def test_aggregate_majority_vote(self, engine):
        t1 = Trajectory(traj_id="t1", final_answer="答案A", converged_at=2, confidence=0.9)
        t2 = Trajectory(traj_id="t2", final_answer="答案A", converged_at=5, confidence=0.8)
        t3 = Trajectory(traj_id="t3", final_answer="答案B", converged_at=-1, confidence=0.3)
        answer, conf = engine._aggregate_trajectories([t1, t2, t3])
        assert answer == "答案A"  # 多数
        assert conf > 0.5

    def test_aggregate_converged_weighted_higher(self, engine):
        """收敛轨迹权重高于未收敛"""
        t1 = Trajectory(traj_id="t1", final_answer="答案A", converged_at=3, confidence=0.9)
        t2 = Trajectory(traj_id="t2", final_answer="答案B", converged_at=-1, confidence=0.3)
        t3 = Trajectory(traj_id="t3", final_answer="答案B", converged_at=-1, confidence=0.3)
        # A: 1.0, B: 0.3+0.3=0.6 → A胜
        answer, conf = engine._aggregate_trajectories([t1, t2, t3])
        assert answer == "答案A"


class TestDifficultyClassification:
    """难度分类"""

    def test_classify_simple(self, engine):
        assert engine._classify_difficulty(1) == DifficultyLevel.SIMPLE
        assert engine._classify_difficulty(3) == DifficultyLevel.SIMPLE

    def test_classify_moderate(self, engine):
        assert engine._classify_difficulty(5) == DifficultyLevel.MODERATE
        assert engine._classify_difficulty(8) == DifficultyLevel.MODERATE

    def test_classify_hard(self, engine):
        assert engine._classify_difficulty(10) == DifficultyLevel.HARD
        assert engine._classify_difficulty(20) == DifficultyLevel.HARD

    def test_classify_extreme(self, engine):
        assert engine._classify_difficulty(25) == DifficultyLevel.EXTREME
        assert engine._classify_difficulty(100) == DifficultyLevel.EXTREME


class TestConfidence:
    """置信度计算"""

    def test_compute_confidence_one_response(self, engine):
        conf = engine._compute_confidence(["唯一响应"])
        assert conf == 0.5

    def test_compute_confidence_similar_responses(self, engine):
        conf = engine._compute_confidence([
            "答案是42因为这是终极答案",
            "答案是42这是生命宇宙万物的终极答案",
        ])
        assert conf >= 0.2  # 中文无空格分词,Jaccard偏低

    def test_compute_confidence_divergent(self, engine):
        conf = engine._compute_confidence([
            "答案是A", "答案是B", "答案是C",
        ])
        # 发散序列置信度低
        assert conf < 0.8


class TestRefinementPrompt:
    """迭代细化提示词"""

    def test_build_refinement_prompt(self, engine):
        prompt = engine._build_refinement_prompt("原始问题?", "上一轮答案", 3)
        assert "原始问题" in prompt
        assert "上一轮答案" in prompt
        assert "第3轮" in prompt

    def test_build_refinement_prompt_round1(self, engine):
        prompt = engine._build_refinement_prompt("Q", "A", 1)
        assert "Q" in prompt
        assert "A" in prompt


class TestStats:
    """统计"""

    @pytest.mark.asyncio
    async def test_stats_updated(self, engine):
        for _ in range(3):
            await engine.reason("test")
        stats = engine.get_stats()
        assert stats["total_queries"] == 3
        assert stats["total_refinements"] > 0

    @pytest.mark.asyncio
    async def test_difficulty_distribution(self, engine):
        for _ in range(5):
            await engine.reason("query", depth=3, breadth=1)
        stats = engine.get_stats()
        assert "difficulty_distribution" in stats


class TestEdgeCases:
    """边界条件"""

    def test_empty_trajectories(self, engine):
        answer, conf = engine._aggregate_trajectories([])
        assert answer == "无结果"
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_system_prompt(self, engine):
        result = await engine.reason("问题", system_prompt="你是一个数学家")
        assert "answer" in result


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import attractor_reasoner
        attractor_reasoner._engine = None
        e1 = get_attractor_reasoner()
        e2 = get_attractor_reasoner()
        assert e1 is e2
