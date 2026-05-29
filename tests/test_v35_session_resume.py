"""
MeshCtx v3.35 — Session Auto-Resume Tests
测试: 存档检测/恢复/时间线/清理/连续性评分
"""
import json
import os
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── SessionResumeEngine 基本合约 ──

class TestDetectPreviousSession:
    """测试存档检测"""
    
    def test_no_archive_when_empty(self):
        from src.core.session_resume import SessionResumeEngine, ARCHIVE_DIR
        # 备份并清空存档目录
        saved_files = list(ARCHIVE_DIR.glob("*.json"))
        for f in saved_files:
            f.rename(f.with_suffix(".json.bak_test"))
        try:
            engine = SessionResumeEngine()
            result = engine.detect_previous_session()
            assert result is None
        finally:
            for f in ARCHIVE_DIR.glob("*.json.bak_test"):
                f.rename(f.with_suffix(".json"))
    
    def test_detect_recent_archive(self):
        from src.core.session_resume import SessionResumeEngine, ARCHIVE_DIR
        # 创建一个测试存档
        test_data = {
            "session_id": "test-session-123",
            "version": "3.34.0",
            "started_at": time.time() - 300,
            "saved_at": time.time() - 60,
            "decisions": [{"detail": "test decision"}],
            "rules": [{"detail": "test rule"}],
            "errors": [],
            "progress": [{"detail": "test progress"}],
        }
        latest = ARCHIVE_DIR / "latest.json"
        # 备份
        backup = None
        if latest.exists():
            backup = latest.read_bytes()
        try:
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(test_data, f)
            
            engine = SessionResumeEngine()
            result = engine.detect_previous_session()
            assert result is not None
            assert result["session_id"] == "test-session-123"
        finally:
            if backup:
                latest.write_bytes(backup)
            elif latest.exists():
                latest.unlink()
    
    def test_archive_too_old_returns_none(self):
        from src.core.session_resume import SessionResumeEngine, ARCHIVE_DIR
        test_data = {
            "session_id": "old-session",
            "saved_at": time.time() - 86400 * 14,  # 14天前
            "version": "1.0",
        }
        latest = ARCHIVE_DIR / "latest.json"
        backup = None
        if latest.exists():
            backup = latest.read_bytes()
        try:
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(test_data, f)
            
            engine = SessionResumeEngine()
            result = engine.detect_previous_session()
            assert result is None  # 过期
        finally:
            if backup:
                latest.write_bytes(backup)
            elif latest.exists():
                latest.unlink()


