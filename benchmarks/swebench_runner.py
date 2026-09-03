#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SWE-bench Verified runner (WP2, P0-2).

编排: 读实例 JSONL → (可选项) 官方评测容器逐实例验证 patch → 汇总 report。
真实运行需要: swebench 官方镜像 + docker + 凭据 (MESHCTX_SWE_* env), 由
benchmark-nightly CI 独立触发 — 不进日常 pytest/CI。--dry-run 仅出实例汇总与计划。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from meshctx_benchmarks.core import (load_swe_instances, summarize_instances,
                                     validate_report, write_report)


def _plan(instances) -> dict:
    return {"steps": len(instances), "per_instance":
            [{"instance_id": i["instance_id"], "base_commit": i["base_commit"],
              "patch_lines": len((i.get("patch") or "").splitlines())}
             for i in instances]}


def run_dry(jsonl: str, head: str) -> dict:
    instances = load_swe_instances(jsonl)
    return {"schema": "1.0", "benchmark": "swebench_verified",
            "mode_hint": "dry-run (真实运行需 docker+镜像+凭据, 见 README)",
            "head": head, "config": {"instances_file": jsonl},
            "results": {"mode": "self_run", "metric": "resolved",
                        "summary": summarize_instances(instances),
                        "plan": _plan(instances)}}


def run_real(jsonl: str, head: str, out: str, image: str,
             timeout_min: int = 60) -> dict:
    """真实容器评测 (P2-W2-1/002meshctx): 判定落地前显式不可用。

    官方 SWE-bench Verified harness 接入 (读 harness stdout/日志 → FAIL_TO_PASS/
    PASS_TO_PASS 判定统计) 为 3.124.0-final 工作项 — 禁止"占位假跑分"产出合规报告。
    """
    raise NotImplementedError(
        "swebench run_real 判定落地中 (3.124.0-final): 官方 harness 结果解析 + "
        "resolved 统计实算后才开放; 当前请用 --dry-run 出实例汇总")


def main() -> int:
    ap = argparse.ArgumentParser(description="SWE-bench Verified runner")
    ap.add_argument("--jsonl", required=True, help="实例 JSONL")
    ap.add_argument("--head", default=os.environ.get("GITHUB_SHA", "local"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="swebench_report.json")
    ap.add_argument("--image", default=os.environ.get("MESHCTX_SWE_IMAGE", ""))
    a = ap.parse_args()
    if a.dry_run or not a.image:
        rep = run_dry(a.jsonl, a.head)
        if not a.dry_run:
            print("dry 计划 (未配镜像): 请设 MESHCTX_SWE_IMAGE 后真跑", file=sys.stderr)
        write_report(rep, a.out)
    else:
        rep = run_real(a.jsonl, a.head, a.out, a.image)
    print(json.dumps(rep.get("results", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
