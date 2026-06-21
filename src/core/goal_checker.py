"""meshctx goal_checker"""
from dataclasses import dataclass

@dataclass
class GoalCheckResult:
    goal: str = ""
    met: bool = False
    reason: str = ""
    progress: float = 0.0

_gc = None
def get_goal_checker():
    global _gc
    if _gc is None:
        _gc = type("GoalChecker", (), {"check": lambda self, g: GoalCheckResult(goal=str(g), met=True)})()
    return _gc

def reset_goal_checker():
    global _gc
    _gc = None
