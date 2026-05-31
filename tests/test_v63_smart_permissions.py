"""v3.63 Smart Permissions — tests"""
import pytest
from src.core.smart_permissions import SmartPermissions, Permission, get_smart_permissions

class TestSmartPermissions:
    def test_default_ask(self):
        sp = SmartPermissions()
        assert sp.check("unknown_action") == Permission.ASK

    def test_learn_auto_approve(self):
        sp = SmartPermissions()
        sp._auto_approve_threshold = 2
        sp.learn("git status", True); sp.learn("git status", True)
        assert sp.check("git status") == Permission.AUTO_ALLOW

    def test_learn_deny_resets(self):
        sp = SmartPermissions()
        sp.learn("risky", True); sp.learn("risky", False)
        assert sp.check("risky") == Permission.ASK

    def test_add_rule(self):
        sp = SmartPermissions()
        sp.add_rule("git *", Permission.ALLOW)
        assert sp.check("git status") == Permission.ALLOW

    def test_is_safe(self):
        sp = SmartPermissions()
        assert sp.is_safe("git status")
        assert not sp.is_safe("rm -rf /")

    def test_stats(self):
        sp = SmartPermissions()
        sp.learn("git push", True)
        s = sp.get_stats()
        assert s["total_decisions"] == 1

    def test_singleton(self):
        assert get_smart_permissions() is get_smart_permissions()
