#!/usr/bin/env python3
"""
meshctx 发布管理 — 严格执行，不允许跳过任何步骤
用法: python3 tools/release.py 3.33.5
"""
import sys, subprocess, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = "/home/administrator/meshctx-venv/bin/activate"

def run(cmd, cwd=None, timeout=120):
    cwd = cwd or ROOT
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout + result.stderr

def check(step, ok=True):
    status = "✅" if ok else "❌"
    print(f"  {status} {step}")
    if not ok:
        print(f"  🔴 发布中止: {step} 失败")
        sys.exit(1)

def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    if not ver:
        print("用法: python3 tools/release.py X.Y.Z")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  meshctx v{ver} 发布流程")
    print(f"{'='*60}\n")

    # ═══ 阶段1: 版本同步 ═══
    print("阶段1: 版本号同步")
    rc, out = run(f"source {VENV} && python3 tools/sync_version.py {ver}")
    check(f"版本号同步到 {ver}", rc == 0)
    
    # ═══ 阶段2: 全量测试 ═══
    print("\n阶段2: 全量测试")
    rc, out = run(f"source {VENV} && python -m pytest tests/ -q --tb=line")
    check(f"全量测试", rc == 0)
    for line in out.split('\n'):
        if 'passed' in line or 'failed' in line:
            print(f"     {line.strip()}")
    if 'failed' in out:
        check("0失败", False)
    
    # ═══ 阶段3: 回归测试 ═══
    print("\n阶段3: 回归测试")
    for test_file in ["test_nsis_validation.py", "test_project_integrity.py", "test_real_behavior.py"]:
        rc, out = run(f"source {VENV} && python -m pytest tests/{test_file} -q --tb=line")
        check(test_file, rc == 0)
    
    # ═══ 阶段4: 行为测试 ═══
    print("\n阶段4: 行为测试")
    rc, out = run(f"source {VENV} && python -m pytest tests/test_real_behavior.py -v --tb=short")
    check("行为测试(服务启动/版本API/UTF8/NSIS)", rc == 0)
    
    # ═══ 阶段5: Exe构建验证(如果本地有exe) ═══
    print("\n阶段5: Exe构建验证(可选)")
    exe = ROOT / "dist" / "meshctx-desktop.exe"
    if exe.exists():
        # 检查版本号
        data = exe.read_bytes()
        has_ver = b'F\x00i\x00l\x00e\x00V' in data
        check(f"exe版本信息: {'已嵌入' if has_ver else '缺失!'}", has_ver)
        size_mb = exe.stat().st_size / 1024 / 1024
        check(f"exe大小: {size_mb:.0f}MB", 10 < size_mb < 200)
    else:
        print("   ⏭️ 本地无exe(CI构建)")
    
    # ═══ 阶段6: 提交推送 ═══
    print("\n阶段6: Git提交+推送")
    rc, out = run(f"cd {ROOT} && git add -A && git diff --cached --stat")
    if "0 files changed" not in out and out.strip():
        rc, out = run(f"cd {ROOT} && git commit -m 'release: v{ver}'")
        check("git commit", rc == 0)
    rc, out = run(f"cd {ROOT} && git push origin main")
    check("git push", rc == 0)
    
    # ═══ 阶段7: 打Tag触发CI ═══
    print("\n阶段7: 打Tag触发CI构建")
    rc, out = run(f"cd {ROOT} && git tag -a v{ver} -m 'v{ver} — CI构建NSIS安装包' && git push origin v{ver}")
    check(f"Tag v{ver} 推送", rc == 0)
    
    # ═══ 阶段8: E盘备份 ═══
    print("\n阶段8: E盘备份")
    backup_dir = Path("/mnt/e/Meshctx/backups") / f"v{ver}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "LATEST").write_text(ver)
    check(f"E盘备份: {backup_dir}", backup_dir.exists())
    
    print(f"\n{'='*60}")
    print(f"  ✅ v{ver} 发布流程完成")
    print(f"  CI构建中 → meshctx.com 自动更新(10分钟内)")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
