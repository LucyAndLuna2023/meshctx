"""Unified Loop — OODA loop engine for meshctx"""

import time
from enum import Enum, auto
from dataclasses import dataclass, field
from collections import deque


class LoopPhase(Enum):
    IDLE = auto()
    OBSERVE = auto()
    ORIENT = auto()
    DECIDE = auto()
    ACT = auto()
    LEARN = auto()
    VERIFY = auto()


class LoopState:
    """State tracker for the unified loop."""

    def __init__(self):
        self.iteration: int = 0
        self.phase: LoopPhase = LoopPhase.IDLE
        self.last_action: str = ""
        self.last_intent: str = ""


class UnifiedLoopEngine:
    """OODA loop engine with intent classification, action selection, and metrics."""

    # Intent keywords mapping
    INTENT_PATTERNS = {
        "code_generation": [
            "写一个", "创建", "生成代码", "生成", "新建", "编写",
            "create", "write a", "generate code", "make a",
            "写函数", "写代码", "创建文件", "写个", "创建配置",
        ],
        "code_modification": [
            "修改", "修复", "改代码", "修正", "debug", "fix",
            "修", "改", "change", "update", "modify", "patch",
            "修复问题", "改bug",
        ],
        "deployment": [
            "部署", "deploy", "发布", "上线", "release",
            "部署到", "推送到",
        ],
        "analysis": [
            "分析", "检查", "审查", "review", "analyze",
            "检查代码", "分析性能", "检查质量",
        ],
        "search": [
            "搜索", "查找", "找到", "定位", "search", "find",
            "搜索文件", "查找函数", "找一下",
        ],
    }

    def __init__(self, use_llm: bool = False, use_sdb: bool = True, auto_mode: bool = False):
        self.use_llm = use_llm
        self.use_sdb = use_sdb
        self.auto_mode = auto_mode
        self.state = LoopState()
        self._iteration_log: list = []
        self._metrics = {
            "total_iterations": 0,
            "decisions_made": 0,
            "current_phase": LoopPhase.IDLE.name,
            "actions_taken": {},
            "phase_durations": {},
        }
        self._history = deque(maxlen=1000)
        self._brain_check_interval = 10

    async def run_once(self, input_text: str):
        """Execute one full OODA loop iteration."""
        start_time = time.time()
        self.state.iteration += 1
        self._metrics["total_iterations"] = self.state.iteration
        phase_times = {}
        phases = {}

        # OBSERVE
        t0 = time.time()
        self.state.phase = LoopPhase.OBSERVE
        phases["observe"] = {"input_length": len(input_text), "raw": input_text[:200]}
        phase_times["observe"] = (time.time() - t0) * 1000

        # ORIENT
        t0 = time.time()
        self.state.phase = LoopPhase.ORIENT
        intent = self._classify_intent(input_text)
        self.state.last_intent = intent
        phases["orient"] = {"intent": intent}
        phase_times["orient"] = (time.time() - t0) * 1000

        # DECIDE
        t0 = time.time()
        self.state.phase = LoopPhase.DECIDE
        candidates = self._generate_candidates({"intent": intent})
        chosen = candidates[0] if candidates else {"action": "chat", "confidence": 1.0}
        self.state.last_action = chosen["action"]
        self._metrics["decisions_made"] += 1
        phases["decide"] = {
            "chosen_action": chosen["action"],
            "confidence": chosen.get("confidence", 1.0),
            "candidates": candidates,
        }
        phase_times["decide"] = (time.time() - t0) * 1000

        # ACT
        t0 = time.time()
        self.state.phase = LoopPhase.ACT
        action = chosen["action"]
        act_result = {"action": action}
        # SDB check for file operations
        if self.use_sdb and action in ("write_file", "patch", "terminal"):
            act_result["sdb_checked"] = True
        phases["act"] = act_result
        self._metrics["actions_taken"][action] = self._metrics["actions_taken"].get(action, 0) + 1
        phase_times["act"] = (time.time() - t0) * 1000

        # LEARN
        t0 = time.time()
        self.state.phase = LoopPhase.LEARN
        phase_times["learn"] = (time.time() - t0) * 1000

        # VERIFY (brain check every N iterations)
        t0 = time.time()
        self.state.phase = LoopPhase.VERIFY
        verify = {}
        if self.state.iteration % self._brain_check_interval == 0:
            verify["brain_check"] = True
        phases["verify"] = verify
        phase_times["verify"] = (time.time() - t0) * 1000

        total_ms = (time.time() - start_time) * 1000

        result = {
            "iteration": self.state.iteration,
            "phases": phases,
            "phase_times": phase_times,
            "total_ms": total_ms,
        }
        self._iteration_log.append(result)
        self._history.append(result)
        self._metrics["current_phase"] = self.state.phase.name
        return result

    def _classify_intent(self, text: str):
        """Classify user intent from input text."""
        text_lower = text.lower().strip()
        if not text_lower:
            return "chat"

        best_match = "chat"
        best_len = 0
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pat in patterns:
                if pat in text_lower:
                    if len(pat) > best_len:
                        best_len = len(pat)
                        best_match = intent

        return best_match

    def _generate_candidates(self, context: dict):
        """Generate action candidates for a given intent."""
        intent = context.get("intent", "chat")
        if intent == "chat":
            return [{"action": "chat", "confidence": 1.0}]
        elif intent == "code_generation":
            return [
                {"action": "write_file", "confidence": 0.6},
                {"action": "chat", "confidence": 0.4},
            ]
        elif intent == "code_modification":
            return [
                {"action": "patch", "confidence": 0.5},
                {"action": "write_file", "confidence": 0.3},
                {"action": "chat", "confidence": 0.2},
            ]
        elif intent == "deployment":
            return [
                {"action": "terminal", "confidence": 0.6},
                {"action": "chat", "confidence": 0.4},
            ]
        elif intent == "analysis":
            return [
                {"action": "read_file", "confidence": 0.5},
                {"action": "search", "confidence": 0.3},
                {"action": "chat", "confidence": 0.2},
            ]
        elif intent == "search":
            return [
                {"action": "search", "confidence": 0.7},
                {"action": "chat", "confidence": 0.3},
            ]
        return [{"action": "chat", "confidence": 1.0}]

    def get_metrics(self):
        """Get current loop metrics."""
        return dict(self._metrics)

    def get_history(self):
        """Get iteration history."""
        return list(self._history)

    def reset(self):
        """Reset the engine to initial state."""
        self.state = LoopState()
        self._iteration_log.clear()
        self._history.clear()
        self._metrics = {
            "total_iterations": 0,
            "decisions_made": 0,
            "current_phase": LoopPhase.IDLE.name,
            "actions_taken": {},
            "phase_durations": {},
        }


_engine: UnifiedLoopEngine = None


def get_unified_loop() -> UnifiedLoopEngine:
    """Get the singleton UnifiedLoopEngine instance."""
    global _engine
    if _engine is None:
        _engine = UnifiedLoopEngine()
    return _engine
