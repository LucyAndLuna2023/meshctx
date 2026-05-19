"""
文件Checkpoint回滚 — 测试
测试 src/core/checkpoint.py

覆盖:
- 创建快照
- 文件恢复
- 会话管理
- 快照大小限制
"""
import pytest
import tempfile
import os
import shutil


class TestCheckpointManager:
    """文件系统快照回滚"""

    @pytest.fixture
    def tmp_workdir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_create_checkpoint(self, tmp_workdir):
        """创建快照后文件被保存"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir)
        # 创建测试文件
        test_file = os.path.join(tmp_workdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original content")
        cid = cm.save("初始状态")
        assert cid is not None
        assert len(cm.list()) > 0

    def test_restore_file(self, tmp_workdir):
        """修改文件后可以恢复"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir)
        test_file = os.path.join(tmp_workdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")
        cm.save("v1")
        # 修改
        with open(test_file, "w") as f:
            f.write("modified")
        # 恢复
        cm.rollback()
        with open(test_file) as f:
            content = f.read()
        assert content == "original"

    def test_list_checkpoints(self, tmp_workdir):
        """列出所有快照"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir)
        cm.save("first")
        cm.save("second")
        checkpoints = cm.list()
        assert len(checkpoints) >= 2
        assert checkpoints[0]["label"] in ("first", "second")

    def test_rollback_to_specific(self, tmp_workdir):
        """回滚到指定快照"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir)
        test_file = os.path.join(tmp_workdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("v1")
        cm.save("v1")
        with open(test_file, "w") as f:
            f.write("v2")
        cm.save("v2")
        with open(test_file, "w") as f:
            f.write("v3")
        # 回滚到v1
        checkpoints = cm.list()
        v1 = [c for c in checkpoints if c["label"] == "v1"][0]
        cm.rollback(v1["id"])
        with open(test_file) as f:
            content = f.read()
        assert content == "v1"

    def test_max_checkpoints_limit(self, tmp_workdir):
        """快照数量不超过上限"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir, max_snapshots=3)
        for i in range(5):
            cm.save(f"snap{i}")
        assert len(cm.list()) <= 3

    def test_clear_all(self, tmp_workdir):
        """清空所有快照"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(workdir=tmp_workdir)
        cm.save("test")
        cm.clear()
        assert len(cm.list()) == 0

    def test_ignore_patterns(self, tmp_workdir):
        """忽略模式排除特定文件"""
        from src.core.checkpoint import CheckpointManager
        cm = CheckpointManager(
            workdir=tmp_workdir,
            ignore_patterns=["*.log", "__pycache__", ".git"]
        )
        # 创建应被忽略的文件
        log_file = os.path.join(tmp_workdir, "debug.log")
        os.makedirs(os.path.join(tmp_workdir, "__pycache__"), exist_ok=True)
        with open(log_file, "w") as f:
            f.write("log content")
        cm.save("test")
        # 恢复后日志文件不应被恢复（不在快照中）
        os.remove(log_file)
        cm.rollback()
        assert not os.path.exists(log_file), "忽略的文件不应被恢复"
