# -*- coding: utf-8 -*-
"""CLI 对话→记忆 自动写入管线回归测试（修复 cc0c9113: CLI 记忆从未落盘）

覆盖:
1. 规则式用户事实抽取（_extract_user_facts）—— 记住/我叫/我是/我的项目 等模式
2. 双通道自动保存（_auto_save_memory）:
   - 通道1 MemoryEngine(17脑区) 落盘 data/memories/*.json
   - 通道2 persistent_memory.json（build_system_prompt 实际读取）
3. build_system_prompt(include_memory=True) 同时读取两来源
4. 零阻塞: 异常输入/空对话不抛错
"""
import json
import os
import shutil
import tempfile

import pytest

from src.cli import _auto_save_memory, _extract_user_facts
from src.chat_tools import build_system_prompt

# 隔离 HOME，避免污染真实 ~/.meshctx
@pytest.fixture()
def iso_home(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="cli_mem_test_")
    os.makedirs(os.path.join(tmp, ".meshctx"), exist_ok=True)
    monkeypatch.setenv("HOME", tmp)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def _sample_messages():
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "记住我是做量化交易的"},
        {"role": "assistant", "content": "好的，已了解。"},
        {"role": "user", "content": "我叫李明，我的项目是meshctx"},
        {"role": "assistant", "content": "工具调用帧", "tool_calls": [{"id": "1"}]},
        {"role": "user", "content": "帮我查一下天气（噪声，不命中模式）"},
    ]


# ── 1. 规则抽取 ──────────────────────────────────────────

def test_extract_user_facts_zh_patterns(iso_home):
    """记住/我叫/我的项目 等中文模式命中"""
    facts = _extract_user_facts(_sample_messages())
    assert any("量化" in f for f in facts)          # 记住我...
    assert any("李明" in f for f in facts)          # 我叫...
    assert any("meshctx" in f for f in facts)       # 我的项目...
    # 噪声消息不应命中（不以模式开头）
    assert not any("天气" in f for f in facts)


def test_extract_user_facts_skips_tool_frames(iso_home):
    """assistant 工具调用帧不参与抽取（只看 user 消息）"""
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "run tool", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "output"},
    ]
    assert _extract_user_facts(msgs) == []


# ── 2. 双通道自动保存 ────────────────────────────────────

def test_auto_save_memory_dual_channel(iso_home):
    """通道1 MemoryEngine 落盘 + 通道2 persistent_memory.json 落盘"""
    _auto_save_memory(_sample_messages())

    # 通道2
    mem_file = os.path.join(iso_home, ".meshctx", "persistent_memory.json")
    assert os.path.exists(mem_file), "persistent_memory.json 应被创建"
    data = json.load(open(mem_file, encoding="utf-8"))
    assert any("量化" in e for e in data["entries"])

    # 通道1
    mem_dir = os.path.join(iso_home, ".meshctx", "data", "memories")
    files = [f for f in os.listdir(mem_dir) if f.endswith(".json")]
    assert files, "MemoryEngine 应有记忆落盘"
    mem = json.load(open(os.path.join(mem_dir, files[0]), encoding="utf-8"))
    assert mem.get("value"), "记忆 value 不应为空"


def test_auto_save_memory_empty_short(iso_home):
    """空/过短对话不落盘也不抛错（零阻塞）"""
    _auto_save_memory([])                       # 空
    _auto_save_memory([{"role": "user", "content": "hi"}])  # 单条
    _auto_save_memory(None)
    # 不抛错即为通过


# ── 3. build_system_prompt 读取两来源 ────────────────────

def test_build_system_prompt_reads_both_sources(iso_home):
    """系统提示同时包含 persistent_memory 与 MemoryEngine 记忆"""
    _auto_save_memory(_sample_messages())
    prompt = build_system_prompt(include_memory=True)
    assert "持久化记忆" in prompt
    assert "量化" in prompt  # 来自 persistent_memory.json（通道2）
    assert "李明" in prompt  # 来自 MemoryEngine 落盘记忆（通道1，关键词"记住"抽取）


def test_build_system_prompt_no_memory_files(iso_home):
    """无任何记忆文件时构建不报错"""
    prompt = build_system_prompt(include_memory=True)
    assert isinstance(prompt, str) and prompt
