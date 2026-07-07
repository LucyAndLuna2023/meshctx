"""SDB Framework — real implementation (Stochastic-Deterministic Barrier)"""

import hashlib
import time
import uuid
import statistics
from enum import Enum


class SDBPhase(str, Enum):
    PROPOSE = "propose"
    VERIFY = "verify"
    COMMIT = "commit"
    REJECT = "reject"


class RejectReason(str, Enum):
    SYNTAX_ERROR = "syntax_error"
    PRINCIPLE_VIOLATION = "principle_violation"
    REPLAY_DIVERGENCE = "replay_divergence"
    VERIFICATION_FAILED = "verification_failed"


class SDBRecord:
    """A single SDB record representing a proposed action through the pipeline."""

    def __init__(self, record_id="", proposer_model="", proposed_action="",
                 phase=SDBPhase.PROPOSE, replay_hash="", raw_output="",
                 deterministic_context=""):
        self.record_id = record_id
        self.proposer_model = proposer_model
        self.proposed_action = proposed_action
        self.params = {}
        self.raw_output = raw_output
        self.deterministic_context = deterministic_context
        self.phase = phase
        self.replay_hash = replay_hash
        self.verification_passed = False
        self.commit_success = False
        self.reject_reason = None
        self.rules = []
        self.verification_checks = {}
        self.timestamp = time.time()


