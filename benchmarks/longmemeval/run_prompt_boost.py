#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词增强实验 — chat 全量历史 + 逐字引述指令（EM 是子串匹配）

证据链：oracle 47.9% / reasoner 50.0% / chat 52.1% → 检索与换模型均无增益，
瓶颈在模型+提示词层。本实验验证：要求模型「逐字引述原文短语」能否提升 EM（公平的产品优化，不改测试集）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_meshctx_memory import (
    DATA, OUT, MODEL, N_PER_TYPE, flatten_sessions, best_subspan_em, ask,
)

BOOST_TEMPLATE = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\n"
    "Answer by QUOTING VERBATIM the exact sentence/phrase from the history that contains the answer. "
    "Copy the original wording exactly (do not paraphrase, reword, or explain). "
    "If the answer is a single fact (number, name, time, color), copy it exactly as it appears.\n"
    "Answer:"
)


def build_full(msgs):
    parts = [f"### Session {si + 1}:\nSession Content:\n{json.dumps(m, ensure_ascii=False)}"
             for si, role, m in msgs]
    return "\n\n".join(parts)


def main():
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    samples = [e for t, s in by_type.items() for e in s[:N_PER_TYPE]]

    print(f"== 提示词增强（{MODEL} 全量历史 + 逐字引述，{len(samples)} 样本）==\n", flush=True)
    correct = total = 0
    details = []
    for e in samples:
        msgs = flatten_sessions(e)
        if not msgs:
            continue
        hist = build_full(msgs)
        prompt = BOOST_TEMPLATE.format(hist, e["question_date"], e["question"])
        ans = ask(prompt)
        em = best_subspan_em(ans, e["answer"])
        correct += em
        total += 1
        details.append({"qid": e["question_id"], "question": e["question"], "answer": e["answer"],
                        "response": ans[:300], "em": em, "mode": "full+quote"})
        print(f"  [full+quote] {e['question'][:40]}... EM={em}", flush=True)

    acc = correct / total if total else 0
    result = {
        "model": MODEL,
        "benchmark": "LongMemEval-oracle 提示词增强（逐字引述）",
        "n_per_type": N_PER_TYPE,
        "prompt_boost": {"correct": correct, "total": total, "accuracy": acc},
        "compare": {"full_baseline_48q": 0.5208, "oracle_upper_48q": 0.4792,
                    "reasoner_48q": 0.5000},
        "note": "要求逐字引述原文（EM 子串匹配；公平产品优化，不改测试集）",
        "samples": details,
    }
    out = os.path.join(OUT, "prompt_boost_results.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n== 提示词增强: {correct}/{total} = {acc:.1%}（对照 全量 52.1% / oracle 47.9% / reasoner 50.0%）==", flush=True)
    print(f"结果已归档: {out}", flush=True)


if __name__ == "__main__":
    main()
