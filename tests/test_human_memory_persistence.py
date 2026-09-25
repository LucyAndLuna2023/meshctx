# -*- coding: utf-8 -*-
"""仿脑记忆引擎持久化守门 (v3.131.15, 用户拍板).

原 HumanLikeMemory 纯内存 — 重启即失忆 (离线自证 XK7 发现)。
现: encode/replay 后原子落盘, get_human_memory 单例首建自动 load。
"""
import pytest

from src.core.human_memory import HumanLikeMemory, get_human_memory, EmotionIntensity


@pytest.fixture()
def sandbox_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # 单例可能已被其他测试创建 — 重置并隔离
    import src.core.human_memory as hm
    monkeypatch.setattr(hm, "_human_memory_instance", None)
    return tmp_path


def test_encode_survives_new_process(sandbox_home):
    """encode → 落盘 → 全新实例 (模拟重启) → recall 命中"""
    m1 = get_human_memory()
    m1.encode("XK7-DELTA deployment window is 03:00 UTC Friday",
              EmotionIntensity.IMPORTANT, {"deploy"})
    assert m1.save() is True
    # 模拟跨进程: 重置单例 + 全新实例
    import src.core.human_memory as hm
    hm._human_memory_instance = None
    m2 = get_human_memory()
    assert m2.total_chunks == 1
    hits = m2.recall("XK7-DELTA deployment")
    assert any("xk7" in c.pattern.lower() and "delta" in c.pattern.lower() for c in hits)  # pattern 为分词序列


def test_dedup_reconsolidate_persists(sandbox_home):
    m1 = get_human_memory()
    c1 = m1.encode("alpha beta gamma", EmotionIntensity.NEUTRAL)
    c2 = m1.encode("alpha beta gamma", EmotionIntensity.CRITICAL)  # 同模式 → 重巩固
    assert c1.id == c2.id and c2.recall_count >= 1
    # 重巩固已落盘: 新实例读回 recall_count
    import src.core.human_memory as hm
    hm._human_memory_instance = None
    m2 = get_human_memory()
    assert m2._chunks[c1.id].recall_count >= 1


def test_force_replay_persists_strength(sandbox_home):
    m1 = get_human_memory()
    m1.encode("strong memory delta", EmotionIntensity.CRITICAL)
    before = m1._chunks["mem_1"].strength
    m1.force_replay()
    import src.core.human_memory as hm
    hm._human_memory_instance = None
    m2 = get_human_memory()
    assert m2._chunks["mem_1"].strength == pytest.approx(
        min(1.0, before * 1.05))


def test_atomic_write_no_tmp_left(sandbox_home):
    m = get_human_memory()
    m.encode("persist check charlie", EmotionIntensity.NEUTRAL)
    p = HumanLikeMemory._persistence_path()
    assert p.exists() and not p.with_suffix(".json.tmp").exists()


def test_load_missing_file_returns_false(sandbox_home):
    m = HumanLikeMemory()
    assert m.load() is False  # 无文件不抛错
    assert m.total_chunks == 0
