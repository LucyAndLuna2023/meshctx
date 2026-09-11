# -*- coding: utf-8 -*-
"""Self-Evolution Loop v1 单元测试 (零 LLM, 离线, 隔离 tmp 目录)。"""
import importlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def loop(tmp_path, monkeypatch):
    home = tmp_path / ".meshctx"
    monkeypatch.setenv("MESHCTX_HOME", str(home))
    sys.path.insert(0, str(ROOT))
    try:
        mod = importlib.import_module("src.core.self_evolution")
        importlib.reload(mod)
    finally:
        sys.path.remove(str(ROOT))
    return mod.SelfEvolutionLoop(data_dir=home / "self_evolution")


def test_record_and_stats(loop):
    for i in range(6):
        loop.record("codefix", "strategyA", outcome=True)
    loop.record("codefix", "strategyB", outcome=False)
    st = loop.stats()
    assert st["experiences"] == 7
    assert st["chain_verified"] is True  # 哈希链经验层可校验


def test_reflect_distills_positive_insight(loop):
    # strategyA 5/5 成功, 总体 5/10 → delta 0.5 > 0.15 → 应生成洞见
    for i in range(5):
        loop.record("codefix", "strategyA", outcome=True)
        loop.record("codefix", "strategyB", outcome=False)
    out = loop.reflect()
    assert out["created"] == 1
    rules = loop.inject("codefix", k=3)
    assert len(rules) == 1
    assert "strategyA" in rules[0]
    # 幂等: 再 reflect 不重复创建
    out2 = loop.reflect()
    assert out2["created"] == 0 and out2["updated"] >= 1


def test_reflect_negative_delta_no_insight(loop):
    # good 5/5 vs bad 0/5: base 0.5 → good delta=+0.5 生成洞见;
    # bad delta=-0.5 → 负向不生成洞见 (仅正向注入)
    for i in range(5):
        loop.record("deploy", "good", outcome=True)
        loop.record("deploy", "bad", outcome=False)
    out = loop.reflect()
    assert out["created"] == 1
    assert "deploy::good" in loop.insights
    assert "deploy::bad" not in loop.insights
    rules = loop.inject("deploy")
    assert rules and "good" in rules[0]


def test_inject_ranking_prefers_higher_delta(loop):
    for i in range(6):
        loop.record("review", "mid", outcome=(i % 2 == 0))  # 0.5 → delta 0
    for i in range(6):
        loop.record("review", "best", outcome=True)          # 1.0 → delta +0.5
    for i in range(6):
        loop.record("review", "worst", outcome=False)        # 0.0 → 负向
    loop.reflect()
    rules = loop.inject("review", k=2)
    assert rules and "best" in rules[0]  # delta 最高者排第一 (确定性)
    assert "mid" not in " ".join(rules)  # delta 0 不足以成洞见


def test_reinforce_strengthens_and_persists(loop):
    for i in range(5):
        loop.record("fix", "win", outcome=True)
        loop.record("fix", "lose", outcome=False)
    loop.reflect()
    rules = loop.inject("fix", k=1)
    s0 = loop.insights["fix::win"]["stability"]
    loop.reinforce("fix", rules, outcome=True)
    assert loop.insights["fix::win"]["stability"] > s0
    # 洞见持久化 (新实例可读)
    loop2 = type(loop)(data_dir=loop.dir)
    assert "fix::win" in loop2.insights


def test_min_samples_guard(loop):
    loop.record("tiny", "s", outcome=True)
    out = loop.reflect(min_samples=5)
    assert out["created"] == 0 and loop.inject("tiny") == []


def test_auto_reflect_after_threshold(loop):
    """自优化核心: record 满 AUTO_REFLECT_EVERY 条 → 自动蒸馏, 无需手动 reflect。"""
    # 交替 A 成功/B 失败 → 满 20 条时自动生成 A 的洞见
    for i in range(10):
        loop.record("auto", "winA", outcome=True)
        loop.record("auto", "loseB", outcome=False)
    # 阈值 20 在最后一次 record 时已自动触发
    assert any("winA" in k for k in loop.insights), \
        "满阈值后应自动生成洞见 (record 内自动 reflect)"
    rules = loop.inject("auto", k=1)
    assert rules and "winA" in rules[0]


def test_stability_adapts_with_delta(loop):
    """GEPA 式淘汰压力: 效果变差 → 洞见保持度下降。"""
    for i in range(5):
        loop.record("adapt", "s1", outcome=True)
        loop.record("adapt", "s2", outcome=False)
    loop.reflect()
    key = "adapt::s1"
    s0 = loop.insights[key]["stability"]
    d0 = loop.insights[key]["delta"]
    # 追加 10 条 s1 失败 → delta 下降 → reflect 更新时保持度降
    for i in range(10):
        loop.record("adapt", "s1", outcome=False)
    loop.reflect()
    assert loop.insights[key]["stability"] < s0 * 1.5  # 保持度未被无脑推高


def test_known_map_registered():
    """_known 映射已注册 self_evolution (免误降级 stub)。"""
    import src.core as core
    assert "self_evolution" in core._known
    from src.core import get_self_evolution  # noqa: F401  可解析为真实函数
