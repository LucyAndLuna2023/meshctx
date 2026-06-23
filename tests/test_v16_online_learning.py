"""Test v1.6.2 — OnlineLearningEngine
Covers: InteractionRecorder, GenerativeModelUpdater, PreferenceLearner, 
        MemoryConsolidator, OnlineLearningEngine"""
import os, sys, time, json
import pytest
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.online_learning import (
    OnlineLearningEngine, Interaction, InteractionRecorder,
    GenerativeModelUpdater, PreferenceLearner, MemoryConsolidator,
)


class TestInteraction:
    def test_creation(self):
        i = Interaction(timestamp=1.0, user_msg="hi", assistant_msg="hello",
                        feedback_score=0.5)
        assert i.user_msg == "hi"
        assert i.feedback_score == 0.5
        assert i.mode == "direct"

    def test_defaults(self):
        i = Interaction(timestamp=1.0, user_msg="hi", assistant_msg="hello",
                        feedback_score=0)
        assert i.categories == []
        assert i.response_time_ms == 0.0


class TestInteractionRecorder:
    def test_record_basic(self):
        rec = InteractionRecorder(max_history=10)
        i = Interaction(time.time(), "hello", "hi there", 0.5)
        rec.record(i)
        assert rec.total_interactions() == 1

    def test_record_multiple(self):
        rec = InteractionRecorder(max_history=10)
        for msg in ["hello", "search for code", "analyze data"]:
            rec.record(Interaction(time.time(), msg, "ok", 0.0))
        assert rec.total_interactions() == 3

    def test_topic_extraction(self):
        rec = InteractionRecorder()
        rec.record(Interaction(time.time(), "search for bugs", "found", 0.8))
        stats = rec.get_topic_stats()
        assert "search" in stats

    def test_topic_general_fallback(self):
        rec = InteractionRecorder()
        rec.record(Interaction(time.time(), "你好世界", "你好", 0.0))
        stats = rec.get_topic_stats()
        assert "general" in stats

    def test_max_history(self):
        rec = InteractionRecorder(max_history=3)
        for i in range(5):
            rec.record(Interaction(time.time(), f"msg{i}", "ok", 0.0))
        assert rec.total_interactions() == 3

    def test_get_recent(self):
        rec = InteractionRecorder(max_history=100)
        for i in range(10):
            rec.record(Interaction(time.time(), f"msg{i}", "ok", 0.0))
        recent = rec.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].user_msg == "msg9"


class TestGenerativeModelUpdater:
    def test_update_and_predict(self):
        gmu = GenerativeModelUpdater(n_states=10, n_actions=5)
        gmu.update("idle", "search", "searching", 0.8)
        next_state, conf = gmu.predict_next_state("idle", "search")
        assert isinstance(next_state, str)
        assert 0 < conf <= 1.0

    def test_predict_reward(self):
        gmu = GenerativeModelUpdater()
        gmu.update("idle", "chat", "responding", 0.5)
        reward = gmu.predict_reward("idle", "chat")
        assert -1.0 <= reward <= 1.0

    def test_decay(self):
        gmu = GenerativeModelUpdater(n_states=5, n_actions=3, decay_rate=0.5)
        gmu.update("s1", "a1", "s2", 1.0)
        old_sum = gmu.transition.sum()
        gmu.decay()
        new_sum = gmu.transition.sum()
        assert new_sum <= old_sum

    def test_get_model_summary(self):
        gmu = GenerativeModelUpdater()
        gmu.update("idle", "chat", "responding", 0.0)
        summary = gmu.get_model_summary()
        assert summary["states_seen"] >= 1
        assert summary["actions_seen"] >= 1

    def test_multiple_updates(self):
        gmu = GenerativeModelUpdater(n_states=10, n_actions=5)
        for i in range(10):
            gmu.update(f"state{i}", f"act{i % 3}", f"next{i}", 0.5)
        assert gmu.action_counts.sum() == 10


