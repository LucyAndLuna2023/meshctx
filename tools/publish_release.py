#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 release ID 人工发布 meshctx draft release (v3.137.11, 002meshctx F-A 根修).

为什么必须按 ID: GitHub API 的 `PATCH /releases/tags/{tag}` 对 **draft** release 恒 404
(draft 不能用 tag 定位)。CI 里用 by-tag PATCH 的自动发布通道因此是结构性死步骤 —
本工具改为: 先按 tag 在 releases 列表里找到 draft 的 **id**, 再
`PATCH /releases/{id} {"draft": false}`。

安全约束 (与五方审计口径一致):
  1. 只发布 draft=true 且 published_at=null 的 release
  2. 发布前 final no-drift 三点: tag SHA / assets 数 / body 含版本号
  3. 缺省 dry-run; 必须显式 --apply 才真发布
  4. 发布后按 ID 复查 draft=false 且 assets 数不变 (不掉包)

用法:
    python3 tools/publish_release.py --tag v3.137.11                 # dry-run 检查
    python3 tools/publish_release.py --tag v3.137.11 --apply          # 真发布
    python3 tools/publish_release.py --tag v3.137.11 --apply --expect-assets 24

Token: 环境变量 GITHUB_TOKEN (需 repo 权限)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import hashlib
import re
import urllib.error
import urllib.request

API = "https://api.github.com"


