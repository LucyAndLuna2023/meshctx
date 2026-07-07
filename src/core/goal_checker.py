"""meshctx goal_checker — P0-5 Goal自检机制"""

from __future__ import annotations
import time
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════
# Keyword dictionaries
# ═══════════════════════════════════════════════════════════════════

_COMPLETED_KW = [
    "完成", "成功", "已部署", "已上线", "已通过", "已修复",
    "已完成", "全部通过", "done", "completed", "success",
    "pass", "finished", "resolved", "merged", "deployed",
]

_FAILURE_KW = [
    "失败", "错误", "崩溃", "异常", "无法", "未通过",
    "failed", "error", "crash", "exception", "cannot",
    "broken", "bug", "缺陷",
]

_IN_PROGRESS_KW = [
    "进行中", "处理中", "待完成", "尚未", "还需", "继续",
    "in progress", "pending", "todo", "wip",
    "步骤", "step", "阶段",
]


# ═══════════════════════════════════════════════════════════════════
# Data class
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GoalCheckResult:
    goal: str = ""
    score: float = 0.0
    unfinished: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    llm_analysis: str = ""
    source: str = "keyword"
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "score": self.score,
            "unfinished": list(self.unfinished),
            "suggestions": list(self.suggestions),
            "llm_analysis": self.llm_analysis,
            "source": self.source,
            "checked_at": self.checked_at,
        }


# ═══════════════════════════════════════════════════════════════════
# GoalChecker
# ═══════════════════════════════════════════════════════════════════

