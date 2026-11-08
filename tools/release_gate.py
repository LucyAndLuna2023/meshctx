#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 发版门禁 (release gate) — v3.135.5 落地, 002meshctx round71-74 催办 (应验 8 次).

pre-tag 四检 (任何一项失败 exit 1, 阻断 tag/push):
  1. 版本对位: 六资产逐文件含当前版本号 (bump 原子中止/tag 错位九犯根治)
  2. CHANGELOG: 头部含当前版本条目 (七/八/九犯根治)
  3. 测试绿: 定向守门跑通 (task_cards+G10+cascade)
  4. KNOWN_ISSUES: 新挂账须在仓内台账 (002codex 阻断②根治)

用法: python3 tools/release_gate.py 3.135.5   (tag 前跑)
"""
import pathlib
import re
import subprocess
import sys

VER = sys.argv[1] if len(sys.argv) > 1 else ""
if not re.fullmatch(r"\d+\.\d+\.\d+", VER or ""):
    print("用法: release_gate.py X.Y.Z"); sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
fail = []

# 1. 版本对位 (六资产)
assets = {
    "pyproject.toml": f'version = "{VER}"',
    "package.json": f'"version": "{VER}"',
    "src/__init__.py": f'__version__ = "{VER}"',
    "install.sh": f'VERSION="{VER}"',
    "install-mac.sh": f'VERSION="{VER}"',
    "meshctx_desktop.py": f'DESKTOP_VERSION = "v{VER}"',
}
for f, needle in assets.items():
    t = (ROOT / f).read_text(encoding="utf-8", errors="replace")
    ok = needle in t
    print(f"  [{'✓' if ok else '✗'}] 版本对位 {f}: {needle}")
    if not ok:
        fail.append(f"版本错位: {f}")

# 2. CHANGELOG 条目
ch = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
ok = f"## [v{VER}]" in ch
print(f"  [{'✓' if ok else '✗'}] CHANGELOG [v{VER}] 条目")
if not ok:
    fail.append(f"CHANGELOG 缺 [v{VER}] 条目 (九犯线)")

# 3. 定向守门
r = subprocess.run([sys.executable, "-m", "pytest",
                    "tests/test_task_cards.py", "tests/test_project_integrity.py",
                    "tests/test_cascade_router.py", "-q", "-o", "addopts="],
                   cwd=ROOT, capture_output=True, text=True, timeout=600)
ok = r.returncode == 0
tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else "(无输出)"
print(f"  [{'✓' if ok else '✗'}] 定向守门: {tail[:70]}")
if not ok:
    fail.append(f"定向守门红: {tail[:80]}")

# 4. KNOWN_ISSUES 在位 (仓内台账载体)
ki = ROOT / "KNOWN_ISSUES.md"
ok = ki.exists() and len(ki.read_text(encoding="utf-8", errors="replace")) > 100
print(f"  [{'✓' if ok else '✗'}] KNOWN_ISSUES.md 台账在位")
if not ok:
    fail.append("KNOWN_ISSUES.md 缺失")

# post-tag 第五检 — 真实现 (v3.135.6, 002codex 2dfbcd60): --post-tag 模式
# 用法: python3 tools/release_gate.py X.Y.Z --post-tag  (tag+push 后跑)
# v3.137.20 (002codex P4 "--post-tag 未接 CI"): CI 阶段专用模式 —
# 此时 draft body 尚未填写 (派单阶段才填), 完整 --post-tag 的 body 校验必然失败。
# --post-tag-ci 只校验 CI 阶段可判定的项: tag 锚 (rev-parse returncode) + draft assets uploaded。
if "--post-tag-ci" in sys.argv:
    import json as _json, urllib.request as _ur
    # v3.137.20 补: GITHUB_TOKEN 创建的 draft 对其他 token 不可见 (GitHub 隔离机制) —
    # 必须用创建方同源 PAT (MESHCTX_RELEASE_PAT secret) 才能扫到 draft
    tok = __import__("os").environ.get("MESHCTX_RELEASE_PAT") or __import__("os").environ.get("GITHUB_TOKEN", "")
    if not tok:
        print("🔴 需要 GITHUB_TOKEN env (post-tag-ci)"); sys.exit(1)
    _rp = subprocess.run(["git", "rev-parse", f"v{VER}^{{commit}}"], cwd=ROOT,
                         capture_output=True, text=True)
    tag_sha = _rp.stdout.strip() if _rp.returncode == 0 else ""
    c_sha = __import__("os").environ.get("C_SHA", "")
    if not tag_sha:
        print(f"  [✗] tag v{VER} 不存在 (RC={_rp.returncode}) — fail-closed"); sys.exit(1)
    ok_anchor = (not c_sha) or (tag_sha == c_sha)
    print(f"  [{'✓' if ok_anchor else '✗'}] tag^{{commit}} == C_SHA: {tag_sha[:12]}")
    draft_found = None
    total_seen = 0
    for page in range(1, 4):
        req = _ur.Request(f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases?per_page=100&page={page}",
                          headers={"Authorization": f"token {tok}"})
        raw = _ur.urlopen(req).read().decode()
        batch = _json.loads(raw)
        if not isinstance(batch, list):
            print(f"  [debug] releases page{page} 非列表: {raw[:120]}"); break
        if not batch:
            print(f"  [debug] releases page{page} 空"); break
        total_seen += len(batch)
        for rel in batch:
            tag_n, rel_n = rel.get("tag_name"), rel.get("name")
            if rel.get("draft"):
                print(f"  [debug] draft 可见: tag_name={tag_n!r} name={rel_n!r} target={rel.get('target_commitish','')!r}")
            if rel.get("draft") and (tag_n == f"v{VER}" or rel_n == f"v{VER}"):
                draft_found = rel; break
        if draft_found: break
    print(f"  [debug] 扫描 releases 总数={total_seen}, 目标 v{VER}")
    ok_draft = draft_found is not None
    ok_assets = ok_draft and len(draft_found["assets"]) == 24 and all(
        a.get("state") == "uploaded" for a in draft_found["assets"])
    print(f"  [{'✓' if ok_draft else '✗'}] draft 存在 (tag_name 或 name 匹配)")
    print(f"  [{'✓' if ok_assets else '✗'}] 24 assets 全 uploaded (body 校验留待派单阶段 --post-tag)")
    if not (ok_anchor and ok_draft and ok_assets):
        print("\n🔴 post-tag-ci 拦截"); sys.exit(1)
    print("\n🟢 post-tag-ci 过 (CI 阶段可判定项全过; body 校验由派单阶段 --post-tag 承担)")
    sys.exit(0)

# v3.137.18 (002codex F1-2): pre-tag 失败先拦截 — post-tag 分支不再绕过 pre-tag ✗
if fail and "--post-tag" in sys.argv:
    for x in fail:
        print(f"  ✗ (pre-tag, post-tag 前拦截): {x}")
    print(f"\n🔴 post-tag 拦截 — pre-tag 失败 {len(fail)} 项未清 (不得绕过)")
    sys.exit(1)
if "--post-tag" in sys.argv:
    import json as _json
    import urllib.request as _ur
    tok = __import__("os").environ.get("GITHUB_TOKEN", "")
    if not tok:
        print("🔴 需要 GITHUB_TOKEN env (post-tag 检查)"); sys.exit(1)
    req = _ur.Request(
        f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases?per_page=20",
        headers={"Authorization": f"token {tok}"})
    ds = _json.loads(_ur.urlopen(req, timeout=30).read())
    # v3.136.8 修复: draft release 不出现在 tags 端点 (404) — 走列表端点按 tag 匹配
    _match = [r for r in ds if r.get("tag_name") == f"v{VER}"]
    if not _match:
        print(f"🔴 v{VER} release 未创建"); sys.exit(1)
    d = _match[0]
    body = d.get("body") or ""
    # v3.137.15 (002codex 阻断1 + 004meshctx P3): HEAD-only 盲区根修 —
    # post-tag 模式下以 tag^{commit} 为锚 (HEAD 可能领先 tag); HEAD+tag 双校验
    # v3.137.16 (002codex 发布后审计): fail-closed —
    # ① tag 不存在 → 直接红 (不得回退 HEAD; 旧 `tag_sha or head_sha` 是盲区)
    # ② tag 存在但 HEAD≠tag → 仅提示 (main 领先 tag 是常态), 锚点以 tag 为准
    # v3.137.18 (002codex F1): rev-parse 必须查 returncode —
    # 缺失 tag 时 RC=128 但 stdout 非空 (字面量参数), 仅查 stdout 会使 fail-closed 成死代码
    _rp = subprocess.run(["git", "rev-parse", f"v{VER}^{{commit}}"], cwd=ROOT,
                         capture_output=True, text=True)
    tag_sha = _rp.stdout.strip() if _rp.returncode == 0 else ""
    head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    if not tag_sha:
        print(f"  [✗] tag v{VER} 不存在 (rev-parse RC={_rp.returncode}) — post-tag fail-closed (不回退 HEAD)")
        print(f"\n🔴 post-tag 第五/六检拦截 — tag v{VER} 缺失, 锚点不可用")
        sys.exit(1)
    full = tag_sha
    ok_body = bool(body)
    ok_sha = full and full in body
    print(f"  [{'✓' if ok_body else '✗'}] release body 非空 ({len(body)}c)")
    print(f"  [{'✓' if ok_sha else '✗'}] body 含 tag^{{commit}} 完整 40 位 SHA: {full[:12]}...")
    if head_sha != tag_sha:
        print(f"  [ℹ] HEAD ({head_sha[:12]}) 领先 tag ({tag_sha[:12]}) — main 常态, 锚点以 tag 为准")
    # v3.136.9 第六检 (002meshctx 传承: body 空正/负例 — 空 body 曾上线)
    has_version = f"v{VER}" in body or VER in body
    print(f"  [{'✓' if has_version else '✗'}] body 含版本号 v{VER}")
    if not (ok_body and ok_sha and has_version):
        print(f"\n🔴 post-tag 第五/六检拦截 — body 需含真实 SHA {full} 与版本号 v{VER}")
        sys.exit(1)
    print("\n🟢 post-tag 第五/六检过")
    sys.exit(0)

if fail:
    print(f"\n🔴 发版门禁拦截 ({len(fail)} 项):")
    for x in fail:
        print(f"  - {x}")
    sys.exit(1)
print(f"\n🟢 发版门禁全过 — {VER} 可 tag")