def _req(path: str, tok: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"token {tok}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else {})


def find_draft(repo: str, tag: str, tok: str) -> dict:
    """按 tag 在 releases 列表里找 draft (by-tag 端点对 draft 恒 404)."""
    for page in range(1, 6):
        _, batch = _req(f"/repos/{repo}/releases?per_page=100&page={page}", tok)
        if not isinstance(batch, list) or not batch:
            break
        for rel in batch:
            if not rel.get("draft"):
                continue
            # draft 的 tag_name 会被 GitHub 重置成 untagged-*（身份脱钩）——
            # 此时用 release 的 name 字段回退匹配（CI/build 上传时 name 就是 tag）
            if rel.get("tag_name") == tag or rel.get("name") == tag:
                return rel
        if len(batch) < 100:
            break
    raise SystemExit(f"🔴 找不到 {tag} 的 draft release (by-tag 端点对 draft 恒 404, 已用列表扫描)")


def tag_sha(repo: str, tag: str, tok: str) -> str:
    _, ref = _req(f"/repos/{repo}/git/refs/tags/{tag}", tok)
    return ref["object"]["sha"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="LucyAndLuna2023/meshctx")
    ap.add_argument("--tag", required=True, help="例如 v3.137.11")
    ap.add_argument("--apply", action="store_true", help="真的发布 (缺省 dry-run)")
    ap.add_argument("--expect-assets", type=int, default=24, help="期望资产数 (默认24; 002codex/002meshctx B3: 不得以默认0跳过校验)")
    ap.add_argument("--expect-sha", default="", help="期望 tag SHA (前 12 位亦可)")
    args = ap.parse_args()

    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        print("🔴 需要 GITHUB_TOKEN 环境变量", file=sys.stderr)
        return 2

    rel = find_draft(args.repo, args.tag, tok)
    rid = rel["id"]
    body = rel.get("body") or ""
    sha = tag_sha(args.repo, args.tag, tok)
    ver = args.tag.lstrip("v")

    checks = {
        "draft=true": rel["draft"] is True,
        "published_at=null": rel.get("published_at") is None,
        f"tag_name={args.tag}": rel["tag_name"] == args.tag,
        "body 含版本号": ver in body,
        "body 含完整 40 位 SHA": sha in body,
        "assets 全部 uploaded": all(a.get("state") == "uploaded" for a in rel["assets"]),
    }
    if args.expect_assets:
        checks[f"assets={args.expect_assets}"] = len(rel["assets"]) == args.expect_assets
    if args.expect_sha:
        checks["tag SHA 匹配期望"] = sha.startswith(args.expect_sha)

    print(f"release ID = {rid} | tag = {rel['tag_name']} | assets = {len(rel['assets'])}")
    print(f"tag SHA    = {sha}")
    for k, v in checks.items():
        print(f"  [{'✓' if v else '✗'}] {k}")
    if not all(checks.values()):
        print("🔴 final no-drift 未过 — 拒绝发布")
        return 1

    # F-E (002meshctx): 资产 SHA256 清单 — 发布前后都可复核 (sidecar .sha256 为 CI 生成值)
    sidecars = {a["name"]: a for a in rel["assets"] if a["name"].endswith(".sha256")}
    if sidecars:
        print(f"\n资产 SHA256 对 (sidecar {len(sidecars)} 个):")
        for name in sorted(sidecars)[:6]:
            print(f"  {name}")
        if len(sidecars) > 6:
            print(f"  … 共 {len(sidecars)} 对 (binary/sidecar 一一对应)")

    if not args.apply:
        print("\n(dry-run) 校验全过。加 --apply 执行:\n"
              f"  PATCH /releases/{rid} {{'draft': false}}")
        return 0

    before_ids = sorted(a["id"] for a in rel["assets"])

    # ═══ v3.137.14 (002codex B3 终版): sidecar digest 交叉校验 MUST happen BEFORE PATCH ═══
    # 旧版交叉校验在 PATCH 之后才跑 (只打印不阻断) — 002codex 四探针 RC=0 证实。
    # 现: PATCH 前逐 binary 下载 sidecar 并与 GitHub API asset.digest 交叉比对。
    import hashlib as _hl
    import time as _t

    digest_failures = []
    binary_to_sidecar_digest = {}
    for a in sorted(rel["assets"], key=lambda x: x["name"]):
        if a["name"].endswith(".sha256"):
            continue
        sc = next((x for x in rel["assets"] if x["name"] == a["name"] + ".sha256"), None)
        if not sc:
            digest_failures.append(f"{a['name']}: 缺 sidecar")
            continue
        try:
            # v3.137.15 补: draft 资产的 browser_download_url 恒 404 (未公开),
            # 必须走 API 端点 /releases/assets/{id} (Accept: application/octet-stream)
            api_url = f"https://api.github.com/repos/{args.repo}/releases/assets/{sc['id']}"
            with urllib.request.urlopen(urllib.request.Request(
                    api_url,
                    headers={"Authorization": f"token {tok}",
                             "Accept": "application/octet-stream"})) as r:
                sidecar_digest = r.read().decode().strip().split()[0]
        except Exception as e:
            digest_failures.append(f"{a['name']}: sidecar 下载失败 {e}")
            continue
        gh_digest = ""
        if a.get("digest"):
            gh_digest = a["digest"].split(":")[-1] if ":" in a["digest"] else a["digest"]
        if not sidecar_digest or len(sidecar_digest) != 64:
            digest_failures.append(f"{a['name']}: sidecar digest 无效 ({sidecar_digest[:20]})")
        elif gh_digest and sidecar_digest.lower() != gh_digest.lower():
            digest_failures.append(f"{a['name']}: sidecar={sidecar_digest[:12]} ≠ GH={gh_digest[:12]}")
        else:
            binary_to_sidecar_digest[a["name"]] = sidecar_digest

    if digest_failures:
        print("🔴 B3 交叉校验失败 — 拒绝发布:")
        for df in digest_failures:
            print(f"  ❌ {df}")
        return 1
    print(f"  [✓] B3 交叉校验: {len(binary_to_sidecar_digest)} 个 binary 的 sidecar digest 全部一致")

    # ═══ PATCH draft:false (仅在全部校验通过后) ═══
    status, res = _req(f"/repos/{args.repo}/releases/{rid}", tok, "PATCH", {"draft": False})
    print(f"\nPATCH status={status} | draft={res.get('draft')} | published_at={res.get('published_at')}")

    _, after = _req(f"/repos/{args.repo}/releases/{rid}", tok)
    after_ids = sorted(a["id"] for a in after["assets"])
    post = {
        "按 ID 复查 draft=false": after["draft"] is False,
        "published_at 非空": bool(after.get("published_at")),
        f"assets 仍 {len(before_ids)} (不掉包)": len(after["assets"]) == len(before_ids),
        "asset IDs 零漂移": after_ids == before_ids,
        "name/size 零漂移": all(
            (a["id"], a["size"]) in {(x["id"], x["size"]) for x in after["assets"]}
            for a in rel["assets"]
        ),
    }
    for k, v in post.items():
        print(f"  [{'✓' if v else '✗'}] {k}")
    if not all(post.values()):
        print("🔴 发布后复查失败 — 立即人工介入")
        return 1

    # v3.137.12 (002zcode F-E 终版): --apply 后自动 append 资产 SHA256 清单到 body
    digest_by_name = {}
    for a in sorted(after["assets"], key=lambda x: x["name"]):
        if a["name"].endswith(".sha256"):
            continue
        sc = next((x for x in after["assets"] if x["name"] == a["name"] + ".sha256"), None)
        digest = ""
        if sc:
            import time as _t2
            for _attempt in range(3):
                try:
                    api_url = f"https://api.github.com/repos/{args.repo}/releases/assets/{sc['id']}"
                    with urllib.request.urlopen(urllib.request.Request(
                            api_url,
                            headers={"Authorization": f"token {tok}",
                                     "Accept": "application/octet-stream"})) as r:
                        digest = r.read().decode().strip().split()[0]
                    break
                except Exception:
                    if _attempt == 2:
                        pass
                    _t2.sleep(2)
        digest_by_name[a["name"]] = digest
    sha_list_lines = []
    for a in sorted(after["assets"], key=lambda x: x["name"]):
        if a["name"].endswith(".sha256"):
            continue
        d = digest_by_name.get(a["name"], "")
        sha_list_lines.append(f"- `{a['name']}`  `{d}`")
    sha_block = "\n\n## 资产 SHA256 (发布时固化)\n" + "\n".join(sha_list_lines)
    new_body = (after.get("body") or "") + sha_block
    _, updated = _req(f"/repos/{args.repo}/releases/{rid}", tok, "PATCH",
                      {"body": new_body})
    import re as _re
    n64 = len(_re.findall(r"[0-9a-f]{64}", updated["body"]))
    n_binaries = len([a for a in after['assets'] if not a['name'].endswith('.sha256')])
    print(f"  [{'✓' if n64 >= n_binaries else '✗'}] body 已附资产 SHA256 清单 ({n64}/{n_binaries} 个 64 位摘要)")
    ubh = hashlib.sha256(updated["body"].encode()).hexdigest()
    print(f"  ℹ body 已更新 (len={len(updated['body'])}, sha256={ubh[:16]}…) — 此变更已披露")

    print(f"\n🟢 {args.tag} 已发布 (release ID {rid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
