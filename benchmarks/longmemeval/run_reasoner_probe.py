#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型升级探针 — deepseek-reasoner vs deepseek-chat（全量历史模式，小样本）

背景：oracle 检索上限 47.9% < 全量 52.1% → 检索非瓶颈，模型能力才是。
本探针验证模型升级（reasoner）是否带来 EM 增益（60%+ 路径第二步）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_meshctx_memory import (
    DATA, OUT, MODEL, N_PER_TYPE, ANSWER_TEMPLATE,
    flatten_sessions, best_subspan_em,
)

import openai

env_path = "/home/administrator/.meshctx/.env"
key = None
if os.path.exists(env_path):
    for ln in open(env_path, encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("DEEPSEEK_API_KEY="):
            key = ln.split("=", 1)[1].strip().strip('"').strip("'")
            break
assert key, "DEEPSEEK_API_KEY 未找到"
client = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")

PROBE_MODEL = "deepseek-reasoner"  # 探针模型
MAX_TOKENS = 500  # reasoner 最终输出上限（thinking 独立计）


def ask_r(prompt, max_tokens=MAX_TOKENS):
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=PROBE_MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            print(f"  [retry{attempt}] {str(e)[:120]}", flush=True)
            time.sleep(3)
    return ""


def build_full(msgs):
    parts = [f"### Session {si + 1}:\nSession Content:\n{json.dumps(m, ensure_ascii=False)}"
             for si, role, m in msgs]
    return "\n\n".join(parts)


def main():
    per_type = int(os.environ.get("PROBE_PER_TYPE", "1"))
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    samples = [e for t, s in by_type.items() for e in s[:per_type]]
    print(f"== 模型升级探针: {PROBE_MODEL}（全量历史，每类{per_type}个，共 {len(samples)} 样本）==\n", flush=True)

    correct = total = 0
    details = []
    for e in samples:
        msgs = flatten_sessions(e)
        if not msgs:
            continue
        hist = build_full(msgs)
        prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
        ans = ask_r(prompt)
        em = best_subspan_em(ans, e["answer"])
        correct += em
        total += 1
        details.append({"qid": e["question_id"], "question": e["question"], "answer": e["answer"],
                        "response": ans[:300], "em": em, "model": PROBE_MODEL, "mode": "full"})
        print(f"  [{PROBE_MODEL}/full] {e['question'][:40]}... EM={em}", flush=True)

    acc = correct / total if total else 0
    result = {
        "model": PROBE_MODEL,
        "compare_model": MODEL,
        "mode": "full_history",
        "per_type": per_type,
        "probe": {"correct": correct, "total": total, "accuracy": acc},
        "reference": {"chat_full_baseline_48q": 0.5208, "chat_oracle_upper_48q": 0.4792},
        "samples": details,
    }
    out = os.path.join(OUT, "reasoner_probe_results.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n== 探针结果: {correct}/{total} = {acc:.1%}（对照 chat 全量 52.1%）==", flush=True)
    print(f"结果已归档: {out}", flush=True)


if __name__ == "__main__":
    main()
