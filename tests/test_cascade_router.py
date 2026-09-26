# -*- coding: utf-8 -*-
"""SMA Phase 1 级联路由守门 — 三级分级/工具下限/升级触发."""
from src.cascade_router import classify_task, route, should_escalate


def test_l0_greeting_and_translation():
    assert classify_task("你好！") == "L0"
    assert classify_task("thanks") == "L0"
    assert classify_task("翻译这段话") == "L0"
    assert classify_task("总结一下") == "L0"


def test_l2_architecture_and_long_analysis():
    assert classify_task("请给出系统架构设计方案") == "L2"
    assert classify_task("分析这段代码的根因") == "L2"
    assert classify_task("x" * 900) == "L2"  # 长文分析


def test_l1_default_and_tool_floor():
    assert classify_task("写一个函数实现快排") == "L1"
    assert classify_task("你好", has_tools=True) == "L1"  # 工具任务不低于 L1


def test_route_explicit_models_override():
    out = route("你好", models={"L0": "ollama:qwen3:0.6b"})
    assert out["tier"] == "L0" and out["model"] == "ollama:qwen3:0.6b"


def test_escalate_trigger():
    assert should_escalate(fail_count=2) is True
    assert should_escalate(fail_count=1, validation_failed=True) is True
    assert should_escalate(fail_count=0) is False
