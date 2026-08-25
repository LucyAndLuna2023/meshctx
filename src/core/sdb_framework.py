"""SDB Framework — real implementation (Stochastic-Deterministic Barrier)

SDB 是 meshctx 的自修改安全屏障:
  1. Propose  (stochastic) — 模型生成的动作/输出被记录, 连同确定性上下文一起哈希。
  2. Verify   (deterministic) — 规则检查 + 重放一致性校验, 全部通过才放行。
  3. Commit   — 通过则提交 (并缓存输出用于重放检测), 否则 Reject (记录拒绝原因)。

纯 stdlib 实现: hashlib / time / uuid, 无第三方依赖。
"""
from __future__ import annotations
from enum import Enum
from abc import ABC
import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional

class SDBPhase(str, Enum):
    PROPOSE = 'propose'
    VERIFY = 'verify'
    COMMIT = 'commit'
    REJECT = 'reject'

class RejectReason(str, Enum):
    SYNTAX_ERROR = 'syntax_error'
    PRINCIPLE_VIOLATION = 'principle_violation'
    REPLAY_DIVERGENCE = 'replay_divergence'
    VERIFICATION_FAILED = 'verification_failed'

class SDBRecord:
    """A single SDB record representing a proposed action through the pipeline."""

    def __init__(
        self,
        record_id='',
        proposer_model='',
        proposed_action='',
        phase=SDBPhase.PROPOSE,
        replay_hash='',
        raw_output='',
        deterministic_context='',
    ):
        self.record_id = record_id or f"sdb_{uuid.uuid4().hex[:12]}"
        self.proposer_model = proposer_model
        self.proposed_action = proposed_action
        self.phase = phase
        self.replay_hash = replay_hash
        self.raw_output = raw_output
        self.deterministic_context = deterministic_context

        # Pipeline-stage state (filled by verify / commit)
        self.params: Dict[str, Any] = {}
        self.timestamp: float = time.time()
        self.rules: List[str] = []
        self.check_results: Dict[str, bool] = {}
        self.verification_passed: bool = False
        self.reject_reason: Optional[RejectReason] = None
        self.commit_success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """可序列化的记录视图 (不含内部 live 引用)。"""
        return {
            "record_id": self.record_id,
            "proposer_model": self.proposer_model,
            "proposed_action": self.proposed_action,
            "phase": self.phase.value,
            "replay_hash": self.replay_hash,
            "deterministic_context": self.deterministic_context,
            "verification_passed": self.verification_passed,
            "reject_reason": self.reject_reason.value if self.reject_reason else None,
            "commit_success": self.commit_success,
            "timestamp": self.timestamp,
        }

    def __repr__(self):
        return (
            f"<SDBRecord {self.record_id} {self.proposer_model} "
            f"{self.proposed_action} phase={self.phase.value} "
            f"passed={self.verification_passed}>"
        )


