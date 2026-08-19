#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Token 预算公平对比 — 展示 17脑区精选在同预算下的优势

场景: 超长上下文(59KB)下, 限定 16KB token 预算:
  A. 暴力截断: 保留历史前 16KB（朴素 RAG/上下文压缩）
  B. 脑区精选: SalienceTagger+ThalamicGate+HippocampalReplay 选高价值记忆到 16KB
  C. 全量参考: 59KB 全量（上限, 不计预算）

预期: 预算内 B > A（脑区精选知道"哪些记忆重要", 暴力截断不知道）
"""
import json
import os
import time

import openai

from run_meshctx_memory import flatten_sessions, build_history, best_subspan_em
from run_longcontext import inflate_history
from run_judge import judge

DATA = "/home/administrator/benchmarks-ext/LongMemEval/data/longmemeval_oracle.json"
OUT = "/home/administrator/benchmarks-ext/results"

key = None
if os.path.exists("/home/administrator/.meshctx/.env"):
    for ln in open("/home/administrator/.meshctx/.env", encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("DEEPSEEK_API_KEY="):
            key = ln.split("=", 1)[1].strip().strip('"').strip("'")
            break
assert key
client = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")

ANSWER_TEMPLATE = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:"
)

BUDGET = 16 * 1000  # 16KB


def ask(prompt, max_tokens=80):
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                          {"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=0.0,
            )
            return r.choices[0].message.content or ""
        except Exception:
            time.sleep(3)
    return ""


def full_truncated(msgs, question):
    """暴力截断: 保留前 BUDGET 字符（朴素基线）"""
    text = build_history(msgs, mode="full")
    return text[:BUDGET]


def brain_budget(msgs, question):
    """脑区精选: 按 salience 降序累积到 BUDGET"""
    tagger_import = __import__("src.core.super_brain", fromlist=["SalienceTagger", "ThalamicGate"])
    SalienceTagger, ThalamicGate = tagger_import.SalienceTagger, tagger_import.ThalamicGate
    from run_meshctx_memory import calc_salience
    tagger = SalienceTagger()
    gate = ThalamicGate()
    gate.gate_openness = 0.8
    scored = []
    for si, role, content in msgs:
        s = calc_salience(content, question, tagger)
        if gate.gate(s, 1.0 if role == "user" else 0.6):
            scored.append((s, si, role, content))
    scored.sort(key=lambda x: -x[0])
    parts, total = [], 0
    for s, si, role, content in scored:
        block = f"### Session {si+1}:\nSession Content:\n{json.dumps({'role': role, 'content': content}, ensure_ascii=False)}"
        if total + len(block) > BUDGET:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


def main():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    samples = [e for s in by_type.values() for e in s[:2]]
    print(f"Token 预算公平对比: {len(samples)} 样本, 预算 {BUDGET//1000}KB\n", flush=True)

    results = {}
    for mode, builder in [("full_truncated", full_truncated), ("brain_budget", brain_budget), ("full", None)]:
        em_c, j_c, total = 0, 0, 0
        print(f"== 模式: {mode} ==", flush=True)
        for e in samples:
            msgs = flatten_sessions(e)
            long_msgs = inflate_history(msgs)
            if builder:
                hist = builder(long_msgs, e["question"])
            else:
                hist = build_history(long_msgs, mode="full")
            prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
            ans = ask(prompt)
            em = best_subspan_em(ans, e["answer"])
            jv = judge(e["question"], e["answer"], ans)
            em_c += em
            j_c += jv
            total += 1
            print(f"  [{mode}] {e['question'][:35]}... EM={em} J={jv} len={len(hist)//1000}KB", flush=True)
        results[mode] = {"em": em_c / total, "judge": j_c / total, "correct": j_c, "total": total}
        print(f"== {mode}: EM={em_c/total:.1%} judge={j_c/total:.1%} (len≈{len(hist)//1000}KB)\n", flush=True)

    out = os.path.join(OUT, "token_budget_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("保存:", out)


if __name__ == "__main__":
    main()
