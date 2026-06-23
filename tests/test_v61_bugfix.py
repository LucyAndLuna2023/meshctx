"""v2.61 Autonomous Bug Fix Pipeline — 测试"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def engine():
    from src.core.autonomous_bugfix import (
        AutonomousBugFixEngine, FixStatus
    )
    return AutonomousBugFixEngine(auto_deploy=False)


class TestErrorDetection:
    def test_listen_key_error(self, engine):
        event = engine.listen({
            "type": "KeyError",
            "message": "KeyError: 'missing_key'",
            "traceback": 'File "test.py", line 42, in foo\n    d["missing_key"]\nKeyError: missing_key',
            "module": "test",
            "file": "/tmp/test.py",
            "line": 42,
        })
        assert event.error_type == "KeyError"
        assert "missing_key" in event.message

    def test_listen_attribute_error(self, engine):
        event = engine.listen({
            "type": "AttributeError",
            "message": "AttributeError: 'NoneType' object has no attribute 'value'",
            "traceback": "",
            "module": "api",
            "file": "handler.py",
            "line": 10,
        })
        assert event.error_type == "AttributeError"

    def test_collect_from_logs(self, engine):
        logs = [
            "INFO: Starting server",
            "ERROR: Connection refused on port 3001",
            "CRITICAL: Out of memory",
            "DEBUG: Request processed",
        ]
        events = engine.collect_from_logs(logs)
        assert len(events) == 2
        assert events[0].error_type == "ERROR"


class TestRootCauseAnalysis:
    def test_analyze_key_error(self, engine):
        event = engine.listen({
            "type": "KeyError",
            "message": "KeyError: 'config'",
            "traceback": 'File "/opt/app.py", line 100, in load\n    settings["config"]',
            "file": "/opt/app.py",
            "line": 100,
        })
        analysis = engine.analyze(event)
        assert analysis.root_cause != ""
        assert analysis.confidence > 0.7
        assert "config" in analysis.root_cause

    def test_analyze_attribute_error(self, engine):
        event = engine.listen({
            "type": "AttributeError",
            "message": "'dict' object has no attribute 'value'",
            "traceback": "",
        })
        analysis = engine.analyze(event)
        assert analysis.confidence > 0.5

    def test_analyze_import_error(self, engine):
        event = engine.listen({
            "type": "ImportError",
            "message": "ImportError: No module named 'unicorn'",
            "traceback": "",
        })
        analysis = engine.analyze(event)
        assert "Missing module" in analysis.root_cause

    def test_analyze_unknown_error(self, engine):
        event = engine.listen({
            "type": "WeirdError",
            "message": "Something happened",
            "traceback": "",
        })
        analysis = engine.analyze(event)
        assert analysis.confidence <= 0.3


class TestFixGeneration:
    def test_generate_fix_from_analysis(self, engine):
        from src.core.autonomous_bugfix import RootCauseAnalysis, ErrorEvent

        event = ErrorEvent(error_type="KeyError", message="KeyError: 'key'")
        analysis = RootCauseAnalysis(
            error=event,
            root_cause="Missing key",
            suggested_fix="Use .get()",
            confidence=0.85,
        )
        fix = engine.generate_fix(analysis)
        assert fix.id != ""
        assert fix.fix_diff != ""

    def test_full_pipeline(self, engine):
        """完整管道: Listen→Analyze→Generate→SDB→Test"""
        import asyncio
        result = asyncio.run(engine.fix_error({
            "type": "KeyError",
            "message": "KeyError: 'important_key'",
            "traceback": 'File "test.py", line 1, in <module>\n    data["important_key"]',
            "file": "test.py",
            "line": 1,
            "module": "test_module",
        }))
        assert result.id != ""
        assert result.status.value in ("generating", "sdb_review", "verified", "failed")


class TestStats:
    def test_get_stats_empty(self, engine):
        stats = engine.get_stats()
        assert stats["total_errors"] == 0
        assert stats["total_fixes"] == 0

    def test_get_stats_after_fix(self, engine):
        import asyncio
        asyncio.run(engine.fix_error({
            "type": "KeyError",
            "message": "KeyError: 'test'",
            "traceback": "",
            "file": "test.py",
            "line": 1,
            "module": "test",
        }))
        stats = engine.get_stats()
        assert stats["total_errors"] >= 1


class TestKnownPatterns:
    def test_learn_pattern_from_fix(self, engine):
        engine._known_patterns["KeyError"] = "Dictionary key missing — use .get()"
        event = engine.listen({
            "type": "KeyError",
            "message": "KeyError: 'any'",
            "traceback": "",
        })
        analysis = engine.analyze(event)
        assert "Dictionary key missing" in analysis.root_cause
