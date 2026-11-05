# -*- coding: utf-8 -*-
"""base.html 双真源一致性守门 (002meshctx F-D).

事实: web_ui.py 用 DictLoader 注册内嵌 `_TEMPLATES["base.html"]`, **优先级高于** templates/base.html
(2026-10 曾因此让 12 语言下拉在生产只渲染 10 项)。两边漂移 = 改文件不生效。
本守门断言: 关键主题/语言片段在两份源里一致。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _both_sources():
    file_src = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    py_src = (ROOT / "src" / "web_ui.py").read_text(encoding="utf-8")
    m = re.search(r'_TEMPLATES\["base\.html"\] = r"""(.*?)"""', py_src, re.S)
    assert m, "web_ui.py 里找不到 _TEMPLATES[\"base.html\"] 内嵌源"
    return file_src, m.group(1)


def test_base_dual_source_lang_options_parity():
    """语言下拉选项必须两源一致 (12 语言)。"""
    f, e = _both_sources()
    pat = re.compile(r'<option value="([a-z]{2})"')
    fopts, eopts = set(pat.findall(f)), set(pat.findall(e))
    assert fopts == eopts, f"语言选项漂移: file-only={fopts-eopts} embedded-only={eopts-fopts}"
    assert {"zh", "en", "ja", "ko", "fr", "de", "es", "it", "ar", "ru", "he", "fa"} <= fopts


def test_base_dual_source_theme_markers_parity():
    """浅色主题覆盖的关键**规则块**必须两源都在 (改文件不生效的高发区).

    注意: 只断言选择器子串会被其它规则误命中 (如 `.terminal` 也在
    `[data-theme="light"] .terminal,` 的兄弟规则里出现) → 必须匹配带 `{ ... }` 的完整规则。
    """
    f, e = _both_sources()
    # v3.137.11 增强 (002zcode 提案): 清单式只盖 3/8 规则 → 改为**全部 light 规则块集合比对**
    # (任何规则漂移全捕获; 002zcode 已验证零假红)
    pat = re.compile(r'\[data-theme="light"\][^{]*\{[^}]*\}')
    fblocks = set(pat.findall(f))
    eblocks = set(pat.findall(e))
    assert fblocks == eblocks, (
        f"双真源漂移: file-only={fblocks - eblocks}\n"
        f"embedded-only={eblocks - fblocks}"
    )
    assert len(fblocks) >= 8, f"浅色规则块异常少 ({len(fblocks)}) — 疑截断"


def test_base_no_hardcoded_dark_border_in_html_preview():
    """002meshctx F-C: html-preview 边框不得硬编码 #30363d (须 var(--border))。"""
    f, e = _both_sources()
    assert "border-top:1px solid #30363d" not in f
    assert "border-top:1px solid #30363d" not in e
    assert "border-top:1px solid var(--border)" in f
    assert "border-top:1px solid var(--border)" in e
