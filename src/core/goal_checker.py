"""meshctx goal_checker — P0-5 Goal self-check engine"""
from __future__ import annotations
import time, re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_COMPLETED = [
    "完成", "成功", "已部署", "已上线", "已通过", "已修复", "已完成", "全部通过",
    "done", "completed", "success", "pass", "finished", "resolved", "merged", "deployed",
]
_FAILURE = [
    "失败", "错误", "崩溃", "异常", "无法", "未通过",
    "failed", "error", "crash", "exception", "cannot", "broken", "bug", "缺陷",
]
_IN_PROGRESS = [
    "进行中", "处理中", "待完成", "尚未", "还需", "继续",
    "in progress", "pending", "todo", "wip", "步骤", "step", "阶段",
]

@dataclass
class GoalCheckResult:
    goal: str = ""; score: float = 0.0
    unfinished: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    llm_analysis: str = ""; source: str = "keyword"; checked_at: float = 0.0
    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


class GoalChecker:
    """Goal validator: keyword-based progress tracking + completion detection."""
    _max_history = 50

    def __init__(self):
        self._goal = ""; self._history: List[dict] = []
        self._last: Optional[dict] = None; self._checks = 0
        self._score_sum = 0.0; self._max_score = 0.0

    def set_goal(self, text: str) -> None: self._goal = text.strip()
    def get_goal(self) -> str: return self._goal

    def reset(self) -> None:
        self._goal = ""; self._history.clear(); self._last = None
        self._checks = 0; self._score_sum = 0.0; self._max_score = 0.0

    def _keyword_check(self, text: str) -> dict:
        """Return dict with score, matched, unfinished, suggestions."""
        t = text.lower()
        c_hits = [kw for kw in _COMPLETED if kw in text or kw.lower() in t]
        f_hits = [kw for kw in _FAILURE if kw in text or kw.lower() in t]
        p_hits = [kw for kw in _IN_PROGRESS if kw in text or kw.lower() in t]
        score = 50.0 + len(c_hits) * 10 - len(f_hits) * 15 - len(p_hits) * 10
        score = max(0.0, min(100.0, score))
        suggestions = []
        if score <= 30: suggestions.append("任务可能遇到严重问题，建议检查错误日志")
        elif score <= 50: suggestions.append("建议补充任务状态更新，确认当前进度")
        elif score < 80: suggestions.append("任务进展良好，可继续推进剩余项")
        return {"score": score, "matched": c_hits + f_hits + p_hits,
                "unfinished": p_hits, "suggestions": suggestions}

    def check_completion(self) -> dict:
        """Validate goal, detect completion, track progress."""
        now = time.time()
        if not self._goal:
            result = {"goal": "", "score": 0, "unfinished": ["未设置目标"],
                      "suggestions": ["请先调用 set_goal() 设置任务目标"],
                      "llm_analysis": "", "source": "keyword", "checked_at": now}
            self._record(result); return result
        kw = self._keyword_check(self._goal)
        for part in re.split(r'[,，;；\s]+', self._goal):
            if re.search(r'(步骤|step)\s*\d+', part, re.I):
                if not any(k in part for k in _COMPLETED): kw["unfinished"].append(part.strip())
            elif any(k in part for k in _IN_PROGRESS): kw["unfinished"].append(part.strip())
        kw["unfinished"] = list(dict.fromkeys(kw["unfinished"]))
        result = {"goal": self._goal, "score": kw["score"],
                  "unfinished": kw["unfinished"], "suggestions": kw["suggestions"],
                  "llm_analysis": "", "source": "keyword" if not kw["unfinished"] else "mixed",
                  "checked_at": now}
        self._record(result); return result

    def _record(self, result: dict) -> None:
        self._checks += 1; s = result["score"]; self._score_sum += s
        if s > self._max_score: self._max_score = s
        self._history.append(dict(result))
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        self._last = dict(result)

    def get_history(self, limit: Optional[int] = None) -> List[dict]:
        return list(self._history[-limit:] if limit else self._history)

    def get_last_result(self) -> Optional[dict]: return self._last

    def get_stats(self) -> dict:
        return {"total_checks": self._checks,
                "avg_score": round(self._score_sum / max(1, self._checks), 1),
                "max_score": self._max_score, "current_goal": self._goal}

    # ── LLM output parsing ─────────────────────────────────────────
    @staticmethod
    def _parse_llm_score(text: str) -> int:
        for pat in [r'评分[：:]\s*(\d+)', r'(?:Score|score)[：:]\s*(\d+)',
                     r'(\d+)\s*/\s*100', r'达成度[：:]\s*(\d+)']:
            m = re.search(pat, text)
            if m: return int(m.group(1))
        return -1

    @staticmethod
    def _parse_list(text: str, start_kw: str, stop_kws: list) -> list:
        items, in_sec = [], False
        for line in text.splitlines():
            s = line.strip()
            if start_kw in s: in_sec = True; continue
            if in_sec and any(k in s for k in stop_kws): break
            if in_sec and s.startswith(('-', '*', '•', '·')):
                items.append(s.lstrip('-*•· '))
        return items

    @staticmethod
    def _parse_llm_unfinished(text: str) -> List[str]:
        return GoalChecker._parse_list(text, '未完成', ['建议', '补救', 'suggest'])

    @staticmethod
    def _parse_llm_suggestions(text: str) -> List[str]:
        return GoalChecker._parse_list(text, '补救', ['建议', 'suggest', '总结', 'summary'])


# ── Singleton ─────────────────────────────────────────────────────────
_gc: Optional[GoalChecker] = None

def get_goal_checker() -> GoalChecker:
    global _gc
    if _gc is None: _gc = GoalChecker()
    return _gc

def reset_goal_checker() -> None:
    global _gc; _gc = None

_orig_new = GoalChecker.__new__
def _singleton_new(cls):
    global _gc
    if _gc is None: _gc = _orig_new(cls)
    return _gc
GoalChecker.__new__ = staticmethod(_singleton_new)
