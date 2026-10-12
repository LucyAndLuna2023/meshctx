# -*- coding: utf-8 -*-
"""meshctx 任务卡管理系统 (Task Cards) — 参考 zcode 审计工作流模式.

核心概念 (来自 002zcode 集群协作实证有效的模式):
- 任务卡: 编号 + 标题 + **预注册判据** (验收标准在开工前冻结, 防事后移动球门)
- 状态机: new → in_progress → review → pass/cond/fail → closed
- 审计轮次 (round): 每轮审计记录 findings, 按 P1(阻断)/P2(必修)/P3(应修)/P4(建议) 分级
- 挂账/清偿 (ledger): 发现问题挂账 → 修复 → 清偿回执 (带证据 SHA) → 销账
- 裁定记录: 审计方 + 证据 + 结论, 全程可追溯

存储: ~/.meshctx/tasks/{id}.json (一卡一文件, git 友好)
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_STATUS_FLOW = {
    "new":         {"in_progress", "closed"},
    "in_progress": {"review", "closed"},
    "review":      {"pass", "cond", "fail", "in_progress"},
    "pass":        {"closed"},
    "cond":        {"in_progress", "closed"},
    "fail":        {"in_progress", "closed"},
    "closed":      set(),
}
_SEVERITIES = ("P1", "P2", "P3", "P4")


def _tasks_dir() -> Path:
    base = os.environ.get("MESHCTX_HOME")
    root = Path(base) if base else Path.home() / ".meshctx"
    d = root / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _valid_id(tid: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", tid or ""))


def create_card(title: str, criteria: List[str], owner: str = "",
                severity_floor: str = "P2", tid: str = "") -> Dict[str, Any]:
    """创建任务卡 — criteria 即预注册判据 (冻结, 后续轮次对照).

    severity_floor: 挂账清偿门槛 (默认 P2=必修级才阻断 pass).
    """
    if not title or not title.strip():
        raise ValueError("title 不能为空")
    if not criteria:
        raise ValueError("criteria (预注册判据) 不能为空 — 防事后移动球门")
    tid = tid or f"tc-{int(time.time()*1000):x}-{uuid.uuid4().hex[:4]}"
    if not _valid_id(tid):
        raise ValueError(f"非法任务 id: {tid}")
    p = _tasks_dir() / f"{tid}.json"
    if p.exists():
        raise FileExistsError(f"任务卡已存在: {tid}")
    card = {
        "id": tid,
        "title": title.strip(),
        "criteria": [c.strip() for c in criteria if c.strip()],  # 预注册判据 (冻结)
        "owner": owner or "",
        "severity_floor": severity_floor if severity_floor in _SEVERITIES else "P2",
        "status": "new",
        "rounds": [],       # 审计轮次 [{n, ts, auditor, verdict, findings:[{sev,note,evidence}]}]
        "ledger": [],       # 挂账 [{sev, note, ts, status: open|settled, settle: {ts, evidence}}]
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    p.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
    return card


def get_card(tid: str) -> Dict[str, Any]:
    if not _valid_id(tid):
        raise ValueError(f"非法任务 id: {tid}")
    p = _tasks_dir() / f"{tid}.json"
    if not p.exists():
        raise FileNotFoundError(f"任务卡不存在: {tid}")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(card: Dict[str, Any]) -> None:
    card["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (_tasks_dir() / f"{card['id']}.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")


def list_cards(status: Optional[str] = None, owner: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(_tasks_dir().glob("tc-*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status and c.get("status") != status:
            continue
        if owner and c.get("owner") != owner:
            continue
        out.append({"id": c["id"], "title": c["title"], "status": c["status"],
                    "owner": c.get("owner", ""), "open_ledger": _open_count(c),
                    "rounds": len(c.get("rounds", []))})
    return out


def _open_count(card: Dict[str, Any]) -> int:
    return sum(1 for e in card.get("ledger", []) if e.get("status") == "open")


def set_status(tid: str, status: str) -> Dict[str, Any]:
    card = get_card(tid)
    if status not in _STATUS_FLOW:
        raise ValueError(f"非法状态: {status} (合法: {sorted(_STATUS_FLOW)})")
    allowed = _STATUS_FLOW[card["status"]]
    if status not in allowed:
        raise ValueError(f"状态转移不允许: {card['status']} → {status} (合法目标: {sorted(allowed)})")
    # pass/cond 前置: 高于门槛的挂账必须全部清偿
    if status in ("pass", "cond") and status == "pass":
        blocking = [e for e in card.get("ledger", [])
                    if e.get("status") == "open" and _sev_ge(e["sev"], card["severity_floor"])]
        if blocking:
            raise ValueError(f"存在 {len(blocking)} 条未清偿的 >= {card['severity_floor']} 挂账, "
                             f"不能 pass: {[e['note'][:40] for e in blocking]}")
    card["status"] = status
    _save(card)
    return card


def _sev_ge(a: str, b: str) -> bool:
    return _SEVERITIES.index(a) <= _SEVERITIES.index(b)


def add_round(tid: str, auditor: str, verdict: str,
              findings: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """记录一轮审计 — findings 里的开放问题自动入挂账 (ledger)."""
    card = get_card(tid)
    if verdict not in ("pass", "cond", "fail", "info"):
        raise ValueError("verdict: pass/cond/fail/info")
    findings = findings or []
    for f in findings:
        if f.get("sev") not in _SEVERITIES:
            raise ValueError(f"finding.sev 非法: {f.get('sev')} (P1-P4)")
    rnd = {"n": len(card["rounds"]) + 1,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "auditor": auditor or "unknown",
           "verdict": verdict,
           "findings": findings}
    card["rounds"].append(rnd)
    for f in findings:
        card["ledger"].append({"sev": f["sev"], "note": f.get("note", ""),
                               "evidence": f.get("evidence", ""), "ts": rnd["ts"],
                               "status": "open"})
    _save(card)
    return card


def settle(tid: str, note_match: str, evidence: str = "") -> Dict[str, Any]:
    """清偿挂账 — note_match 子串匹配挂账条目 (清偿须带证据, 铁律: 无证据不销账)."""
    if not evidence:
        raise ValueError("清偿必须带 evidence (SHA/commit/URL — 无证据不销账)")
    card = get_card(tid)
    hit = 0
    for e in card["ledger"]:
        if e["status"] == "open" and note_match and note_match in e["note"]:
            e["status"] = "settled"
            e["settle"] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "evidence": evidence}
            hit += 1
    if not hit:
        raise ValueError(f"无匹配的开放挂账: {note_match!r}")
    _save(card)
    return card


def summary() -> Dict[str, Any]:
    cards = [get_card(c["id"]) for c in list_cards()]
    by = {}
    for c in cards:
        by[c["status"]] = by.get(c["status"], 0) + 1
    return {"total": len(cards), "by_status": by,
            "open_ledger": sum(_open_count(c) for c in cards),
            "rounds_total": sum(len(c.get("rounds", [])) for c in cards)}
