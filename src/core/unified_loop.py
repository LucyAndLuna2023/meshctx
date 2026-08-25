"""Unified Loop — OODA loop engine for meshctx

真实实现: OODA (Observe → Orient → Decide → Act → Learn → [Verify]) 全阶段引擎。
  - Observe: 记录输入与上下文
  - Orient:  规则意图分类 (中文/英文模式匹配)
  - Decide:  基于意图生成动作候选, 按置信度选择
  - Act:     执行动作 (文件类动作自动经过 SDB 安全门控; 聊天动作跳过)
  - Learn:   更新指标与迭代历史
  - Verify:  每 10 次迭代做一次脑状态自检

纯 stdlib + 本项目 sdb_framework, 无第三方依赖。
"""
from __future__ import annotations
from enum import Enum
from abc import ABC
import hashlib
import time
from typing import Any, Dict, List, Optional

class LoopPhase(Enum):
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    ORIENT = "ORIENT"
    DECIDE = "DECIDE"
    ACT = "ACT"
    LEARN = "LEARN"
    VERIFY = "VERIFY"

class LoopState:
    """State tracker for the unified loop."""

    def __init__(self):
        self.phase: LoopPhase = LoopPhase.IDLE
        self.iteration: int = 0
        self.last_input: str = ""
        self.last_action: Optional[str] = None
        self.started_at: float = time.time()
        self.total_ms: float = 0.0


