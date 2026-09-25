# -*- coding: utf-8 -*-
"""离线记忆兜底规则抽取守门 — 中英双语句式 (v3.131.14b).

自证 XK7 发现: 原规则只认中文句式, 英文用户 "Please remember..." 不触发
离线兜底记忆 — 11 语言产品的记忆兜底必须双语。
"""
from src.cli import _extract_user_facts
from src.chat_tools import _save_memory


def test_chinese_remember_triggers():
    facts = _extract_user_facts([
        {"role": "user", "content": "请记住：XK7-DELTA 部署窗口是周五 03:00 UTC"}])
    assert len(facts) == 1 and "XK7-DELTA" in facts[0]


def test_english_remember_triggers():
    facts = _extract_user_facts([
        {"role": "user", "content": "Please remember that the SABLE-KEY rotation is every 90 days"}])
    assert len(facts) == 1 and "SABLE-KEY" in facts[0]
    facts2 = _extract_user_facts([
        {"role": "user", "content": "Remember: LUMEN docs live in /srv/docs/lumen"}])
    assert len(facts2) == 1 and "LUMEN" in facts2[0]


def test_english_name_triggers():
    facts = _extract_user_facts([
        {"role": "user", "content": "My name is Priya and I own the rollback"}])
    assert facts and "Priya" in facts[0]


def test_plain_chat_does_not_trigger():
    facts = _extract_user_facts([
        {"role": "user", "content": "what is the weather today in Berlin?"}])
    assert facts == []


def test_save_memory_roundtrip(tmp_path, monkeypatch):
    """_save_memory 落盘往返 (HOME 沙盒) — 跨会话记忆的物理基础."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _save_memory("XK7-DELTA window 03:00 UTC Friday")
    from pathlib import Path
    f = Path(tmp_path) / ".meshctx" / "persistent_memory.json"
    assert f.exists()
    import json
    assert "XK7-DELTA window 03:00 UTC Friday" in json.loads(f.read_text(encoding="utf-8"))["entries"]
    # 去重: 同事实不重复
    _save_memory("XK7-DELTA window 03:00 UTC Friday")
    assert len(json.loads(f.read_text(encoding="utf-8"))["entries"]) == 1
