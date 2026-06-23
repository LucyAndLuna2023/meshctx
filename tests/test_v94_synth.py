"""v2.94 Knowledge Synthesis — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def ks():
    from src.core.knowledge_synth import KnowledgeSynthesizer
    s = KnowledgeSynthesizer()
    s.add_fragment("React is the best frontend framework", "agent-A", 0.9, ["frontend"])
    s.add_fragment("React is a good frontend framework but Vue is simpler", "agent-B", 0.7, ["frontend"])
    s.add_fragment("Use FastAPI for Python backend", "agent-C", 0.85, ["backend"])
    s.add_fragment("FastAPI is excellent for APIs", "agent-D", 0.8, ["backend"])
    s.add_fragment("Avoid React, use Svelte instead", "agent-E", 0.6, ["frontend"])
    return s


class TestFragments:
    def test_add_fragment(self, ks):
        fid = ks.add_fragment("new knowledge", "agent-X", 0.5)
        assert fid != ""

    def test_find_related(self, ks):
        fid = ks.add_fragment("FastAPI performance optimization tips", "agent-F", 0.8)
        related = ks.find_related(fid)
        assert len(related) > 0  # Should find other FastAPI fragments


class TestSynthesis:
    def test_synthesize(self, ks):
        # Synthesize the FastAPI fragments
        fastapi_fids = [fid for fid, f in ks._fragments.items() if "FastAPI" in f.content]
        synth = ks.synthesize(fastapi_fids)
        assert synth.consensus_score > 0
        assert len(synth.source_agents) >= 1

    def test_conflict_detection(self, ks):
        all_fids = list(ks._fragments.keys())
        synth = ks.synthesize(all_fids)
        # Should detect React vs Svelte conflict
        assert len(synth.conflicts) >= 1

    def test_consensus_high_for_agreement(self, ks):
        # FastAPI fragments agree
        fids = [fid for fid, f in ks._fragments.items() if "FastAPI" in f.content]
        synth = ks.synthesize(fids)
        assert synth.consensus_score > 0.5


class TestMergeAgents:
    def test_merge_agent_knowledge(self, ks):
        ks.add_fragment("FastAPI is fast", "agent-C", 0.9)
        ks.add_fragment("FastAPI uses Pydantic", "agent-C", 0.8)
        result = ks.merge_agent_knowledge(["agent-C"])
        assert result["merged"] >= 1


class TestQuery:
    def test_query_synthesized(self, ks):
        fids = [fid for fid, f in ks._fragments.items() if "FastAPI" in f.content]
        ks.synthesize(fids)
        result = ks.query_synthesized("FastAPI backend")
        assert result is not None


class TestStats:
    def test_stats(self, ks):
        stats = ks.get_stats()
        assert stats["fragments"] >= 5
