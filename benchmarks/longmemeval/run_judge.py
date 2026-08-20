#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM judge 重评 — 展示真实记忆能力（EM 严格匹配低估语义正确的回答）

对两份结果（基线全量 / MeshCtx 脑区增强 v2）用 deepseek judge 判定
response 是否满足问题与答案要求，输出两套准确率对比。
"""
import json
import os
import time


OUT = "/home/administrator/benchmarks-ext/results"

from model_io import ask as _ask_io, resolve_model_id as _resolve_mid
MODEL = _resolve_mid()  # 模型无关：MODEL_ID 切换任意主流模型（见 model_io.py）

JUDGE_PROMPT = """You are an evaluator. Given a QUESTION, a GOLD ANSWER (what the correct response should contain or fulfil), and a MODEL RESPONSE, decide whether the MODEL RESPONSE correctly fulfils the question and conveys/contains the gold answer (or a semantically equivalent correct answer).

Rules:
- The gold answer may be a specific fact OR a description of what the user prefers (e.g. "The user would prefer..."). In both cases, judge if the MODEL RESPONSE satisfies it.
- If the response gives a specific, relevant, correct answer to the question (e.g. a concrete recommendation matching the user's stated preferences), answer yes even if it is worded differently than the gold.
- Answer with ONLY "yes" or "no".

QUESTION: {question}
GOLD ANSWER: {answer}
MODEL RESPONSE: {response}
Your verdict (yes/no):"""


def judge(question, answer, response):
    """统一模型评估（模型无关：MODEL_ID 切换任意主流模型，见 model_io.py）"""
    for attempt in range(3):
        try:
            txt = (_ask_io(JUDGE_PROMPT.format(question=question, answer=answer, response=response[:800]),
                           max_tokens=8, temperature=0.0) or "").strip().lower()
            return 1.0 if txt.startswith("yes") else 0.0
        except Exception as e:
            time.sleep(3)
    return 0.0

def rescore(name, path):
    data = json.load(open(path, encoding="utf-8"))
    samples = data.get("samples") or data.get("per_task") or []
    # 统一字段: LongMemEval results 用 question/answer/response/em
    correct, total = 0, 0
    per_qtype = {}
    for s in samples:
        q = s.get("question") or s.get("question_id", "")
        a = s.get("answer") or s.get("ground_truth", "")
        resp = s.get("response") or s.get("raw_answer", "")
        if not a or not resp:
            continue
        v = judge(q, a, resp)
        correct += v
        total += 1
        qtype = s.get("question_type") or "other"
        per_qtype.setdefault(qtype, [0, 0])
        per_qtype[qtype][0] += v
        per_qtype[qtype][1] += 1
    print(f"== {name}: judge 准确率 {correct}/{total} = {correct/total:.1%}")
    for qt, (c, t) in sorted(per_qtype.items()):
        print(f"   {qt}: {c}/{t} = {c/t:.1%}")
    return correct, total


def main():
    print("=== LLM judge 重评（deepseek judge, 语义判定）===\n")
    c1, t1 = rescore("基线（全量历史）", os.path.join(OUT, "longmemeval_results.json"))
    print()
    c2, t2 = rescore("MeshCtx 脑区增强 v2", os.path.join(OUT, "meshctx_memory_enhanced_results.json"))
    print()
    print(f"汇总: 基线 {c1}/{t1} vs 脑区增强 {c2}/{t2}")
    json.dump({
        "baseline": {"correct": c1, "total": t1, "accuracy": c1 / t1 if t1 else 0},
        "meshctx_brainv2": {"correct": c2, "total": t2, "accuracy": c2 / t2 if t2 else 0},
    }, open(os.path.join(OUT, "judge_comparison.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
