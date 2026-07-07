"""meshctx permission_intel — Permission Intelligence"""
import re
from enum import IntEnum
from collections import defaultdict
from typing import Tuple


class RiskLevel(IntEnum):
    TRIVIAL = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5


CRITICAL_PATTERNS = [
    r'\brm\s+-rf\b', r'\bdrop\s+table\b', r'\bdelete\b.*\bfrom\b',
    r'\bshutdown\b', r'\breboot\b', r'\bformat\b', r'\bmkfs\b',
    r'\bchmod\s+777\b', r'\btruncate\b', r'\bkill\s+-9\b',
]
HIGH_PATTERNS = [
    r'\bdelete\b', r'\brm\b', r'\bmv\b.*\/', r'\bcp\b.*\/etc',
    r'\bwget\b.*\|.*sh', r'\bcurl\b.*\|.*sh', r'\beval\b',
    r'\bexec\b', r'\bsudo\b', r'\bchown\b', r'\bchmod\b',
    r'\bopenssl\b', r'\bdocker\s+rm\b', r'\bwrite\b',
]
TRIVIAL_PATTERNS = [
    r'\bls\b', r'\bcat\b', r'\bhead\b', r'\btail\b', r'\bpwd\b',
    r'\bwhoami\b', r'\bdate\b', r'\buname\b', r'\becho\b', r'\bcd\b',
    r'\bping\b', r'\bwhich\b', r'\bman\b', r'\bhelp\b',
    r'\bcreate\b', r'\bread\b', r'\bcopy\b',
]


class RiskPredictor:
    """Predicts risk level of commands/actions."""

    def predict_risk(self, action: str) -> Tuple[RiskLevel, float]:
        action_lower = action.lower()
        for pat in CRITICAL_PATTERNS:
            if re.search(pat, action_lower):
                return RiskLevel.CRITICAL, 0.95
        for pat in HIGH_PATTERNS:
            if re.search(pat, action_lower):
                return RiskLevel.HIGH, 0.85
        for pat in TRIVIAL_PATTERNS:
            if re.search(pat, action_lower):
                return RiskLevel.TRIVIAL, 0.7
        return RiskLevel.MEDIUM, 0.5

    def get_jepa_risk_score(self, action: str) -> float:
        risk, conf = self.predict_risk(action)
        base = risk.value / float(RiskLevel.CRITICAL.value)
        return max(0.0, min(1.0, base * conf))


class PermissionLearner:
    """Learns from user decisions to predict auto-approval."""

    def __init__(self):
        self._decisions: dict[str, list[bool]] = defaultdict(list)
        self.trust_score: float = 0.5

    def learn_from_decision(self, action: str, risk: RiskLevel, approved: bool):
        self._decisions[action].append(approved)
        if approved:
            self.trust_score = min(1.0, self.trust_score + 0.01)
        else:
            self.trust_score = max(0.0, self.trust_score - 0.02)

    def get_approval_rate(self, action: str) -> float:
        decisions = self._decisions.get(action, [])
        if not decisions:
            return 0.0
        return sum(1 for d in decisions if d) / len(decisions)

    def should_auto_approve(self, action: str, risk: RiskLevel) -> bool:
        rate = self.get_approval_rate(action)
        return risk < RiskLevel.CRITICAL and rate > 0.8


class PermissionIntelligence:
    """Full permission intelligence system combining prediction and learning."""

    def __init__(self):
        self.predictor = RiskPredictor()
        self.learner = PermissionLearner()
        self._feedbacks: list[dict] = []
        self._decisions: list[dict] = []
        self._stats: dict = {"total_decisions": 0, "saved_prompts": 0}

    def evaluate(self, action: str, reason: str = "") -> dict:
        risk, conf = self.predictor.predict_risk(action)
        approval_rate = self.learner.get_approval_rate(action)
        should_auto = self.learner.should_auto_approve(action, risk)
        decision = "auto_approve" if should_auto else "require_confirmation"
        result = {
            "action": action,
            "risk_level": risk.name,
            "confidence": round(conf, 2),
            "approval_rate": round(approval_rate, 2),
            "decision": decision,
        }
        self._decisions.append(result)
        if len(self._decisions) > 100:
            self._decisions = self._decisions[-100:]
        if should_auto:
            self._stats["saved_prompts"] += 1
        return result

    def record_feedback(self, action: str, approved: bool):
        risk, _ = self.predictor.predict_risk(action)
        self.learner.learn_from_decision(action, risk, approved)
        self._feedbacks.append({"action": action, "approved": approved})
        self._stats["total_decisions"] += 1

    def get_stats(self) -> dict:
        return {
            "total_decisions": self._stats["total_decisions"],
            "trust_score": round(self.learner.trust_score, 2),
            "auto_approve_ratio": round(
                self._stats["saved_prompts"] / max(1, self._stats["total_decisions"]), 2
            ),
            "saved_prompts": self._stats["saved_prompts"],
            "recent_decisions": [
                d["action"] for d in self._decisions[-3:]
            ],
        }
