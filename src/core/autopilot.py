"""
MeshCtx Autopilot v1.0 — 自治看门狗系统

解决Hermes致命缺陷: CLI会话结束=Agent消失
架构: cron驱动 → 每个组件独立自检→自修→汇报 → 不依赖任何CLI会话

组件:
- server_watchdog: 服务存活性检查+自动重启
- disk_watchdog: 磁盘空间监控
- test_watchdog: 定时全量测试
- deploy_watchdog: 自动git pull+部署
- health_report: 定时汇总报告→飞书

所有组件独立运行，无依赖关系，单个组件失败不影响其他。
"""
import os, sys, time, json, subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

HOME = Path.home()
MESHCTX_DIR = Path(os.environ.get('MESHCTX_HOME', str(Path(__file__).parent.parent.parent)))
LOG_DIR = HOME / ".meshctx" / "autopilot"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_DIR / "autopilot.log", "a") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"[{timestamp}] {msg}")

def run(cmd: str, timeout: int = 30) -> tuple:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", f"TIMEOUT({timeout}s)", -1
    except Exception as e:
        return "", str(e), -2

# ═══ 1. 服务看门狗 ═══
def check_server(host: str = "", port: int = 3001) -> bool:
    if not host: host = os.environ.get("MESHCTX_HOST", "127.0.0.1")
    """检查meshctx服务是否存活"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=5)
        return resp.status == 200
    except Exception:
        return False

def restart_server() -> bool:
    """重启meshctx服务"""
    cmd = "systemctl restart meshctx 2>&1 || sudo systemctl restart meshctx 2>&1"
    out, err, code = run(cmd)
    success = code == 0
    log(f"Server restart: {'OK' if success else f'FAILED: {err}'}")
    return success

def server_watchdog():
    """服务看门狗主循环"""
    if check_server():
        log("Server: OK")
        return "OK"
    
    log("Server: DOWN - attempting restart")
    for attempt in range(3):
        if restart_server():
            import time; time.sleep(5)
            if check_server():
                log(f"Server: RESTORED (attempt {attempt+1})")
                return "RESTORED"
        import time; time.sleep(3)
    
    log("Server: FAILED after 3 attempts")
    return "FAILED"

# ═══ 2. 磁盘看门狗 ═══
def check_disk(path: str = "/", threshold_pct: int = 90) -> Dict:
    """检查磁盘空间"""
    import shutil
    usage = shutil.disk_usage(path)
    pct = (usage.used / usage.total) * 100
    status = "CRITICAL" if pct > threshold_pct else "WARNING" if pct > 80 else "OK"
    
    result = {
        "path": path,
        "total_gb": usage.total / (1024**3),
        "used_gb": usage.used / (1024**3),
        "pct": round(pct, 1),
        "status": status,
    }
    
    if status != "OK":
        log(f"Disk {status}: {pct:.1f}% used ({result['used_gb']:.1f}/{result['total_gb']:.1f} GB)")
    
    return result

# ═══ 3. 测试看门狗 ═══
def run_tests(test_dir: str = "tests/") -> Dict:
    """运行测试套件"""
    os.chdir(str(MESHCTX_DIR))
    
    venv_python = MESHCTX_DIR / "venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = "python3"
    
    cmd = f"{venv_python} -m pytest {test_dir} -q --tb=no --ignore=tests/archived --ignore=tests/test_api_full_coverage.py --ignore=tests/test_e2e 2>&1"
    out, err, code = run(cmd, timeout=300)
    
    # 提取通过/失败数
    import re
    passed = re.search(r'(\d+) passed', out)
    failed = re.search(r'(\d+) failed', out)
    
    result = {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "exit_code": code,
    }
    
    log(f"Tests: {result['passed']} passed, {result['failed']} failed")
    return result

# ═══ 4. 部署看门狗 ═══
def check_updates() -> Dict:
    """检查GitHub更新并自动部署"""
    os.chdir(str(MESHCTX_DIR))
    
    # Git pull
    out, err, code = run("git fetch origin 2>&1 && git status -uno 2>&1")
    
    behind = "behind" in out.lower()
    if behind:
        log("Updates available - pulling...")
        out2, err2, code2 = run("git pull --ff-only 2>&1")
        if code2 == 0:
            log("Git pull: OK - restarting server")
            restart_server()
            return {"action": "UPDATED", "message": "Pulled and restarted"}
        else:
            log(f"Git pull FAILED: {err2}")
            return {"action": "FAILED", "message": err2[:200]}
    
    return {"action": "UP_TO_DATE"}

# ═══ 5. 健康汇总 ═══
def generate_health_report() -> Dict[str, Any]:
    """生成健康报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "hostname": os.uname().nodename,
        "server": "UP" if check_server() else "DOWN",
        "disk": check_disk(),
        "version": "",
    }
    
    # 获取版本
    try:
        import urllib.request
        _host = os.environ.get("MESHCTX_HOST", "127.0.0.1")
        resp = urllib.request.urlopen(f"http://{_host}:3001/api/version", timeout=5)
        import json
        data = json.loads(resp.read())
        report["version"] = data.get("version", "unknown")
    except Exception:
        report["version"] = "unreachable"
    
    # 写入报告文件
    report_file = LOG_DIR / f"health_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    log(f"Health report: {report_file}")
    return report

# ═══ 主入口 ═══
def run_all():
    """运行所有看门狗检查"""
    log("=== Autopilot Check Start ===")
    
    results = {
        "server": server_watchdog(),
        "disk": check_disk(),
        "timestamp": datetime.now().isoformat(),
    }
    
    # 每小时跑一次测试（可配置）
    hour = datetime.now().hour
    if hour % 4 == 0:  # 每4小时
        results["tests"] = run_tests()
    
    # 每小时检查更新
    results["updates"] = check_updates()
    
    # 每6小时生成报告
    if hour % 6 == 0:
        results["health_report"] = generate_health_report()
    
    log(f"=== Autopilot Check End: server={results['server']} ===")
    return results

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "server": server_watchdog()
        elif cmd == "disk": check_disk()
        elif cmd == "tests": run_tests()
        elif cmd == "deploy": check_updates()
        elif cmd == "report": generate_health_report()
        elif cmd == "install":
            print("Installing meshctx-autopilot cron jobs...")
            cron_lines = [
                "*/5 * * * * cd /opt/meshctx && python3 src/core/autopilot.py server >> /root/.meshctx/autopilot/server.log 2>&1",
                "0 * * * * cd /opt/meshctx && python3 src/core/autopilot.py disk >> /root/.meshctx/autopilot/disk.log 2>&1",
                "0 */4 * * * cd /opt/meshctx && python3 src/core/autopilot.py tests >> /root/.meshctx/autopilot/tests.log 2>&1",
                "*/30 * * * * cd /opt/meshctx && python3 src/core/autopilot.py deploy >> /root/.meshctx/autopilot/deploy.log 2>&1",
                "0 */6 * * * cd /opt/meshctx && python3 src/core/autopilot.py report >> /root/.meshctx/autopilot/report.log 2>&1",
            ]
            existing = run("crontab -l 2>&1")[0]
            new_crontab = existing + "\n# meshctx-autopilot\n" + "\n".join(cron_lines)
            with open("/tmp/crontab.txt", "w") as f: f.write(new_crontab)
            run("crontab /tmp/crontab.txt")
            print("Cron jobs installed: server/5min, disk/1h, tests/4h, deploy/30min, report/6h")
        else:
            print("Usage: python autopilot.py [server|disk|tests|deploy|report|install]")
    else:
        run_all()
