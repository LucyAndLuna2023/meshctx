"""meshctx behavior_monitor — real implementation"""

import enum
from typing import Dict, Any, List


class ComplianceStatus(enum.Enum):
    COMPLIANT = "compliant"
    VIOLATION = "violation"
    CRITICAL = "critical"


class PressureLevel(enum.Enum):
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceEvent:
    """A single compliance check result."""

    def __init__(self, action: str, status: ComplianceStatus, reason: str = ""):
        self.action = action
        self.status = status
        self.reason = reason


class BehaviorMonitor:
    """Monitors agent behavior for compliance with safety rules."""

    DANGEROUS_PATTERNS = [
        ("rm -rf /", ComplianceStatus.CRITICAL),
        ("rm -rf", ComplianceStatus.VIOLATION),
        ("/etc/passwd", ComplianceStatus.CRITICAL),
        ("/etc/shadow", ComplianceStatus.CRITICAL),
        ("sudo ", ComplianceStatus.VIOLATION),
        ("chmod 777", ComplianceStatus.VIOLATION),
        ("curl", ComplianceStatus.VIOLATION),
        ("wget", ComplianceStatus.VIOLATION),
        ("eval(", ComplianceStatus.VIOLATION),
        ("exec(", ComplianceStatus.VIOLATION),
        ("__import__", ComplianceStatus.VIOLATION),
        ("subprocess", ComplianceStatus.VIOLATION),
        ("os.system", ComplianceStatus.VIOLATION),
    ]

    def __init__(self):
        self._violations: List[ComplianceEvent] = []
        self._actions: List[ComplianceEvent] = []
        self._pressure_level = PressureLevel.NORMAL
        self._baseline: Dict[str, float] = {}
        self._deviation_count = 0
        self._safe_mode = False

    def check_action(self, action: str) -> ComplianceEvent:
        """Check if an action is compliant with safety rules."""
        for pattern, severity in self.DANGEROUS_PATTERNS:
            if pattern in action:
                event = ComplianceEvent(action=action, status=severity, reason=f"Matched pattern: {pattern}")
                self._violations.append(event)
                self._actions.append(event)
                return event
        event = ComplianceEvent(action=action, status=ComplianceStatus.COMPLIANT, reason="Safe action")
        self._actions.append(event)
        return event

    def update_pressure(self, metrics: Dict[str, float]) -> PressureLevel:
        """Update system pressure level based on resource metrics."""
        cpu = metrics.get("cpu_percent", 0)
        mem = metrics.get("memory_percent", 0)
        err = metrics.get("error_rate", 0)

        if cpu > 90 or mem > 85 or err > 0.05:
            self._pressure_level = PressureLevel.CRITICAL
        elif cpu > 75 or mem > 65 or err > 0.02:
            self._pressure_level = PressureLevel.HIGH
        else:
            self._pressure_level = PressureLevel.NORMAL
        return self._pressure_level

    def get_safe_mode_config(self) -> Dict[str, Any]:
        """Get configuration for safe mode."""
        return {
            "require_human_approval": True,
            "max_concurrent_tasks": 2,
            "active": self._safe_mode,
        }

    def check_deviation(self, metrics: Dict[str, float]) -> Dict[str, Any]:
        """Check if behavior deviates from established baseline."""
        if not self._baseline:
            # First run: establish baseline
            self._baseline = dict(metrics)
            return {"deviated": False, "baseline": self._baseline}

        deviated = False
        for key, value in metrics.items():
            baseline_val = self._baseline.get(key, value)
            if baseline_val > 0 and value / baseline_val > 3.0:
                deviated = True
                self._deviation_count += 1
                break

        return {"deviated": deviated, "deviation_count": self._deviation_count}

    def get_compliance_report(self) -> Dict[str, Any]:
        """Get a report on compliance status."""
        total = len(self._actions)
        compliant = sum(1 for a in self._actions if a.status == ComplianceStatus.COMPLIANT)
        return {
            "total_actions": total,
            "compliance_rate": compliant / max(total, 1),
            "violations": len(self._violations),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics."""
        report = self.get_compliance_report()
        return {
            "compliance_rate": report["compliance_rate"],
            "pressure_level": self._pressure_level.value,
            "total_actions": report["total_actions"],
            "violations": report["violations"],
        }
