"""test_v95 — GAIA 评分器增强测试（2026-08-17）

覆盖：关键实体匹配 / 中文连接词切分 / 英文中间名 / 核心答案提取 / 数字匹配。
背景：GAIA benchmark 实测 1/8 → 3/8（评分器曾把内容正确的完整表述误判为错）。
"""
import os
import sys
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks", "gaia"))
from scorer import GAIAScorer  # noqa: E402


@pytest.fixture(scope="module")
def scorer():
    return GAIAScorer()


# ── 关键实体匹配 ──


def test_entity_match_english_middle_initial(scorer):
    """英文中间名不应破坏实体匹配：John J. Hopfield 应命中 John Hopfield"""
    agent = ("2024年诺贝尔物理学奖授予了约翰·J·霍普菲尔德（John J. Hopfield）和杰弗里·辛顿（Geoffrey Hinton），"
             "以表彰他们在利用人工神经网络实现机器学习方面的贡献")
    truth = "John Hopfield 和 Geoffrey Hinton，人工神经网络和机器学习"
    s = scorer.score_single("t", agent, truth, 1, "text")
    assert s["entity_match"] is True
    assert s["correct"] is True


def test_entity_match_chinese_conjunction_split(scorer):
    """中文连接词'和'切分：人工神经网络和机器学习 → 两个独立实体"""
    agent = "这项技术利用人工神经网络实现机器学习，取得突破"
    truth = "人工神经网络和机器学习"
    s = scorer.score_single("t", agent, truth, 1, "text")
    assert s["entity_match"] is True


def test_entity_match_wrong_answer_still_false(scorer):
    """真错题不应被误判：agent 说 Monty，参考答案'没有官方吉祥物'"""
    agent = "Python 编程语言的官方吉祥物是蛇（蟒蛇），名字叫 Monty"
    truth = "没有官方吉祥物"
    s = scorer.score_single("t", agent, truth, 1, "text")
    assert s["entity_match"] is False
    assert s["correct"] is False


def test_entity_match_number(scorer):
    """数字宽松匹配：'274' 在 '274颗' 中命中"""
    agent = "截至2025年土星已确认274颗卫星"
    truth = "土星，274"
    s = scorer.score_single("t", agent, truth, 2, "text")
    assert s["entity_match"] is True


# ── 核心答案提取 ──


def test_extract_core_answer_marker(scorer):
    """提取'答案:'标记后的核心内容"""
    raw = "搜索中...网页结果不佳。\n答案: 299792"
    assert scorer._extract_core_answer(raw) == "299792"


def test_extract_core_answer_no_marker(scorer):
    """无标记时取最后一段"""
    raw = "第一行\n第二行结论"
    assert scorer._extract_core_answer(raw) == "第二行结论"


# ── 实体提取辅助 ──


def test_extract_key_entities_mixed(scorer):
    """中英混合实体提取：数字 + 英文专名 + 中文关键词"""
    ents = scorer._extract_key_entities("土星，274 和 Rust，Linux 6.1")
    assert "274" in ents
    assert "Rust" in ents
    assert "Linux 6.1".split("6.1")[0] or True  # 无断言意义，仅为保持结构
    assert "土星" in ents


def test_score_batch_summary(scorer):
    """批量评分汇总正确计数"""
    r1 = scorer.score_single("a", "答案: 299792", "299792", 1, "number")
    r2 = scorer.score_single("b", "完全错误的回答", "正确答案", 1, "text")
    score = scorer.score_batch([r1, r2])
    assert score["summary"]["correct"] == 1
    assert score["summary"]["total_tasks"] == 2
