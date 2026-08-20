#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle 检索上限分析 — 只注入答案所在 session（answer_session_ids）

回答 60%+ 路径问题：「如果检索器完美，EM 上限是多少？」
- oracle 注入：仅 answer_session_ids 对应会话（完美检索，测试集标注仅用于上限分析）
- 对照：全量基线 52.1%（48Q）· P2 注入 50.0%（48Q）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_meshctx_memory import (
    DATA, OUT, MODEL, N_PER_TYPE, ANSWER_TEMPLATE,
    flatten_sessions, best_subspan_em, ask,
)

def build_oracle(msgs, session_ids, oracle_ids):
    """只注入 answer_session_ids 对应会话。

    msgs 的 si 是 haystack_sessions 的 enumerate 索引，与 haystack_session_ids 同序；
    oracle_ids 是 session id 字符串集合。
    """
    ans = {str(x) for x in (oracle_ids or [])}
    if ans and session_ids:
        sub = [(si, role, c) for si, role, c in msgs
               if si < len(session_ids) and str(session_ids[si]) in ans]
    else:
        sub = msgs
    parts = [f"### Session {si + 1}:\nSession Content:\n{json.dumps(m, ensure_ascii=False)}"
             for si, role, m in sub]
    return "\n\n".join(parts)

def main():
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    samples = [e for t, s in by_type.items() for e in s[:N_PER_TYPE]]

    print(f"== oracle 检索上限（{MODEL}，只注入答案 session，{len(samples)} 样本）==\n", flush=True)
    correct = total = 0
    details = []
    for e in samples:
        msgs = flatten_sessions(e)
        if not msgs:
            continue
        hist = build_oracle(msgs, e.get("haystack_session_ids"), e.get("answer_session_ids"))
        prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
        ans = ask(prompt)
        em = best_subspan_em(ans, e["answer"])
        correct += em
        total += 1
        details.append({"qid": e["question_id"], "question": e["question"], "answer": e["answer"],
                        "response": ans[:300], "em": em, "mode": "oracle"})
        print(f"  [oracle] {e['question'][:40]}... EM={em}", flush=True)

    acc = correct / total if total else 0
    result = {
        "model": MODEL,
        "benchmark": "LongMemEval-oracle 检索上限分析",
        "n_per_type": N_PER_TYPE,
        "oracle_injection": {"correct": correct, "total": total, "accuracy": acc},
        "compare": {"full_baseline_48q": 0.5208, "p2_injection_48q": 0.5000},
        "note": "oracle 仅注入答案所在 session（测试集标注，仅上限分析用，不可在生产使用）",
        "samples": details,
    }
    out = os.path.join(OUT, "oracle_upper_bound_results.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n== oracle 上限: {correct}/{total} = {acc:.1%}（对照: 全量 52.1% / P2 注入 50.0%）==", flush=True)
    print(f"结果已归档: {out}", flush=True)

if __name__ == "__main__":
    main()
