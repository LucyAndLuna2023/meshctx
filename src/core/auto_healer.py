"""
meshctx 智能自愈模块 — 自动检测+修复常见问题
"""
import time, subprocess, json, os, threading
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("/opt/meshctx/logs/healer.log")
CHECK_INTERVAL = 60  # seconds
HISTORY_SIZE = 50

class AutoHealer:
    def __init__(self):
        self.running = False
        self.thread = None
        self.history = []
        self.heal_count = 0
        self.last_check = None
        self.status = "initializing"
        self._lock = threading.Lock()
    
    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._log("AutoHealer started")
    
    def stop(self):
        self.running = False
        if self.thread: self.thread.join(timeout=5)
    
    def _log(self, msg):
        ts = datetime.now().isoformat()
        line = f"[{ts}] {msg}"
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as f: f.write(line + "\n")
        except: pass
        with self._lock:
            self.history.append({"timestamp": ts, "message": msg, "type": "log"})
            if len(self.history) > HISTORY_SIZE: self.history.pop(0)
    
    def _loop(self):
        consecutive_failures = 0
        while self.running:
            try:
                healthy = self._run_checks()
                self.last_check = datetime.now().isoformat()
                if healthy:
                    consecutive_failures = 0
                    self.status = "healthy"
                else:
                    consecutive_failures += 1
                    self.status = "degraded"
                    if consecutive_failures >= 3:
                        self.status = "critical"
                        self._heal()
                        consecutive_failures = 0
            except Exception as e:
                self._log(f"Check error: {e}")
            time.sleep(CHECK_INTERVAL)
    
    def _run_checks(self):
        checks = []
        # Check critical endpoints
        for endpoint in ["/api/health", "/api/version", "/health"]:
            ok = self._check_endpoint(endpoint)
            checks.append(("endpoint", endpoint, ok))
            if not ok: self._log(f"Endpoint DOWN: {endpoint}")
        
        # Check service status
        try:
            r = subprocess.run(["systemctl", "is-active", "meshctx"], capture_output=True, text=True, timeout=5)
            svc_ok = r.stdout.strip() == "active"
            checks.append(("service", "meshctx", svc_ok))
            if not svc_ok: self._log(f"Service not active: {r.stdout.strip()}")
        except: pass
        
        # Check port
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
            port_ok = ":3001" in r.stdout
            checks.append(("port", "3001", port_ok))
            if not port_ok: self._log("Port 3001 not listening")
        except: pass
        
        all_ok = all(c[2] for c in checks)
        with self._lock:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "check",
                "checks": [{"category":c[0],"target":c[1],"ok":c[2]} for c in checks],
                "healthy": all_ok
            })
            if len(self.history) > HISTORY_SIZE: self.history.pop(0)
        return all_ok
    
    def _check_endpoint(self, path):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://localhost:3001{path}")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except: return False
    
    def _heal(self):
        self._log("=== AUTO-HEAL TRIGGERED ===")
        self.heal_count += 1
        
        # Step 1: Check what's wrong
        port_ok = False
        svc_ok = False
        try:
            r = subprocess.run(["systemctl", "is-active", "meshctx"], capture_output=True, text=True, timeout=5)
            svc_ok = r.stdout.strip() == "active"
        except: pass
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
            port_ok = ":3001" in r.stdout
        except: pass
        
        # Step 2: Fix
        if not port_ok:
            self._log("Port not listening — killing stale processes")
            subprocess.run(["fuser", "-k", "3001/tcp"], capture_output=True, timeout=5)
            time.sleep(2)
        
        if not svc_ok or not port_ok:
            self._log("Restarting meshctx service")
            subprocess.run(["systemctl", "restart", "meshctx"], capture_output=True, timeout=10)
            time.sleep(5)
        
        # Step 3: Verify
        if self._run_checks():
            self._log("Auto-heal SUCCESS")
        else:
            self._log("Auto-heal FAILED — manual intervention needed")
    
    def get_status(self):
        return {
            "status": self.status,
            "running": self.running,
            "last_check": self.last_check,
            "heal_count": self.heal_count,
            "uptime_checks": len([h for h in self.history if h.get("type")=="check"])
        }
    
    def get_history(self, limit=20):
        with self._lock:
            return self.history[-limit:]
    
    def run_manual_check(self):
        ok = self._run_checks()
        return {"healthy": ok, "status": self.status, "checks": len(self.history)}

# Singleton
healer = AutoHealer()