class GoalChecker:
    """Goal self-check engine with keyword matching and history."""

    _max_history: int = 50

    def __init__(self):
        self._goal: str = ""
        self._history: List[dict] = []
        self._last_result: Optional[dict] = None
        self._total_checks: int = 0
        self._score_sum: float = 0.0
        self._max_score: float = 0.0

    def set_goal(self, text: str) -> None:
        self._goal = text.strip()

    def get_goal(self) -> str:
        return self._goal

    def reset(self) -> None:
        self._goal = ""
        self._history.clear()
        self._last_result = None
        self._total_checks = 0
        self._score_sum = 0.0
        self._max_score = 0.0

    # ── keyword matching ───────────────────────────────────────

    def _keyword_check(self, text: str) -> dict:
        """Fast keyword-based completion analysis."""
        matched: List[str] = []
        unfinished: List[str] = []
        suggestions: List[str] = []

        text_lower = text.lower()

        # Check completed keywords → boost score
        for kw in _COMPLETED_KW:
            if kw in text or kw.lower() in text_lower:
                matched.append(kw)

        # Check failure keywords → reduce score
        fail_matched = []
        for kw in _FAILURE_KW:
            if kw in text or kw.lower() in text_lower:
                fail_matched.append(kw)
                matched.append(kw)

        # Check in-progress keywords → detect unfinished
        for kw in _IN_PROGRESS_KW:
            if kw in text or kw.lower() in text_lower:
                unfinished.append(kw)
                matched.append(kw)

        # Score: base 50, +10 per completed, -10 per failure, -10 per in-progress
        score = 50.0
        score += len([m for m in matched if m in _COMPLETED_KW or m.lower() in [k.lower() for k in _COMPLETED_KW]]) * 10
        score -= len(fail_matched) * 15
        score -= len(unfinished) * 10

        score = max(0.0, min(100.0, score))

        # Build suggestions
        if score <= 30:
            suggestions.append("任务可能遇到严重问题，建议检查错误日志")
        elif score <= 50:
            suggestions.append("建议补充任务状态更新，确认当前进度")
        elif score < 80:
            suggestions.append("任务进展良好，可继续推进剩余项")

        return {
            "score": score,
            "matched": matched,
            "unfinished": unfinished,
            "suggestions": suggestions,
        }

    def check_completion(self) -> dict:
        """Run full completion check on current goal."""
        import time
        now = time.time()

        if not self._goal:
            result = {
                "goal": "",
                "score": 0,
                "unfinished": ["未设置目标"],
                "suggestions": ["请先调用 set_goal() 设置任务目标"],
                "llm_analysis": "",
                "source": "keyword",
                "checked_at": now,
            }
            self._record(result)
            return result

        kw = self._keyword_check(self._goal)

        # Detect step markers in goal text
        step_unfinished = []
        for part in re.split(r'[,，;；\s]+', self._goal):
            if re.match(r'.*(步骤|step)\s*\d+.*', part, re.IGNORECASE):
                if any(k in part for k in _COMPLETED_KW) and not part.endswith("完成"):
                    step_unfinished.append(part.strip())
            elif any(k in part for k in _IN_PROGRESS_KW):
                step_unfinished.append(part.strip())

        all_unfinished = list(set(kw["unfinished"] + step_unfinished))

        result = {
            "goal": self._goal,
            "score": kw["score"],
            "unfinished": all_unfinished,
            "suggestions": kw["suggestions"],
            "llm_analysis": "",
            "source": "keyword" if not all_unfinished else "mixed",
            "checked_at": now,
        }
        self._record(result)
        return result

    def _record(self, result: dict) -> None:
        self._total_checks += 1
        self._score_sum += result["score"]
        if result["score"] > self._max_score:
            self._max_score = result["score"]
        self._history.append(dict(result))
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        self._last_result = dict(result)

    def get_history(self, limit: Optional[int] = None) -> List[dict]:
        if limit is None:
            return list(self._history)
        return list(self._history[-limit:])

    def get_last_result(self) -> Optional[dict]:
        return self._last_result

    def get_stats(self) -> dict:
        return {
            "total_checks": self._total_checks,
            "avg_score": round(self._score_sum / max(1, self._total_checks), 1),
            "max_score": self._max_score,
            "current_goal": self._goal,
        }

    # ── LLM output parsing ─────────────────────────────────────

    @staticmethod
    def _parse_llm_score(text: str) -> int:
        """Parse a numeric score from LLM output."""
        patterns = [
            r'评分[：:]\s*(\d+)',
            r'(?:Score|score)[：:]\s*(\d+)',
            r'(\d+)\s*/\s*100',
            r'达成度[：:]\s*(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return int(m.group(1))
        return -1

    @staticmethod
    def _parse_llm_unfinished(text: str) -> List[str]:
        """Parse unfinished items from LLM output."""
        items: List[str] = []
        in_section = False
        for line in text.splitlines():
            stripped = line.strip()
            if '未完成' in stripped or 'unfinished' in stripped.lower():
                in_section = True
                continue
            if in_section and ('建议' in stripped or '补救' in stripped
                               or 'suggest' in stripped.lower()):
                break
            if in_section and stripped.startswith(('-', '*', '•', '·')):
                items.append(stripped.lstrip('-*•· '))
        return items

    @staticmethod
    def _parse_llm_suggestions(text: str) -> List[str]:
        """Parse remedy suggestions from LLM output."""
        items: List[str] = []
        in_section = False
        for line in text.splitlines():
            stripped = line.strip()
            if '补救' in stripped or '建议' in stripped or 'suggest' in stripped.lower():
                in_section = True
                continue
            if in_section and stripped.startswith(('-', '*', '•', '·')):
                items.append(stripped.lstrip('-*•· '))
        return items


# ═══════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════

_gc: Optional[GoalChecker] = None


def get_goal_checker() -> GoalChecker:
    global _gc
    if _gc is None:
        _gc = GoalChecker()
    return _gc


def reset_goal_checker() -> None:
    global _gc
    _gc = None


# Compatibility: GoalChecker() also returns the singleton
_original_new = GoalChecker.__new__


def _singleton_new(cls):
    global _gc
    if _gc is None:
        _gc = _original_new(cls)
    return _gc


GoalChecker.__new__ = staticmethod(_singleton_new)
