"""v3.71 Session Resume — tests"""
import pytest, tempfile
from pathlib import Path
from src.core.session_resume import SessionResumeEngine, get_session_resume

class TestResume:
    def test_save_resume(self):
        with tempfile.TemporaryDirectory() as d:
            e = SessionResumeEngine(Path(d))
            e.save("s1", {"profile":"test","messages":5})
            r = e.resume("s1")
            assert r is not None; assert r["messages"] == 5

    def test_resume_missing(self):
        with tempfile.TemporaryDirectory() as d:
            e = SessionResumeEngine(Path(d))
            assert e.resume("nonexistent") is None

    def test_list_recent(self):
        with tempfile.TemporaryDirectory() as d:
            e = SessionResumeEngine(Path(d))
            e.save("s1", {"profile":"a"}); e.save("s2", {"profile":"b"})
            recent = e.list_recent(2)
            assert len(recent) >= 1
