# -*- coding: utf-8 -*-
"""version_bump.py 功能守门 — round61 P2-3 三缺陷的行为级锁定 (002zcode 补).

在 tmp 树内跑真实工具进程, 锁定:
① DESKTOP_VERSION 带v前缀精确替换生效 (P2-3a: 原正则吃前缀致 replace 目标失配永不生效)
② 残留扫描注释行豁免 — 自身注释含旧版本号不再自锁 (P2-3b)
③ 功能性 (非注释) 残留仍必 exit1 (扫描不因豁免而失明)
"""
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "version_bump.py"


def _run_bump(tmp_path, desktop_version, extra_files):
    (tmp_path / "meshctx_desktop.py").write_text(
        f'HOST = "127.0.0.1"\nDESKTOP_VERSION = "{desktop_version}"\n', encoding="utf-8")
    for name, content in extra_files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(TOOL), "3.133.2", "3.134.0"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)


def test_desktop_version_replace_with_v_prefix(tmp_path):
    """P2-3a: DESKTOP_VERSION="v3.133.2" 必须 bump 到 v3.134.0 且 HOST 分毫不动."""
    r = _run_bump(tmp_path, "v3.133.2", {})
    assert r.returncode == 0, r.stdout + r.stderr
    t = (tmp_path / "meshctx_desktop.py").read_text(encoding="utf-8")
    assert 'DESKTOP_VERSION = "v3.134.0"' in t, "v前缀版本未被替换 (P2-3a 回归)"
    assert 'HOST = "127.0.0.1"' in t, "HOST 被 bump 污染 (I-8 同族事故回归)"


def test_comment_lines_exempt_no_selflock(tmp_path):
    """P2-3b: 注释行 (# // <!--) 含旧版本号 → 不算残留, 工具可完成 bump (exit 0)."""
    r = _run_bump(tmp_path, "v3.133.2", {
        "src/mod.py": "# v3.133.2: 历史注释\nX = 1\n",
        "templates/p.html": "<!-- v3.133.2: 审计注释 -->\n<span>ok</span>\n",
        "tools/t.js.txt": "// v3.133.2: js 注释形态\n",
    })
    assert r.returncode == 0, f"注释豁免失效仍自锁: {r.stdout}"
    assert "残留 0" in r.stdout


def test_functional_residue_still_exits_1(tmp_path):
    """P2-3c 反向: 非注释行的功能性版本串必须 exit1 — 豁免不得让扫描失明."""
    r = _run_bump(tmp_path, "v3.133.2", {
        "src/live.py": "VERSION_FALLBACK = '3.133.2'  # 功能串\n",
    })
    assert r.returncode == 1, "功能性残留未被拦截"
    assert "src/live.py" in r.stdout
