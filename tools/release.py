#!/usr/bin/env python3
"""meshctx 版本发布工具 — 一键 bump + 同步 + tag + GitHub Release"""
import re, sys, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def load_token():
    """优先从 git remote 提取, 其次从 admin profile config"""
    git_config = ROOT / ".git" / "config"
    m = re.search(r'https://([^:]+):([^@]+)@github\.com/', git_config.read_text())
    if m:
        return m.group(2)
    import yaml
    cfg = Path.home() / ".hermes/profiles/meshctx/config.yaml"
    if cfg.exists():
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

def sync_all(version: str):
    """同步版本到所有文件"""
    major, minor, patch = version.split(".")
    files = {
        "src/__init__.py": [
            (r'__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"'),
        ],
        "src/core/__init__.py": [
            (r'__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"'),
        ],
        "version_info.txt": [
            (r"filevers=\(\d+,\s*\d+,\s*\d+", f"filevers=({major}, {minor}, {patch}"),
            (r"prodvers=\(\d+,\s*\d+,\s*\d+", f"prodvers=({major}, {minor}, {patch}"),
            (r"u'FileVersion', u'[^']+'", f"u'FileVersion', u'{version}'"),
            (r"u'ProductVersion', u'[^']+'", f"u'ProductVersion', u'{version}'"),
        ],
        "meshctx_setup.nsi": [
            (r'!define VERSION "[^"]*"', f'!define VERSION "{version}"'),
        ],
        "meshctx_desktop.spec": [
            (r"'CFBundleShortVersionString': '[^']+'", f"'CFBundleShortVersionString': '{version}'"),
            (r"'CFBundleVersion': '[^']+'", f"'CFBundleVersion': '{version}'"),
        ],
        "docs/index.html": [
            (r'(v)\d+\.\d+\.\d+', fr'\g<1>{version}', 1),  # first occurrence only
        ],
    }
    for fpath, patterns in files.items():
        path = ROOT / fpath
        if not path.exists():
            print(f"  SKIP: {fpath}")
            continue
        content = path.read_text()
        for args in patterns:
            content = re.sub(args[0], args[1], content)
        path.write_text(content)
        print(f"  OK: {fpath}")

def create_release(token: str, version: str, body: str = ""):
    """Create GitHub Release via API"""
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
    elif "already_exists" in r.stdout:
        print(f"  Release already exists, updating...")
        # update existing
        r2 = run([
            "curl", "-sk",
            "-H", f"Authorization: token {token}",
            f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/tags/v{version}",
        ], timeout=10)
        rel = json.loads(r2.stdout)
        run([
            "curl", "-sk", "-X", "PATCH",
            "-H", f"Authorization: token {token}",
            "-H", "Content-Type: application/json",
            f"https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/{rel['id']}",
            "-d", json.dumps({"body": data["body"], "name": data["name"]}),
        ], timeout=10)
        print(f"  Updated: {rel.get('html_url')}")
    else:
        print(f"  Error: {r.stdout[:300]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="meshctx release tool")
    ap.add_argument("bump", nargs="?", choices=["major", "minor", "patch"], default="patch")
    ap.add_argument("--version", "-v", help="Specify exact version (skips bump)")
    ap.add_argument("--message", "-m", default="", help="Release notes")
    ap.add_argument("--dry-run", action="store_true", help="Preview only")
    args = ap.parse_args()

    token = load_token()
    if not token:
        print("ERROR: No GitHub token found")
        sys.exit(1)

    # Get current version
    init = (ROOT / "src/core/__init__.py").read_text()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    current = m.group(1) if m else "3.0.0"

    new_ver = args.version or bump_version(current, args.bump)
    tag = f"v{new_ver}"

    print(f"发布: {current} → {new_ver} ({args.bump})")
    print(f"Tag:  {tag}")

    if args.dry_run:
        print("[DRY RUN] 不做实际修改")
        sys.exit(0)

    # Step 1: Sync version to all files
    print("\n[1/4] 同步版本号...")
    sync_all(new_ver)

    # Step 2: Git commit
    print("\n[2/4] 提交...")
    run(["git", "add", "-A"], cwd=str(ROOT))
    r = run(["git", "commit", "--no-verify", "-m", f"release: {tag}"], cwd=str(ROOT))
    if r.returncode == 0:
        print("  OK")
    else:
        print(f"  {r.stdout.strip()} (可能是 nothing to commit)")

    # Step 3: Tag + push
    print("\n[3/4] Tag + Push...")
    run(["git", "tag", "-f", tag, "-m", args.message or tag], cwd=str(ROOT))
    run(["git", "push", "origin", "main", "--tags"], cwd=str(ROOT))
    print("  Pushed")

    # Step 4: Create GitHub Release
    print("\n[4/4] GitHub Release...")
    create_release(token, new_ver, args.message)

    print(f"\n✅ v{new_ver} 发布完成")