class SDBEngine:
    """Stochastic-Deterministic Barrier Engine."""

    def __init__(self, variance_threshold=0.3, track_replay=True, max_records=100):
        self.variance_threshold = variance_threshold
        self.track_replay = track_replay
        self.max_records = max_records

        self._records: List[SDBRecord] = []
        self._replay_cache: Dict[str, str] = {}   # replay_hash -> committed raw_output
        self._stats: Dict[str, Any] = {
            "total_proposals": 0,
            "total_commits": 0,
            "total_rejects": 0,
            "replay_divergences": 0,
            "replay_checks": 0,
            "reject_by_reason": {},
            "variance_threshold": variance_threshold,
        }

    # ── helpers ──────────────────────────────────────────────────

    def _hash_context(self, deterministic_context):
        """Hash the deterministic context for replay detection."""
        if not deterministic_context:
            return ""
        return hashlib.sha256(str(deterministic_context).encode("utf-8")).hexdigest()

    def _prune(self):
        """保持记录数量不超过 max_records (淘汰最旧)。"""
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

    def _record(self, record: SDBRecord):
        self._records.append(record)
        self._prune()

    # ── Phase 1: Propose ─────────────────────────────────────────

    def propose(self, model_id, action, params, raw_output, deterministic_context=None):
        """Phase 1: Propose — stochastic generation."""
        replay_hash = self._hash_context(deterministic_context)
        record = SDBRecord(
            record_id=f"sdb_{uuid.uuid4().hex[:12]}",
            proposer_model=model_id,
            proposed_action=action,
            phase=SDBPhase.PROPOSE,
            replay_hash=replay_hash,
            raw_output=raw_output,
            deterministic_context=deterministic_context,
        )
        record.params = dict(params) if params else {}
        self._record(record)
        self._stats["total_proposals"] += 1
        return record

    # ── Phase 2: Verify ───────────────────────────────────────────

    def verify(self, record, rules, checks):
        """Phase 2: Verify — deterministic validation.

        rules 中的每条规则必须在 checks 中给出对应布尔结果 (缺省视为 False, 失败关闭);
        若启用 track_replay 且 deterministic_context 已提交过不同输出 → 重放分歧拒绝。
        """
        record.phase = SDBPhase.VERIFY
        record.rules = list(rules) if rules else []
        record.check_results = {}
        record.verification_passed = True

        # 1) 确定性规则检查 (fail-closed)
        for rule in record.rules:
            passed = bool(checks.get(rule, False)) if isinstance(checks, dict) else False
            record.check_results[rule] = passed
            if not passed:
                record.verification_passed = False

        # 2) 重放一致性: 相同 deterministic_context 必须产出相同输出
        if self.track_replay and record.replay_hash:
            cached = self._replay_cache.get(record.replay_hash)
            if cached is not None:
                self._stats["replay_checks"] += 1
                if cached != record.raw_output:
                    record.verification_passed = False
                    record.reject_reason = RejectReason.REPLAY_DIVERGENCE
                    self._stats["replay_divergences"] += 1

        # 语法错误 / 原则违反的便捷归类 (由调用方显式设置 reject_reason 时优先保留)
        if not record.verification_passed and record.reject_reason is None:
            if not record.check_results.get("syntax_check", True) or \
               not record.check_results.get("syntax", True):
                record.reject_reason = RejectReason.SYNTAX_ERROR
            elif not record.check_results.get("principle_check", True) or \
                 not record.check_results.get("principle", True):
                record.reject_reason = RejectReason.PRINCIPLE_VIOLATION
        return record

    # ── Phase 3/4: Commit / Reject ────────────────────────────────

    def commit(self, record, success=None):
        """Phase 3/4: Commit or Reject."""
        if success is None:
            success = record.verification_passed
        record.commit_success = bool(success)

        if success:
            record.phase = SDBPhase.COMMIT
            self._stats["total_commits"] += 1
            if self.track_replay and record.replay_hash:
                # 只缓存通过验证并提交的输出
                self._replay_cache[record.replay_hash] = record.raw_output
        else:
            record.phase = SDBPhase.REJECT
            self._stats["total_rejects"] += 1
            reason = record.reject_reason or RejectReason.VERIFICATION_FAILED
            record.reject_reason = reason
            key = reason.value
            self._stats["reject_by_reason"][key] = self._stats["reject_by_reason"].get(key, 0) + 1
        return record

    # ── Convenience pipeline ──────────────────────────────────────

    def pipeline(self, model_id, action, params, raw_output, rules, checks, deterministic_context=None):
        """Convenience: propose → verify → commit in one call."""
        record = self.propose(model_id, action, params, raw_output, deterministic_context)
        record = self.verify(record, rules, checks)
        record = self.commit(record)
        return record

    # ── Statistics & reports ──────────────────────────────────────

    def get_stats(self):
        """Return engine statistics."""
        total = self._stats["total_proposals"]
        commits = self._stats["total_commits"]
        rejects = self._stats["total_rejects"]
        divergences = self._stats["replay_divergences"]
        return {
            "total_proposals": total,
            "total_commits": commits,
            "total_rejects": rejects,
            "commit_rate": (commits / total) if total else 0,
            "reject_rate": (rejects / total) if total else 0,
            "replay_divergences": divergences,
            "replay_divergence_rate": (divergences / total) if total else 0,
            "reject_by_reason": dict(self._stats["reject_by_reason"]),
            "records": len(self._records),
            "variance_threshold": self.variance_threshold,
        }

    def get_replay_report(self):
        """Return replay divergence report."""
        total = self._stats["total_proposals"]
        checks = self._stats["replay_checks"]
        divergences = self._stats["replay_divergences"]
        return {
            "total_replays": checks,
            "divergences": divergences,
            "divergence_rate": (divergences / checks) if checks else 0.0,
            "cache_size": len(self._replay_cache),
        }

    def _window_records(self, window):
        """取最近 window 条记录 (每条记录含 commit 结果)。"""
        return self._records[-window:] if window > 0 else self._records

    def get_variance_report(self, window=100):
        """Return variance report over the last `window` records."""
        records = self._window_records(window)
        n = len(records)
        commits = [r for r in records if r.commit_success]

        overall = {
            "sample_size": n,
            "commit_count": len(commits),
            "commit_rate": (len(commits) / n) if n else 0.0,
            "variance_coefficient": 0.0,
        }

        # 按模型分组统计提交率 → 计算变异系数 (CV = std/mean)
        by_model: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            m = by_model.setdefault(
                rec.proposer_model,
                {"samples": 0, "commits": 0, "commit_rate": 0.0},
            )
            m["samples"] += 1
            if rec.commit_success:
                m["commits"] += 1
        for m in by_model.values():
            m["commit_rate"] = m["commits"] / m["samples"] if m["samples"] else 0.0

        rates = [m["commit_rate"] for m in by_model.values() if m["samples"] > 0]
        if len(rates) > 1:
            mean = sum(rates) / len(rates)
            if mean > 0:
                var = sum((r - mean) ** 2 for r in rates) / len(rates)
                overall["variance_coefficient"] = round((var ** 0.5) / mean, 4)

        # 架构惯性 (architectural momentum): 连续成功提交的保持率
        momentum = 0.0
        if n > 1:
            consecutive = sum(
                1 for i in range(1, n) if records[i - 1].commit_success and records[i].commit_success
            )
            momentum = consecutive / (n - 1)
        overall["architectural_momentum"] = round(momentum, 4)

        return {
            "overall": overall,
            "by_model": {k: {"samples": v["samples"], "commits": v["commits"],
                             "commit_rate": v["commit_rate"]} for k, v in by_model.items()},
            "architectural_momentum": overall["architectural_momentum"],
            "window": window,
        }

    def get_reliability_score(self):
        """Compute reliability score (0-100) with grade."""
        stats = self.get_stats()
        variance = self.get_variance_report(window=self.max_records)
        commit_rate = stats["commit_rate"]
        replay_rate = stats["replay_divergence_rate"]
        momentum = variance["overall"].get("architectural_momentum", 0.0)

        commit_rate_contribution = round(commit_rate * 60, 2)
        replay_contribution = round((1.0 - replay_rate) * 20, 2)
        architectural_contribution = round(momentum * 20, 2)
        reliability_score = round(
            commit_rate_contribution + replay_contribution + architectural_contribution, 2
        )

        if reliability_score >= 90:
            grade, recommendation = "S (顶尖可靠)", "模型输出高度稳定, 可放开自主执行。"
        elif reliability_score >= 80:
            grade, recommendation = "A (可靠)", "模型整体可靠, 建议保持现有审批策略。"
        elif reliability_score >= 70:
            grade, recommendation = "B (基本可靠)", "存在一定波动, 建议高风险动作保留人工审批。"
        elif reliability_score >= 60:
            grade, recommendation = "C (需监控)", "波动明显, 建议收紧规则并增加验证项。"
        else:
            grade, recommendation = "D (不可靠)", "强烈建议暂停自主执行, 全面人工审批。"

        return {
            "reliability_score": reliability_score,
            "grade": grade,
            "recommendation": recommendation,
            "components": {
                "commit_rate_contribution": commit_rate_contribution,
                "replay_contribution": replay_contribution,
                "architectural_contribution": architectural_contribution,
            },
            "commit_rate": commit_rate,
            "replay_divergence_rate": replay_rate,
            "architectural_momentum": momentum,
        }

    def get_recent_records(self, limit=10):
        """Return the most recent records."""
        return self._records[-limit:]

    def get_rejects(self):
        """Return all rejected records."""
        return [r for r in self._records if r.phase == SDBPhase.REJECT]

    def clear(self):
        """Clear records but retain statistics."""
        self._records = []


_engine = None


def get_sdb_engine():
    """Get the singleton SDBEngine instance."""
    global _engine
    if _engine is None:
        _engine = SDBEngine()
    return _engine


__all__ = ["SDBPhase", "RejectReason", "SDBRecord", "SDBEngine", "get_sdb_engine"]
