# -*- coding: utf-8 -*-
"""v3.131.13: UI 语言联动 AI 回复语言 — build_system_prompt(ui_lang) 守门.

用户报"11 种语言, 用不同语言 chat 是否自动用相应语言回复":
现状无语言规则(纯中文人设), 回复语言靠模型自觉; 本机制把 UI 语言注入系统提示,
同时保留"跟随用户输入语言"优先级。
"""
import pytest

from src.chat_tools import build_system_prompt, UI_LANG_NAMES


def test_ui_lang_injects_language_rule():
    p = build_system_prompt(ui_lang="ja")
    assert "## Response Language" in p
    assert "日本語 (ja)" in p
    assert "follow the user's language" in p


def test_ui_lang_none_keeps_prompt_unchanged():
    p = build_system_prompt(ui_lang=None)
    assert "## Response Language" not in p


def test_ui_lang_invalid_is_ignored():
    p = build_system_prompt(ui_lang="xx")
    assert "## Response Language" not in p


def test_ui_lang_uppercase_normalized():
    p = build_system_prompt(ui_lang="EN")
    assert "English (en)" in p


def test_all_11_ui_langs_covered():
    assert set(UI_LANG_NAMES) == {"en", "zh", "ja", "ko", "fr", "de", "es", "it", "ar", "ru", "he"}
    for lg in UI_LANG_NAMES:
        p = build_system_prompt(ui_lang=lg, include_memory=False)
        assert "## Response Language" in p
        assert UI_LANG_NAMES[lg] in p


def test_language_rule_before_memory_section():
    """语言指令插在稳定段末尾/记忆段之前 — 同语言下记忆段前缀稳定(T1 缓存契约)."""
    p = build_system_prompt(ui_lang="en", current_query="test query")
    i_rule = p.find("## Response Language")
    i_mem = p.find("## 🔒 持久化记忆")
    if i_mem != -1:  # 有记忆时指令必须在记忆段之前
        assert i_rule != -1 and i_rule < i_mem
