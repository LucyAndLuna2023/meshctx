"""Tests for observability (Span / TraceLogger / traced_span)."""
import os
import tempfile
import threading

import pytest

from src.core.observability import (
    Span,
    TraceLogger,
    get_trace_logger,
    traced_span,
)


def test_span_basics():
    span = Span(span_type="tool", name="web_search")
    assert span.span_id
    assert span.trace_id
    assert not span.is_complete
    assert span.duration_ms == 0.0


def test_trace_logger_start_end():
    logger = TraceLogger(enabled=True)
    span = logger.start_span("llm", "gemini-2.5-pro",
                             inputs={"prompt": "hi"})
    assert span in logger.spans()
    logger.end_span(span, outputs={"text": "hello"})
    assert span.is_complete
    assert span.duration_ms > 0
    d = span.to_dict()
    assert d["name"] == "gemini-2.5-pro"
    assert d["outputs"]["text"] == "hello"


def test_trace_logger_error():
    logger = TraceLogger(enabled=True)
    span = logger.start_span("tool", "terminal")
    logger.error_span(span, RuntimeError("boom"))
    assert span.error and "boom" in span.error
    assert logger.stats()["errors"] == 1


def test_parent_child_trace_id():
    logger = TraceLogger(enabled=True)
    parent = logger.start_span("chain", "plan")
    child = logger.start_span("tool", "search",
                              parent_id=parent.span_id,
                              trace_id=parent.trace_id)
    logger.end_span(child)
    logger.end_span(parent)
    trace = logger.get_trace(parent.trace_id)
    assert len(trace) == 2
    assert child.trace_id == parent.trace_id


def test_traced_span_context_manager():
    logger = TraceLogger(enabled=True)
    with traced_span(logger, "tool", "web_extract",
                     inputs={"url": "https://x"}) as span:
        assert span.span_type == "tool"
    assert span.is_complete


def test_traced_span_exception():
    logger = TraceLogger(enabled=True)
    with pytest.raises(ValueError):
        with traced_span(logger, "tool", "bad"):
            raise ValueError("nope")
    assert logger.stats()["errors"] == 1


def test_disabled_logger():
    logger = TraceLogger(enabled=False)
    span = logger.start_span("tool", "x")
    logger.end_span(span)
    assert logger.spans() == []


def test_jsonl_persist():
    with tempfile.TemporaryDirectory() as d:
        logger = TraceLogger(enabled=True, trace_dir=d)
        span = logger.start_span("llm", "deepseek")
        logger.end_span(span, outputs={"ok": True})
        files = os.listdir(d)
        assert files, "JSONL file should exist"
        path = os.path.join(d, files[0])
        content = open(path, encoding="utf-8").read()
        assert "deepseek" in content


def test_thread_safety():
    logger = TraceLogger(enabled=True)
    errors = []

    def worker(i):
        try:
            for _ in range(50):
                span = logger.start_span("tool", f"w{i}")
                logger.end_span(span)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert logger.stats()["total"] == 400


def test_singleton():
    a = get_trace_logger()
    b = get_trace_logger()
    assert a is b
