"""benchmark runner 导入冒烟测试 — 防路径参数化 NameError 回归 (2026-08-26 004meshctx)

背景: 5 个 runner 路径参数化 (MESHCTX_BENCH_EXT) 后, 002codex 审计实测
run_judge/run_lost 导入即崩 NameError (引用 _os/_BENCH_EXT 但未定义)。
运行期崩、原测试不覆盖 — 本测试确保 import 不崩。
"""
import importlib
import pathlib
import pytest

RUNNERS = [
    "run_budget",
    "run_judge",
    "run_longcontext",
    "run_lost",
    "run_meshctx_memory",
]

RUNNER_DIR = pathlib.Path(__file__).parent.parent / "benchmarks" / "longmemeval"


@pytest.mark.parametrize("runner", RUNNERS)
def test_runner_imports(runner):
    """runner 可导入 (路径参数化后不 NameError)。"""
    import sys
    sys.path.insert(0, str(RUNNER_DIR))
    try:
        importlib.import_module(runner)
    except Exception as e:
        pytest.fail(f"{runner} import failed: {type(e).__name__}: {e}")


def test_benchmark_paths_resolve():
    """DATA/OUT 路径基于 MESHCTX_BENCH_EXT 或 ~/benchmarks-ext, 无硬编码 /home/administrator。"""
    import re
    for runner in RUNNERS:
        src = (RUNNER_DIR / f"{runner}.py").read_text(encoding="utf-8")
        assert "/home/administrator/benchmarks-ext" not in src, f"{runner} 仍硬编码路径"
        assert "_BENCH_EXT" in src, f"{runner} 缺 _BENCH_EXT 定义"
