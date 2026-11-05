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


def _chat_html():
    from pathlib import Path as _P
    return (_P(__file__).resolve().parent.parent / "templates" / "chat.html").read_text(encoding="utf-8")


def test_streaming_and_tool_output_use_theme_vars():
    """用户实测 (2026-11-05): UI 流式输出区一部分是黑底黑字 → 什么都看不到.

    根因: 浅色主题是默认 (body[data-theme=light]), 但流式正文/工具结果区
    仍是硬编码深底 (#0d1117/#0d1120) + 硬编码浅字或继承深色 → 浅色主题下
    黑底黑字不可读; 且 :root 变量默认是深色, 主题只在 body 尾部设置 → 首屏闪黑.
    """
    t = _chat_html()
    # ① 工具结果容器背景不再硬编码深色
    assert "background: #0d1117;\n  border: 1px solid #30363d" not in t, "工具结果容器仍硬编码深底"
    # ② 内联 tool-result <pre> 不再硬编码深底
    assert "background:#0d1120" not in t, "内联工具结果 pre 仍硬编码深底"
    # ③ 浅色主题必须显式覆盖流式/工具/推理区
    for sel in [
        '[data-theme="light"] .tool-result',
        '[data-theme="light"] .streaming .bubble',
        '[data-theme="light"] .reasoning-text',
        '[data-theme="light"] pre',
    ]:
        assert sel in t, f"浅色主题缺覆盖: {sel}"
    # ④ 主题变量挂在 html 级并双写 (变量定义在 html 上, 只在 body 设置会脱钩)
    assert 'html[data-theme="light"], body[data-theme="light"]' in t, "浅色变量必须覆盖 html 级"
    assert "document.documentElement.setAttribute('data-theme'" in t, "主题必须同步到 html 元素"
    # ⑤ 首屏不闪黑: head 内先行应用主题
    head_end = t.index("</head>")
    assert "document.documentElement.setAttribute('data-theme'" in t[:head_end], "主题初始化必须在 <head> 内"


def test_base_light_theme_covers_command_panel():
    """命令面板/终端区同型问题 (浅色主题下硬编码深底)."""
    from pathlib import Path as _P
    b = (_P(__file__).resolve().parent.parent / "templates" / "base.html").read_text(encoding="utf-8")
    assert '[data-theme="light"] .cmd-panel' in b
    assert '[data-theme="light"] .terminal' in b
