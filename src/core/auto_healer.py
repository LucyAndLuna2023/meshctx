"""meshctx auto_healer — automated health checks and self-healing (v3.115.33)

Real implementation: psutil-based disk/memory/cpu checks, connectivity test.
No more hardcoded results."""

from __future__ import annotations

import time
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CheckResult:
    name: str
    status: str = "ok"  # "ok", "warn", "critical", "unknown"
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AutoHealerV2 — real health checks
# ---------------------------------------------------------------------------

class AutoHealerV2:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._check_count: int = 0
        self._heal_count: int = 0
        self._last_check: float = 0.0
        self._uptime_start: float = time.time()

    # -- real checks ----------------------------------------------------------

    def _check_cache(self) -> CheckResult:
        """Check internal cache health."""
        import tempfile
        try:
            tmp = tempfile.gettempdir()
            test_file = os.path.join(tmp, ".meshctx_health_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            return CheckResult(name="cache", status="ok", message="cache r/w OK")
        except Exception as e:
            return CheckResult(name="cache", status="warn", message=f"cache issue: {e}")

    def _check_memory(self) -> CheckResult:
        """Check real memory usage via psutil or /proc/meminfo."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            pct = mem.percent
            gb_used = mem.used / (1024**3)
            gb_total = mem.total / (1024**3)
            if pct > 90:
                return CheckResult(name="memory", status="critical",
                    message=f"memory critical: {pct:.1f}% ({gb_used:.1f}/{gb_total:.1f} GB)",
                    details={"percent": pct, "used_gb": round(gb_used, 1), "total_gb": round(gb_total, 1)})
            elif pct > 75:
                return CheckResult(name="memory", status="warn",
                    message=f"memory high: {pct:.1f}%",
                    details={"percent": pct})
            return CheckResult(name="memory", status="ok",
                message=f"memory OK: {pct:.1f}%",
                details={"percent": pct})
        except ImportError:
            # Fallback to /proc/meminfo on Linux
            try:
                with open("/proc/meminfo") as f:
                    lines = f.read()
                import re
                total = int(re.search(r"MemTotal:\s+(\d+)", lines).group(1))
                avail = int(re.search(r"MemAvailable:\s+(\d+)", lines).group(1))
                pct = (total - avail) / total * 100
                if pct > 90:
                    return CheckResult(name="memory", status="critical",
                        message=f"memory critical: {pct:.1f}%")
                elif pct > 75:
                    return CheckResult(name="memory", status="warn",
                        message=f"memory high: {pct:.1f}%")
                return CheckResult(name="memory", status="ok",
                    message=f"memory OK: {pct:.1f}%")
            except Exception:
                return CheckResult(name="memory", status="unknown", message="cannot read memory")

    def _check_disk(self) -> CheckResult:
        """Check real disk space."""
        try:
            import psutil
            disk = psutil.disk_usage("/")
            pct = disk.percent
            gb_free = disk.free / (1024**3)
            if pct > 95:
                return CheckResult(name="disk", status="critical",
                    message=f"disk critical: {pct:.1f}% used, {gb_free:.1f} GB free",
                    details={"percent": pct, "free_gb": round(gb_free, 1)})
            elif pct > 85:
                return CheckResult(name="disk", status="warn",
                    message=f"disk low: {pct:.1f}% used, {gb_free:.1f} GB free",
                    details={"percent": pct})
            return CheckResult(name="disk", status="ok",
                message=f"disk OK: {gb_free:.1f} GB free",
                details={"percent": pct, "free_gb": round(gb_free, 1)})
        except ImportError:
            try:
                stat = shutil.disk_usage("/")
                pct = (stat.used / stat.total) * 100
                gb_free = stat.free / (1024**3)
                if pct > 95:
                    return CheckResult(name="disk", status="critical",
                        message=f"disk critical: {pct:.1f}% used")
                elif pct > 85:
                    return CheckResult(name="disk", status="warn",
                        message=f"disk low: {pct:.1f}% used")
                return CheckResult(name="disk", status="ok",
                    message=f"disk OK: {gb_free:.1f} GB free")
            except Exception:
                return CheckResult(name="disk", status="unknown", message="cannot read disk")

    def _check_connectivity(self) -> CheckResult:
        """Check network connectivity."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(("8.8.8.8", 53))
            s.close()
            return CheckResult(name="connectivity", status="ok", message="network reachable")
        except Exception:
            return CheckResult(name="connectivity", status="warn", message="network unreachable")

    def _check_cpu(self) -> CheckResult:
        """Check CPU load."""
        try:
            import psutil
            pct = psutil.cpu_percent(interval=0.5)
            if pct > 90:
                return CheckResult(name="cpu", status="critical",
                    message=f"CPU critical: {pct:.1f}%", details={"percent": pct})
            elif pct > 70:
                return CheckResult(name="cpu", status="warn",
                    message=f"CPU high: {pct:.1f}%", details={"percent": pct})
            return CheckResult(name="cpu", status="ok",
                message=f"CPU OK: {pct:.1f}%", details={"percent": pct})
        except ImportError:
            try:
                load = os.getloadavg()[0]
                cores = os.cpu_count() or 1
                pct = load / cores * 100
                if pct > 90:
                    return CheckResult(name="cpu", status="critical",
                        message=f"CPU critical: load {load:.1f}")
                elif pct > 70:
                    return CheckResult(name="cpu", status="warn",
                        message=f"CPU high: load {load:.1f}")
                return CheckResult(name="cpu", status="ok",
                    message=f"CPU OK: load {load:.1f}")
            except Exception:
                return CheckResult(name="cpu", status="unknown", message="cannot read CPU")

    def check_all(self) -> List[CheckResult]:
        """Run every real health check."""
        self._last_check = time.time()
        self._check_count += 1

        checks: List[Callable[[], CheckResult]] = [
            self._check_cache,
            self._check_memory,
            self._check_disk,
            self._check_connectivity,
            self._check_cpu,
        ]
        return [fn() for fn in checks]

    # -- healing -------------------------------------------------------------

    def heal(self, checks: List[CheckResult]) -> List[Dict[str, Any]]:
        """Apply healing actions for non-ok checks.

        Graded response per 002 audit:
        - warn (75%+): gc.collect() only
        - critical (90%+): gc.collect() + set throttle flag to pause new tasks
        """
        actions: List[Dict[str, Any]] = []
        for c in checks:
            if c.status != "ok":
                action = {
                    "check": c.name,
                    "status": c.status,
                    "message": c.message,
                    "action": "logged",
                    "timestamp": time.time(),
                }
                if c.name == "memory":
                    try:
                        import gc
                        collected = gc.collect()
                    except Exception:
                        collected = -1

                    if c.status == "critical":
                        # 90%+ memory — gc + throttle new tasks
                        action["action"] = "gc_collected_and_throttled"
                        action["gc_collected"] = collected
                        self._should_throttle = True
                        logger.critical(
                            f"Memory critical: {c.message}, GC={collected}, throttling new tasks"
                        )
                    elif c.status == "warn":
                        # 75%+ memory — gc only
                        action["action"] = "gc_collected"
                        action["gc_collected"] = collected
                        self._should_throttle = False
                        logger.warning(
                            f"Memory warn: {c.message}, GC={collected}"
                        )
                    else:
                        self._should_throttle = False
                elif c.name == "disk" and c.status == "critical":
                    # Disk critical — clean temp files
                    try:
                        self._cleanup_temp_files()
                        action["action"] = "cleaned_temp_files"
                    except Exception:
                        pass
                elif c.name == "cpu" and c.status == "critical":
                    self._should_throttle = True
                    action["action"] = "throttled"

                actions.append(action)

        self._heal_count += len(actions)
        return actions

    @property
    def should_throttle(self) -> bool:
        """Whether the kernel should pause accepting new tasks (memory/cpu critical)."""
        return getattr(self, '_should_throttle', False)

    # -- stats ----------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        uptime = time.time() - self._uptime_start
        return {
            "checks": self._check_count,
            "heals": self._heal_count,
            "last_check": self._last_check,
            "uptime_seconds": round(uptime),
            "uptime_human": f"{uptime/3600:.1f}h",
        }

    def get_dashboard_report(self) -> Dict[str, Any]:
        checks = self.check_all()
        ok = sum(1 for c in checks if c.status == "ok")
        warn = sum(1 for c in checks if c.status == "warn")
        crit = sum(1 for c in checks if c.status == "critical")
        total = len(checks)
        score = round(100 * ok / max(total, 1), 1)
        return {
            "status": "healthy" if crit == 0 else "degraded",
            "color": "green" if crit == 0 else ("yellow" if warn > 0 else "red"),
            "health_score": score,
            "checks": [{"name": c.name, "status": c.status, "message": c.message} for c in checks],
            "ok": ok, "warn": warn, "critical": crit,
            "heals_performed": self._heal_count,
            "uptime_human": f"{(time.time()-self._uptime_start)/3600:.1f}h",
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_healer: AutoHealerV2 = AutoHealerV2()
healer: AutoHealerV2 = _healer


def get_auto_healer() -> AutoHealerV2:
    return _healer
