"""
Profiles多实例管理 — 测试
测试 src/core/profile_manager.py

覆盖:
- 创建/切换/删除/列表
- 隔离配置目录
- 默认profile
"""
import pytest
import tempfile
import os
import shutil
from pathlib import Path


class TestProfileManager:
    """多实例Profile管理"""

    @pytest.fixture
    def tmp_home(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_create_profile(self, tmp_home):
        """创建profile后目录存在"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("dev")
        assert os.path.isdir(os.path.join(tmp_home, "profiles", "dev"))

    def test_list_profiles(self, tmp_home):
        """list返回所有profile名称"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("dev")
        pm.create("prod")
        profiles = pm.list()
        assert "dev" in profiles
        assert "prod" in profiles

    def test_default_profile_exists(self, tmp_home):
        """默认profile 'default' 始终存在"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        assert "default" in pm.list()

    def test_switch_profile(self, tmp_home):
        """切换profile更新active状态"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("dev")
        pm.use("dev")
        assert pm.active == "dev"

    def test_delete_profile(self, tmp_home):
        """删除profile后不可再切换"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("test")
        pm.delete("test")
        profiles = pm.list()
        assert "test" not in profiles

    def test_cannot_delete_default(self, tmp_home):
        """不能删除default profile"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        with pytest.raises(ValueError, match="default"):
            pm.delete("default")

    def test_profiles_are_isolated(self, tmp_home):
        """不同profile有不同的配置目录"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("a")
        pm.create("b")
        path_a = pm.get_path("a")
        path_b = pm.get_path("b")
        assert path_a != path_b
        assert "a" in path_a
        assert "b" in path_b

    def test_clone_profile(self, tmp_home):
        """克隆profile复制配置"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("dev")
        # 在dev中放一个配置文件
        dev_path = pm.get_path("dev")
        with open(os.path.join(dev_path, "test.txt"), "w") as f:
            f.write("hello")
        pm.clone("dev", "dev2")
        dev2_path = pm.get_path("dev2")
        assert os.path.isfile(os.path.join(dev2_path, "test.txt"))

    def test_active_profile_path(self, tmp_home):
        """get_active_path返回当前活跃profile路径"""
        from src.core.profile_manager import ProfileManager
        pm = ProfileManager(home=tmp_home)
        pm.create("dev")
        pm.use("dev")
        path = pm.get_active_path()
        assert "dev" in path
