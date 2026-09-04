#!/usr/bin/env python3
"""LongMem 样例跑分 (WP3 阶段2, 管线验证) — demo-scale self_run。

诚实口径: 本跑分仅验证「语料入库 → MemoryService 检索 → EM 打分」管线可用性
(n=10, 检索式预测, 非 LLM 生成; 官方 LongMemEval_S 提交待凭据 runner)。
结果以 mode=self_run + config.demo=true 呈现, 不与任何厂商分数比较。
"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gaia_longmem_runner import grade_longmem  # noqa: E402
from src.core.memory_api import MemoryService  # noqa: E402

BASE = Path(__file__).resolve().parent
OUT = BASE / "reports" / "longmem_sample_report.json"

def main() -> int:
    corpus = BASE / "sample" / "longmem_sample_corpus.jsonl"
    qs = BASE / "sample" / "longmem_sample_questions.jsonl"
    svc = MemoryService(base_dir=str(Path(tempfile.mkdtemp(prefix="longmem_demo_"))))
    for line in corpus.read_text(encoding="utf-8").splitlines():
        if line.strip():
            svc.store("demo:longmem", json.loads(line)["text"])
    preds = BASE / "reports" / "longmem_sample_predictions.jsonl"
    preds.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in qs.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        q = json.loads(line)
        hits = svc.search("demo:longmem", q["question"], top_k=1)
        rows.append({"id": q["id"], "answer": hits[0]["text"] if hits else ""})
    preds.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                     encoding="utf-8")
    rep = grade_longmem(qs, preds, loose=True,
                        head="demo-pipeline (retrieval baseline)", out=str(OUT))
    rep["config"]["demo"] = True
    rep["config"]["note"] = "retrieval-baseline pipeline validation; not an official submission"
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep["results"], ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
