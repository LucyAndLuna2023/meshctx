# -*- coding: utf-8 -*-
"""安装器升级数据保护守门 — I-8 (升级 rm -rf 全灭用户数据) 类级防线.

三道断言:
1. 三平台安装器 (install.sh/install-mac.sh/install.bat) 不得含
   "rm -rf/rmdir INSTALL_DIR 全灭重建" 模式 (就地覆盖+排除是唯一合法形态)
2. 三平台 + edition 脚本必须带数据白名单排除参数 (升级时数据原地保留)
3. docs 镜像同步 (docs/install*.sh 与根目录一致, 三平台修复不同步的历史教训)

根因链 (2026-09-27 考古): 08-25 修复只改 install.sh 扩大备份、未同步
install-mac/bat、未消灭 rm -rf → 用户 Mac 升级全灭重配 (I-8)。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSTALLERS = {
    "install.sh": "sh",
    "install-mac.sh": "sh",
    "install.bat": "bat",
}
EXCLUDE_MARK = ("config.yaml", "memories", "conversations")
FORBIDDEN_SH = re.compile(r"rm\s+-rf\s+[\"']?\$\{?INSTALL_DIR", re.I)
FORBIDDEN_BAT = re.compile(r"rmdir\s+/s\s+/q\s+\"?%INSTALL_DIR%", re.I)


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_no_wipe_rebuild_in_any_installer():
    """三安装器不得存在 INSTALL_DIR 全灭删除 (v3.132.2 就地覆盖取代)."""
    for name in INSTALLERS:
        t = _read(name)
        assert not FORBIDDEN_SH.search(t), f"{name} 仍有 rm -rf INSTALL_DIR 全灭模式"
        if name.endswith(".bat"):
            assert not FORBIDDEN_BAT.search(t), f"{name} 仍有 rmdir INSTALL_DIR 全灭模式"


def test_exclude_whitelist_present():
    """升级解压必须带数据白名单排除 (config/memories/conversations 等原地保留)."""
    for name in INSTALLERS:
        t = _read(name)
        for mark in EXCLUDE_MARK:
            assert mark in t, f"{name} 缺数据保护排除标记: {mark}"


def test_edition_sh_no_wipe():
    """install-edition.sh git 更新模式, 不得有全灭删除."""
    t = _read("install-edition.sh")
    assert not FORBIDDEN_SH.search(t)


def test_docs_mirror_synced():
    """docs/install*.sh 与根目录一致 (三平台修复不同步的历史教训)."""
    for name in ("install.sh", "install-mac.sh", "install-edition.sh"):
        assert (_read(name) == _read(f"docs/{name}")), f"docs/{name} 镜像漂移"
