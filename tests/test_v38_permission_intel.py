"""
MeshCtx v3.38 — Permission Intelligence Tests
"""
import pytest
from unittest.mock import MagicMock


class TestRiskLevel:
    def test_risk_ordering(self):
        from src.core.permission_intel import RiskLevel
        assert RiskLevel.TRIVIAL.value < RiskLevel.LOW.value
        assert RiskLevel.CRITICAL.value > RiskLevel.HIGH.value


class TestRiskPredictor:
    def test_critical_actions(self):
        from src.core.permission_intel import RiskPredictor, RiskLevel
        p = RiskPredictor()
        risk, conf = p.predict_risk("rm -rf /tmp/test")
        assert risk == RiskLevel.CRITICAL
        assert conf > 0.9
    
    def test_trivial_actions(self):
        from src.core.permission_intel import RiskPredictor, RiskLevel
        p = RiskPredictor()
        risk, conf = p.predict_risk("ls -la")
        assert risk == RiskLevel.TRIVIAL
    
    def test_high_risk_actions(self):
        from src.core.permission_intel import RiskPredictor, RiskLevel
        p = RiskPredictor()
        risk, conf = p.predict_risk("delete important_file.py")
        assert risk == RiskLevel.HIGH
    
    def test_jepa_risk_score(self):
        from src.core.permission_intel import RiskPredictor
        p = RiskPredictor()
        score = p.get_jepa_risk_score("rm -rf /")
        assert 0.5 <= score <= 1.0  # Critical → high score


class TestPermissionLearner:
    def test_learn_approval(self):
        from src.core.permission_intel import PermissionLearner, RiskLevel
        learner = PermissionLearner()
        for _ in range(10):
            learner.learn_from_decision("read file.txt", RiskLevel.TRIVIAL, True)
        rate = learner.get_approval_rate("read file.txt")
        assert rate > 0.9
    
    def test_learn_denial(self):
        from src.core.permission_intel import PermissionLearner, RiskLevel
        learner = PermissionLearner()
        for _ in range(5):
            learner.learn_from_decision("rm -rf /", RiskLevel.CRITICAL, False)
        rate = learner.get_approval_rate("rm -rf /")
        assert rate < 0.5
    
    def test_auto_approve_learned(self):
        from src.core.permission_intel import PermissionLearner, RiskLevel
        learner = PermissionLearner()
        # Learn: user always approves "ls"
        for _ in range(10):
            learner.learn_from_decision("ls", RiskLevel.TRIVIAL, True)
        # Should now auto-approve
        assert learner.should_auto_approve("ls", RiskLevel.TRIVIAL)
    
    def test_never_auto_approve_critical(self):
        from src.core.permission_intel import PermissionLearner, RiskLevel
        learner = PermissionLearner()
        # Even after 100 approvals, critical ops never auto-approve
        for _ in range(100):
            learner.learn_from_decision("rm", RiskLevel.CRITICAL, True)
        assert not learner.should_auto_approve("rm -rf /", RiskLevel.CRITICAL)
    
    def test_trust_score_adjusts(self):
        from src.core.permission_intel import PermissionLearner, RiskLevel
        learner = PermissionLearner()
        initial = learner.trust_score
        learner.learn_from_decision("ls", RiskLevel.TRIVIAL, True)
        assert learner.trust_score > initial
        learner.learn_from_decision("rm -rf", RiskLevel.CRITICAL, False)
        assert learner.trust_score < 0.55


class TestPermissionIntelligence:
    def test_evaluate_trivial_action(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        result = pi.evaluate("ls -la", "file listing")
        assert "decision" in result
        assert "risk_level" in result
        assert result["risk_level"] == "TRIVIAL"
    
    def test_evaluate_critical_action(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        result = pi.evaluate("rm -rf /important", "cleanup")
        assert result["decision"] in ("require_confirmation", "ask_user")
        assert result["risk_level"] == "CRITICAL"
    
    def test_evaluate_write_action(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        result = pi.evaluate("create new_module.py", "add feature")
        assert result["risk_level"] in ("LOW", "TRIVIAL")
    
    def test_feedback_loop(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        # Simulate learning cycle
        for _ in range(8):
            pi.record_feedback("read config.yaml", True)
        # Now evaluate
        result = pi.evaluate("read config.yaml")
        assert result["approval_rate"] >= 0.8
    
    def test_get_stats(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        pi.record_feedback("ls", True)
        pi.record_feedback("rm", False)
        pi.evaluate("ls")
        
        stats = pi.get_stats()
        assert stats["total_decisions"] == 2
        assert "trust_score" in stats
        assert "auto_approve_ratio" in stats
        assert "saved_prompts" in stats
    
    def test_recent_decisions_tracked(self):
        from src.core.permission_intel import PermissionIntelligence
        pi = PermissionIntelligence()
        for i in range(5):
            pi.evaluate(f"action_{i}")
        stats = pi.get_stats()
        assert len(stats["recent_decisions"]) <= 3

    def test_sql_injection_detected(self):
        from src.core.permission_intel import PermissionIntelligence, RiskLevel
        pi = PermissionIntelligence()
        result = pi.evaluate("DROP TABLE users")
        assert result["risk_level"] == "CRITICAL"
