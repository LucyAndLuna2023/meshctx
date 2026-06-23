"""
MeshCtx v3.71 — Session Resume Tests (v3.83 API)
"""
import json, time, pytest
from pathlib import Path
from src.core.session_resume import SessionResumeEngine, SessionState


class TestSessionState:
    def test_state_creation(self):
        s = SessionState(id="test-1", profile="meshctx", messages=10)
        assert s.id == "test-1"
        assert s.messages == 10


class TestSessionResume:
    def test_save_and_resume(self, tmp_path):
        engine = SessionResumeEngine(storage=tmp_path)
        engine.save("s1", {"id": "s1", "profile": "test", "messages": 5})
        result = engine.resume("s1")
        assert result is not None
        assert result["id"] == "s1"

    def test_resume_nonexistent(self, tmp_path):
        engine = SessionResumeEngine(storage=tmp_path)
        assert engine.resume("nonexistent") is None

    def test_list_recent(self, tmp_path):
        engine = SessionResumeEngine(storage=tmp_path)
        for i in range(3):
            engine.save(f"s{i}", {"id": f"s{i}"})
        recent = engine.list_recent(2)
        assert len(recent) <= 2

    def test_get_stats(self, tmp_path):
        engine = SessionResumeEngine(storage=tmp_path)
        engine.save("a", {"id": "a"})
        stats = engine.get_stats()
        assert stats["sessions"] == 1


class TestArchiverBugFix:
    def test_last_full_save_is_instance_variable(self):
        from src.core.session_archiver import SessionArchiver
        a1 = SessionArchiver()
        a2 = SessionArchiver()
        assert hasattr(a1, '_last_full_save')
        assert hasattr(a2, '_last_full_save')
        a1._last_full_save = 999.0
        assert a2._last_full_save != 999.0
