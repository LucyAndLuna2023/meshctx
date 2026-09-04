"""WP3 阶段2: LongMem 样例跑分管线守护 — 语料入库→检索→EM 报告 (demo-scale self_run)。"""
import json
import subprocess
import sys
from pathlib import Path


def test_sample_pipeline_report():
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "benchmarks" / "longmem_sample_run.py")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    rep = json.loads((root / "benchmarks" / "reports" / "longmem_sample_report.json").read_text(encoding="utf-8"))
    assert rep["results"]["mode"] == "self_run"
    assert rep["config"]["demo"] is True          # 诚实口径: demo-scale
    assert rep["results"]["em"] >= 0.5, rep["results"]
    assert rep["results"]["total"] == 10
    preds = (root / "benchmarks" / "reports" / "longmem_sample_predictions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(preds) == 10
