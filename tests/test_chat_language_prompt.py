# -*- coding: utf-8 -*-
"""v3.131.14: 流式输出 + 思考/推理过程统一英语 — build_system_prompt 无条件注入守门.

用户要求 (2026-09-22): AI 产出 (正文 + reasoning/thinking) 统一英语,
与界面语言 / 用户消息语言无关。取代 v3.131.13 的 UI 语言联动。
"""
from src.chat_tools import build_system_prompt, SYSTEM_PROMPT

RULE = "## Response Language"


def test_english_rule_always_injected():
    p = build_system_prompt()
    assert RULE in p
    assert "Always respond in English" in p


def test_thinking_also_english():
    p = build_system_prompt()
    assert "reasoning/thinking output must also be written in English" in p


def test_rule_regardless_of_ui_lang_param():
    """ui_lang 参数不再影响语言规则 — 统一英语 (v3.131.13 联动已取代)."""
    for lg in (None, "ja", "ko", "zh", "EN"):
        p = build_system_prompt(ui_lang=lg)
        assert "Always respond in English" in p
        assert "follow the user's language" not in p  # 旧跟随条款已移除


def test_rule_after_system_prompt_and_before_memory():
    """规则在 SYSTEM_PROMPT 之后、记忆段之前 — 同态下前缀稳定 (T1 缓存契约)."""
    p = build_system_prompt(ui_lang="en", current_query="probe")
    assert p.find(SYSTEM_PROMPT) != -1
    i_rule = p.find(RULE)
    i_mem = p.find("## 🔒 持久化记忆")
    assert i_rule > p.find(SYSTEM_PROMPT)
    if i_mem != -1:
        assert i_rule < i_mem


def test_rule_kept_once():
    p = build_system_prompt()
    assert p.count(RULE) == 1
