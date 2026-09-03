#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 遥测 — 标准化运行指标 (2026-08-28, 借鉴 @earendil-works/pi telemetry)

记录 agent 每次运行的指标: token/延迟/工具调用/错误/模型,
提供 /api/telemetry/events + /api/telemetry/stats (可观测性)。

WP1 (MCTX-PLAN-2026-0903) 扩展 (2026-09-03):
- Span / trace_ctx / span_ctx: contextvar 级 span 语义 (嵌套父子关联, 全链路追踪)
- TelemetryEvent 增 trace_id / span_id 关联字段 (向后兼容, 既有路由不受影响)
- OTLP 导出: 环境变量 MESHCTX_OTLP_ENDPOINT 开启 (默认关, 零开销; 团队/企业版)
- JSONL 轮转: 既有 >2MB → 保留最近 5000 行 (002meshctx P3① 已内置, 注释标明)
"""
import json
import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.telemetry")

# ── WP1: trace / span 上下文 ──────────────────────────────────────────────
trace_ctx: "ContextVar[str]" = ContextVar("meshctx_trace_id", default="")
span_ctx: "ContextVar[str]" = ContextVar("meshctx_span_id", default="")
# 同一 trace 内嵌套 span 的栈 (最内层为当前父 span 链), 用于事件归因
_span_stack_ctx: "ContextVar[tuple]" = ContextVar("meshctx_span_stack", default=())


def new_span_id() -> str:
    """短 id (16 hex) — 足够集群内跨进程唯一。"""
    return uuid.uuid4().hex[:16]


@dataclass
class TelemetryEvent:
    ts: float
    agent: str            # chat / task / swarm / team_memory ...
    event_type: str       # token / tool_call / tool_result / error / turn_start / turn_end / span
    model: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool: str = ""
    detail: str = ""
    session_id: str = ""
    # WP1: 全链路关联字段 (向后兼容, 默认空)
    trace_id: str = ""
    span_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "agent": self.agent, "event_type": self.event_type,
                "model": self.model, "latency_ms": self.latency_ms,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "tool": self.tool, "detail": self.detail, "session_id": self.session_id,
                "trace_id": self.trace_id, "span_id": self.span_id}


class Span:
    """上下文管理器 span (WP1)。

    用法::

        with Span("agent.round", agent="task", tags={"round": 1}) as sp:
            ...  # 内部 record() 自动带 trace_id/span_id 归因
        # 退出时落一条 event_type="span" (含耗时/状态)

    顶层进入自动生成 trace_id; 嵌套自动挂父 span_id。
    异常不吞 (__exit__ 返回 False), 状态记入 detail。
    """

    def __init__(self, name: str, agent: str = "task",
                 trace_id: str = "", tags: Optional[Dict[str, Any]] = None):
        self.name = name
        self.agent = agent
        self.trace_id = trace_id or trace_ctx.get()
        self.span_id = new_span_id()
        self.tags = dict(tags or {})
        self.start_ts = time.time()
        self._tok_trace = self._tok_span = self._tok_stack = None
        self._closed = False

    def __enter__(self) -> "Span":
        if not self.trace_id:                      # 顶层 span: 生成新 trace
            self.trace_id = new_span_id()
        parent = span_ctx.get()
        stack = _span_stack_ctx.get()
        self._tok_trace = trace_ctx.set(self.trace_id)
        self._tok_span = span_ctx.set(self.span_id)
        self._tok_stack = _span_stack_ctx.set(stack + (self.span_id,))
        self.parent_span = parent or ""
        return self

    def __exit__(self, et, ev, tb) -> bool:
        if self._closed:
            return False
        self._closed = True
        ok = et is None
        status = "ok" if ok else f"error:{ev.__class__.__name__}"
        dur_ms = int((time.time() - self.start_ts) * 1000)
        detail = json.dumps({"span": self.name, "status": status,
                             "parent": self.parent_span},
                            ensure_ascii=False)
        if self.tags:
            detail = json.dumps({"span": self.name, "status": status,
                                 "parent": self.parent_span, **self.tags},
                                ensure_ascii=False)
        try:
            get_telemetry().record(self.agent, "span", latency_ms=dur_ms,
                                   detail=detail[:1000],
                                   trace_id=self.trace_id, span_id=self.span_id)
            _maybe_export_span(self.trace_id, self.span_id, self.parent_span,
                               self.name, status, dur_ms, self.tags, self.agent)
        except Exception:                           # 遥测失败绝不干扰业务
            logger.debug("span record failed", exc_info=True)
        if self._tok_trace is not None:
            trace_ctx.reset(self._tok_trace)
        if self._tok_span is not None:
            span_ctx.reset(self._tok_span)
        if self._tok_stack is not None:
            _span_stack_ctx.reset(self._tok_stack)
        return False                                # 不吞异常

    @property
    def stack_depth(self) -> int:
        return len(_span_stack_ctx.get())


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
               tool: str = "", detail: str = "", session_id: str = "",
               trace_id: str = "", span_id: str = "") -> None:
        """WP1: trace_id/span_id 空时自动从当前 span 上下文归因。"""
        if not trace_id:
            trace_id = trace_ctx.get()
        if not span_id:
            span_id = span_ctx.get()
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
                            tool=tool, detail=detail, session_id=session_id,
                            trace_id=trace_id, span_id=span_id)
        with self._lock:
            self._events.append(ev)
            if len(self._events) > self._capacity:
                self._events = self._events[-self._capacity:]
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
                # 轮转 (WP1/002meshctx P3①): 文件超 2MB → 保留最近 5000 行,
                # 防长跑磁盘膨胀 (个人版 JSONL 存储即此上限内轮转)
                if self._path.stat().st_size > 2 * 1024 * 1024:
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

    def events_by_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        """WP1: 按 trace_id 取全链路事件 (父子 span 关联查询)。"""
        with self._lock:
            return [e.to_dict() for e in self._events if e.trace_id == trace_id]

    def stats(self, window_hours: int = 24) -> Dict[str, Any]:
        cutoff = time.time() - window_hours * 3600
        with self._lock:
            recent = [e for e in self._events if e.ts >= cutoff]
        tokens_in = sum(e.tokens_in for e in recent)
        tokens_out = sum(e.tokens_out for e in recent)
        tools = {}
        errors = 0
        spans_ok = spans_err = 0
        for e in recent:
            if e.tool:
                tools[e.tool] = tools.get(e.tool, 0) + 1
            if e.event_type == "error":
                errors += 1
            if e.event_type == "span":
                if "error:" in e.detail:
                    spans_err += 1
                else:
                    spans_ok += 1
        lat_events = [e.latency_ms for e in recent if e.latency_ms > 0]
        return {"window_hours": window_hours, "events": len(recent),
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "tool_calls": tools, "errors": errors,
                "spans_ok": spans_ok, "spans_error": spans_err,
                "avg_latency_ms": int(sum(lat_events) / max(1, len(lat_events))) if lat_events else 0}


# ── WP1: OTLP 可选导出 (团队/企业版; feature flag MESHCTX_OTLP_ENDPOINT) ──
_otlp_exporter = None


def _otlp_endpoint() -> str:
    return os.environ.get("MESHCTX_OTLP_ENDPOINT", "").strip()


def _maybe_export_span(trace_id: str, span_id: str, parent_span: str,
                       name: str, status: str, dur_ms: int,
                       tags: Dict[str, Any], agent: str) -> None:
    """默认关: 无 MESHCTX_OTLP_ENDPOINT 时零开销直接返回。"""
    ep = _otlp_endpoint()
    if not ep:
        return
    global _otlp_exporter
    if _otlp_exporter is None:
        from src.core.telemetry_otlp import OTLPExporter   # 惰性导入 (仅开启时)
        _otlp_exporter = OTLPExporter(ep)
    try:
        _otlp_exporter.export_span({
            "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_span,
            "name": name, "status": status, "duration_ms": dur_ms,
            "tags": tags, "agent": agent, "ts": time.time()})
    except Exception:
        logger.debug("otlp export failed", exc_info=True)


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
