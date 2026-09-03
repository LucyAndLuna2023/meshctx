#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx benchmarks 共享核心 (WP2, MCTX-PLAN-2026-0903 P0-2).

纯函数/可测部分 — 无外部依赖 (不用 docker/数据集即可单测):
- report schema 校验与 JSON 落盘 (统一结果口径, 分表呈现 自测 vs 官方提交)
- SWE-bench 风格: instance JSONL 解析 + FAIL_TO_PASS/PASS_TO_PASS 统计
- GAIA/LongMem 风格: 答案规范化 + Exact-Match 分级打分 (STRICT/LOOSE)
评测 runner (swebench/gaia/longmem) 只做编排与凭据门控, 本模块保证口径一致。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "1.0"
REPORT_KEYS = {"schema", "benchmark", "date", "head", "config", "results"}


def validate_report(report: Dict[str, Any]) -> List[str]:
    """返回问题清单 (空 = 合规)。口径: 自测/官方分表呈现, 不混排; metric 须实算。"""
    problems = []
    for k in REPORT_KEYS:
        if k not in report:
            problems.append(f"缺顶层字段 {k}")
    res = report.get("results") or {}
    mode = res.get("mode") or ""
    if mode not in ("self_run", "official_submission", "reference"):
        problems.append(f"results.mode 必须 self_run|official_submission|reference, 实为 {mode!r}")
    if "metric" not in res:
        problems.append("缺 results.metric (如 resolved|pass_rate|em)")
    dry = bool(report.get("mode_hint"))          # dry-run 计划报告豁免实算断言 (P3-B)
    metric = res.get("metric")
    if not dry:
        if metric == "resolved" and not isinstance(res.get("resolved"), (int, float)) \
                and "resolved_count" not in res:
            problems.append("metric=resolved 需实算: results.resolved/resolved_count 数值 (禁占位)")
        if metric == "em" and not isinstance(res.get("em"), (int, float)):
            problems.append("metric=em 需实算: results.em 数值")
        if metric == "pass_rate" and not isinstance(res.get("pass_rate"), (int, float)):
            problems.append("metric=pass_rate 需实算数值")
    return problems


def write_report(report: Dict[str, Any], path: str | Path) -> Path:
    report.setdefault("schema", SCHEMA_VERSION)
    report.setdefault("date", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    problems = validate_report(report)
    if problems:
        raise ValueError("report 不合规: " + "; ".join(problems))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ── SWE-bench 风格 ────────────────────────────────────────────────────────
def load_swe_instances(jsonl: str | Path) -> List[Dict[str, Any]]:
    """解析 SWE-bench 实例 JSONL; 校验必填键 (instance_id/base_commit/test_patch/
    patch/F2P/P2P 字段名兼容 swebench 官方格式)。"""
    required = ("instance_id", "base_commit", "patch")
    out = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            inst = json.loads(line)
            for k in required:
                if k not in inst:
                    raise ValueError(f"实例缺 {k}: {line[:120]}")
            out.append(inst)
    return out


def f2p_p2p_sets(instance: Dict[str, Any]) -> tuple:
    """从实例取 FAIL_TO_PASS/PASS_TO_PASS 集合 (兼容 'FAIL_TO_PASS' 或小写/列表/逗号串)。"""
    def _norm(v) -> set:
        if v is None:
            return set()
        if isinstance(v, str):
            return {x.strip() for x in v.split(",") if x.strip()}
        return set(v)
    f2p = _norm(instance.get("FAIL_TO_PASS", instance.get("fail_to_pass")))
    p2p = _norm(instance.get("PASS_TO_PASS", instance.get("pass_to_pass")))
    return f2p, p2p


def summarize_instances(instances: List[Dict[str, Any]]) -> Dict[str, Any]:
    """实例集汇总 (无运行即可出的口径数据: 规模/字段覆盖/补丁统计)。"""
    n = len(instances)
    f2p_total = p2p_total = 0
    for inst in instances:
        f2p, p2p = f2p_p2p_sets(inst)
        f2p_total += len(f2p)
        p2p_total += len(p2p)
    return {"instances": n, "f2p_tests": f2p_total, "p2p_tests": p2p_total,
            "patched": sum(1 for i in instances if i.get("patch"))}


# ── GAIA / LongMem 风格 答案打分 ───────────────────────────────────────────
_NORM_SPACES = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    """大小写/空白/两端标点规范化 (EM 打分用; LOOSE 模式可容忍分隔差异)。"""
    t = (text or "").strip().lower()
    t = _NORM_SPACES.sub(" ", t)
    return t.strip()


def exact_match(pred: str, gold: str, loose: bool = False) -> bool:
    """STRICT: 规范化后全等; LOOSE: gold 任一候选 (| 分隔) 命中即可。"""
    if not gold:
        return False
    pred_n = normalize_answer(pred)
    if not pred_n:
        return False
    candidates = [normalize_answer(g) for g in str(gold).split("|")]
    if loose:
        return pred_n in candidates or any(c in pred_n for c in candidates if len(c) > 2)
    return pred_n in candidates


def em_score(pairs: Iterable[tuple], loose: bool = False) -> Dict[str, Any]:
    """批打分: 返回 em / correct / total / misses。"""
    pairs = list(pairs)
    hits = [1 if exact_match(p, g, loose) else 0 for p, g in pairs]
    return {"em": round(sum(hits) / len(pairs), 4) if pairs else 0.0,
            "correct": sum(hits), "total": len(pairs),
            "misses": [i for i, h in enumerate(hits) if not h]}