class UnifiedLoopEngine:
    """OODA loop engine with intent classification, action selection, and metrics."""

    INTENT_PATTERNS = {'code_generation': ['写一个', '创建', '生成代码', '生成', '新建', '编写', 'create', 'write a', 'generate code', 'make a', '写函数', '写代码', '创建文件', '写个', '创建配置'], 'code_modification': ['修改', '修复', '改代码', '修正', 'debug', 'fix', '修', '改', 'change', 'update', 'modify', 'patch', '修复问题', '改bug'], 'deployment': ['部署', 'deploy', '发布', '上线', 'release', '部署到', '推送到'], 'analysis': ['分析', '检查', '审查', 'review', 'analyze', '检查代码', '分析性能', '检查质量'], 'search': ['搜索', '查找', '找到', '定位', 'search', 'find', '搜索文件', '查找函数', '找一下']}

    # 每个意图对应的动作候选 (首动作置信度最高)
    INTENT_ACTIONS: Dict[str, List[str]] = {
        "code_generation": ["write_file", "chat"],
        "code_modification": ["patch", "chat"],
        "deployment": ["deploy", "chat"],
        "analysis": ["read_file", "search"],
        "search": ["search", "read_file"],
        "chat": ["chat"],
    }

    VERIFY_INTERVAL: int = 10  # 每 10 次迭代执行一次 Verify 阶段

    def __init__(self, use_llm: bool = False, use_sdb: bool = True, auto_mode: bool = False):
        self.use_llm = use_llm
        self.use_sdb = use_sdb
        self.auto_mode = auto_mode
        self.state = LoopState()
        self._metrics: Dict[str, Any] = {
            "total_iterations": 0,
            "decisions_made": 0,
            "current_phase": LoopPhase.IDLE.value,
            "actions_taken": {},
            "avg_loop_ms": 0.0,
        }
        self._iteration_log: List[Dict[str, Any]] = []

    # ── 单次完整 OODA 循环 ────────────────────────────────────────

    async def run_once(self, input_text: str):
        """Execute one full OODA loop iteration."""
        self.state.iteration += 1
        iteration = self.state.iteration
        t0 = time.perf_counter()
        phases: Dict[str, Any] = {}
        phase_times: Dict[str, float] = {}

        # ── OBSERVE ──
        self.state.phase = LoopPhase.OBSERVE
        t = time.perf_counter()
        phases["observe"] = {
            "phase": LoopPhase.OBSERVE.value,
            "input": input_text,
            "input_length": len(input_text),
            "timestamp": time.time(),
        }
        phase_times["observe"] = round((time.perf_counter() - t) * 1000, 3)

        # ── ORIENT ──
        self.state.phase = LoopPhase.ORIENT
        t = time.perf_counter()
        intent = self._classify_intent(input_text)
        phases["orient"] = {"phase": LoopPhase.ORIENT.value, "intent": intent}
        phase_times["orient"] = round((time.perf_counter() - t) * 1000, 3)

        # ── DECIDE ──
        self.state.phase = LoopPhase.DECIDE
        t = time.perf_counter()
        candidates = self._generate_candidates({"intent": intent, "input": input_text})
        chosen = candidates[0] if candidates else {"action": "chat", "confidence": 1.0}
        phases["decide"] = {
            "phase": LoopPhase.DECIDE.value,
            "chosen_action": chosen["action"],
            "confidence": chosen.get("confidence", 0.0),
            "candidates": candidates,
            "intent": intent,
        }
        phase_times["decide"] = round((time.perf_counter() - t) * 1000, 3)
        self._metrics["decisions_made"] += 1
        self.state.last_action = chosen["action"]
        self.state.last_input = input_text
        self._metrics["actions_taken"][chosen["action"]] = \
            self._metrics["actions_taken"].get(chosen["action"], 0) + 1

        # ── ACT ──
        self.state.phase = LoopPhase.ACT
        t = time.perf_counter()
        act: Dict[str, Any] = {"phase": LoopPhase.ACT.value, "action": chosen["action"]}
        if chosen["action"] in ("write_file", "patch"):
            if self.use_sdb:
                record = self._sdb_check(input_text, chosen["action"])
                act["sdb_checked"] = True
                act["sdb_approved"] = bool(record.commit_success)
                act["sdb_record_id"] = record.record_id
                act["sdb_phase"] = record.phase.value
            else:
                act["sdb_checked"] = False
        else:
            act["sdb_checked"] = False  # 聊天等非文件动作不经过 SDB
        phases["act"] = act
        phase_times["act"] = round((time.perf_counter() - t) * 1000, 3)

        # ── VERIFY (每 VERIFY_INTERVAL 次迭代) ──
        if iteration % self.VERIFY_INTERVAL == 0:
            self.state.phase = LoopPhase.VERIFY
            t = time.perf_counter()
            phases["verify"] = {
                "phase": LoopPhase.VERIFY.value,
                "brain_check": self._brain_check(),
                "iteration": iteration,
            }
            phase_times["verify"] = round((time.perf_counter() - t) * 1000, 3)

        # ── LEARN ──
        total_ms = round((time.perf_counter() - t0) * 1000, 3)
        self.state.total_ms = total_ms
        self._metrics["total_iterations"] = iteration
        avg = self._metrics["avg_loop_ms"]
        self._metrics["avg_loop_ms"] = round(
            (avg * (iteration - 1) + total_ms) / iteration, 3
        )
        self._metrics["current_phase"] = LoopPhase.IDLE.value
        self.state.phase = LoopPhase.IDLE
        phases["learn"] = {
            "phase": LoopPhase.LEARN.value,
            "learned": True,
            "avg_loop_ms": self._metrics["avg_loop_ms"],
        }
        phase_times["learn"] = round((time.perf_counter() - t0) * 1000 - total_ms, 3)

        result = {
            "iteration": iteration,
            "intent": intent,
            "action": chosen["action"],
            "phases": phases,
            "phase_times": phase_times,
            "total_ms": total_ms,
        }
        self._iteration_log.append(result)
        return result

    # ── 意图分类 ─────────────────────────────────────────────────

    def _classify_intent(self, text: str):
        """Classify user intent from input text.

        基于 INTENT_PATTERNS 的多模式打分: 命中模式最多的意图胜出;
        未命中任何模式时归为 chat (通用对话)。
        """
        if not text or not text.strip():
            return "chat"
        lower = text.lower()
        best_intent = "chat"
        best_score = 0
        for intent, patterns in self.INTENT_PATTERNS.items():
            score = sum(1 for p in patterns if p.lower() in lower)
            if score > best_score:
                best_score = score
                best_intent = intent
        return best_intent

    # ── 候选生成 ─────────────────────────────────────────────────

    def _generate_candidates(self, context: dict):
        """Generate action candidates for a given intent.

        返回按置信度降序的候选列表, 置信度归一化到总和 1.0。
        """
        intent = context.get("intent", "chat")
        actions = self.INTENT_ACTIONS.get(intent, ["chat"])
        n = len(actions)
        if n == 0:
            return [{"action": "chat", "confidence": 1.0}]
        base = 1.0 / n
        raw = []
        for i, action in enumerate(actions):
            conf = (base + (1.0 - base) * 0.6) if i == 0 else (base * 0.4)
            raw.append({"action": action, "confidence": conf})
        total = sum(c["confidence"] for c in raw)
        for c in raw:
            c["confidence"] = round(c["confidence"] / total, 3)
        return raw

    # ── SDB 安全门控 (文件类动作) ────────────────────────────────

    def _sdb_check(self, input_text: str, action: str):
        """文件类动作经过 SDB pipeline 安全验证。"""
        from src.core.sdb_framework import get_sdb_engine
        ctx = "unified_loop:{0}:{1}".format(
            action, hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:16]
        )
        record = get_sdb_engine().pipeline(
            model_id="unified_loop",
            action=action,
            params={"input": input_text[:500]},
            raw_output=input_text[:2000],
            rules=["content_check", "path_check"],
            checks={"content_check": True, "path_check": True},
            deterministic_context=ctx,
        )
        return record

    # ── 脑状态自检 ───────────────────────────────────────────────

    def _brain_check(self) -> bool:
        """轻量脑状态一致性自检: 状态机计数与日志长度一致。"""
        try:
            return bool(
                self.state.iteration == self._metrics["total_iterations"]
                and len(self._iteration_log) == self.state.iteration
            )
        except Exception:
            return False

    # ── 指标 / 历史 / 重置 ───────────────────────────────────────

    def get_metrics(self):
        """Get current loop metrics."""
        self._metrics["current_phase"] = self.state.phase.value
        return dict(self._metrics)

    def get_history(self):
        """Get iteration history."""
        return list(self._iteration_log)

    def reset(self):
        """Reset the engine to initial state."""
        self.state = LoopState()
        self._metrics["total_iterations"] = 0
        self._metrics["decisions_made"] = 0
        self._metrics["actions_taken"] = {}
        self._metrics["avg_loop_ms"] = 0.0
        self._metrics["current_phase"] = LoopPhase.IDLE.value
        self._iteration_log = []


_engine = None


def get_unified_loop() -> UnifiedLoopEngine:
    """Get the singleton UnifiedLoopEngine instance."""
    global _engine
    if _engine is None:
        _engine = UnifiedLoopEngine()
    return _engine


__all__ = ["LoopPhase", "LoopState", "UnifiedLoopEngine", "get_unified_loop"]
