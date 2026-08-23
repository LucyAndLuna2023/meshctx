"""闭源核心检测 — 回归保护

修复(2026-08-23, 004 审计): PyInstaller 封装版闭源模块在 PYZ 字节码内,
磁盘无 desktop_tool.py, 原 os.path.exists 检测会误判 STUB → 封装完整版
启动即警告降级。改为 importlib.util.find_spec 探测 (frozen/source 通用)。
"""
import importlib
import importlib.machinery
import importlib.util

import pytest


def test_public_repo_is_stub():
    """公开仓库 (无私有 core) 必须判定为 stub, 不误报完整版。"""
    import src.core as core
    assert core._HAS_MESHCTX_CORE is False
    assert importlib.util.find_spec('src.core.desktop_tool') is None


def test_frozen_fallback_detects_core(monkeypatch):
    """模拟 PyInstaller frozen: find_spec 命中 desktop_tool → 判定为完整版。"""
    import src.core as core
    assert core._HAS_MESHCTX_CORE is False

    real_find_spec = importlib.util.find_spec
    fake = importlib.machinery.ModuleSpec('src.core.desktop_tool', loader=None)
    monkeypatch.setattr(
        importlib.util, 'find_spec',
        lambda name, *a, **k: fake if name == 'src.core.desktop_tool'
        else real_find_spec(name, *a, **k),
    )
    importlib.reload(core)
    assert core._HAS_MESHCTX_CORE is True

    # 还原真实 find_spec 并重载, 恢复公开仓库 stub 状态 (不污染后续测试)
    monkeypatch.undo()
    importlib.reload(core)
    assert core._HAS_MESHCTX_CORE is False
