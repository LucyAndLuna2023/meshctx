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


# ── 004zcode (codex 025dd371 复审 P2 现场修正): 语言清单恒等守门 ──

def test_available_langs_match_language_keys():
    """每语言 __available_langs__ 的 code 集必须与词典语言键集恒等.

    历史: fa 缺 (45fad371 树, codex 实证) → v3.136.14 补 fa 但 ru 仍缺 (11 语言
    时代的历史缺口) — 新语言接入时清单"补新忘旧"的同型第二犯, 本守门恒等断言根除。"""
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "src" / "i18n_translations.json")
                      .read_text(encoding="utf-8"))
    langs = set(data.keys())
    bad = []
    for lang, tbl in data.items():
        al = tbl.get("__available_langs__")
        if not isinstance(al, list):
            continue
        codes = {e.get("code") for e in al if isinstance(e, dict)}
        if codes != langs:
            bad.append(f"{lang}: 清单 {sorted(codes - langs)} 多 / {sorted(langs - codes)} 缺")
    assert not bad, f"__available_langs__ 与语言键集不恒等: {bad}"


# ── codex v3.136.17 放行要求: 生产渲染语言下拉持久守门 (第三层, 静态/双源守门覆盖不到) ──

def test_production_lang_selects_render_12():
    """TestClient 实渲染三入口的下拉必须 12 语言齐 (值集恒等词典键集).

    层次: 静态模板守门 (双源一致) → 本测试 (真渲染输出) — 内嵌 base/独立 base/
    chat/setup 三路径全测; v3.136.15 曾现 '静态 12 项但生产渲染 10 项缺 he/fa'。"""
    import re as _re
    from fastapi.testclient import TestClient
    from src.main import app

    client = TestClient(app)
    import json as _json
    from pathlib import Path as _P
    langs = set(_json.loads((_P(__file__).resolve().parent.parent / "src" / "i18n_translations.json")
                            .read_text(encoding="utf-8")).keys())
    cases = [("/ui/chat", "langSelect"), ("/ui/setup", "setupLangSelect")]
    for path, sel_id in cases:
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code}"
        html = r.text
        m = _re.search(rf'<select[^>]*id="{sel_id}"[^>]*>(.*?)</select>', html, _re.S)
        assert m, f"{path} 未找到 #{sel_id}"
        values = set(_re.findall(r'<option[^>]*value="([a-z]{2})"', m.group(1)))
        assert values == langs, f"{path} #{sel_id}: 渲染 {sorted(values)} != 词典 {sorted(langs)} (缺 {sorted(langs - values)})"
