# -*- coding: utf-8 -*-
"""night-6 (round33 P3-2): landing.json ↔ src 主 JSON 交叉键集断言。

背景: 主页动态加载 docs/i18n/landing.json, 应用页用 src/i18n_translations.json,
两侧键集互相独立 — 本测试钉住两侧的【语言覆盖一致性】与【各自内部键集 parity】,
防止任何一侧新增语言/掉键后另一侧静默漂移。
"""
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LANGS = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'it', 'ar', 'ru', 'he', "fa"]


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


# ── 004zcode v3.136.12 审计: RTL 三语齐守门 (fa 漏 4 处 + he 回归 1 处的类级防线) ──

def test_all_rtl_judgments_include_ar_he_fa():
    """全仓 dir/rtl 判定凡含 ar 必须同时含 he 与 fa (round46 he 漏判 + 本次 fa 漏 4 处
    + setup.html he 被后续改动挤掉的回归 — 扫描型守门防第五次同型)。"""
    import re
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    bad = []
    for d in ("templates", "src"):
        for p in (ROOT / d).rglob("*"):
            if p.suffix not in (".html", ".py"):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, ln in enumerate(text.splitlines(), 1):
                if ("rtl" in ln.lower() or "dir=" in ln) and "'ar'" in ln:
                    if "'fa'" not in ln and '"fa"' not in ln:
                        bad.append(f"{p.relative_to(ROOT)}:L{i}")
                    if "'he'" not in ln and '"he"' not in ln:
                        bad.append(f"{p.relative_to(ROOT)}:L{i} (缺 he)")
    assert not bad, f"RTL 判定漏 RTL 语言: {bad}"
