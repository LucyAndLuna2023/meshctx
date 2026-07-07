"""Profile Manager — 多 Profile 管理

支持 create/delete/list/clone/switch 操作，profile 间配置隔离。
"""
import os
import shutil
from pathlib import Path
from typing import Optional


class ProfileNotFoundError(Exception):
    """Profile 不存在"""
    pass


class ProfileManager:
    """多 Profile 管理器

    Profile 目录结构:
        ~/.meshctx/profiles/<name>/
            config.yaml
            memory.db
            agents/
            skills/
    """

    DEFAULT = "default"

    def __init__(self, home: Optional[str] = None):
        self._home = Path(home or os.environ.get("HOME", str(Path.home())))
        self._base = self._home / "profiles"
        self._base.mkdir(parents=True, exist_ok=True)
        self._active = self.DEFAULT
        # 确保 default profile 存在
        self._ensure_profile(self.DEFAULT)

    # ── 创建 ────────────────────────────────────────────────

    def create(self, name: str) -> str:
        """创建新 profile，返回其路径"""
        if not name or "/" in name or "\\" in name:
            raise ValueError(f"非法 profile 名称: {name}")
        profile_dir = self._base / name
        if profile_dir.exists():
            raise FileExistsError(f"Profile '{name}' 已存在")
        profile_dir.mkdir(parents=True)
        (profile_dir / "config.yaml").touch()
        (profile_dir / "agents").mkdir(exist_ok=True)
        (profile_dir / "skills").mkdir(exist_ok=True)
        return str(profile_dir)

    def _ensure_profile(self, name: str):
        """确保 profile 存在，不存在则创建"""
        p = self._base / name
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            (p / "config.yaml").touch()

    # ── 删除 ────────────────────────────────────────────────

    def delete(self, name: str):
        """删除 profile，default 不可删除"""
        if name == self.DEFAULT:
            raise ValueError("不能删除 default profile")
        profile_dir = self._base / name
        if not profile_dir.exists():
            raise ProfileNotFoundError(f"Profile '{name}' 不存在")
        shutil.rmtree(str(profile_dir))
        if self._active == name:
            self._active = self.DEFAULT

    # ── 查询 ────────────────────────────────────────────────

    def list(self) -> list:
        """列出所有 profile 名称"""
        if not self._base.exists():
            return [self.DEFAULT]
        return sorted([
            d.name for d in self._base.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]) or [self.DEFAULT]

    def get_path(self, name: str) -> str:
        """获取 profile 目录路径"""
        return str(self._base / name)

    def exists(self, name: str) -> bool:
        """检查 profile 是否存在"""
        return (self._base / name).is_dir()

    # ── 切换 ────────────────────────────────────────────────

    def switch(self, name: str) -> bool:
        """切换到指定 profile"""
        if not self.exists(name):
            return False
        self._active = name
        return True

    def use(self, name: str) -> bool:
        """切换到指定 profile (switch 别名)"""
        return self.switch(name)

    @property
    def active(self) -> str:
        """当前活跃 profile"""
        return self._active

    @property
    def active_path(self) -> str:
        """当前活跃 profile 路径"""
        return str(self._base / self._active)

    def get_active_path(self) -> str:
        """获取活跃 profile 路径 (兼容旧接口)"""
        return self.active_path

    # ── 克隆 ────────────────────────────────────────────────

    def clone(self, source: str, target: str) -> str:
        """克隆 profile，复制所有配置"""
        if not self.exists(source):
            raise ProfileNotFoundError(f"源 Profile '{source}' 不存在")
        src_dir = self._base / source
        dst_dir = self._base / target
        if dst_dir.exists():
            raise FileExistsError(f"目标 Profile '{target}' 已存在")
        shutil.copytree(str(src_dir), str(dst_dir), symlinks=False)
        return str(dst_dir)

    # ── 统计 ────────────────────────────────────────────────

    def stats(self) -> dict:
        """profile 统计"""
        profiles = self.list()
        return {
            "total": len(profiles),
            "active": self._active,
            "profiles": profiles,
        }

    # ── 兼容旧接口 ──────────────────────────────────────────

    def list_profiles(self) -> list:
        """兼容旧接口 — 返回 profile 名称列表"""
        return self.list()

    def get_profile(self, name: str = "default") -> dict:
        """兼容旧接口 — 返回 profile 配置"""
        return {
            "name": name,
            "path": self.get_path(name),
            "exists": self.exists(name),
            "is_active": name == self._active,
        }

    def create_profile(self, name: str) -> bool:
        """兼容旧接口"""
        self.create(name)
        return True
