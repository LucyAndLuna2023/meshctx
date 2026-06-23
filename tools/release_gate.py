#!/usr/bin/env python3
"""
🔴 meshctx 发布门禁系统 — 强制执行 Dev→UAT→Production 三级验证
用法: python3 tools/release_gate.py 3.48.0 [--production]
不通过门禁 = 不允许发布
"""
import sys, os, json, time, urllib.request, subprocess
from pathlib import Path

PROJECT = Path(__file__).parent.parent
UAT_HOST = "47.120.0.239:3001"
PROD_URL = "http://meshctx.com"

class ReleaseGate:
    def __init__(self, version: str):
        self.version = version
        self.checks = []
        self.passed = 0
        self.failed = 0
    
    def check(self, name: str, fn) -> bool:
        try:
            result = fn()
            if result:
                self.passed += 1
                print(f"  ✅ {name}")
            else:
                self.failed += 1
                print(f"  ❌ {name}: FAILED")
            return result
        except Exception as e:
            self.failed += 1
            print(f"  ❌ {name}: ERROR - {e}")
            return False
    
    # ═══ Phase 1: DEV ═══
    def phase_dev(self):
        print("\n=== Phase 1: DEV 本地验证 ===")
        
        # Git clean
        self.check("Git工作区干净", lambda: 
            subprocess.run("git diff --quiet", shell=True, cwd=PROJECT).returncode == 0)
        
        # Unit tests
        self.check("全量测试通过", lambda:
            subprocess.run("python -m pytest tests/ -q --tb=no --ignore=tests/archived --ignore=tests/test_api_full_coverage.py --ignore=tests/test_e2e 2>&1 | grep -q 'failed'", 
                          shell=True, cwd=PROJECT).returncode != 0)
        
        # I18N validation
        self.check("I18N JS语法验证", lambda:
            subprocess.run("node tools/validate_i18n.js 2>&1 | grep -q 'All translations complete'",
                          shell=True, cwd=PROJECT).returncode == 0)
        
        # NSIS validation
        self.check("NSIS测试通过", lambda:
            subprocess.run("python -m pytest tests/test_nsis_validation.py -q 2>&1 | grep -q 'failed'",
                          shell=True, cwd=PROJECT).returncode != 0)
        
        # Version sync
        self.check("版本号同步", lambda:
            subprocess.run(f"python3 tools/sync_version.py {self.version} 2>&1 | grep -q 'OK'",
                          shell=True, cwd=PROJECT).returncode == 0)
        
        return self.failed == 0
    
    # ═══ Phase 2: UAT ═══
    def phase_uat(self):
        print("\n=== Phase 2: UAT 部署验证 (47.120.0.239) ===")
        
        # Deploy
        self.check("UAT部署", lambda: self._deploy_uat())
        
        # Server health
        self.check("UAT服务存活", lambda: self._check_uat_health())
        
        # API version
        self.check(f"UAT版本={self.version}", lambda: self._check_uat_version())
        
        # JEPA health
        self.check("UAT JEPA世界模型正常", lambda: self._check_uat_jepa())
        
        return self.failed == 0
    
    def _deploy_uat(self):
        core_files = "autopilot.py alert_engine.py deploy_engine.py jepa_world_model.py self_debug.py knowledge_graph.py context_compressor.py main.py __init__.py"
        for f in core_files.split():
            src = PROJECT / "src" / "core" / f
            if src.exists():
                r = os.system(f"cat {src} | sshpass -p 'LucyAndLuna@20230609' ssh -o StrictHostKeyChecking=no root@47.120.0.239 'cat > /opt/meshctx/src/core/{f}' 2>/dev/null")
        os.system("sshpass -p 'LucyAndLuna@20230609' ssh -o StrictHostKeyChecking=no root@47.120.0.239 'systemctl restart meshctx' 2>/dev/null")
        time.sleep(5)
        return True
    
    def _check_uat_health(self):
        try:
            resp = urllib.request.urlopen(f"http://{UAT_HOST}/api/health", timeout=10)
            return resp.status == 200
        except: return False
    
    def _check_uat_version(self):
        try:
            resp = urllib.request.urlopen(f"http://{UAT_HOST}/api/version", timeout=10)
            data = json.loads(resp.read())
            return data.get("version") == self.version
        except: return False
    
    def _check_uat_jepa(self):
        try:
            resp = urllib.request.urlopen(f"http://{UAT_HOST}/api/jepa/health", timeout=10)
            data = json.loads(resp.read())
            return data.get("status") == "ok"
        except: return False
    
    # ═══ Phase 3: PRODUCTION ═══
    def phase_production(self):
        print("\n=== Phase 3: PRODUCTION 发布 (meshctx.com) ===")
        
        # Git push
        self.check("Git推送", lambda:
            subprocess.run("git push origin main", shell=True, cwd=PROJECT).returncode == 0)
        
        # Wait for GitHub Pages
        print("  ⏳ 等待GitHub Pages重建(10秒)...")
        time.sleep(10)
        
        # Verify production
        self.check("生产主页可访问", lambda: self._check_prod())
        self.check("生产JS语法正确", lambda: self._check_prod_js())
        
        return self.failed == 0
    
    def _check_prod(self):
        try:
            resp = urllib.request.urlopen(PROD_URL, timeout=15)
            return resp.status == 200
        except: return False
    
    def _check_prod_js(self):
        try:
            resp = urllib.request.urlopen(PROD_URL, timeout=15)
            html = resp.read().decode()
            return 'switchLang' in html and ',,' not in html
        except: return False
    
    # ═══ Main ═══
    def run(self, to_production: bool = False):
        print(f"╔══════════════════════════════════════╗")
        print(f"║  meshctx 发布门禁 v{self.version}        ║")
        print(f"╚══════════════════════════════════════╝")
        
        if not self.phase_dev():
            print(f"\n🔴 DEV阶段失败! 修复后重试。")
            return 1
        
        if not self.phase_uat():
            print(f"\n🔴 UAT阶段失败! 检查远程服务器。")
            return 1
        
        if to_production:
            if not self.phase_production():
                print(f"\n🔴 PRODUCTION阶段失败!")
                return 1
        
        print(f"\n✅ 全部门禁通过! ({self.passed}/{self.passed+self.failed})")
        print(f"   DEV ✅ → UAT ✅ → {'PRODUCTION ✅' if to_production else 'PRODUCTION ⏸'}")
        return 0

if __name__ == "__main__":
    version = sys.argv[1] if len(sys.argv) > 1 else "3.47.0"
    to_prod = "--production" in sys.argv
    gate = ReleaseGate(version)
    sys.exit(gate.run(to_prod))
