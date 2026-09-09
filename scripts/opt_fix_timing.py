# -*- coding: utf-8 -*-
"""v3.129.0 优化④: 耗时测量统一 perf_counter。

Windows time.time() 粒度 ~15.6ms, 快操作 duration/elapsed/latency 恒为 0.0
(可观测性指标失真)。time.perf_counter() 单调高精度, 跨平台一致。
仅替换"测量耗时"用途的 time.time(); 墙钟时间戳 (ts/sent_at/saved_at) 保留。
字节安全, 幂等。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPLS = {
    "src/core/workflow_engine.py": [
        (b"start = time.time()", b"start = time.perf_counter()"),
        (b"step_start = time.time()", b"step_start = time.perf_counter()"),
        (b"duration_ms=(time.time() - step_start) * 1000",
         b"duration_ms=(time.perf_counter() - step_start) * 1000"),
        (b"result.total_duration_ms = (time.time() - start) * 1000",
         b"result.total_duration_ms = (time.perf_counter() - start) * 1000"),
    ],
    "src/core/data_pipeline.py": [
        (b"t0 = time.time()", b"t0 = time.perf_counter()"),
        (b"t_extract_start = time.time()", b"t_extract_start = time.perf_counter()"),
        (b'self._stats.stages["extract_ms"] = (time.time() - t_extract_start) * 1000',
         b'self._stats.stages["extract_ms"] = (time.perf_counter() - t_extract_start) * 1000'),
        (b"t_transform_start = time.time()", b"t_transform_start = time.perf_counter()"),
        (b'self._stats.stages["transform_ms"] = (time.time() - t_transform_start) * 1000',
         b'self._stats.stages["transform_ms"] = (time.perf_counter() - t_transform_start) * 1000'),
        (b"t_validate_start = time.time()", b"t_validate_start = time.perf_counter()"),
        (b'self._stats.stages["validate_ms"] = (time.time() - t_validate_start) * 1000',
         b'self._stats.stages["validate_ms"] = (time.perf_counter() - t_validate_start) * 1000'),
        (b"t_load_start = time.time()", b"t_load_start = time.perf_counter()"),
        (b'self._stats.stages["load_ms"] = (time.time() - t_load_start) * 1000',
         b'self._stats.stages["load_ms"] = (time.perf_counter() - t_load_start) * 1000'),
        (b"self._stats.elapsed_seconds = time.time() - t0",
         b"self._stats.elapsed_seconds = time.perf_counter() - t0"),
    ],
}

for rel, pairs in REPLS.items():
    p = ROOT / rel
    raw = p.read_bytes()
    n = 0
    for old, new in pairs:
        n += raw.count(old)
        raw = raw.replace(old, new)
    if n:
        p.write_bytes(raw)
    print(f"{rel}: {n} replacements")
print("DONE")