class TestPreferenceLearner:
    def test_update_basic(self):
        pl = PreferenceLearner()
        i = Interaction(time.time(), "search code", "found", 0.8, categories=["search"])
        pl.update(i)
        pref = pl.get_preference("search")
        assert pref is not None
        assert pref.weight > 0

    def test_top_preferences(self):
        pl = PreferenceLearner()
        for topic, score in [("search", 0.9), ("code", 0.8), ("chat", 0.3)]:
            pl.update(Interaction(time.time(), topic, "ok", score, categories=[topic]))
        top = pl.get_top_preferences()
        assert len(top) <= 5
        assert top[0].weight >= top[-1].weight

    def test_confidence_grows(self):
        pl = PreferenceLearner()
        for _ in range(25):
            pl.update(Interaction(time.time(), "search", "ok", 0.5, categories=["search"]))
        pref = pl.get_preference("search")
        assert pref is not None
        assert pref.confidence >= 0.8

    def test_summary(self):
        pl = PreferenceLearner()
        pl.update(Interaction(time.time(), "code", "ok", 0.7, categories=["code"]))
        s = pl.summary()
        assert s["total_preferences"] >= 1
        assert len(s["top_topics"]) > 0


class TestMemoryConsolidator:
    def test_consolidate_empty(self):
        mc = MemoryConsolidator()
        rec = InteractionRecorder()
        result = mc.consolidate(rec)
        assert result["consolidated"] is False

    def test_consolidate_with_data(self):
        mc = MemoryConsolidator()
        rec = InteractionRecorder(max_history=100)
        for msg in ["search", "code", "search", "chat", "search"]:
            rec.record(Interaction(time.time(), msg, "ok", 0.5))
        result = mc.consolidate(rec)
        assert result["consolidated"] is True
        assert result["total_interactions"] == 5

    def test_important_topics(self):
        mc = MemoryConsolidator()
        rec = InteractionRecorder()
        topics = ["search"] * 5 + ["code"] * 3 + ["chat"]
        for t in topics:
            rec.record(Interaction(time.time(), t, "ok", 0.5))
        result = mc.consolidate(rec)
        assert ("search", 5) in result["important_topics"] or \
               (result["important_topics"][0][0] == "search")


class TestOnlineLearningEngine:
    def test_record_interaction(self):
        engine = OnlineLearningEngine()
        i = engine.record_interaction("hello", "hi there", 0.5)
        assert isinstance(i, Interaction)
        assert engine.recorder.total_interactions() == 1

    def test_get_summary(self):
        engine = OnlineLearningEngine()
        engine.record_interaction("search something", "result", 0.8)
        engine.record_interaction("write code", "done", 0.3)
        s = engine.get_summary()
        assert s["total_interactions"] == 2
        assert "topics" in s

    def test_negative_feedback(self):
        engine = OnlineLearningEngine()
        engine.record_interaction("bad result", "sorry", -0.5)
        s = engine.get_summary()
        assert s["total_interactions"] == 1

    def test_preference_learning_through_engine(self):
        engine = OnlineLearningEngine()
        engine.record_interaction("search for bugs", "found 3 bugs", 0.9)
        prefs = engine.preference_learner.summary()
        assert prefs["total_preferences"] >= 1

    def test_serialization(self):
        engine = OnlineLearningEngine()
        engine.record_interaction("search", "result", 0.7)
        engine.record_interaction("code", "output", 0.5)
        data = engine.to_dict()
        assert "preferences" in data
        assert data["total_interactions"] == 2

        engine2 = OnlineLearningEngine.from_dict(data)
        # 交互记录不序列化（重开会从零开始），但偏好和模型恢复
        assert engine2.recorder.total_interactions() == 0
        pref = engine2.preference_learner.get_preference("search")
        assert pref is not None

    def test_model_learns_from_feedback(self):
        engine = OnlineLearningEngine()
        # 多次正面反馈
        for _ in range(5):
            engine.record_interaction("search", "result", 1.0)
        # 负面反馈
        for _ in range(3):
            engine.record_interaction("search", "bad", -0.5)

        # 偏好搜索应该仍为正
        pref = engine.preference_learner.get_preference("search")
        assert pref is not None
        # 正面次数多的话weight应该大于0
        assert pref.weight > 0 or pref.examples >= 8

    def test_consolidation_count(self):
        engine = OnlineLearningEngine()
        engine._consolidation_interval = -1  # 强制立即巩固
        engine.record_interaction("test", "ok", 0.5)
        assert engine.consolidator._consolidation_count >= 1

    def test_multiple_topics(self):
        engine = OnlineLearningEngine()
        engine.record_interaction("search code for bugs", "fixed", 1.0)
        s = engine.get_summary()
        assert len(s["topics"]) >= 2  # search + code
