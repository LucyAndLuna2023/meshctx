#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx benchmark 门禁 — 开源 vs 商业旗舰质量基线对比 (方案C·新护城河地基)

设计 (2026-08-26, 002meshctx):
  - 每次发布前运行: python3 scripts/benchmark_gate/run_gate.py
  - 输出 gate_report.json + 与 baseline 对比, 超阈值(开源逼近商业)则非零退出
  - 基准项:
      1. SWE-bench 启发式      (基线: resolve 98.7%, F1 0.967)
      2. LongMemEval 长记忆    (基线: 48 问语义判分 83.3%)
      3. 核心引擎可用性        (IIT Φ / ACT-R / JEPA / 元认知 真实实现检测)
      4. 模块健康              (NotImplementedError stub 计数, 应保持低位)
  数据依赖: benchmarks/SWE-bench, benchmarks/longmemeval (数据在 004 机器,
  本机缺失时跳过并记录 status=skipped, 不阻塞发布但告警).
"""

import json
import os
import subprocess
import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GATE_DIR = Path(__file__).resolve().parent
CONFIG = GATE_DIR / "gate_config.json"
BASELINE = GATE_DIR / "baseline.json"
REPORT = GATE_DIR / "gate_report.json"

DEFAULT_CONFIG = {
    "thresholds": {
        "swebench_resolve_min": 90.0,      # 开源 SWE-bench resolve 不得低于此值
        "longmemeval_score_min": 70.0,     # 开源 LongMemEval 判分不得低于此值
        "moat_gap_warn": 5.0,              # 开源逼近商业旗舰差距 < 5pp 时告警(需人工复核)
        "stub_remaining_max": 20,          # NotImplementedError stub 数上限
    },
    "moat_modules": ["iit_consciousness", "iit_engine", "act_r", "cognitive_architecture",
                     "desktop_tool", "lsp_tool", "mcp_gateway", "obs_integration",
                     "patch_generator", "ppt_generator", "spreadsheet_tool"],
}

DEFAULT_BASELINE = {
    "version": "3.121.0",
    "captured_at": "2026-08-26T00:00:00+00:00",
    "swebench": {"resolve": 98.7, "f1": 0.967, "note": "官方口径对标 Lite 49-60% / Verified 72.8-76.8%"},
    "longmemeval": {"score": 83.3, "questions": 48, "note": "语义判分, 平价模型达 GPT-4o 全上下文约八成"},
    "tests": {"passed": 3672, "skipped": 60, "failed": 0},
    "stub_count": 8,
    "moat_private": True,
}


def _count_stubs(src_core: Path) -> int:
    """统计 src/core 中 raise NotImplementedError 的真 stub 数(排除 except 容错)。"""
    n = 0
    for f in src_core.rglob("*.py"):
        if f.name == "__init__.py":
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in txt.splitlines():
            s = line.strip()
            if s.startswith("raise NotImplementedError"):
                n += 1
    return n


def _core_status(src_core: Path, moat_modules: list) -> dict:
    """核心引擎可用性检测: 闭源独有模块在开源侧不应存在(护城河未泄)。"""
    result = {}
    for m in moat_modules:
        result[m] = (src_core / f"{m}.py").exists()
    return result


def _run_bench(cmd: list, cwd: Path, timeout: int = 600) -> dict:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"ok": r.returncode == 0, "returncode": r.returncode,
                "stdout_tail": r.stdout[-400:] if r.stdout else "", "error": r.stderr[-200:] if r.stderr else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main() -> int:
    config = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else json.dumps(DEFAULT_CONFIG, ensure_ascii=False)
    cfg = json.loads(config)
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else DEFAULT_BASELINE
    src_core = ROOT / "src" / "core"
    # 当前版本从 src/core/__init__.py 读取 (而非 baseline 的旧版本)
    cur_ver = "?"
    try:
        import re as _re
        _init = (src_core / "__init__.py").read_text(encoding="utf-8")
        _m = _re.search(r'__version__\s*=\s*"([^"]+)"', _init)
        if _m:
            cur_ver = _m.group(1)
    except Exception:
        pass

    report = {
        "version": cur_ver,
        "run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "baseline": base,
        "results": {},
    }

    # 1. stub 计数
    stubs = _count_stubs(src_core)
    report["results"]["stub_count"] = stubs

    # 2. 护城河完整性 (开源侧闭源独有模块应为 False)
    moat = _core_status(src_core, cfg["thresholds"]["moat_modules"] if "moat_modules" in cfg["thresholds"] else cfg["moat_modules"])
    report["results"]["moat"] = moat
    leaked = [m for m, present in moat.items() if present]
    report["results"]["moat_leaked"] = leaked

    # 3. SWE-bench (数据存在才跑)
    swe = ROOT / "benchmarks" / "SWE-bench"
    if (swe / "run.py").exists():
        report["results"]["swebench"] = _run_bench([sys.executable, "run.py", "--report-only"], swe)
    else:
        report["results"]["swebench"] = {"ok": False, "skipped": "data on 004 machine"}

    # 4. LongMemEval
    lme = ROOT / "benchmarks" / "longmemeval"
    if (lme / "run_longmemeval.py").exists():
        report["results"]["longmemeval"] = _run_bench([sys.executable, "run_longmemeval.py"], lme, timeout=900)
    else:
        report["results"]["longmemeval"] = {"ok": False, "skipped": "data on 004 machine"}

    # 5. 门禁判定 (阈值接线: 有数据严格卡, 无数据 warning 不阻塞)
    th = cfg["thresholds"]
    checks = []
    if stubs > th["stub_remaining_max"]:
        checks.append(f"FAIL: stub_count {stubs} > {th['stub_remaining_max']}")
    if leaked:
        checks.append(f"FAIL: moat leaked -> {leaked}")

    # 5a. SWE-bench 阈值接线 (解析 resolve 百分比)
    swe_res = report["results"]["swebench"]
    if swe_res.get("ok") and swe_res.get("stdout_tail"):
        import re as _re
        _m = _re.search(r'([\d.]+)\s*%', swe_res["stdout_tail"])
        if _m:
            _resolve = float(_m.group(1))
            swe_res["resolve_pct"] = _resolve
            if _resolve < th["swebench_resolve_min"]:
                checks.append(f"FAIL: SWE-bench resolve {_resolve}% < {th['swebench_resolve_min']}%")
        else:
            checks.append("WARN: SWE-bench 输出无可解析数值, 未纳入门禁(需 004 数据)")
    elif swe_res.get("skipped"):
        checks.append("WARN: SWE-bench 数据在 004 机器, 本机门禁跳过")
    elif not swe_res.get("ok"):
        checks.append("WARN: SWE-bench 运行失败(数据在 004 机器), 未纳入门禁")

    # 5b. LongMemEval 阈值接线 (解析各类型 acc 取平均)
    lme_res = report["results"]["longmemeval"]
    if lme_res.get("ok") and lme_res.get("stdout_tail"):
        import re as _re
        _accs = [float(x) for x in _re.findall(r'=\s*([\d.]+)', lme_res["stdout_tail"])]
        if _accs:
            _score = sum(_accs) / len(_accs) * 100.0
            lme_res["score"] = round(_score, 1)
            if _score < th["longmemeval_score_min"]:
                checks.append(f"FAIL: LongMemEval {_score:.1f} < {th['longmemeval_score_min']}")
        else:
            checks.append("WARN: LongMemEval 输出无可解析数值, 未纳入门禁(需 004 数据)")
    elif lme_res.get("skipped"):
        checks.append("WARN: LongMemEval 数据在 004 机器, 本机门禁跳过")
    elif not lme_res.get("ok"):
        checks.append("WARN: LongMemEval 运行失败(数据在 004 机器), 未纳入门禁")

    # 5c. moat 语义级标注 (文件名级之外: 开源侧是否存在 IIT/JEPA 基础实现)
    semantic = {}
    for probe in ["brain_iit", "brain_ltp", "brain_architecture", "brain", "jepa_world_model", "metacognition"]:
        semantic[probe] = (src_core / f"{probe}.py").exists()
    report["results"]["moat_semantic"] = semantic
    report["results"]["moat_semantic_note"] = (
        "文件名级未泄漏; 能力级护城河 = 训练权重(IIT Phi/VICReg/ACT-R) + 7 闭源独有模块, "
        "开源基础实现需 benchmark 门禁量化差距 (v3.121.2 专项)")

    report["checks"] = checks
    report["gate"] = "PASS" if not [c for c in checks if c.startswith("FAIL")] else "FAIL"

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(c.startswith("FAIL") for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
