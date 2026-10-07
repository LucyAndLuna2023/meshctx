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
    "docs/install.bat": "bat",          # 002meshctx round61 P2-2: docs 镜像入防 (三犯后补)
    "docs/install-edition.bat": "bat",  # 002meshctx round61 P2-1: 同上
}
# tar 系安装器 (解包覆盖, 需要数据白名单排除) — round61 P2-1 守门精化:
# edition 系为 git 更新模式 (pull --ff-only, 无解包), 不适用排除标记, 另测 git 语义
TAR_INSTALLERS = {
    "install.sh": "sh",
    "install-mac.sh": "sh",
    "install.bat": "bat",
    "docs/install.sh": "sh",
    "docs/install-mac.sh": "sh",
    "docs/install.bat": "bat",
}
EDITION_GIT = ("install-edition.sh", "install-edition.bat", "docs/install-edition.bat")
EXCLUDE_MARK = ("config.yaml", "memories", "conversations")
FORBIDDEN_SH = re.compile(r"rm\s+-rf\s+[\"']?\$\{?INSTALL_DIR", re.I)
FORBIDDEN_BAT = re.compile(r"rmdir\s+/s\s+/q\s+\"?%INSTALL_DIR%", re.I)


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_no_wipe_rebuild_in_any_installer():
    """三安装器不得存在 INSTALL_DIR 全灭删除 (v3.133.1 就地覆盖取代)."""
    for name in INSTALLERS:
        t = _read(name)
        assert not FORBIDDEN_SH.search(t), f"{name} 仍有 rm -rf INSTALL_DIR 全灭模式"
        if name.endswith(".bat"):
            assert not FORBIDDEN_BAT.search(t), f"{name} 仍有 rmdir INSTALL_DIR 全灭模式"


def test_exclude_whitelist_present():
    """tar 系升级解压必须带数据白名单排除 (config/memories/conversations 等原地保留).

    round61 P2-1 精化: edition 系是 git 更新模式 (无 tar 解包), 排除标记不适用 —
    其数据保护语义由 test_edition_git_mode_preserves_data 单独守门。
    """
    for name in TAR_INSTALLERS:
        t = _read(name)
        for mark in EXCLUDE_MARK:
            assert mark in t, f"{name} 缺数据保护排除标记: {mark}"


def test_edition_git_mode_preserves_data():
    """edition 系 (git 更新模式): 必须 pull --ff-only 原地升级, 不得全灭重建."""
    for name in EDITION_GIT:
        t = _read(name)
        assert "pull --ff-only" in t, f"{name} 缺 git pull --ff-only (原地升级语义)"
        assert "clone" in t, f"{name} 缺 clone (首装路径)"


def test_edition_sh_no_wipe():
    """install-edition.sh git 更新模式, 不得有全灭删除."""
    t = _read("install-edition.sh")
    assert not FORBIDDEN_SH.search(t)


def test_docs_mirror_synced():
    """docs/install* 与根目录一致 (三平台修复不同步的历史教训; 002meshctx round61 P2-1/P2-2: .bat 入防)."""
    for name in ("install.sh", "install-mac.sh", "install-edition.sh",
                 "install.bat", "install-edition.bat"):
        assert (_read(name) == _read(f"docs/{name}")), f"docs/{name} 镜像漂移"


def test_desktop_host_never_version_polluted():
    """I-8 同族防线: desktop HOST 曾被版本 bump 全局替换污染 (127.0.0.1→123.132.0.1)
    致 bind 失败 — 静态守门: HOST 必须 loopback."""
    t = (ROOT / "meshctx_desktop.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'HOST\s*=\s*"([^"]+)"', t)
    assert m, "HOST 定义缺失"
    host = m.group(1)
    assert host == "127.0.0.1", f"desktop HOST 被污染: {host} (必须 loopback)"
