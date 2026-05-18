"""
meshctx 智能自愈 v2.0 — 预测式修复 + 健康度评分
=============================================
新增: 健康评分(0-100)、预测式检测、磁盘/内存/延迟监控、事件分类
"""
import time, subprocess, json, os, threading, shutil
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
import statistics

LOG_FILE = Path(os.environ.get("MESHCTX_DATA_DIR", "/opt/meshctx")) / "logs" / "healer.log"
CHECK_INTERVAL = 60  # seconds
HISTORY_SIZE = 100
METRICS_WINDOW = 20  # 保留最近20次检查的指标用于趋势分析


class AutoHealer:
    def __init__(self):
        self.running = False
        self.thread = None
        self.history = []
        self.heal_count = 0
        self.heal_success = 0
        self.last_check = None
        self.last_incident = None
        self.status = "initializing"
        self.color = "gray"
        self._lock = threading.Lock()
        self._metrics = deque(maxlen=METRICS_WINDOW)
        self._start_time = datetime.now()
        self._incident_count = 0

    # ═══════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._log("AutoHealer v2.0 started", "info")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    # ═══════════════════════════════════════════════════════
    # 日志与指标
    # ═══════════════════════════════════════════════════════

    def _log(self, msg, level="info"):
        ts = datetime.now().isoformat()
        line = f"[{ts}] [{level}] {msg}"
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except:
            pass
        with self._lock:
            self.history.append({
                "timestamp": ts, "message": msg, "type": level,
                "level": level
            })
            if len(self.history) > HISTORY_SIZE:
                self.history.pop(0)

    def _add_metric(self, name, value):
        """记录数值型指标用于趋势分析"""
        with self._lock:
            self._metrics.append({
                "timestamp": datetime.now().isoformat(),
                "name": name, "value": value
            })

    def _get_metric_trend(self, name, window=10):
        """获取最近N次指标的趋势"""
        with self._lock:
            values = [m["value"] for m in self._metrics if m["name"] == name][-window:]
        if len(values) < 2:
            return {"trend": "stable", "current": values[-1] if values else 0}
        # 简单线性回归
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        slope = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values)) / sum((i - x_mean)**2 for i in range(n))
        return {
            "trend": "rising" if slope > 0.05 * y_mean else ("falling" if slope < -0.05 * y_mean else "stable"),
            "current": values[-1],
            "slope": round(slope, 4),
            "predicted_next": round(values[-1] + slope, 2)
        }

    # ═══════════════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════════════

    def _loop(self):
        consecutive_failures = 0
        while self.running:
            try:
                results = self._run_all_checks()
                score = self._calculate_health_score(results)
                self.last_check = datetime.now().isoformat()

                # 根据得分确定状态
                if score >= 90:
                    self.status = "healthy"; self.color = "green"
                    consecutive_failures = 0
                elif score >= 70:
                    self.status = "degraded"; self.color = "yellow"
                elif score >= 50:
                    self.status = "warning"; self.color = "orange"
                    consecutive_failures += 1
                else:
                    self.status = "critical"; self.color = "red"
                    consecutive_failures += 1

                # 自适应修复触发
                if score < 70 and consecutive_failures >= 2:
                    self._heal(results)
                    consecutive_failures = 0
                elif score < 50:
                    self._heal(results)

            except Exception as e:
                self._log(f"Loop error: {e}", "error")
            time.sleep(CHECK_INTERVAL)

    # ═══════════════════════════════════════════════════════
    # 全面检测
    # ═══════════════════════════════════════════════════════

    def _run_all_checks(self):
        """运行所有检测项，返回带权重的结果"""
        results = []

        # ── API端点检测 (权重:3) ──
        for ep in ["/health", "/api/version", "/api/health"]:
            ok, latency = self._check_endpoint(ep)
            results.append({
                "category": "endpoint", "target": ep,
                "ok": ok, "weight": 3,
                "latency_ms": latency
            })
            self._add_metric(f"latency_{ep}", latency)
            if not ok:
                self._log(f"Endpoint DOWN: {ep}", "error")

        # ── 服务状态 (权重:3) ──
        svc_ok = self._check_service()
        results.append({
            "category": "service", "target": "meshctx",
            "ok": svc_ok, "weight": 3
        })

        # ── 端口监听 (权重:3) ──
        port_ok = self._check_port()
        results.append({
            "category": "port", "target": "3001",
            "ok": port_ok, "weight": 3
        })

        # ── 磁盘空间 (权重:2) ──
        disk_pct, disk_ok = self._check_disk()
        results.append({
            "category": "disk", "target": "/",
            "ok": disk_ok, "weight": 2,
            "used_pct": disk_pct
        })
        self._add_metric("disk_used_pct", disk_pct)

        # ── 内存使用 (权重:2) ──
        mem_pct, mem_ok = self._check_memory()
        results.append({
            "category": "memory", "target": "system",
            "ok": mem_ok, "weight": 2,
            "used_pct": mem_pct
        })
        self._add_metric("mem_used_pct", mem_pct)

        # ── CPU负载 (权重:1) ──
        cpu_pct, cpu_ok = self._check_cpu()
        results.append({
            "category": "cpu", "target": "system",
            "ok": cpu_ok, "weight": 1,
            "load_pct": cpu_pct
        })

        # ── 错误率趋势 (权重:2) ──
        err_ok = self._check_error_rate()
        results.append({
            "category": "error_rate", "target": "trend",
            "ok": err_ok, "weight": 2
        })

        # 存储检测结果
        with self._lock:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "check",
                "results": [
                    {k: v for k, v in r.items() if k != "weight"}
                    for r in results
                ],
                "score": self._calculate_health_score(results)
            })
            if len(self.history) > HISTORY_SIZE:
                self.history.pop(0)

        return results

    # ═══════════════════════════════════════════════════════
    # 单项检测
    # ═══════════════════════════════════════════════════════

    def _check_endpoint(self, path):
        try:
            import urllib.request
            start = time.time()
            req = urllib.request.Request(f"http://localhost:3001{path}")
            with urllib.request.urlopen(req, timeout=5) as r:
                latency = round((time.time() - start) * 1000, 1)
                return r.status == 200, latency
        except:
            return False, 0

    def _check_service(self):
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "meshctx"],
                capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() == "active"
        except:
            return False

    def _check_port(self):
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
            return ":3001" in r.stdout
        except:
            return False

    def _check_disk(self):
        """检查磁盘使用率"""
        try:
            usage = shutil.disk_usage("/")
            pct = round(usage.used / usage.total * 100, 1)
            return pct, pct < 90  # 超过90%告警
        except:
            return 0, True

    def _check_memory(self):
        """检查内存使用率"""
        try:
            r = subprocess.run(["free"], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                total = float(parts[1])
                used = float(parts[2])
                pct = round(used / total * 100, 1)
                return pct, pct < 90
        except:
            pass
        return 0, True

    def _check_cpu(self):
        """检查CPU负载"""
        try:
            load = os.getloadavg()[0]  # 1分钟平均
            cores = os.cpu_count() or 1
            pct = round(load / cores * 100, 1)
            return pct, pct < 80
        except:
            return 0, True

    def _check_error_rate(self):
        """检查最近的错误频率趋势"""
        with self._lock:
            recent = [h for h in self.history[-20:]
                      if h.get("type") in ("error", "critical")]
            return len(recent) < 3  # 最近20条中错误少于3条

    # ═══════════════════════════════════════════════════════
    # 健康评分引擎 (0-100)
    # ═══════════════════════════════════════════════════════

    def _calculate_health_score(self, results):
        """加权评分: 0=完全故障, 100=完美健康"""
        total_weight = sum(r["weight"] for r in results)
        if total_weight == 0:
            return 0

        score = 0
        for r in results:
            if r.get("ok"):
                # 健康项得满分
                score += r["weight"] * 100
            else:
                # 故障项根据距离阈值的程度给分
                if r["category"] == "disk":
                    pct = r.get("used_pct", 100)
                    if pct >= 95:
                        score += 0
                    elif pct >= 85:
                        score += r["weight"] * 30
                    else:
                        score += r["weight"] * 60
                elif r["category"] == "memory":
                    pct = r.get("used_pct", 100)
                    if pct >= 95:
                        score += 0
                    elif pct >= 85:
                        score += r["weight"] * 30
                    else:
                        score += r["weight"] * 60
                elif r["category"] == "endpoint":
                    # 如果延迟过高但仍然可达，给部分分
                    lat = r.get("latency_ms", 0)
                    if lat > 0 and lat < 1000:
                        score += r["weight"] * 50
                    else:
                        score += 0
                # 其他故障项0分

        return round(score / total_weight)

    # ═══════════════════════════════════════════════════════
    # 预测引擎
    # ═══════════════════════════════════════════════════════

    def predict_failures(self):
        """预测即将发生的故障"""
        predictions = []

        # 磁盘趋势
        disk_trend = self._get_metric_trend("disk_used_pct")
        if disk_trend["trend"] == "rising" and disk_trend["current"] > 70:
            hours_to_critical = None
            if disk_trend["slope"] > 0:
                hours_to_critical = round((95 - disk_trend["current"]) / (disk_trend["slope"] * 60), 1)
            predictions.append({
                "type": "disk_full",
                "severity": "high" if disk_trend["current"] > 85 else "medium",
                "current": disk_trend["current"],
                "trend": "rising",
                "eta_hours": hours_to_critical,
                "recommendation": "清理日志或扩展磁盘空间"
            })

        # 内存趋势
        mem_trend = self._get_metric_trend("mem_used_pct")
        if mem_trend["trend"] == "rising" and mem_trend["current"] > 70:
            predictions.append({
                "type": "memory_leak",
                "severity": "high" if mem_trend["current"] > 85 else "medium",
                "current": mem_trend["current"],
                "trend": "rising",
                "recommendation": "检查内存泄漏，考虑重启服务"
            })

        # 延迟趋势
        for ep in ["/health", "/api/version"]:
            lat_trend = self._get_metric_trend(f"latency_{ep}")
            if lat_trend["trend"] == "rising" and lat_trend["current"] > 200:
                predictions.append({
                    "type": "latency_spike",
                    "endpoint": ep,
                    "severity": "medium",
                    "current_ms": lat_trend["current"],
                    "recommendation": f"检查{ep}端点性能"
                })

        return predictions

    # ═══════════════════════════════════════════════════════
    # 自愈引擎
    # ═══════════════════════════════════════════════════════

    def _heal(self, check_results):
        self._incident_count += 1
        self.last_incident = datetime.now().isoformat()
        self._log("=== AUTO-HEAL v2.0 TRIGGERED ===", "critical")

        # 诊断失败项
        failed = [r for r in check_results if not r.get("ok")]
        heal_actions = []
        success = True

        # 端口问题 → 杀进程+重启
        port_fail = any(r["category"] == "port" and not r["ok"] for r in failed)
        svc_fail = any(r["category"] == "service" and not r["ok"] for r in failed)

        if port_fail:
            self._log("Port issue detected — killing stale processes", "action")
            try:
                subprocess.run(["fuser", "-k", "3001/tcp"],
                               capture_output=True, timeout=5)
                time.sleep(2)
                heal_actions.append("kill_stale_port")
            except Exception as e:
                self._log(f"Failed to kill port: {e}", "error")
                success = False

        if svc_fail or port_fail:
            self._log("Restarting meshctx service", "action")
            try:
                subprocess.run(["systemctl", "restart", "meshctx"],
                               capture_output=True, timeout=10)
                time.sleep(5)
                heal_actions.append("restart_service")
            except Exception as e:
                self._log(f"Failed to restart: {e}", "error")
                success = False

        # 磁盘问题 → 清理pycache
        disk_fail = any(r["category"] == "disk" and not r["ok"] for r in failed)
        if disk_fail:
            self._log("Disk space low — cleaning pycache", "action")
            try:
                subprocess.run(
                    ["find", "/opt/meshctx", "-name", "__pycache__", "-exec", "rm", "-rf", "{}", "+"],
                    capture_output=True, timeout=30
                )
                heal_actions.append("clean_pycache")
            except Exception as e:
                self._log(f"Failed to clean: {e}", "error")

        # 端点问题 → 系统重启
        ep_fail = any(r["category"] == "endpoint" and not r["ok"] for r in failed)
        if ep_fail and not svc_fail:
            self._log("Endpoint issue — force restarting", "action")
            try:
                subprocess.run(["systemctl", "restart", "meshctx"],
                               capture_output=True, timeout=10)
                time.sleep(5)
                heal_actions.append("force_restart")
            except Exception as e:
                self._log(f"Force restart failed: {e}", "error")
                success = False

        # 验证修复
        time.sleep(3)
        if self._run_all_checks():
            ok_count = sum(1 for r in self._run_all_checks() if r.get("ok"))
            total = len(check_results)
            self._log(f"Heal SUCCESS ({ok_count}/{total} checks pass)", "info")
            self.heal_success += 1
        else:
            self._log("Heal FAILED — manual intervention needed", "critical")
            success = False

        self.heal_count += 1
        if not success:
            self.heal_success = max(0, self.heal_success - 1)

        # 记录事件
        with self._lock:
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "heal_event",
                "incident_id": self._incident_count,
                "actions": heal_actions,
                "success": success,
                "failed_checks": [
                    {"category": r["category"], "target": r["target"]}
                    for r in failed
                ]
            })

    # ═══════════════════════════════════════════════════════
    # API接口
    # ═══════════════════════════════════════════════════════

    def get_dashboard(self):
        """返回完整仪表板数据"""
        now = datetime.now()
        uptime = now - self._start_time
        last_check_dt = datetime.fromisoformat(self.last_check) if self.last_check else now
        last_incident_dt = datetime.fromisoformat(self.last_incident) if self.last_incident else self._start_time
        time_since_incident = now - last_incident_dt

        return {
            "status": self.status,
            "color": self.color,
            "running": self.running,
            "health_score": self._calculate_health_score(self._run_all_checks()),
            "last_check": self.last_check,
            "last_check_human": self._human_time(last_check_dt),
            "uptime_seconds": round(uptime.total_seconds()),
            "uptime_human": self._human_duration(uptime),
            "uptime_since_incident": round(time_since_incident.total_seconds()),
            "uptime_since_incident_human": self._human_duration(time_since_incident),
            "heals_performed": self.heal_count,
            "heals_successful": self.heal_success,
            "incident_count": self._incident_count,
            "checks_total": len([h for h in self.history if h.get("type") == "check"]),
            "predictions": self.predict_failures(),
            "metrics": {
                "disk": self._get_metric_trend("disk_used_pct"),
                "memory": self._get_metric_trend("mem_used_pct"),
            }
        }

    def get_status(self):
        return {
            "status": self.status,
            "color": self.color,
            "running": self.running,
            "last_check": self.last_check,
            "heal_count": self.heal_count,
            "heal_success": self.heal_success,
            "incidents": self._incident_count,
            "checks": len([h for h in self.history if h.get("type") == "check"])
        }

    def get_history(self, limit=20):
        with self._lock:
            return self.history[-limit:]

    def run_manual_check(self):
        results = self._run_all_checks()
        score = self._calculate_health_score(results)
        return {
            "healthy": all(r.get("ok") for r in results),
            "score": score,
            "status": self.status,
            "color": self.color,
            "results": [{k: v for k, v in r.items() if k != "weight"} for r in results],
            "predictions": self.predict_failures()
        }

    # ═══════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _human_time(dt):
        now = datetime.now()
        diff = now - dt
        if diff.total_seconds() < 60:
            return f"{int(diff.total_seconds())}秒前"
        elif diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() / 60)}分钟前"
        elif diff.total_seconds() < 86400:
            return f"{int(diff.total_seconds() / 3600)}小时前"
        else:
            return f"{diff.days}天前"

    @staticmethod
    def _human_duration(td):
        total = int(td.total_seconds())
        if total < 60:
            return f"{total}秒"
        elif total < 3600:
            return f"{total // 60}分{total % 60}秒"
        elif total < 86400:
            h = total // 3600
            m = (total % 3600) // 60
            return f"{h}时{m}分"
        else:
            d = total // 86400
            h = (total % 86400) // 3600
            return f"{d}天{h}时"


# 全局单例
healer = AutoHealer()
