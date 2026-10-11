# -*- coding: utf-8 -*-
"""模板 UI 守门 — 模板级断言专文件.

004meshctx round66 P4 / round67 挂账: confirm-panel 守门原住 test_cascade_router.py
(与级联路由无关), 迁此专文件。
"""
from pathlib import Path


def test_confirm_panel_overflow_guard():
    """用户实测: 授权UI溢出屏幕 — v3.133.7 终修: position:fixed bottom bar.

    前三版 (100vw/100dvw/width:100%) 全失败 — 根因: confirmPanel 不在
    .chat-main/.messages DOM 内 (chat-main 闭合位置 < confirmPanel 位置),
    width:100% 相对错误父级计算。唯一可靠: fixed 定位三边锚定。
    """
    h = Path(__file__).resolve().parent.parent / "templates" / "chat.html"
    t = h.read_text(encoding="utf-8")
    # 面板必须 fixed 定位 + 三边锚定
    assert "position: fixed" in t, "面板必须 fixed (前三版相对父级 width 全失败)"
    assert "bottom: 0; left: 0; right: 0" in t, "三边锚定"
    assert "max-width: 100vw" in t, "视口宽上限"
    assert "overflow-wrap: anywhere" in t, "11 语言长词断行"
    assert "max-height: 60vh" in t, "高度上限"
    # 选项/标题/自定义输入同样受控
    assert "confirm-options" in t and "confirm-custom" in t
    assert ".confirm-panel * { max-width: 100%" in t
    assert "flex-wrap: wrap" in t and "flex-shrink: 0" in t
