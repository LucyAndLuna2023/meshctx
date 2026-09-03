#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GAIA / LongMemEval runner (WP2, P0-2) — 提交 JSON 构造 + EM 打分。

GAIA: 私测集提交协议构造 (官方格式预留) — 凭据门控, 分数归属运营资产。
LongMemEval_S: 本地可跑的问答 (Q→A) 打分, 复用 core.exact_match/em_score。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from meshctx_benchmarks.core import em_score, validate_report, write_report


def build_gaia_submission(answers: dict, model: str) -> dict:
    """GAIA 风格提交: {task_id: final_answer} (官方 protocol 以实际发布为准)。"""
    return {"model_name": model, "date": os.environ.get("GITHUB_SHA", "local"),
            "submission": {str(k): {"final_answer": str(v)} for k, v in answers.items()}}


def validate_gaia_submission(sub: dict) -> list:
    problems = []
    if not sub.get("submission"):
        problems.append("submission 为空")
    for tid, ans in (sub.get("submission") or {}).items():
        if not isinstance(ans, dict) or "final_answer" not in ans:
            problems.append(f"{tid} 缺 final_answer")
    return problems


def grade_longmem(questions: Path, predictions: Path, loose: bool = False,
                  head: str = "local", out: str = "longmem_report.json") -> dict:
    """LongMem 风格问答打分: questions.jsonl {id, question, answer} ×
    predictions.jsonl {id, answer} → EM 报告。"""
    qs = {}
    with open(questions, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            qs[str(d["id"])] = d
    preds = {}
    with open(predictions, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            preds[str(d["id"])] = d.get("answer", "")
    pairs = [(preds.get(i, ""), q.get("answer", "")) for i, q in qs.items()]
    scored = em_score(pairs, loose=loose)
    report = {"benchmark": "longmem_s", "head": head,
              "config": {"loose": loose, "questions": len(qs), "graded": len(pairs)},
              "results": {"mode": "self_run", "metric": "em",
                          "em": scored["em"], "correct": scored["correct"],
                          "total": scored["total"]}}
    write_report(report, out_path)     # write 自动补 schema/date + validate
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="GAIA/LongMem runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gaia-submission")
    g.add_argument("--answers", required=True, help="answers.json {task_id: answer}")
    g.add_argument("--model", default="meshctx-v3.123")
    g.add_argument("--out", default="gaia_submission.json")
    l = sub.add_parser("longmem")
    l.add_argument("--questions", required=True)
    l.add_argument("--predictions", required=True)
    l.add_argument("--loose", action="store_true")
    l.add_argument("--out", default="longmem_report.json")
    a = ap.parse_args()
    if a.cmd == "gaia-submission":
        ans = json.loads(Path(a.answers).read_text(encoding="utf-8"))
        sub_ = build_gaia_submission(ans, a.model)
        problems = validate_gaia_submission(sub_)
        if problems:
            sys.exit("; ".join(problems))
        Path(a.out).write_text(json.dumps(sub_, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print("gaia submission written:", a.out)
    else:
        rep = grade_longmem(Path(a.questions), Path(a.predictions),
                            loose=a.loose, out=a.out)
        print(json.dumps(rep["results"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
