"""v2.70 Context Restorer — 测试"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def restorer(tmp_path):
    from src.core.context_restorer import ContextRestorer
    return ContextRestorer(data_dir=tmp_path / "projects")


@pytest.fixture
def sample_project(tmp_path):
    """创建一个模拟Python项目"""
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')")
    (proj / "requirements.txt").write_text("fastapi>=0.100\npytest>=7.0\n")
    (proj / "tests").mkdir()
    (proj / "tests" / "test_main.py").write_text("def test(): pass")
    return proj


class TestProjectDetection:
    def test_detect_project(self, restorer, sample_project):
        ctx = restorer.detect_project(sample_project)
        assert ctx.project_name == "myproject"
        assert ctx.language == "Python"

    def test_detect_language(self, restorer, sample_project):
        lang = restorer._detect_language(sample_project)
        assert lang == "Python"

    def test_detect_framework(self, restorer, sample_project):
        fw = restorer._detect_framework(sample_project)
        assert "FastAPI" in fw or "Fast" in fw

    def test_detect_file_patterns(self, restorer, sample_project):
        patterns = restorer._detect_file_patterns(sample_project)
        assert len(patterns) > 0

    def test_detect_test_command(self, restorer, sample_project):
        cmd = restorer._detect_test_command(sample_project)
        assert cmd == "pytest"


class TestContextRestoration:
    def test_restore(self, restorer, sample_project):
        result = restorer.restore(sample_project)
        assert result["project"]["name"] == "myproject"
        assert result["project"]["language"] == "Python"
        assert "lessons" in result
        assert "related_projects" in result

    def test_restore_second_time(self, restorer, sample_project):
        restorer.restore(sample_project)
        result = restorer.restore(sample_project)
        assert "lessons" in result


class TestLearning:
    def test_learn_lesson(self, restorer, sample_project):
        restorer.learn_lesson(sample_project, "Always use .get() for dict access")
        restorer.learn_lesson(sample_project, "Test before commit")

        result = restorer.restore(sample_project)
        assert len(result["lessons"]) >= 2

    def test_learn_command(self, restorer, sample_project):
        restorer.learn_command(sample_project, "pytest -x")
        restorer.learn_command(sample_project, "make deploy")

        result = restorer.restore(sample_project)
        assert len(result["common_commands"]) >= 2

    def test_record_conversation(self, restorer, sample_project):
        restorer.record_conversation(sample_project)
        restorer.record_conversation(sample_project)
        # Check conversation count
        ctx = restorer._contexts.get(restorer.detect_project(sample_project).project_id)
        if ctx:
            assert ctx.conversation_count >= 2


class TestCrossProject:
    def test_find_related(self, restorer, tmp_path):
        p1 = tmp_path / "project1"; p1.mkdir(); (p1 / "main.py").write_text("")
        p2 = tmp_path / "project2"; p2.mkdir(); (p2 / "main.py").write_text("")

        restorer.detect_project(p1)
        restorer.detect_project(p2)

        ctx1 = restorer.detect_project(p1)
        related = restorer._find_related_projects(ctx1)
        # 同语言应该相关
        assert len(related) >= 1

    def test_transfer_knowledge(self, restorer, tmp_path):
        p1 = tmp_path / "proj_a"; p1.mkdir(); (p1 / "main.py").write_text("")
        p2 = tmp_path / "proj_b"; p2.mkdir(); (p2 / "main.py").write_text("")

        restorer.learn_lesson(p1, "Use async/await for IO")
        result = restorer.transfer_knowledge(p1, p2)
        assert result["lessons_transferred"] >= 1


class TestStats:
    def test_list_projects(self, restorer, sample_project):
        restorer.detect_project(sample_project)
        projects = restorer.list_projects()
        assert len(projects) >= 1

    def test_get_stats(self, restorer, sample_project):
        restorer.detect_project(sample_project)
        stats = restorer.get_stats()
        assert stats["total_projects"] >= 1
        assert "recent_projects" in stats