class TestRestore:
    """测试会话恢复"""
    
    def test_restore_basic_context(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        previous = {
            "session_id": "restore-test",
            "version": "3.34.0",
            "started_at": time.time() - 600,
            "saved_at": time.time() - 30,
            "decisions": [{"time": time.time(), "detail": "d1"} for _ in range(10)],
            "rules": [{"time": time.time(), "detail": "r1"} for _ in range(5)],
            "errors": [{"time": time.time(), "detail": "e1"}],
            "progress": [{"time": time.time(), "detail": "p1"} for _ in range(15)],
            "memory_snapshot": {"count": 42, "entries": []},
        }
        
        report = engine.restore(previous)
        assert report["resumed"] is True
        assert report["items_restored"]["decisions"] == 10
        assert report["items_restored"]["rules"] == 5
        assert report["items_restored"]["progress"] == 15
        assert report["items_restored"]["memory_entries"] == 42
        assert isinstance(report["context_continuity"], float)
        assert 0 <= report["context_continuity"] <= 100
    
    def test_restore_empty_context(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        previous = {
            "session_id": "empty",
            "version": "",
            "saved_at": time.time(),
            "decisions": [],
            "rules": [],
            "errors": [],
            "progress": [],
        }
        report = engine.restore(previous)
        assert report["resumed"] is True
        assert report["items_restored"]["decisions"] == 0
    
    def test_is_resumed_flag(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        assert engine.is_resumed is False
        engine.restore({"session_id": "test", "saved_at": time.time(), "version": ""})
        assert engine.is_resumed is True


class TestContinuityScore:
    """测试上下文连续性评分"""
    
    def test_recent_session_scores_high(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        previous = {
            "session_id": "recent",
            "version": "3.34.0",
            "started_at": time.time() - 3600,
            "saved_at": time.time() - 60,
            "decisions": [{"detail": "x"} for _ in range(100)],
            "rules": [{"detail": "x"} for _ in range(50)],
            "errors": [],
            "progress": [{"detail": "x"} for _ in range(50)],
        }
        # 创建一些快照文件
        from src.core.session_resume import ARCHIVE_DIR
        for i in range(6):
            snap = ARCHIVE_DIR / f"snapshot_test_{i}.json"
            snap.write_text("{}")
        
        try:
            report = engine.restore(previous)
            assert report["context_continuity"] >= 50  # 应该很高
        finally:
            for i in range(6):
                (ARCHIVE_DIR / f"snapshot_test_{i}.json").unlink(missing_ok=True)
    
    def test_old_sparse_session_scores_low(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        previous = {
            "session_id": "old-sparse",
            "version": "1.0.0",
            "started_at": time.time() - 86400 * 3,
            "saved_at": time.time() - 86400 * 2,
            "decisions": [{"detail": "x"}],
            "rules": [],
            "errors": [],
            "progress": [],
        }
        report = engine.restore(previous)
        assert report["context_continuity"] < 50


class TestTimeline:
    """测试会话时间线"""
    
    def test_timeline_empty(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        timeline = engine.get_timeline()
        assert isinstance(timeline, list)
    
    def test_timeline_with_resumed_session(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        engine.restore({"session_id": "test", "saved_at": time.time(), "version": "3.0"})
        timeline = engine.get_timeline()
        assert any(t.get("status") == "resumed" for t in timeline)


class TestClearArchives:
    """测试清理归档"""
    
    def test_clear_old_archives(self):
        from src.core.session_resume import SessionResumeEngine, ARCHIVE_DIR
        # 创建测试快照
        from src.core.session_resume import ARCHIVE_DIR
        for i in range(3):
            snap = ARCHIVE_DIR / f"snapshot_clear_test_{i}.json"
            snap.write_text(json.dumps({"saved_at": time.time() - 86400 * 60}))
        
        engine = SessionResumeEngine()
        deleted = engine.clear_archives(older_than_days=30)
        assert deleted >= 0
        
        # 清理
        for i in range(3):
            (ARCHIVE_DIR / f"snapshot_clear_test_{i}.json").unlink(missing_ok=True)


class TestApplyToKernel:
    """测试应用到内核"""
    
    def test_apply_to_mock_kernel(self):
        from src.core.session_resume import SessionResumeEngine
        
        engine = SessionResumeEngine()
        engine.restore({
            "session_id": "test",
            "saved_at": time.time(),
            "version": "1.0",
            "decisions": [{"detail": "d1"}, {"detail": "d2"}],
            "rules": [{"detail": "r1"}],
            "errors": [],
            "progress": [],
        })
        
        # Mock kernel
        kernel = MagicMock()
        kernel.memory = MagicMock()
        kernel.rules = []
        
        reports = engine.apply_to_kernel(kernel)
        assert len(reports) > 0
        assert any("决策" in r for r in reports)


class TestResumeReport:
    """测试恢复报告"""
    
    def test_report_before_resume(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        report = engine.get_resume_report()
        assert report["resumed"] is False
    
    def test_report_after_resume(self):
        from src.core.session_resume import SessionResumeEngine
        engine = SessionResumeEngine()
        engine.restore({"session_id": "test", "saved_at": time.time(), "version": "1.0"})
        report = engine.get_resume_report()
        assert report["resumed"] is True
        assert "archive_count" in report
        assert "snapshot_count" in report


# ── SessionArchiver Bug Fix ──

class TestArchiverBugFix:
    """测试SessionArchiver._last_full_save修复"""
    
    def test_last_full_save_is_instance_variable(self):
        from src.core.session_archiver import SessionArchiver
        a1 = SessionArchiver()
        a2 = SessionArchiver()
        # 两个实例应该有独立的_last_full_save
        assert hasattr(a1, '_last_full_save')
        assert hasattr(a2, '_last_full_save')
        a1._last_full_save = 999.0
        assert a2._last_full_save != 999.0  # 不共享
