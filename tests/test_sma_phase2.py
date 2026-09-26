# -*- coding: utf-8 -*-
"""SMA Phase 2 守门 — 验证器库 / 自修复链 / 自一致投票."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.validators import (validate_json_output, validate_python_code,
                            validate_file_refs, validate_response)
from src.sma_repair import repair_prompt, run_with_repair, escalation_path, self_consistency_vote


# ── JSON 验证器 ─────────────────────────────────────────────

def test_json_valid_direct():
    assert validate_json_output('{"a": 1}').ok


def test_json_in_fence():
    assert validate_json_output('结果如下:\n```json\n{"a": [1,2]}\n```').ok


def test_json_trailing_comma_tolerated():
    assert validate_json_output('{"a": 1, "b": [2,],}').ok  # 弱模型常见尾逗号


def test_json_broken_reports_error():
    r = validate_json_output('{"a": 1,,}')
    assert not r.ok and "JSON 解析失败" in r.errors[0]


# ── Python 验证器 ───────────────────────────────────────────

def test_python_valid_block():
    r = validate_python_code("```python\ndef f():\n    return 1\n```")
    assert r.ok and r.meta["blocks"] == 1


def test_python_syntax_error_reported():
    r = validate_python_code("```python\ndef f(:\n    return 1\n```")
    assert not r.ok and any("语法错误" in e for e in r.errors)


# ── file_refs ───────────────────────────────────────────────

def test_file_refs_missing_relative(tmp_path):
    r = validate_file_refs("请查看 config.yaml 并对比 pyproject.toml", base=tmp_path)
    assert not r.ok and r.meta["checked"] == 2


def test_file_refs_existing_ok(tmp_path):
    (tmp_path / "config.yaml").write_text("a: 1")
    r = validate_file_refs("请查看 config.yaml", base=tmp_path)
    assert r.ok


# ── 自修复链 ────────────────────────────────────────────────

def test_escalation_path():
    assert escalation_path("L0") == ["L1", "L2"]
    assert escalation_path("L2") == []
    assert escalation_path("user") == []


def test_repair_chain_retry_then_pass():
    """同模型带反馈重试: 第 1 次坏 JSON, 第 2 次修好 → ok 不升级."""
    calls = []

    def task_fn(model, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "```json\n{'a': 1,}```"  # 单引号+尾逗号 → 修复前失败
        return '{"a": 1}'

    out = run_with_repair(task_fn, "输出 json", "L1",
                          {"L1": "m1", "L2": "m2"}, checks=["json"], max_retry=2)
    assert out["ok"] and out["tier_used"] == "L1" and len(calls) == 2
    assert "校验反馈" in calls[1]  # 修复提示词带错误反馈


def test_repair_chain_escalates_after_retries():
    """L0 两次重试全败 → 升级 L1 一次通过 (级联升级联动实证)."""
    log = []

    def task_fn(model, prompt):
        log.append(model)
        return '{"ok": true}' if model == "m_L1" else "not json at all"

    out = run_with_repair(task_fn, "输出 json", "L0",
                          {"L0": "m_L0", "L1": "m_L1", "L2": "m_L2"},
                          checks=["json"], max_retry=1)
    assert out["ok"] and out["tier_used"] == "L1"
    assert log[:2] == ["m_L0", "m_L0"] and log[2] == "m_L1"


def test_repair_chain_exhausted_returns_best():
    """全档位耗尽 → ok=False 但保留最佳候选 (不空手)."""

    def task_fn(model, prompt):
        return "garbage"

    out = run_with_repair(task_fn, "输出 json", "L1",
                          {"L1": "m1", "L2": "m2"}, checks=["json"])
    assert not out["ok"] and out["output"] == "garbage" and out.get("exhausted")


# ── 自一致投票 ──────────────────────────────────────────────

def test_vote_json_majority():
    out = self_consistency_vote(['{"a":1}', '{"a":1}', '{"a":2}'], mode="json")
    assert out["ok"] and json.loads(out["output"])["a"] == 1
    assert out["agree"] == "2/3"


def test_vote_no_majority():
    out = self_consistency_vote(['{"a":1}', '{"b":2}', '{"c":3}'], mode="json")
    assert not out["ok"]


def test_vote_exact_mode():
    out = self_consistency_vote(["yes", "yes", "no"], mode="exact")
    assert out["ok"] and out["output"] == "yes"
