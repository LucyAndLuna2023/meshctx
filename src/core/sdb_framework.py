"""
SDB (Stochastic-Deterministic Boundary) Framework — v2.46
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从论文 arXiv 2605.20173 直接实现: "A Methodology for Selecting and
Composing Runtime Architecture Patterns for Production LLM Agents"

核心理论: 生产级LLM Agent的可靠性取决于随机输出与确定性系统之间的
边界管理。SDB = 四部分合约 {Proposer → Verifier → Commit → Reject}

meshctx应用: 升级ActionGate + PreActionChecker → 形式化SDB层
量化指标: rejection_rate, commit_rate, variance_coefficient, replay_divergence
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# SDB 核心合约
# ═══════════════════════════════════════════════════════════════

class SDBPhase(Enum):
    """SDB四阶段"""
    PROPOSE = "propose"    # LLM提出行动 (stochastic)
    VERIFY = "verify"      # 确定性验证
    COMMIT = "commit"      # 执行行动
    REJECT = "reject"      # 安全拒绝


class RejectReason(Enum):
    """拒绝原因分类"""
    PRINCIPLE_VIOLATION = "principle_violation"  # 违反安全原则
    SYNTAX_ERROR = "syntax_error"               # 语法/格式错误
    VARIANCE_THRESHOLD = "variance_threshold"    # 方差超过阈值
    SCHEMA_MISMATCH = "schema_mismatch"         # 输出格式不匹配
    REPLAY_DIVERGENCE = "replay_divergence"      # 重放分歧
    MANUAL_OVERRIDE = "manual_override"          # 人工干预


@dataclass
class SDBRecord:
    """单次SDB边界的完整记录"""
    # 身份
    record_id: str = ""
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""

    # 提议 (stochastic)
    proposer_model: str = ""       # 使用的LLM模型
    proposed_action: str = ""      # 提议的工具/操作
    proposed_params: Dict = field(default_factory=dict)
    raw_llm_output: str = ""       # 原始LLM输出

    # 验证 (deterministic)
    verifier_rules: List[str] = field(default_factory=list)
    verification_passed: bool = False
    verification_details: Dict = field(default_factory=dict)

    # 结果
    phase: SDBPhase = SDBPhase.PROPOSE
    commit_success: bool = False
    reject_reason: Optional[RejectReason] = None
    elapsed_ms: float = 0.0

    # 重放检测
    replay_hash: str = ""          # 确定性输入的hash
    replay_previous_output: Optional[str] = None  # 上次同样输入的输出

    def to_dict(self) -> Dict:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "proposer_model": self.proposer_model,
            "proposed_action": self.proposed_action,
            "proposed_params": self.proposed_params,
            "verification_passed": self.verification_passed,
            "phase": self.phase.value,
            "commit_success": self.commit_success,
            "reject_reason": self.reject_reason.value if self.reject_reason else None,
            "elapsed_ms": self.elapsed_ms,
            "replay_hash": self.replay_hash,
        }


# ═══════════════════════════════════════════════════════════════
# SDB 引擎
# ═══════════════════════════════════════════════════════════════

class SDBEngine:
    """SDB边界管理引擎 — 生产级LLM Agent的可靠性核心"""

    def __init__(self, variance_threshold: float = 0.3,
                 track_replay: bool = True,
                 max_records: int = 1000):
        self.variance_threshold = variance_threshold
        self.track_replay = track_replay
        self.max_records = max_records

        # 记录存储
        self._records: List[SDBRecord] = []
        self._replay_cache: Dict[str, str] = {}  # hash → previous_output

        # 统计
        self._stats = {
            "total_proposals": 0,
            "total_commits": 0,
            "total_rejects": 0,
            "reject_by_reason": {},
            "total_replay_checks": 0,
            "replay_divergences": 0,
        }

    # ── Propose (Phase 1: Stochastic) ──────────────────────

    def propose(self, model_id: str, action: str, params: Dict,
                raw_output: str, deterministic_context: str = "",
                agent_id: str = "") -> SDBRecord:
        """LLM提出行动 → 进入SDB管道

        Args:
            model_id: LLM模型标识 (用于方差追踪)
            action: 提议的工具/操作名
            params: 参数
            raw_output: 原始LLM输出
            deterministic_context: 确定性上下文 (用于重放检测)
            agent_id: Agent标识
        """
        record = SDBRecord(
            record_id=f"sdb_{int(time.time()*1000)}_{len(self._records):06d}",
            timestamp=time.time(),
            agent_id=agent_id,
            proposer_model=model_id,
            proposed_action=action,
            proposed_params=params,
            raw_llm_output=raw_output,
            phase=SDBPhase.PROPOSE,
        )

        # 计算重放hash (确定性上下文的指纹)
        if self.track_replay and deterministic_context:
            record.replay_hash = hashlib.md5(
                deterministic_context.encode()
            ).hexdigest()
            # 检查是否有之前的输出
            if record.replay_hash in self._replay_cache:
                record.replay_previous_output = self._replay_cache[record.replay_hash]
                self._stats["total_replay_checks"] += 1

        self._stats["total_proposals"] += 1
        return record

    # ── Verify (Phase 2: Deterministic) ────────────────────

    def verify(self, record: SDBRecord,
               rules: List[str],
               checks: Dict[str, bool]) -> SDBRecord:
        """确定性验证

        Args:
            record: 从propose()返回的记录
            rules: 应用的验证规则列表
            checks: {rule_name: passed?} 验证结果
        """
        record.phase = SDBPhase.VERIFY
        record.verifier_rules = rules
        record.verification_details = checks

        # 全部规则通过才放行
        record.verification_passed = all(checks.values())

        # 重放分歧检测
        if (self.track_replay and record.replay_previous_output is not None
                and record.verification_passed):
            # 检查输出是否与上次不同
            if record.raw_llm_output != record.replay_previous_output:
                # 重放分歧: 相同确定性输入产生不同LLM输出
                record.reject_reason = RejectReason.REPLAY_DIVERGENCE
                record.verification_passed = False
                record.phase = SDBPhase.REJECT
                self._stats["replay_divergences"] += 1
                logger.warning(f"⚠️ 重放分歧: 相同输入产生不同输出 "
                               f"(model={record.proposer_model}, hash={record.replay_hash[:12]})")

        return record

    # ── Commit / Reject (Phase 3-4) ────────────────────────

    def commit(self, record: SDBRecord, success: bool = True) -> SDBRecord:
        """执行或拒绝"""
        if record.verification_passed and success:
            record.phase = SDBPhase.COMMIT
            record.commit_success = True
            self._stats["total_commits"] += 1

            # 缓存输出用于重放检测
            if self.track_replay and record.replay_hash:
                self._replay_cache[record.replay_hash] = record.raw_llm_output
        else:
            record.phase = SDBPhase.REJECT
            if record.reject_reason is None:
                record.reject_reason = RejectReason.SCHEMA_MISMATCH
            self._stats["total_rejects"] += 1
            reason_key = record.reject_reason.value
            self._stats["reject_by_reason"][reason_key] = \
                self._stats["reject_by_reason"].get(reason_key, 0) + 1

        # 保存记录
        record.elapsed_ms = (time.time() - record.timestamp) * 1000
        self._records.append(record)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

        return record

    # ── Quick SDB Pipeline ──────────────────────────────────

    def pipeline(self, model_id: str, action: str, params: Dict,
                 raw_output: str, rules: List[str], checks: Dict[str, bool],
                 deterministic_context: str = "", agent_id: str = "") -> SDBRecord:
        """一键SDB管道: propose → verify → commit"""
        record = self.propose(model_id, action, params, raw_output,
                              deterministic_context, agent_id)
        record = self.verify(record, rules, checks)
        record = self.commit(record)
        return record

    # ── Statistics & Metrics (可量化!) ─────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取SDB统计 — 证明可靠性"""
        total = self._stats["total_proposals"]
        commits = self._stats["total_commits"]
        rejects = self._stats["total_rejects"]
        divergences = self._stats["replay_divergences"]

        return {
            # 核心指标
            "total_proposals": total,
            "total_commits": commits,
            "total_rejects": rejects,
            "commit_rate": round(commits / total, 4) if total > 0 else 0,
            "reject_rate": round(rejects / total, 4) if total > 0 else 0,

            # 拒绝原因分布
            "reject_by_reason": dict(self._stats["reject_by_reason"]),

            # 重放指标 (论文核心)
            "replay_checks": self._stats["total_replay_checks"],
            "replay_divergences": divergences,
            "replay_divergence_rate": round(divergences / self._stats["total_replay_checks"], 4)
            if self._stats["total_replay_checks"] > 0 else 0,

            # 延迟
            "avg_elapsed_ms": round(
                sum(r.elapsed_ms for r in self._records[-100:]) / min(100, len(self._records)), 1
            ) if self._records else 0,

            # 缓存
            "replay_cache_size": len(self._replay_cache),
            "total_records": len(self._records),
        }

    def get_variance_report(self, window: int = 100) -> Dict[str, Any]:
        """模型输出方差报告 — 测量per-call LLM variance

        论文核心贡献: 分离 per-call model variance 和 architectural momentum
        """
        if len(self._records) < 2:
            return {"variance": 0, "message": "数据不足"}

        recent = self._records[-window:]

        # 按模型分组计算提交率方差
        model_stats: Dict[str, List[float]] = {}
        for r in recent:
            model = r.proposer_model or "unknown"
            if model not in model_stats:
                model_stats[model] = []
            model_stats[model].append(1.0 if r.commit_success else 0.0)

        variances = {}
        for model, outcomes in model_stats.items():
            if len(outcomes) >= 3:
                arr = np.array(outcomes)
                variances[model] = {
                    "commit_rate": round(float(np.mean(arr)), 4),
                    "std_dev": round(float(np.std(arr)), 4),
                    "variance": round(float(np.var(arr)), 4),
                    "sample_size": len(outcomes),
                }

        # 整体方差
        all_outcomes = [1.0 if r.commit_success else 0.0 for r in recent]
        all_arr = np.array(all_outcomes)

        return {
            "overall": {
                "commit_rate": round(float(np.mean(all_arr)), 4),
                "std_dev": round(float(np.std(all_arr)), 4),
                "variance_coefficient": round(
                    float(np.std(all_arr) / max(0.001, np.mean(all_arr))), 4
                ),
                "sample_size": len(recent),
            },
            "by_model": variances,
            "architectural_momentum": round(
                1.0 - float(np.var(all_arr)), 4
            ) if len(recent) >= 3 else 0,
            "timestamp": time.time(),
        }

    def get_replay_report(self) -> Dict[str, Any]:
        """重放分歧报告"""
        return {
            "total_checks": self._stats["total_replay_checks"],
            "divergences": self._stats["replay_divergences"],
            "divergence_rate": round(
                self._stats["replay_divergences"] / max(1, self._stats["total_replay_checks"]), 4
            ),
            "cache_entries": len(self._replay_cache),
        }

    def get_reliability_score(self) -> Dict[str, Any]:
        """综合可靠性评分 (0-100)

        计算公式: commit_rate * 0.5 + (1-replay_divergence_rate) * 0.3 + architectural_momentum * 0.2
        """
        stats = self.get_stats()
        var_report = self.get_variance_report()

        commit_rate = stats["commit_rate"]
        replay_factor = 1.0 - stats["replay_divergence_rate"]
        arch_momentum = var_report.get("architectural_momentum", 0.5)

        score = (commit_rate * 50.0 + replay_factor * 30.0 + arch_momentum * 20.0)

        return {
            "reliability_score": round(score, 2),
            "grade": self._score_grade(score),
            "components": {
                "commit_rate_contribution": round(commit_rate * 50.0, 2),
                "replay_contribution": round(replay_factor * 30.0, 2),
                "architectural_contribution": round(arch_momentum * 20.0, 2),
            },
            "recommendation": self._recommend(score),
        }

    def _score_grade(self, score: float) -> str:
        if score >= 90:
            return "S (生产级)"
        elif score >= 75:
            return "A (高可靠)"
        elif score >= 60:
            return "B (中等)"
        elif score >= 40:
            return "C (需改进)"
        else:
            return "D (不可靠)"

    def _recommend(self, score: float) -> str:
        if score >= 90:
            return "系统已达到生产级可靠性，SDB边界强健。"
        elif score >= 75:
            return "可靠性良好。建议: 加强重放检测,减少模型方差。"
        elif score >= 60:
            return "中等可靠性。建议: 增加验证规则,降低方差阈值。"
        elif score >= 40:
            return "可靠性不足。建议: 启用冻结模式,增加确定性检查。"
        else:
            return "⚠️ 可靠性严重不足。建议: 完全冻结自动提交,仅允许人工审批。"

    # ── History ──────────────────────────────────────────────

    def get_recent_records(self, limit: int = 50) -> List[Dict]:
        """获取最近的SDB记录"""
        return [r.to_dict() for r in self._records[-limit:]]

    def get_rejects(self, limit: int = 20) -> List[Dict]:
        """获取最近的拒绝记录"""
        rejects = [r for r in self._records if r.phase == SDBPhase.REJECT]
        return [r.to_dict() for r in rejects[-limit:]]

    def clear(self):
        """清除所有记录 (保留统计)"""
        self._records.clear()
        self._replay_cache.clear()


# 单例
_engine: Optional[SDBEngine] = None


def get_sdb_engine() -> SDBEngine:
    global _engine
    if _engine is None:
        _engine = SDBEngine()
    return _engine
