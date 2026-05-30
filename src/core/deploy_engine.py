"""
MeshCtx v3.47 — One-Click Deploy Engine (一键部署引擎)

整合: Git → Build → Test → Deploy → Verify → Report
解决"部署到生产需要手动10步"的痛点
"""
import os, sys, time, json, subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

class DeployEngine:
    """一键部署引擎"""
    
    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir).absolute()
        self.steps = []
        self.log = []
    
    def _log(self, msg: str):
        self.log.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        print(msg)
    
    def step_git_pull(self) -> bool:
        self._log("Step 1/6: Git pull...")
        r = os.system(f"cd {self.project_dir} && git pull --ff-only 2>&1")
        return r == 0
    
    def step_run_tests(self) -> bool:
        self._log("Step 2/6: Running tests...")
        r = os.system(f"cd {self.project_dir} && python -m pytest tests/ -q --tb=no --ignore=tests/archived --ignore=tests/test_api_full_coverage.py --ignore=tests/test_e2e 2>&1 | tail -3")
        return r == 0
    
    def step_sync_version(self, version: str) -> bool:
        self._log(f"Step 3/6: Syncing version {version}...")
        r = os.system(f"cd {self.project_dir} && python3 tools/sync_version.py {version} 2>&1")
        return r == 0
    
    def step_deploy_uat(self) -> bool:
        self._log("Step 4/6: Deploying to UAT...")
        files = "autopilot.py alert_engine.py jepa_world_model.py self_debug.py knowledge_graph.py context_compressor.py"
        ok = True
        for f in files.split():
            r = os.system(f"cat {self.project_dir}/src/core/{f} | sshpass -p 'LucyAndLuna@20230609' ssh -o StrictHostKeyChecking=no root@47.120.0.239 'cat > /opt/meshctx/src/core/{f}' 2>/dev/null")
            if r != 0: ok = False
        return ok
    
    def step_verify(self) -> bool:
        self._log("Step 5/6: Verifying UAT...")
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://47.120.0.239:3001/api/version", timeout=10)
            data = json.loads(resp.read())
            self._log(f"  UAT version: {data.get('version', 'unknown')}")
            return True
        except Exception as e:
            self._log(f"  UAT unreachable: {e}")
            return False
    
    def step_backup(self) -> bool:
        self._log("Step 6/6: E盘备份...")
        r = os.system(f"mkdir -p /mnt/e/Meshctx/backups/auto && tar czf /mnt/e/Meshctx/backups/auto/meshctx_$(date +%Y%m%d_%H%M).tar.gz -C {self.project_dir} src/core/ tests/ docs/ 2>&1")
        self._log("  Backup OK" if r == 0 else "  Backup FAILED")
        return r == 0
    
    def deploy(self, version: str, to_production: bool = False) -> Dict:
        """一键部署"""
        self._log(f"=== Deploying v{version} {'→ PRODUCTION' if to_production else '→ UAT'} ===")
        start = time.time()
        
        results = {
            "git": self.step_git_pull(),
            "tests": self.step_run_tests(),
            "version": self.step_sync_version(version),
            "uat": self.step_deploy_uat(),
            "verify": self.step_verify(),
            "backup": self.step_backup(),
        }
        
        if to_production and all(results.values()):
            self._log("Pushing to production...")
            r = os.system(f"cd {self.project_dir} && git push origin main 2>&1")
            results["production"] = r == 0
        
        elapsed = time.time() - start
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        self._log(f"Done in {elapsed:.0f}s: {passed}/{total} steps passed")
        
        return {"steps": results, "elapsed": elapsed, "passed": passed, "total": total}

if __name__ == "__main__":
    engine = DeployEngine()
    engine.deploy("3.47.0", to_production=False)