class SDBEngine:
    """Stochastic-Deterministic Barrier Engine.

    Pipeline: Propose → Verify → Commit/Reject
    """

    def __init__(self, variance_threshold=0.3, track_replay=True, max_records=100):
        self.variance_threshold = variance_threshold
        self.track_replay = track_replay
        self.max_records = max_records
        self._records = []
        self._replay_cache = {}  # replay_hash → raw_output
        self._stats = {
            "total_proposals": 0,
            "total_commits": 0,
            "total_rejects": 0,
            "replay_divergences": 0,
            "reject_by_reason": {},
        }

    def _hash_context(self, deterministic_context):
        """Hash the deterministic context for replay detection."""
        if not deterministic_context:
            return ""
        return hashlib.sha256(deterministic_context.encode()).hexdigest()[:16]

    def propose(self, model_id, action, params, raw_output, deterministic_context=None):
        """Phase 1: Propose — stochastic generation."""
        ctx = deterministic_context or ""
        replay_hash = self._hash_context(ctx)

        record = SDBRecord(
            record_id=f"sdb_{uuid.uuid4().hex[:16]}",
            proposer_model=model_id,
            proposed_action=action,
            phase=SDBPhase.PROPOSE,
            replay_hash=replay_hash,
            raw_output=raw_output,
            deterministic_context=ctx,
        )
        record.params = dict(params) if params else {}

        self._stats["total_proposals"] += 1
        self._records.append(record)

        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

        return record

    def verify(self, record, rules, checks):
        """Phase 2: Verify — deterministic validation."""
        record.rules = list(rules)
        record.verification_checks = dict(checks)
        record.phase = SDBPhase.VERIFY

        all_passed = all(checks.values()) if checks else True

        # Replay divergence check
        if self.track_replay and record.replay_hash and record.replay_hash in self._replay_cache:
            cached_output = self._replay_cache[record.replay_hash]
            if cached_output != record.raw_output:
                record.reject_reason = RejectReason.REPLAY_DIVERGENCE
                record.verification_passed = False
                self._stats["replay_divergences"] += 1
                return record

        record.verification_passed = all_passed
        return record

    def commit(self, record, success=None):
        """Phase 3/4: Commit or Reject."""
        if success is None:
            success = record.verification_passed

        if record.verification_passed and success:
            record.phase = SDBPhase.COMMIT
            record.commit_success = True
            self._stats["total_commits"] += 1

            # Cache for replay detection
            if self.track_replay and record.replay_hash:
                self._replay_cache[record.replay_hash] = record.raw_output
        else:
            record.phase = SDBPhase.REJECT
            record.commit_success = False
            self._stats["total_rejects"] += 1

            reason = record.reject_reason
            if reason is None:
                reason = RejectReason.VERIFICATION_FAILED
                record.reject_reason = reason

            reason_key = reason.value if isinstance(reason, RejectReason) else str(reason)
            self._stats["reject_by_reason"][reason_key] = (
                self._stats["reject_by_reason"].get(reason_key, 0) + 1
            )

        return record

    def pipeline(self, model_id, action, params, raw_output, rules, checks,
                 deterministic_context=None):
        """Convenience: propose → verify → commit in one call."""
        record = self.propose(model_id, action, params, raw_output, deterministic_context)
        record = self.verify(record, rules, checks)
        record = self.commit(record)
        return record

    def get_stats(self):
        """Return engine statistics."""
        total = self._stats["total_proposals"]
        commits = self._stats["total_commits"]
        rejects = self._stats["total_rejects"]
        divergences = self._stats["replay_divergences"]

        commit_rate = commits / total if total > 0 else 0.0
        reject_rate = rejects / total if total > 0 else 0.0
        divergence_rate = divergences / total if total > 0 else 0.0

        return {
            "total_proposals": total,
            "total_commits": commits,
            "total_rejects": rejects,
            "commit_rate": commit_rate,
            "reject_rate": reject_rate,
            "replay_divergences": divergences,
            "replay_divergence_rate": divergence_rate,
            "reject_by_reason": dict(self._stats["reject_by_reason"]),
        }

    def get_replay_report(self):
        """Return replay divergence report."""
        stats = self.get_stats()
        return {
            "divergences": stats["replay_divergences"],
            "divergence_rate": stats["replay_divergence_rate"],
        }

    def get_variance_report(self, window=100):
        """Return variance report over the last `window` records."""
        records = self._records[-window:]
        commits = [r for r in records if r.phase == SDBPhase.COMMIT]
        rejects = [r for r in records if r.phase == SDBPhase.REJECT]
        total = len(commits) + len(rejects)

        sample_size = total
        commit_rate = len(commits) / total if total > 0 else 0.0

        # Variance coefficient: std dev of binary outcomes / mean
        if total > 0:
            outcomes = [1 if r.phase == SDBPhase.COMMIT else 0 for r in records
                        if r.phase in (SDBPhase.COMMIT, SDBPhase.REJECT)]
            if len(outcomes) > 1:
                variance_coefficient = statistics.pstdev(outcomes) / statistics.mean(outcomes) if statistics.mean(outcomes) > 0 else 0.0
            else:
                variance_coefficient = 0.0
        else:
            variance_coefficient = 0.0

        # By model
        by_model = {}
        for r in records:
            if r.phase not in (SDBPhase.COMMIT, SDBPhase.REJECT):
                continue
            model = r.proposer_model
            if model not in by_model:
                by_model[model] = {"commits": 0, "total": 0}
            by_model[model]["total"] += 1
            if r.phase == SDBPhase.COMMIT:
                by_model[model]["commits"] += 1

        by_model_result = {}
        for model, data in by_model.items():
            rate = data["commits"] / data["total"] if data["total"] > 0 else 0.0
            by_model_result[model] = {"commit_rate": rate, "sample_size": data["total"]}

        # Architectural momentum: proportion of consecutive commits
        recent_outcomes = [1 if r.phase == SDBPhase.COMMIT else 0 for r in records
                           if r.phase in (SDBPhase.COMMIT, SDBPhase.REJECT)]
        momentum = 0.0
        if len(recent_outcomes) > 1:
            consecutive = sum(1 for a, b in zip(recent_outcomes, recent_outcomes[1:]) if a == 1 and b == 1)
            pairs = len(recent_outcomes) - 1
            momentum = consecutive / pairs if pairs > 0 else 0.0
        elif len(recent_outcomes) == 1:
            momentum = 1.0 if recent_outcomes[0] == 1 else 0.0

        return {
            "overall": {
                "sample_size": sample_size,
                "commit_rate": commit_rate,
                "variance_coefficient": variance_coefficient,
            },
            "by_model": by_model_result,
            "architectural_momentum": momentum,
        }

    def get_reliability_score(self):
        """Compute reliability score (0-100) with grade."""
        stats = self.get_stats()
        variance = self.get_variance_report(window=self.max_records)

        commit_rate = stats["commit_rate"]
        divergence_rate = stats["replay_divergence_rate"]
        momentum = variance.get("architectural_momentum", 0)

        # Components weighted to sum to 100
        commit_contribution = round(commit_rate * 60, 2)
        replay_contribution = round((1.0 - min(divergence_rate, 1.0)) * 25, 2)
        architectural_contribution = round(momentum * 15, 2)

        total_score = round(commit_contribution + replay_contribution + architectural_contribution, 2)
        total_score = min(total_score, 100.0)

        if total_score >= 90:
            grade = "S"
        elif total_score >= 75:
            grade = "A"
        elif total_score >= 50:
            grade = "B"
        else:
            grade = "C"

        return {
            "reliability_score": total_score,
            "grade": grade,
            "components": {
                "commit_rate_contribution": commit_contribution,
                "replay_contribution": replay_contribution,
                "architectural_contribution": architectural_contribution,
            },
        }

    def get_recent_records(self, limit=10):
        """Return the most recent records."""
        return list(self._records[-limit:])

    def get_rejects(self):
        """Return all rejected records."""
        return [r for r in self._records if r.phase == SDBPhase.REJECT]

    def clear(self):
        """Clear records but retain statistics."""
        self._records.clear()
        self._replay_cache.clear()


_engine = None


def get_sdb_engine():
    """Get the singleton SDBEngine instance."""
    global _engine
    if _engine is None:
        _engine = SDBEngine()
    return _engine
