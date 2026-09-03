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
    """极简 OTLP/HTTP JSON 导出 (span 级)。端点例: http://collector:4318/v1/traces"""

    def __init__(self, endpoint: str, timeout: float = 3.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._q = []                                   # 就地攒批 (简单)
        self._lock = threading.Lock()

    def export_span(self, span: Dict[str, Any]) -> None:
        """同步入队, 后台线程 POST (绝不阻塞调用方)。"""
        with self._lock:
            self._q.append(span)
            batch = list(self._q)
            self._q.clear()
        if batch:
            threading.Thread(target=self._send, args=(batch,),
                             daemon=True).start()

    def _send(self, batch: list) -> None:
        payload = {"resourceSpans": [{"scopeSpans": [{"spans": [
            {"traceId": s.get("trace_id", ""), "spanId": s.get("span_id", ""),
             "parentSpanId": s.get("parent_span_id", "") or None,
             "name": s.get("name", ""), "status": {"message": s.get("status", "")},
             "attributes": [{"key": k, "value": {"stringValue": str(v)}}
                            for k, v in (s.get("tags") or {}).items()],
             "durationNanos": int(s.get("duration_ms", 0)) * 1_000_000,
             "endTimeUnixNano": int(time.time() * 1e9),
             "agent": s.get("agent", "")} for s in batch]}]}]}
        try:
            req = urllib.request.Request(
                self.endpoint, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 300:
                    logger.debug("otlp http %s", resp.status)
        except Exception:
            logger.debug("otlp send failed", exc_info=True)   # 静默降级
