"""Observability: 结构化追踪 (Span/TraceLogger) — 零依赖，线程安全。

借鉴 LangSmith/Langfuse 的 trace 思想，为 meshctx 提供轻量全链路追踪：
- Span: 单个操作单元 (llm / tool / chain)
- TraceLogger: 线程安全日志器，内存 + 可选磁盘 JSONL
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Span:
    """单个追踪单元。"""
    span_type: str                       # "llm" | "tool" | "chain"
    name: str                            # 操作名
    inputs: Dict[str, Any] = field(default_factory=dict)
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    outputs: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        """耗时毫秒；未结束返回 0。"""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000.0

    @property
    def is_complete(self) -> bool:
        return self.end_time is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "span_type": self.span_type,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 3),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metadata": self.metadata,
            "error": self.error,
        }


class TraceLogger:
    """线程安全追踪日志器。

    - 内存保存所有 span
    - 可选: 若 MESHCTX_TRACE_DIR 环境变量已设置，追加写 JSONL
    """

    def __init__(self, trace_dir: Optional[str] = None,
                 enabled: bool = True):
        self._lock = threading.RLock()
        self._spans: List[Span] = []
        self.enabled = enabled
        self.trace_dir = trace_dir or os.environ.get("MESHCTX_TRACE_DIR")
        if self.trace_dir:
            os.makedirs(self.trace_dir, exist_ok=True)

    # ---- 写 ----
    def start_span(self, span_type: str, name: str,
                   inputs: Optional[Dict[str, Any]] = None,
                   parent_id: Optional[str] = None,
                   trace_id: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> Span:
        """创建一个 span 并记录开始。"""
        if not self.enabled:
            return Span(span_type=span_type, name=name, inputs=inputs or {})
        span = Span(
            span_type=span_type,
            name=name,
            inputs=inputs or {},
            parent_id=parent_id,
            trace_id=trace_id or (parent_id or ""),
            metadata=metadata or {},
        )
        # 若 parent 已知且未指定 trace，沿用父 trace
        if parent_id and not trace_id:
            parent = self._find(parent_id)
            if parent:
                span.trace_id = parent.trace_id
        with self._lock:
            self._spans.append(span)
        return span

    def end_span(self, span: Span, outputs: Optional[Dict[str, Any]] = None,
                 error: Optional[str] = None) -> Span:
        """记录 span 结束。"""
        if not self.enabled:
            return span
        span.end_time = time.time()
        span.outputs = outputs
        span.error = error
        self._persist(span)
        return span

    def error_span(self, span: Span, exc: Exception) -> Span:
        return self.end_span(span, error=f"{type(exc).__name__}: {exc}")

    # ---- 读 ----
    def get_span(self, span_id: str) -> Optional[Span]:
        return self._find(span_id)

    def get_trace(self, trace_id: str) -> List[Span]:
        with self._lock:
            return [s for s in self._spans if s.trace_id == trace_id]

    def recent(self, limit: int = 50) -> List[Span]:
        with self._lock:
            return list(self._spans[-limit:])

    def spans(self) -> List[Span]:
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_type: Dict[str, int] = {}
            for s in self._spans:
                by_type[s.span_type] = by_type.get(s.span_type, 0) + 1
            return {"total": len(self._spans), "by_type": by_type,
                    "errors": sum(1 for s in self._spans if s.error)}

    # ---- 内部 ----
    def _find(self, span_id: str) -> Optional[Span]:
        with self._lock:
            for s in self._spans:
                if s.span_id == span_id:
                    return s
        return None

    def _persist(self, span: Span) -> None:
        """可选：追加写 JSONL。"""
        if not self.trace_dir:
            return
        try:
            path = os.path.join(self.trace_dir,
                                f"trace_{time.strftime('%Y%m%d')}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass  # 观测层绝不抛出


# ---- 便捷上下文管理器 ----
class traced_span:
    """with traced_span("tool", "web_search", inputs=...) as span: ..."""

    def __init__(self, logger: TraceLogger, span_type: str, name: str,
                 inputs: Optional[Dict[str, Any]] = None,
                 parent_id: Optional[str] = None, trace_id: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        self._logger = logger
        self._span = None
        self._args = (span_type, name, inputs, parent_id, trace_id, metadata)

    def __enter__(self) -> Span:
        self._span = self._logger.start_span(*self._args)
        return self._span

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._span is None:
            return False
        if exc is not None:
            self._logger.error_span(self._span, exc)
            return False
        self._logger.end_span(self._span)
        return True


# ---- 模块级单例 ----
_logger: Optional[TraceLogger] = None
_logger_lock = threading.Lock()


def get_trace_logger() -> TraceLogger:
    """进程级单例 TraceLogger。"""
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = TraceLogger()
    return _logger


__all__ = ["Span", "TraceLogger", "traced_span", "get_trace_logger"]
