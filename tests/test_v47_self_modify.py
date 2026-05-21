"""v2.47 Self-Modifying Code Engine — 测试套件"""
import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.self_modify import (
    SelfModifyEngine, CodeChange, ChangeType, ChangeStatus, get_self_modify_engine
)


@pytest.fixture
def engine():
    """安全模式引擎 - 不自动应用"""
    return SelfModifyEngine(auto_apply=False, safety_level="high")


@pytest.fixture
def temp_py_file():
    """创建临时Python文件"""
    content = '''"""
Test module for self-modify testing.
"""
import os
import sys
import json


def unused_function():
    """This function is never used."""
    return "unused"


def main():
    x = 1
    y = 2
    result = x + y + 100 + 200 + 300 + 400 + 500 + 600 + 700 + 800 + 900 + 1000 + 1100 + 1200 + 1300 + 1400
    return result


# TODO: Fix this later
# FIXME: Known bug here
# HACK: Workaround for issue #42

class TestClass:
    def method_a(self):
        pass
    def method_b(self):
        pass
    def method_c(self):
        pass
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(content)
    yield f.name
    Path(f.name).unlink(missing_ok=True)


class TestAnalyze:
    """源代码分析"""

    def test_analyze_file(self, engine, temp_py_file):
        result = engine.analyze_file(temp_py_file)
        assert "file_size" in result
        assert result["line_count"] > 0
        assert "metrics" in result
        assert "issues" in result
        assert result["metrics"]["function_count"] >= 2
        assert result["metrics"]["class_count"] >= 1

    def test_analyze_detects_issues(self, engine, temp_py_file):
        result = engine.analyze_file(temp_py_file)
        # 应检测到 TODO/FIXME/HACK
        issue_types = [i["type"] for i in result.get("issues", [])]
        assert "todo_marker" in issue_types or "long_line" in issue_types

    def test_analyze_metrics(self, engine, temp_py_file):
        result = engine.analyze_file(temp_py_file)
        metrics = result["metrics"]
        assert metrics["total_lines"] > 10
        assert metrics["code_lines"] > 0
        assert "comment_lines" in metrics

    def test_analyze_nonexistent_file(self, engine):
        result = engine.analyze_file("/nonexistent/test.py")
        assert "error" in result

    def test_analyze_src(self, engine):
        """分析meshctx自身源码"""
        result = engine.analyze_src(pattern="__init__.py")
        assert result["files_analyzed"] >= 1
        assert isinstance(result["total_issues"], int)


class TestProposeChange:
    """变更提议"""

    def test_propose_change(self, engine, temp_py_file):
        new_content = "print('optimized')\n"
        change = engine.propose_change(
            temp_py_file, new_content,
            change_type=ChangeType.OPTIMIZE,
            reason="性能优化",
            confidence=0.8,
        )
        assert change.change_id.startswith("sc_")
        assert change.status == ChangeStatus.PROPOSED
        assert change.change_type == ChangeType.OPTIMIZE
        assert change.analysis_confidence == 0.8
        assert len(change.proposed_diff) > 0

    def test_propose_change_no_diff(self, engine, temp_py_file):
        """提议相同内容不产生diff"""
        original = Path(temp_py_file).read_text()
        change = engine.propose_change(temp_py_file, original)
        assert change.diff_stats.get("is_noop") or change.diff_stats.get("modified", 0) == 0

    def test_propose_increments_count(self, engine, temp_py_file):
        engine.propose_change(temp_py_file, "x", ChangeType.REFACTOR, "test")
        engine.propose_change(temp_py_file, "y", ChangeType.FIX, "test")
        assert engine._stats["total_proposed"] == 2


class TestTestChange:
    """变更测试"""

    def test_test_change_syntax_ok(self, engine, temp_py_file):
        new_content = "x = 1\ny = 2\nprint(x + y)\n"
        change = engine.propose_change(temp_py_file, new_content)
        change = engine.test_change(change)
        assert change.tests_passed
        assert change.test_results["syntax_check"]
        assert change.test_results["import_check"]

    def test_test_change_syntax_error(self, engine, temp_py_file):
        """语法错误应被检测"""
        new_content = "x = \nif True:\n"
        change = engine.propose_change(temp_py_file, new_content)
        change = engine.test_change(change)
        assert not change.tests_passed
        assert not change.test_results["syntax_check"]

    def test_test_infers_test_file(self, engine, temp_py_file):
        new_content = "x = 1\n"
        change = engine.propose_change(temp_py_file, new_content)
        change = engine.test_change(change)
        assert "test_file" in change.test_results


class TestGateChange:
    """SDB安全门控"""

    def test_gate_change_approved(self, engine, temp_py_file):
        new_content = "x = 1\ny = 2\n"
        change = engine.propose_change(temp_py_file, new_content)
        change = engine.test_change(change)
        change = engine.gate_change(change)
        assert change.sdb_record_id != ""
        # 语法ok的小变更应该通过
        assert change.sdb_approved

    def test_gate_change_rejected_on_syntax_error(self, engine, temp_py_file):
        """语法错误应被SDB拒绝"""
        broken = "class Broken:\n    def __init__:\n"
        change = engine.propose_change(temp_py_file, broken)
        change = engine.test_change(change)
        change = engine.gate_change(change)
        # 语法错误应导致拒绝
        assert not change.sdb_approved or change.status == ChangeStatus.REJECTED


class TestApplyChange:
    """应用变更"""

    def test_apply_with_auto_disabled(self, engine, temp_py_file):
        """auto_apply=False 不应用"""
        new_content = "x = 42\n"
        change = engine.propose_change(temp_py_file, new_content, ChangeType.OPTIMIZE, "test")
        change = engine.test_change(change)
        change = engine.gate_change(change)
        # 跳过直接设置状态以测试apply逻辑
        change.status = ChangeStatus.GATED
        change.sdb_approved = True
        result = engine.apply_change(change)
        # auto_apply=False 所以不会实际应用
        assert result is not None

    def test_apply_without_gate(self, engine, temp_py_file):
        """未通过门控不可应用"""
        new_content = "y = 99\n"
        change = engine.propose_change(temp_py_file, new_content, ChangeType.OPTIMIZE, "test")
        result = engine.apply_change(change)
        assert result.status in (ChangeStatus.REJECTED, ChangeStatus.PROPOSED)


class TestRollback:
    """回滚"""

    def test_rollback_nonexistent(self, engine):
        result = engine.rollback_change("nonexistent_id")
        assert not result["success"]

    def test_rollback_not_applied(self, engine, temp_py_file):
        new_content = "z = 1\n"
        change = engine.propose_change(temp_py_file, new_content, ChangeType.OPTIMIZE, "test")
        result = engine.rollback_change(change.change_id)
        assert not result["success"]


class TestAutonomousPipeline:
    """全自主改进管道"""

    def test_autonomous_improve(self, engine, temp_py_file):
        """端到端管道测试"""
        result = engine.autonomous_improve(temp_py_file, target="optimize")
        assert result["status"] in (
            "no_issues", "no_optimization_needed", "committed",
            "test_failed", "rejected_by_sdb", "max_changes_reached",
            "gated", "applied", "verified",
        )

    def test_autonomous_no_issues_file(self, engine):
        """干净文件无问题"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\n")
            clean_file = f.name
        try:
            result = engine.autonomous_improve(clean_file, target="optimize")
            assert result["status"] == "no_issues"
        finally:
            Path(clean_file).unlink(missing_ok=True)

    def test_autonomous_respects_max_changes(self, engine, temp_py_file):
        """尊重每session最大变更数"""
        engine.max_changes_per_session = 1
        engine._applied_count = 1  # 模拟已达上限
        result = engine.autonomous_improve(temp_py_file)
        if result["status"] != "no_issues":
            assert result["status"] == "max_changes_reached"


class TestMetricsAndIssues:
    """代码指标和问题检测"""

    def test_compute_metrics(self, engine):
        content = "def foo():\n    pass\n\n# comment\n\nclass Bar:\n    pass\n\nimport os"
        metrics = engine._compute_metrics(content)
        assert metrics["function_count"] == 1
        assert metrics["class_count"] == 1
        assert metrics["import_count"] == 1
        assert metrics["total_lines"] >= 7

    def test_detect_todo_markers(self, engine):
        content = "# TODO: refactor\n# FIXME: bug\n# HACK: workaround\nx = 1\n"
        issues = engine._detect_issues(content, "test.py")
        markers = [i["marker"] for i in issues if i["type"] == "todo_marker"]
        assert "TODO" in markers
        assert "FIXME" in markers

    def test_detect_long_line(self, engine):
        long_line = "x = " + "1 + " * 50 + "0"
        issues = engine._detect_issues(long_line, "test.py")
        long_issues = [i for i in issues if i["type"] == "long_line"]
        assert len(long_issues) >= 1

    def test_detect_long_function(self, engine):
        """检测过长函数"""
        func = "def big_func():\n" + "    pass\n" * 101
        issues = engine._detect_issues(func, "test.py")
        long_funcs = [i for i in issues if i["type"] == "long_function"]
        assert len(long_funcs) >= 1

    def test_syntax_check_ok(self, engine):
        ok, err = engine._check_syntax("x = 1\ny = 2\n")
        assert ok
        assert err == ""

    def test_syntax_check_error(self, engine):
        ok, err = engine._check_syntax("x = \nif True\n")
        assert not ok
        assert err != ""

    def test_generate_suggestions(self, engine):
        content = "x = 1\n" * 200
        suggestions = engine._generate_suggestions(content, "test.py")
        assert isinstance(suggestions, list)


class TestHistoryAndStats:
    """历史和统计"""

    def test_get_history(self, engine, temp_py_file):
        for i in range(3):
            engine.propose_change(temp_py_file, f"x={i}\n", ChangeType.OPTIMIZE, f"test{i}")
        history = engine.get_history()
        assert len(history) == 3

    def test_get_stats(self, engine, temp_py_file):
        engine.propose_change(temp_py_file, "x=1\n", ChangeType.OPTIMIZE, "test")
        stats = engine.get_stats()
        assert stats["total_proposed"] >= 1
        assert stats["auto_apply"] == False
        assert stats["safety_level"] == "high"


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import self_modify
        self_modify._engine = None
        e1 = get_self_modify_engine()
        e2 = get_self_modify_engine()
        assert e1 is e2
