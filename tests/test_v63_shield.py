"""v2.63 Regression Shield — 测试(同步版)"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def shield():
    from src.core.regression_shield import RegressionShield
    return RegressionShield(
        project_root=Path(__file__).parent.parent,
        auto_block=True
    )


class TestImpactAnalysis:
    def test_empty_files(self, shield):
        level, affected = shield.analyze_impact([])
        assert level == "low"
        assert affected == []

    def test_single_noncritical_file(self, shield):
        level, affected = shield.analyze_impact(["src/core/smart_router.py"])
        assert level == "low"

    def test_main_py_is_critical(self, shield):
        level, affected = shield.analyze_impact(["src/main.py"])
        assert level == "critical"

    def test_init_py_is_critical(self, shield):
        level, affected = shield.analyze_impact(["src/core/__init__.py"])
        assert level == "critical"

    def test_multiple_files_high(self, shield):
        level, affected = shield.analyze_impact([
            "src/core/sdb_framework.py",
            "src/core/diff_preview.py",
            "src/core/self_modify.py",
            "src/core/brain_validator.py",
            "src/core/task_progress.py",
            "src/core/unified_loop.py",
        ])
        assert level in ("high", "critical")

    def test_dep_propagation(self, shield):
        """测试依赖传播: self_modify依赖diff_preview和sdb"""
        level, affected = shield.analyze_impact(["src/core/diff_preview.py"])
        # diff_preview被self_modify依赖
        assert "diff_preview.py" in affected


class TestTestSelection:
    def test_returns_tests(self, shield):
        targets = shield.select_tests(["sdb_framework.py"])
        assert len(targets) > 0

    def test_critical_triggers_full(self, shield):
        targets = shield.select_tests(["main.py"])
        assert "tests/" in targets

    def test_unknown_module_gets_all(self, shield):
        targets = shield.select_tests(["nonexistent.py"])
        assert "tests/" in targets


class TestChangeRequest:
    def test_create_request(self, shield):
        from src.core.regression_shield import ChangeRequest
        req = ChangeRequest(
            id="test", description="Test change",
            files_changed=["a.py", "b.py"],
        )
        assert req.id == "test"
        assert len(req.files_changed) == 2

    def test_default_author(self, shield):
        from src.core.regression_shield import ChangeRequest
        req = ChangeRequest(id="x", files_changed=["test.py"])
        assert req.author == "agent"


class TestShieldVerdict:
    def test_pass(self, shield):
        from src.core.regression_shield import ShieldVerdict, ShieldReport
        report = ShieldReport(
            request_id="1", verdict=ShieldVerdict.PASS,
            tests_total=10, tests_passed=10,
        )
        assert report.verdict == ShieldVerdict.PASS

    def test_block(self, shield):
        from src.core.regression_shield import ShieldVerdict, ShieldReport
        report = ShieldReport(
            request_id="1", verdict=ShieldVerdict.BLOCK,
            tests_total=10, tests_passed=8, tests_failed=2,
        )
        assert report.verdict == ShieldVerdict.BLOCK

    def test_audit_hash_is_set(self, shield):
        from src.core.regression_shield import ShieldReport, ShieldVerdict
        report = ShieldReport(
            request_id="1", verdict=ShieldVerdict.PASS,
            audit_hash="abc123",
        )
        assert report.audit_hash == "abc123"


class TestStats:
    def test_empty_stats(self, shield):
        stats = shield.get_stats()
        assert stats["total_shields"] == 0
        assert stats["pass_rate"] == 1.0

    def test_after_shield(self, shield):
        from src.core.regression_shield import ShieldReport, ShieldVerdict
        shield._audit_log.append(ShieldReport(
            request_id="1", verdict=ShieldVerdict.PASS,
            tests_total=10, tests_passed=10,
        ))
        shield._audit_log.append(ShieldReport(
            request_id="2", verdict=ShieldVerdict.BLOCK,
            tests_total=10, tests_passed=8, tests_failed=2,
        ))
        stats = shield.get_stats()
        assert stats["total_shields"] == 2
        assert stats["passed"] == 1
        assert stats["blocked"] == 1


class TestSingleton:
    def test_get_shield(self, shield):
        from src.core.regression_shield import get_regression_shield
        s1 = get_regression_shield()
        s2 = get_regression_shield()
        assert s1 is s2
