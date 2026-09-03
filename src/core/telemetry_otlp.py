#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OTLP 导出器 (WP1 MCTX-PLAN-2026-0903, 团队/企业版可观测性)。

- 由 MESHCTX_OTLP_ENDPOINT 环境变量开启; 未设置时 telemetry 侧零开销不构造本类。
- 零第三方依赖: urllib JSON POST (OTLP/HTTP proto), 失败静默降级 JSONL。
- fire-and-forget: 导出放后台线程, 绝不阻塞业务路径。
"""
import json
import logging
import threading
import time
import urllib.request
from typing import Any, Dict

logger = logging.getLogger("meshctx.telemetry_otlp")


class OTLPExporter:
    """极简 OTLP/HTTP JSON 导出 (span 级)。端点例: http://collector:4318/v1/traces
    P3-3 (002meshctx): 并发导出线程上限 (默认关时零线程; 开启后最多 _MAX_INFLIGHT 并行)。"""

    _MAX_INFLIGHT = 4
    _inflight = 0
    _inflight_lock = threading.Lock()

    def __init__(self, endpoint: str, timeout: float = 3.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._q = []                                   # 就地攒批 (简单)
        self._lock = threading.Lock()

    def export_span(self, span: Dict[str, Any]) -> None:
        """同步入队, 后台线程 POST (绝不阻塞调用方; 超并发上限则丢弃本批静默)。"""
        with self._lock:
            self._q.append(span)
            batch = list(self._q)
            self._q.clear()
        if not batch:
            return
        with OTLPExporter._inflight_lock:
            if OTLPExporter._inflight >= OTLPExporter._MAX_INFLIGHT:
                return                      # 已达并发上限: 丢批静默 (保业务)
            OTLPExporter._inflight += 1
        threading.Thread(target=self._send, args=(batch,),
                         daemon=True).start()

    def _send(self, batch: list) -> None:
        try:
            self._do_send(batch)
        finally:
            with OTLPExporter._inflight_lock:
                OTLPExporter._inflight = max(0, OTLPExporter._inflight - 1)

    def _do_send(self, batch: list) -> None:
        spans = []
        for s in batch:
            status = s.get("status", "")
            attrs = [{"key": k, "value": {"stringValue": str(v)}}
                     for k, v in (s.get("tags") or {}).items()]
            # P3-2 (002meshctx): 非规范顶层字段移入 attributes; status 带 code
            # (OTLP StatusCode: 0=unset 1=ok 2=error)
            attrs.append({"key": "agent", "value": {"stringValue": s.get("agent", "")}})
            attrs.append({"key": "meshctx.status",
                          "value": {"stringValue": status}})
            spans.append({
                "traceId": s.get("trace_id", ""), "spanId": s.get("span_id", ""),
                "parentSpanId": s.get("parent_span_id", "") or None,
                "name": s.get("name", ""),
                "status": {"code": 1 if status == "ok" else 2,
                           "message": status},
                "attributes": attrs,
                "startTimeUnixNano": int(time.time() * 1e9)
                - int(s.get("duration_ms", 0)) * 1_000_000,
                "endTimeUnixNano": int(time.time() * 1e9)})
        payload = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
        try:
            req = urllib.request.Request(
                self.endpoint, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 300:
                    logger.debug("otlp http %s", resp.status)
        except Exception:
            logger.debug("otlp send failed", exc_info=True)   # 静默降级
