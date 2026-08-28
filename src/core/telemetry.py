#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 遥测 — 标准化运行指标 (2026-08-28, 借鉴 @earendil-works/pi telemetry)

记录 agent 每次运行的指标: token/延迟/工具调用/错误/模型,
提供 /api/telemetry/events + /api/telemetry/stats (可观测性)。
"""
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.telemetry")


@dataclass
class TelemetryEvent:
    ts: float
    agent: str            # chat / task / swarm / team_memory ...
    event_type: str       # token / tool_call / tool_result / error / turn_start / turn_end
    model: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool: str = ""
    detail: str = ""
    session_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "agent": self.agent, "event_type": self.event_type,
                "model": self.model, "latency_ms": self.latency_ms,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "tool": self.tool, "detail": self.detail, "session_id": self.session_id}


class TelemetryStore:
    """环形缓冲 + JSON 持久化 (最近 N 条)。线程安全。"""

    def __init__(self, capacity: int = 5000, path: str = ""):
        self._lock = threading.Lock()
        self._capacity = capacity
        self._events: List[TelemetryEvent] = []
        self._path = Path(path or (Path.home() / ".meshctx" / "telemetry.jsonl"))
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                for line in self._path.read_text(encoding="utf-8").splitlines()[:self._capacity]:
                    try:
                        d = json.loads(line)
                        self._events.append(TelemetryEvent(**{k: v for k, v in d.items()
                                                              if k in TelemetryEvent.__dataclass_fields__}))
                    except Exception:
                        pass
        except Exception:
            pass

    def record(self, agent: str, event_type: str, model: str = "",
               latency_ms: int = 0, tokens_in: int = 0, tokens_out: int = 0,
               tool: str = "", detail: str = "", session_id: str = "") -> None:
        # 002codex P3: int() 安全转换 (异常输入不 500)
        try:
            latency_ms = int(latency_ms)
        except (TypeError, ValueError):
            latency_ms = 0
        try:
            tokens_in = int(tokens_in); tokens_out = int(tokens_out)
        except (TypeError, ValueError):
            tokens_in = tokens_out = 0
        ev = TelemetryEvent(ts=time.time(), agent=agent, event_type=event_type,
                            model=model, latency_ms=max(0, latency_ms),
                            tokens_in=max(0, tokens_in), tokens_out=max(0, tokens_out),
                            tool=tool, detail=detail, session_id=session_id)
        with self._lock:
            self._events.append(ev)
            if len(self._events) > self._capacity:
                self._events = self._events[-self._capacity:]
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
                # 002codex P3: 裁剪 — 文件超过 10000 行时保留最近 5000
                if self._path.stat().st_size > 2 * 1024 * 1024:  # >2MB 裁剪
                    lines = self._path.read_text(encoding="utf-8").splitlines()[-5000:]
                    self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass

    def events(self, agent: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            evs = [e.to_dict() for e in self._events]
        if agent:
            evs = [e for e in evs if e.get("agent") == agent]
        return evs[-limit:]

    def stats(self, window_hours: int = 24) -> Dict[str, Any]:
        cutoff = time.time() - window_hours * 3600
        with self._lock:
            recent = [e for e in self._events if e.ts >= cutoff]
        tokens_in = sum(e.tokens_in for e in recent)
        tokens_out = sum(e.tokens_out for e in recent)
        tools = {}
        errors = 0
        for e in recent:
            if e.tool:
                tools[e.tool] = tools.get(e.tool, 0) + 1
            if e.event_type == "error":
                errors += 1
        lat_events = [e.latency_ms for e in recent if e.latency_ms > 0]
        return {"window_hours": window_hours, "events": len(recent),
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "tool_calls": tools, "errors": errors,
                "avg_latency_ms": int(sum(lat_events) / max(1, len(lat_events))) if lat_events else 0}


_default: Optional[TelemetryStore] = None


def get_telemetry() -> TelemetryStore:
    global _default
    if _default is None:
        _default = TelemetryStore()
    return _default


def reset_telemetry(path: str = "") -> TelemetryStore:
    global _default
    _default = TelemetryStore(path=path)
    return _default
