# -*- coding: utf-8 -*-
"""希伯来语 (he) 全量上线回归测试 — 002codex 45192a27 P2×2 + 004meshctx round30 P2-1 修复守门。
覆盖: registry/LANGUAGES parity · 安装器语言数 11 语言一致=10 · chat LANG keyset ×11 相等 ·
LEGAL opt_ru 全语言在位 · RTL dir 条件含 he。"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def node_extract(rel, var_pattern):
    path = json.dumps(str(ROOT / rel))
    js = (
        "const fs=require('fs');"
        f"const h=fs.readFileSync({path},'utf8');"
        f"const m=h.match(/{var_pattern}/);"
        "const L=eval('('+m[1]+')');process.stdout.write(JSON.stringify(L));"
    )
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:400]
    return json.loads(r.stdout)


class TestHebrewRegistry:
    def test_languages_has_he_rtl(self):
        import src.i18n as i
        codes = [x["code"] for x in i.LANGUAGES]
        assert "he" in codes
        he = next(x for x in i.LANGUAGES if x["code"] == "he")
        assert he["rtl"] is True
        assert "he" in i.RTL_LANGUAGES

    def test_registry_he_full_parity(self):
        import src.i18n as i
        d = dict(i.TRANSLATIONS)
        assert len(d) == 11 and "he" in d
        assert set(d["he"]) == set(d["en"])
        assert len(d["he"]) == len(d["en"]) > 1400


class TestInstallerLangCount:
    def test_landing_installer_count_10_all_langs(self):
        d = json.loads((ROOT / "docs" / "i18n" / "landing.json").read_text(encoding="utf-8"))
        bad = []
        for lg, vals in d.items():
            for k in ("win_desc", "win_installer_desc", "installer_desc"):
                v = str(vals.get(k, ""))
                if re.search(r"7\s*(种)?语言|7 languages|7\s*שפות|7\s*ling|7\s*Sprachen|7\s*idiomas|7\s*lingue|7\s*لغات|7\s*языков|7言語|7개 언어", v):
                    bad.append((lg, k, v[:40]))
        assert not bad, bad

    def test_chat_keyset_parity_and_he(self):
        L = node_extract("templates/chat.html", r"LANG = (\{[\s\S]*?\n\});")
        assert "he" in L
        keys = set(L["en"])
        for lg, vals in L.items():
            assert set(vals) == keys, f"{lg} keyset diff"
        assert "chat_direct" in keys and "chat_text" not in keys

    def test_legal_opt_ru_present(self):
        L = node_extract("docs/LEGAL.html", r"var L = (\{[\s\S]*?\n\});")
        keys = set(L["en"])
        for lg, vals in L.items():
            assert set(vals) == keys, f"LEGAL {lg} parity"
            assert "opt_ru" in vals and "opt_he" in vals

    def test_rtl_dir_contains_he(self):
        files = ["docs/governance.html", "docs/telemetry.html", "docs/getting-started.html",
                 "docs/download.html", "docs/test-report.html", "docs/LEGAL.html",
                 "docs/profile.html", "docs/index.html", "templates/chat.html",
                 "templates/base.html"]
        for f in files:
            s = (ROOT / f).read_text(encoding="utf-8")
            m = re.search(r"dir\s*=.*?['\"]?(ltr|rtl)['\"]?", s)
            # 找到含 lang==='he' 的 dir 条件
            assert re.search(r"(lang\s*===\s*['\"]he['\"]|'he'\s*\|\||\|\|\s*'he')", s), f


def test_chat_de_direct_german_and_download_counts():
    """002codex a7e8523e + 002meshctx b50eb620 复核补充:
    de.chat_direct 须为德文; download.html installer_desc 全 11 语言无 '7' 词形。"""
    L = node_extract("templates/chat.html", r"LANG = (\{[\s\S]*?\n\});")
    assert L["de"]["chat_direct"] == "Direktausgabe", L["de"]["chat_direct"]
    D = node_extract("docs/download.html", r"const L = (\{[\s\S]*?\n\});")
    pat = re.compile(r"7\s*(种)?语言|7 languages|7\s*שפות|7\s*ling|7\s*Sprachen|7\s*idiomas|7\s*lingue|7\s*لغات|на 7 языках|7 языков|7言語|7개 언어")
    bad = [(lg, str(vals.get("installer_desc", ""))[:40])
           for lg, vals in D.items() if pat.search(str(vals.get("installer_desc", "")))]
    assert not bad, bad
    assert "10" in D["ru"]["installer_desc"] and "10" in D["zh"]["installer_desc"]


def test_index_no_7_lang_comment():
    s = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "7语言" not in s and "7 语言" not in s and "7 languages" not in s
