# -*- coding: utf-8 -*-
"""night-6 (round33 P3-2): landing.json ↔ src 主 JSON 交叉键集断言。

背景: 主页动态加载 docs/i18n/landing.json, 应用页用 src/i18n_translations.json,
两侧键集互相独立 — 本测试钉住两侧的【语言覆盖一致性】与【各自内部键集 parity】,
防止任何一侧新增语言/掉键后另一侧静默漂移。
"""
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LANGS = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'it', 'ar', 'ru', 'he']


def _load():
    landing = json.loads((PROJECT / "docs" / "i18n" / "landing.json").read_text(encoding="utf-8"))
    src = json.loads((PROJECT / "src" / "i18n_translations.json").read_text(encoding="utf-8"))
    return landing, src


def test_language_coverage_matches_across_landing_and_src():
    """两侧语言集必须完全一致 (含 RTL 的 he) — 任何一侧新增/删语言须同步。"""
    landing, src = _load()
    assert set(landing.keys()) == set(LANGS), f"landing langs drifted: {sorted(landing)}"
    assert set(src.keys()) == set(LANGS), f"src langs drifted: {sorted(src)}"


def test_landing_internal_keyset_parity():
    """landing.json 每语言键集 == en 键集 (内部 parity, 掉键立即红)。"""
    landing, _ = _load()
    en_keys = set(landing["en"].keys())
    assert en_keys, "landing en 键集为空"
    for lang, table in landing.items():
        missing = en_keys - set(table.keys())
        extra = set(table.keys()) - en_keys
        assert not missing and not extra, (
            f"landing[{lang}] parity broken: missing={sorted(missing)[:5]} extra={sorted(extra)[:5]}")


def test_src_internal_keyset_parity_with_landing_lang_set():
    """src 主 JSON 键集 parity + 与 landing 语言集交叉 (round33 P3-2 主断言)。"""
    landing, src = _load()
    assert set(landing.keys()) == set(src.keys())
    en_keys = set(src["en"].keys())
    assert len(en_keys) > 1000, f"src en 键数异常: {len(en_keys)}"
    for lang, table in src.items():
        assert set(table.keys()) == en_keys, f"src[{lang}] parity broken"
