"""WP1 (MCTX-PLAN-2026-0903) telemetry span 语义测试。

覆盖: Span 父子关联 / trace 上下文归因 / 异常状态 / OTLP 默认关 / 字段向后兼容。
注意: 每个测试先 reset_telemetry(tmp path), 防污染真实 ~/.meshctx/telemetry.jsonl。
"""
import json
import time

import pytest

from src.core import telemetry as tel


@pytest.fixture(autouse=True)
def _fresh(tmp_path):
    tel.reset_telemetry(str(tmp_path / "tel.jsonl"))
    yield


def test_span_outer_inner_correlation():
    """嵌套 span: 同一 trace_id, 子 span parent=父 span_id。"""
    store = tel.get_telemetry()
    with tel.Span("outer", agent="task"):
        outer_span_id = tel.span_ctx.get()
        trace_id = tel.trace_ctx.get()
        with tel.Span("inner", agent="task") as sp:
            assert sp.trace_id == trace_id
            assert sp.parent_span == outer_span_id
            inner_span_id = tel.span_ctx.get()
            assert inner_span_id != outer_span_id
    # 两条 span 事件均落盘且同 trace
    spans = [e for e in store.events() if e["event_type"] == "span"]
    assert len(spans) >= 2
    assert all(e["trace_id"] == trace_id for e in spans)
    inner = next(e for e in spans if json.loads(e["detail"]).get("span") == "inner")
    assert json.loads(inner["detail"])["parent"] == outer_span_id


def test_record_auto_correlation_inside_span():
    """span 内普通事件自动带 trace_id/span_id 归因; span 外为空。"""
    store = tel.get_telemetry()
    store.record("task", "tool_call", tool="x")          # span 外: 无归因
    with tel.Span("card.run", agent="task"):
        store.record("task", "tool_call", tool="web", detail="go")
        in_trace = tel.trace_ctx.get()
        in_span = tel.span_ctx.get()
    store.record("task", "error", detail="after")        # span 退出后: 无归因
    by_trace = store.events_by_trace(in_trace)
    assert len(by_trace) == 2                            # span 事件 + 内部 tool_call
    assert any(e["tool"] == "web" for e in by_trace)
    tool_ev = next(e for e in by_trace if e["event_type"] == "tool_call")
    assert tool_ev["span_id"] == in_span
    outside = [e for e in store.events()
               if e["event_type"] in ("tool_call", "error") and e["tool"] in ("x", "")]
    assert all(e["trace_id"] == "" for e in outside)


def test_span_error_status_recorded():
    """span 内异常: 状态记入 detail, 异常不吞。"""
    store = tel.get_telemetry()
    with pytest.raises(ValueError):
        with tel.Span("boom", agent="task"):
            raise ValueError("bad")
    spans = [e for e in store.events() if e["event_type"] == "span"]
    boom = next(e for e in spans if "boom" in e["detail"])
    assert "error:ValueError" in boom["detail"]


def test_otlp_disabled_by_default(monkeypatch):
    """无 MESHCTX_OTLP_ENDPOINT: 导出零副作用 (exporter 不构造)。"""
    monkeypatch.delenv("MESHCTX_OTLP_ENDPOINT", raising=False)
    assert tel._otlp_endpoint() == ""
    with tel.Span("card.run", agent="task", tags={"card_id": "c1"}):
        pass
    assert tel._otlp_exporter is None


def test_record_backward_compat_and_new_fields(tmp_path):
    """既有 record() 位置/关键字调用不受影响; 新字段可读写; JSONL 可回载。"""
    store = tel.reset_telemetry(str(tmp_path / "b.jsonl"))
    store.record("task", "token", tokens_in=10, tokens_out=5)   # 旧式调用
    store.record("task", "span", latency_ms=12, detail="d",
                 trace_id="t1", span_id="s1")                    # 新字段
    evs = store.events()
    assert len(evs) == 2
    assert all("trace_id" in e and "span_id" in e for e in evs)
    # 回载: 新文件重新打开也能读出新字段
    store2 = tel.TelemetryStore(path=str(tmp_path / "b.jsonl"))
    reloaded = store2.events()
    assert len(reloaded) == 2
    sp = next(e for e in reloaded if e["event_type"] == "span")
    assert sp["trace_id"] == "t1" and sp["span_id"] == "s1"


def test_stats_include_spans():
    store = tel.get_telemetry()
    with tel.Span("ok1", agent="task"):
        pass
    with tel.Span("ok2", agent="task"):
        pass
    try:
        with tel.Span("bad", agent="task"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    st = store.stats(window_hours=24)
    assert st["spans_ok"] >= 2
    assert st["spans_error"] >= 1
