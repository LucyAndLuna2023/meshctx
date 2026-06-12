"""
meshctx Goal — Goal 设定与追踪
对标: OpenClaw goal tool
"""
import json, time, os
from pathlib import Path
from typing import Optional

GOAL_DIR = Path(os.environ.get("MESHCTX_STATE_DIR", Path.home() / ".meshctx")) / "goals"
GOAL_DIR.mkdir(parents=True, exist_ok=True)

def goal_set(goal_id: str, description: str, milestones: list[str] = None,
             deadline: str = None, priority: str = "medium") -> dict:
    """设定目标
    
    Args:
        goal_id: 目标ID
        description: 描述
        milestones: 里程碑列表
        deadline: 截止日期 (ISO format)
        priority: low | medium | high | critical
    """
    goal = {
        "id": goal_id, "description": description,
        "milestones": [{"text": m, "done": False} for m in (milestones or [])],
        "deadline": deadline, "priority": priority,
        "created_at": time.time(), "updated_at": time.time(),
        "status": "active", "progress_pct": 0
    }
    _save_goal(goal_id, goal)
    return {"ok": True, "goal": goal}

def goal_update(goal_id: str, status: str = None, 
                milestone_index: int = None, milestone_done: bool = None,
                notes: str = None) -> dict:
    """更新目标状态"""
    goal = _load_goal(goal_id)
    if not goal:
        return {"ok": False, "error": f"Goal {goal_id} not found"}
    
    if status:
        goal["status"] = status
    if milestone_index is not None and milestone_index < len(goal["milestones"]):
        goal["milestones"][milestone_index]["done"] = milestone_done
        done = sum(1 for m in goal["milestones"] if m["done"])
        total = len(goal["milestones"])
        goal["progress_pct"] = int(done / total * 100) if total > 0 else 0
    if notes:
        goal.setdefault("notes", []).append({"text": notes, "time": time.time()})
    
    goal["updated_at"] = time.time()
    _save_goal(goal_id, goal)
    return {"ok": True, "goal": goal}

def goal_get(goal_id: str) -> dict:
    """获取目标"""
    goal = _load_goal(goal_id)
    return {"ok": True, "goal": goal} if goal else {"ok": False, "error": f"Goal {goal_id} not found"}

def goal_list(status: str = None) -> dict:
    """列出所有目标"""
    goals = []
    for f in sorted(GOAL_DIR.glob("*.json")):
        g = json.loads(f.read_text())
        if status and g.get("status") != status:
            continue
        goals.append(g)
    goals.sort(key=lambda g: {"critical":0,"high":1,"medium":2,"low":3}.get(g.get("priority"), 5))
    return {"ok": True, "count": len(goals), "goals": goals}

def goal_delete(goal_id: str) -> dict:
    """删除目标"""
    p = GOAL_DIR / f"{goal_id}.json"
    if p.exists():
        p.unlink()
        return {"ok": True, "deleted": goal_id}
    return {"ok": False, "error": f"Goal {goal_id} not found"}

def _save_goal(goal_id, goal):
    (GOAL_DIR / f"{goal_id}.json").write_text(json.dumps(goal, indent=2, ensure_ascii=False))

def _load_goal(goal_id) -> Optional[dict]:
    p = GOAL_DIR / f"{goal_id}.json"
    return json.loads(p.read_text()) if p.exists() else None
