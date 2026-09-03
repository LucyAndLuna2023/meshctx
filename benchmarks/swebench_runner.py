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
    """逐实例进容器验证 (swebench harness)。需 docker 与镜像预置。"""
    if not image:
        sys.exit("缺少 SWE 评测镜像 (MESHCTX_SWE_IMAGE); 先构建 swebench 容器")
    instances = load_swe_instances(jsonl)
    results = []
    for inst in instances:
        cmd = ["docker", "run", "--rm", "-v",
               f"{os.getcwd()}:/work", image,
               "python", "-m", "swebench.harness.run_evaluation",
               "--instance_id", inst["instance_id"], "--patch_file", "/work/patch.txt"]
        subprocess.run(cmd, check=False, timeout=timeout_min * 60)
        results.append({"instance_id": inst["instance_id"],
                        "status": "ran"})   # 真实判定读 harness 输出 (下批)
    report = {"benchmark": "swebench_verified", "head": head,
              "config": {"image": image}, "results": {"mode": "self_run",
              "metric": "resolved", "instances": results}}
    problems = validate_report(report)
    if problems:
        raise SystemExit("; ".join(problems))
    write_report(report, out)
    return report


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
