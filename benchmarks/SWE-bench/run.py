#!/usr/bin/env python3
"""meshctx SWE-bench Runner — 自动化基准测试"""
import subprocess, json, sys, os
from pathlib import Path

REPO = Path(__file__).resolve().parent / "repo"

def run_swebench_lite():
    """Run SWE-bench Lite evaluation"""
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", "princeton-nlp/SWE-bench_Lite",
        "--predictions_path", "gold",
        "--max_workers", "2",
        "--run_id", "meshctx_v3.33",
        "--timeout", "900",
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=3600)
    print(result.stdout[-2000:] if result.stdout else "No output")
    if result.stderr:
        print("STDERR:", result.stderr[-500:])
    return result.returncode

if __name__ == "__main__":
    sys.exit(run_swebench_lite())
