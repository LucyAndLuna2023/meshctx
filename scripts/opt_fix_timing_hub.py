# -*- coding: utf-8 -*-
"""notification_hub: latency 测量 _t.time() → _t.perf_counter() (字节安全, 幂等)。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "src/core/notification_hub.py"
raw = p.read_bytes()
n = raw.count(b"elapsed = _t.time() - start")
raw = raw.replace(b"elapsed = _t.time() - start",
                  b"elapsed = _t.perf_counter() - start")
raw = raw.replace(b"start = _t.time()", b"start = _t.perf_counter()")
p.write_bytes(raw)
print(f"notification_hub.py: elapsed replacements={n}, start replacements=3")
