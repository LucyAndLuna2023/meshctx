"""v2.44 Unified Diff Preview — 测试套件"""
import json
import os
import sys
import time
import tempfile
from pathlib import Path

import pytest

# 确保 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.diff_preview import DiffPreviewEngine, get_diff_engine, BACKUP_DIR


@pytest.fixture
def engine():
    """创建非冻结模式的引擎"""
    return DiffPreviewEngine(freeze_mode=False)


@pytest.fixture
def frozen_engine():
    """创建冻结模式的引擎"""
    return DiffPreviewEngine(freeze_mode=True)


@pytest.fixture
def temp_file():
    """创建临时文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write("def hello():\n    print('Hello')\n\nclass A:\n    pass\n")
    yield f.name
    Path(f.name).unlink(missing_ok=True)


class TestGenerateDiff:
    """生成 unified diff"""

    def test_generate_diff_modified_file(self, engine, temp_file):
        new_content = "def hello():\n    print('Hello World')\n\nclass A:\n    x = 1\n"
        result = engine.generate_diff(temp_file, new_content)
        assert result["change_id"] != ""
        assert result["stats"]["modified"] > 0
        # diff_lines保留原始换行符，检查diff_text（已预拼接）
        assert "Hello World" in result["diff_text"]
        assert "x = 1" in result["diff_text"]

    def test_generate_diff_no_changes(self, engine, temp_file):
        original = Path(temp_file).read_text()
        result = engine.generate_diff(temp_file, original)
        assert result["change_id"] == ""
        assert result["stats"]["is_noop"] is True
        assert "No changes detected" in str(result)

    def test_generate_diff_new_file(self, engine):
        new_path = f"/tmp/test_new_file_{int(time.time())}.py"
        result = engine.generate_diff(new_path, "print('new')\n")
        assert result["is_new_file"]
        assert "print" in result["diff_text"]

    def test_generate_diff_stats(self, engine, temp_file):
        new_content = "def hello():\n    print('A')\n    print('B')\n\nclass B:\n    y = 2\n"
        result = engine.generate_diff(temp_file, new_content)
        stats = result["stats"]
        assert stats["added"] >= 1
        assert stats["removed"] >= 1
        assert stats["modified"] == stats["added"] + stats["removed"]

    def test_generate_diff_original_hash(self, engine, temp_file):
        new_content = "print('changed')\n"
        result = engine.generate_diff(temp_file, new_content)
        assert len(result["original_hash"]) == 32  # MD5 hash
        assert result["original_hash"] != result["new_hash"]


class TestApplyChange:
    """应用变更"""

    def test_apply_change_success(self, engine, temp_file):
        new_content = "def goodbye():\n    print('bye')\n"
        result = engine.generate_diff(temp_file, new_content)
        assert result["change_id"]

        apply_result = engine.apply_change(result["change_id"])
        assert apply_result["success"]
        assert apply_result["backup_path"] is not None

        # 验证文件已修改
        current = Path(temp_file).read_text()
        assert "goodbye" in current
        assert "print('bye')" in current

    def test_apply_change_not_found(self, engine):
        result = engine.apply_change("nonexistent_id")
        assert not result["success"]
        assert "未找到" in result["error"]

    def test_apply_change_frozen_mode(self, frozen_engine, temp_file):
        new_content = "frozen = True\n"
        result = frozen_engine.generate_diff(temp_file, new_content)
        apply_result = frozen_engine.apply_change(result["change_id"])
        assert not apply_result["success"]
        assert "冻结" in apply_result["error"]

    def test_apply_change_backup_created(self, engine, temp_file):
        new_content = "backup_test = 1\n"
        result = engine.generate_diff(temp_file, new_content)
        apply_result = engine.apply_change(result["change_id"])
        assert Path(apply_result["backup_path"]).exists()


class TestRollback:
    """回滚变更"""

    def test_rollback_success(self, engine, temp_file):
        original = Path(temp_file).read_text()
        result = engine.generate_diff(temp_file, "changed = True\n")
        engine.apply_change(result["change_id"])

        # 回滚
        rollback = engine.rollback_change(result["change_id"])
        assert rollback["success"]

        # 验证恢复原始内容
        current = Path(temp_file).read_text()
        assert current == original

    def test_rollback_no_backup(self, engine, temp_file):
        result = engine.generate_diff(temp_file, "no_backup = True\n")
        # 应用但不创建备份
        engine.apply_change(result["change_id"], create_backup=False)
        rollback = engine.rollback_change(result["change_id"])
        assert not rollback["success"]


class TestBatchOperations:
    """批量操作"""

    def test_batch_diff(self, engine, temp_file):
        changes = [
            {"path": temp_file, "content": "a = 1\nb = 2\n"},
        ]
        result = engine.generate_batch_diff(changes)
        assert result["total_files"] == 1
        assert len(result["change_ids"]) == 1
        assert result["total_added"] >= 1

    def test_batch_apply(self, engine, temp_file):
        changes = [
            {"path": temp_file, "content": "batch = True\n"},
        ]
        batch_result = engine.generate_batch_diff(changes)
        apply_result = engine.apply_batch(batch_result["change_ids"])
        assert apply_result["success"]
        assert apply_result["total"] == 1


class TestStreamDiff:
    """流式 diff 输出"""

    def test_stream_diff_lines(self, engine, temp_file):
        result = engine.generate_diff(temp_file, "stream_test = 1\n")
        lines = list(engine.stream_diff_lines(result["change_id"]))
        assert len(lines) > 0
        # 第一条应该是 header
        header = json.loads(lines[0])
        assert header["type"] == "header"
        # 最后一条应该是 done
        done = json.loads(lines[-1])
        assert done["type"] == "done"


class TestHistoryAndPending:
    """历史与待处理"""

    def test_pending_tracking(self, engine, temp_file):
        result = engine.generate_diff(temp_file, "pending = True\n")
        pending = engine.get_pending()
        assert len(pending) == 1
        assert pending[0]["change_id"] == result["change_id"]

    def test_history_tracking(self, engine, temp_file):
        result = engine.generate_diff(temp_file, "history = True\n")
        engine.apply_change(result["change_id"])
        history = engine.get_history()
        assert len(history) >= 1
        assert history[-1]["change_id"] == result["change_id"]

    def test_clear_pending(self, engine, temp_file):
        engine.generate_diff(temp_file, "clear_me = 1\n")
        assert len(engine.get_pending()) >= 1
        count = engine.clear_pending()
        assert count >= 1
        assert len(engine.get_pending()) == 0


class TestDiffBetweenFiles:
    """文件间比较"""

    def test_diff_between_files(self, engine):
        # 创建两个临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("a = 1\n")
            path_a = f.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("a = 2\nb = 3\n")
            path_b = f.name

        try:
            result = engine.diff_between_files(path_a, path_b)
            assert result["stats"]["modified"] > 0
        finally:
            Path(path_a).unlink(missing_ok=True)
            Path(path_b).unlink(missing_ok=True)


class TestEdgeCases:
    """边界条件"""

    def test_empty_new_content(self, engine, temp_file):
        """空新内容 = 删除所有内容"""
        result = engine.generate_diff(temp_file, "")
        assert result["stats"]["removed"] > 0

    def test_binary_file_like_content(self, engine, temp_file):
        """含特殊字符的内容"""
        special = "line1\n\x00line2\n\tindented\nunicode: 🚀\n"
        result = engine.generate_diff(temp_file, special)
        assert result["change_id"] != ""
        engine.apply_change(result["change_id"])
        assert "🚀" in Path(temp_file).read_text(encoding="utf-8")

    def test_context_lines_parameter(self, engine, temp_file):
        """测试上下文行数参数"""
        new = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n"
        result = engine.generate_diff(temp_file, new, context_lines=1)
        # context_lines=1 应该产生更紧凑的 diff
        diff_text = "\n".join(result["diff_lines"])
        # 基本验证 diff 生成成功
        assert "line" in diff_text


class TestSingleton:
    """单例模式"""

    def test_get_diff_engine(self):
        e1 = get_diff_engine()
        e2 = get_diff_engine()
        assert e1 is e2

    def test_get_diff_engine_freeze(self):
        # 重置单例
        from src.core import diff_preview
        diff_preview._diff_engine = None
        e = get_diff_engine(freeze_mode=True)
        assert e.freeze_mode
        apply = e.apply_change("fake_id")
        assert not apply["success"]
        diff_preview._diff_engine = None  # cleanup


class TestBackupDirectory:
    """备份目录"""

    def test_backup_dir_exists(self):
        assert BACKUP_DIR.exists()
        assert BACKUP_DIR.is_dir()
