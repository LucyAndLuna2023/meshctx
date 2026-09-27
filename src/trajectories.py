# -*- coding: utf-8 -*-
"""SMA Phase 3 骨架 — 过程记忆: 成功任务轨迹落盘 + 检索注入.

理念: 弱模型最强的外挂不是更多参数, 而是"强模型历史解法"的模仿——
把成功任务的 (任务→工具序列→输出→反馈) 轨迹存档, 新任务检索 top-k
相似轨迹注入 prompt, 弱模型照着成功路径走。

存储: ~/.meshctx/trajectories/*.json (与 persistent_memory 同根, 本地零依赖)
注入: 与 _collect_memory_entries 同源口径 — build_system_prompt 可引用
守门: tests/test_trajectories.py
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_TRAJ_DIR = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx")) / "trajectories"


def _dir() -> Path:
    _TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    return _TRAJ_DIR


def save_trajectory(task: str, steps: List[Dict[str, Any]], output: str,
                    outcome: str = "success", tags: Optional[List[str]] = None) -> str:
    """落盘一条任务轨迹。outcome: success|fail (失败轨迹带避坑标记, 默认不注入)."""
    tid = f"traj_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    rec = {"id": tid, "task": task[:500], "steps": steps[:50],
           "output": output[:4000], "outcome": outcome,
           "tags": tags or [], "created_at": time.time()}
    fp = _dir() / f"{tid}.json"
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(fp)
    return tid


def load_trajectories(outcome: str = "success") -> List[Dict[str, Any]]:
    out = []
    for fp in _dir().glob("*.json"):
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
            if rec.get("outcome") == outcome:
                out.append(rec)
        except Exception:
            continue
    return out


def search_similar(query: str, top_k: int = 3,
                   min_tokens: int = 2) -> List[Dict[str, Any]]:
    """关键词重叠检索 top-k 相似成功轨迹 (与 chat_tools 检索同风格, 零依赖)."""
    import re as _re
    qwords = set(w.lower() for w in _re.findall(r"\w+", query) if len(w) > 1)
    scored = []
    for rec in load_trajectories("success"):
        twords = set(w.lower() for w in _re.findall(r"\w+",
                     (rec.get("task", "") + " " + " ".join(rec.get("tags", [])))))
        overlap = len(qwords & twords)
        if overlap:
            scored.append((overlap, rec))
    scored.sort(key=lambda x: (-x[0], -x[1].get("created_at", 0)))
    return [r for _, r in scored[:top_k]]


def build_injection(query: str, top_k: int = 2) -> str:
    """构造可注入 system prompt 的轨迹段 (空返回空串 — 零注入零行为变化)."""
    hits = search_similar(query, top_k=top_k)
    if not hits:
        return ""
    parts = ["\n## 过程参考 (相似任务的成功解法轨迹)\n"]
    for h in hits:
        steps = " → ".join(str(s.get("tool", s.get("action", "?")))[:40]
                           for s in (h.get("steps") or [])[:8])
        parts.append(f"- 任务: {h.get('task', '')[:150]}\n"
                     f"  解法步骤: {steps or '(直接作答)'}\n"
                     f"  要点: {h.get('output', '')[:200]}")
    return "\n".join(parts)
