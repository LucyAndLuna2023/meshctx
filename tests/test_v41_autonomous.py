"""Tests for Autonomous Engine — v2.41"""
import pytest
import time
import tempfile
from pathlib import Path
from src.core.autonomous_engine import (
    AutonomousEngine, Incident, IncidentStatus,
    Severity, MetricPoint, FixRecord,
)


class TestAutonomousEngine:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = AutonomousEngine(log_dir=self.tmp)

    def test_init(self):
        assert self.engine.total_incidents == 0
        assert len(self.engine.active_incidents) == 0

    def test_add_metric(self):
        self.engine._add_metric("test_metric", 42.0)
        assert "test_metric" in self.engine.metrics
        assert self.engine.metrics["test_metric"][-1].value == 42.0

    def test_baseline_established(self):
        for i in range(15):
            self.engine._add_metric("stable_metric", 50.0)
        assert "stable_metric" in self.engine.baselines
        mean, std = self.engine.baselines["stable_metric"]
        assert abs(mean - 50.0) < 1.0
        assert std < 1.0

    def test_create_incident(self):
        inc = self.engine._create_incident(
            "test incident", Severity.WARNING, ["symptom1", "symptom2"]
        )
        assert inc is not None
        assert inc.severity == Severity.WARNING
        assert len(inc.symptoms) == 2
        assert self.engine.total_incidents == 1

    def test_incident_dedup(self):
        inc1 = self.engine._create_incident("same", Severity.WARNING, ["s1"])
        inc2 = self.engine._create_incident("same", Severity.WARNING, ["s2"])
        assert inc1 is inc2  # Same incident returned, not duplicated

    def test_diagnose_cpu(self):
        inc = Incident(
            id="test", title="test", severity=Severity.ERROR,
            detected_at=time.time(), symptoms=["cpu_percent=98.0"]
        )
        self.engine._diagnose(inc)
        assert inc.root_cause == "high_cpu_load"

    def test_diagnose_memory(self):
        inc = Incident(
            id="test", title="test", severity=Severity.ERROR,
            detected_at=time.time(), symptoms=["memory_percent=97.0"]
        )
        self.engine._diagnose(inc)
        assert inc.root_cause == "memory_pressure"

    def test_apply_fix_memory_cleanup(self):
        inc = Incident(
            id="test", title="test", severity=Severity.ERROR,
            detected_at=time.time(), root_cause="memory_pressure",
            fix_applied="trigger_memory_cleanup"
        )
        result = self.engine._apply_fix(inc)
        assert result is True

    def test_process_incidents_full_cycle(self):
        # Create incident
        inc = self.engine._create_incident(
            "test", Severity.ERROR, ["memory_percent=98.0"]
        )
        assert inc.status == IncidentStatus.DETECTED

        # Process should diagnose + fix
        self.engine._process_incidents()
        assert inc.status == IncidentStatus.DIAGNOSING
        assert inc.root_cause == "memory_pressure"

        # Process again should fix
        self.engine._process_incidents()
        # Should be fixed and moved to history
        assert inc.status == IncidentStatus.FIXED
        assert len(self.engine.active_incidents) == 0
        assert len(self.engine.incident_history) == 1

    def test_learn_fix(self):
        self.engine.learn_fix(["cpu_percent=99"], "high_cpu", "throttle", True)
        pattern = self.engine._symptom_pattern(["cpu_percent=99"])
        assert pattern in self.engine.fix_database
        assert self.engine.fix_database[pattern].success_count == 1

    def test_fix_database_persistence(self):
        self.engine.learn_fix(["disk=99"], "disk_full", "cleanup", True)
        self.engine._save_fix_database()

        # Reload
        e2 = AutonomousEngine(log_dir=self.tmp)
        pattern = e2._symptom_pattern(["disk=99"])
        assert pattern in e2.fix_database

    def test_health_report(self):
        self.engine._create_incident("test", Severity.WARNING, ["s1"])
        report = self.engine.get_health_report()
        assert report["total_incidents"] == 1
        assert "active_incidents" in report
        assert "fix_success_rate" in report

    def test_anomaly_detection_triggers(self):
        # Establish baseline
        for i in range(15):
            self.engine._add_metric("stable", 50.0)
        # Add anomaly
        self.engine._add_metric("stable", 500.0)  # z-score > 5
        self.engine._detect_anomalies()
        assert self.engine.total_incidents >= 1

    def test_idle_optimization_no_crash(self):
        self.engine._run_idle_optimizations()  # Should not crash

    def test_symptom_pattern_consistent(self):
        p1 = self.engine._symptom_pattern(["cpu=99", "mem=95"])
        p2 = self.engine._symptom_pattern(["cpu=99", "mem=95"])
        assert p1 == p2

    def test_evolution_log(self):
        self.engine._log_evolution("test_event", {"key": "value"})
        assert len(self.engine.evolution_log) == 1
        assert self.engine.evolution_log[0]["event"] == "test_event"

    def test_resource_exhaustion_check(self):
        self.engine._add_metric("cpu_percent", 98.0)
        self.engine._check_resource_exhaustion()
        assert self.engine.total_incidents >= 1


class TestSeverity:
    def test_ordering(self):
        assert Severity.CRITICAL.value > Severity.ERROR.value
        assert Severity.WARNING.value > Severity.INFO.value


class TestIncidentStatus:
    def test_values(self):
        assert IncidentStatus.DETECTED.value == "detected"
        assert IncidentStatus.FIXED.value == "fixed"
