#!/usr/bin/env python3
"""meshctx 版本发布工具 — 一键 bump + 同步 + tag + GitHub Release

用法:
  python3 tools/release.py patch          # 自动 bump 小版本
  python3 tools/release.py minor          # 自动 bump 中版本
  python3 tools/release.py major          # 自动 bump 大版本
  python3 tools/release.py -v 3.115.3     # 指定版本号
  python3 tools/release.py --dry-run      # 预览模式
"""
import re, sys, json, argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 复用 sync_version 的核心函数
sys.path.insert(0, str(ROOT / "tools"))
from sync_version import sync_version


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def load_token():
    """从 git remote 或 Hermes config 提取 GitHub token"""
    git_config = ROOT / ".git" / "config"
    if git_config.exists():
        m = re.search(r'https://([^:]+):([^@]+)@github\.com/', git_config.read_text())
        if m:
            return m.group(2)
    # Fallback: Hermes profile config
    cfg = Path.home() / ".hermes/profiles/meshctx/config.yaml"
    if cfg.exists():
        import yaml
        c = yaml.safe_load(cfg.read_text())
        return (c.get("github") or {}).get("token", "")
    return ""


def bump_version(current: str, level: str = "patch") -> str:
    parts = [int(x) for x in current.split(".")]
    if level == "major":
        parts[0] += 1; parts[1] = 0; parts[2] = 0
    elif level == "minor":
        parts[1] += 1; parts[2] = 0
    else:
        parts[2] += 1
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def get_current_version():
    """从 package.json 或 src/core/__init__.py 读取当前版本"""
    for src in ["package.json", "src/core/__init__.py"]:
        p = ROOT / src
        if p.exists():
            m = re.search(r'(\d+\.\d+\.\d+)', p.read_text())
            if m:
                return m.group(1)
    return "3.0.0"


def create_release(token: str, version: str, body: str = ""):
    """通过 GitHub API 创建/更新 Release"""
    data = {
        "tag_name": f"v{version}",
        "name": f"v{version}",
        "body": body or f"meshctx v{version}",
        "draft": False,
        "prerelease": False,
    }
    r = run([
        "curl", "-sk", "-X", "POST",
        "-H", f"Authorization: token {token}",
        "-H", "Content-Type: application/json",
        "https://api.github.com/repos/LucyAndLuna2023/meshctx/releases",
        "-d", json.dumps(data),
    ], timeout=15)
    resp = json.loads(r.stdout)
    if resp.get("html_url"):
        print(f"  Release: {resp['html_url']}")
        return resp
    elif "already_exists" in r.stdout:
        print(f"  Release exists, updating...")
        r2 = run([
            "curl", "-sk",
            "-H", f"Authorization: token {token}",
            f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/tags/v{version}",
        ], timeout=10)
        rel = json.loads(r2.stdout)
        if rel.get("id"):
            run([
                "curl", "-sk", "-X", "PATCH",
                "-H", f"Authorization: token {token}",
                "-H", "Content-Type: application/json",
                f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/{rel['id']}",
                "-d", json.dumps({"body": data["body"], "name": data["name"]}),
            ], timeout=10)
            print(f"  Updated: {rel.get('html_url')}")
            return rel
    else:
        print(f"  Error: {r.stdout[:300]}")
        return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="meshctx release tool")
    ap.add_argument("bump", nargs="?", choices=["major", "minor", "patch"], default="patch",
                    help="Bump level (default: patch)")
    ap.add_argument("--version", "-v", help="Specify exact version (skips bump)")
    ap.add_argument("--message", "-m", default="", help="Release notes / changelog")
    ap.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    ap.add_argument("--no-push", action="store_true", help="Skip git push (local tag only)")
    args = ap.parse_args()

    token = load_token()
    if not token and not args.dry_run:
        print("ERROR: No GitHub token found (set in git remote or Hermes config)")
        print("Hint: git remote set-url origin https://USER:TOKEN@github.com/LucyAndLuna2023/meshctx.git")
        sys.exit(1)

    current = get_current_version()
    new_ver = args.version or bump_version(current, args.bump)
    tag = f"v{new_ver}"

    print(f"发布: {current} → {new_ver} ({args.bump})")
    print(f"Tag:  {tag}")

    if args.dry_run:
        print("\n[DRY RUN] 预览模式，不做实际修改")
        sys.exit(0)

    # Step 1: Sync version to all files (via sync_version.py)
    print("\n[1/4] 同步版本号到所有文件...")
    sync_version(new_ver)

    # Step 2: Git commit
    print("\n[2/4] 提交...")
    run(["git", "add", "-A"], cwd=str(ROOT))
    r = run(["git", "commit", "--no-verify", "-m", f"release: {tag}"], cwd=str(ROOT))
    if r.returncode == 0:
        print("  Committed")
    else:
        print(f"  {r.stdout.strip()} (nothing to commit)")

    # Step 3: Tag + Push
    if not args.no_push:
        print("\n[3/4] Tag + Push...")
        run(["git", "tag", "-f", tag, "-m", args.message or tag], cwd=str(ROOT))
        run(["git", "push", "origin", "main", "--tags"], cwd=str(ROOT))
        print("  Pushed")
    else:
        print("\n[3/4] Tag (no push)...")
        run(["git", "tag", "-f", tag, "-m", args.message or tag], cwd=str(ROOT))

    # Step 4: GitHub Release
    if not args.no_push and token:
        print("\n[4/4] GitHub Release...")
        create_release(token, new_ver, args.message)

    print(f"\n✅ v{new_ver} 发布{'完成' if not args.no_push else '(本地tag)'}")
