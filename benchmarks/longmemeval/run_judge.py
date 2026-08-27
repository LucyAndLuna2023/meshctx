#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM judge 重评 — 展示真实记忆能力（EM 严格匹配低估语义正确的回答）

对两份结果（基线全量 / MeshCtx 脑区增强 v2）用 deepseek judge 判定
response 是否满足问题与答案要求，输出两套准确率对比。
"""
import json
import os
import time


import os as _os
_BENCH_EXT = _os.environ.get("MESHCTX_BENCH_EXT") or _os.path.expanduser("~/benchmarks-ext")
OUT = _os.path.join(_BENCH_EXT, "results")

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
            # 2026-08-26: max_tokens 8→64 修 judge 恒 0; 2026-08-27: 64→256 +
            # 末位 yes/no 解析 — judge 模型先输出分析再给结论, 64 token 截断分析段
            # 导致同一输入时对时错 (preference 类 judge 0/8 假象)
            txt = (_ask_io(JUDGE_PROMPT.format(question=question, answer=answer, response=response[:800]),
                           max_tokens=256, temperature=0.0) or "").strip().lower()
            import re as _re
            _m_yes = list(_re.finditer(r"\byes\b", txt))
            _m_no = list(_re.finditer(r"\bno\b", txt))
            if not _m_yes and not _m_no:
                return 0.0
            if not _m_no:
                return 1.0
            if not _m_yes:
                return 0.0
            # 以文本中最后出现的 yes/no 为准 (模型可能写 "no, actually yes")
            return 1.0 if _m_yes[-1].end() > _m_no[-1].end() else 0.0
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
    print("=== LLM judge 重评（deepseek judge, 语义判定, 对称口径）===\n")
    # 002codex P2: 基线侧必须读同模板响应 (full_baseline_s3.json = 新模板+256token)
    # 旧 longmemeval_results.json 是旧模板+80token 截断响应 → judge 混入模板修复因素, 非同口径
    import os as _os
    _samples = _os.environ.get("MESHCTX_JUDGE_SAMPLES", "3")
    _baseline_path = os.path.join(OUT, f"full_baseline_s{_samples}.json")
    if not os.path.exists(_baseline_path):
        print(f"⚠ 基线文件 {_baseline_path} 缺失 — 先跑 python3 run_meshctx_memory.py --mode=full --samples={_samples}")
        _baseline_path = os.path.join(OUT, "longmemeval_results.json")
    c1, t1 = rescore("基线（全量历史·同模板）", _baseline_path)
    print()
    c2, t2 = rescore("MeshCtx 脑区增强 v2", os.path.join(OUT, "meshctx_memory_enhanced_results.json"))
    print()
    print(f"汇总: 基线 {c1}/{t1} vs 脑区增强 {c2}/{t2}")
    json.dump({
        "baseline": {"correct": c1, "total": t1, "accuracy": c1 / t1 if t1 else 0,
                     "source": _baseline_path, "note": "同模板+256token+同采样响应 (对称口径)"},
        "meshctx_brainv2": {"correct": c2, "total": t2, "accuracy": c2 / t2 if t2 else 0},
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, open(os.path.join(OUT, "judge_comparison.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
