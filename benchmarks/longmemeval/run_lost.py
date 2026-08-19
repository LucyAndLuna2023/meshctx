#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lost-in-the-middle 基准 runner — 上下文冗长/关键信息位置 对回答准确率的影响

标准: Liu et al. 2023 "Lost in the Middle" (TACL)
数据: nelson-liu/lost-in-the-middle 官方 qa_data
评分: SQuAD 归一化 best_subspan_em（官方 metrics.py）
模型: deepseek-chat (OpenAI 兼容 API)
"""
import gzip
import json
import os
import re
import string
import sys
import time

import openai

# ── 配置 ──
DATA = "/home/administrator/benchmarks-ext/lost-in-the-middle-main/qa_data"
OUT = "/home/administrator/benchmarks-ext/results"
MODEL = "deepseek-chat"
N_PER_FILE = 15  # 每文件取前 N 问（控制成本）

# 读取 API key
key = None
for p in ["/home/administrator/.meshctx/.env"]:
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith("DEEPSEEK_API_KEY="):
                key = ln.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if key:
        break
assert key, "DEEPSEEK_API_KEY 未找到"

client = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")

PROMPT_TEMPLATE = (
    "Write a high-quality answer for the given question using only the provided "
    "search results (some of which might be irrelevant).\n\n"
    "{search_results}\n\nQuestion: {question}\nAnswer:"
)


def normalize_answer(s: str) -> str:
    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text):
        return " ".join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)

    return white_space_fix(remove_articles(remove_punc(s.lower())))


def best_subspan_em(prediction: str, ground_truths) -> float:
    npred = normalize_answer(prediction)
    for gt in ground_truths:
        if normalize_answer(gt) in npred:
            return 1.0
    return 0.0


def build_search_results(ctxs):
    parts = []
    for i, ctx in enumerate(ctxs):
        parts.append(f"Document [{i+1}](Title: {ctx['title']}) {ctx['text']}")
    return "\n".join(parts)


def ask(prompt, max_tokens=64):
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            print(f"  [retry {attempt+1}] {e}", flush=True)
            time.sleep(3)
    return ""


def load_samples(n_docs, pos):
    """pos: begin/middle/end — 官方文件位置分位数（10→0/4/9, 20→0/9/19, 30→0/14/29）"""
    mid = {10: 4, 20: 9, 30: 14}[n_docs]
    end = {10: 9, 20: 19, 30: 29}[n_docs]
    pos_idx = {"begin": 0, "middle": mid, "end": end}[pos]
    fn = f"nq-open-{n_docs}_total_documents_gold_at_{pos_idx}.jsonl.gz"
    samples = []
    with gzip.open(os.path.join(DATA, f"{n_docs}_total_documents", fn), "rt") as f:
        for i, ln in enumerate(f):
            if i >= N_PER_FILE:
                break
            samples.append(json.loads(ln))
    return samples


def run():
    os.makedirs(OUT, exist_ok=True)
    results = {"model": MODEL, "benchmark": "lost-in-the-middle", "n_per_file": N_PER_FILE, "position_results": {}}
    # 长度 × 位置 矩阵
    for n_docs in [10, 20, 30]:
        for pos_name in ["begin", "middle", "end"]:
            samples = load_samples(n_docs, pos_name)
            correct = 0
            for s in samples:
                prompt = PROMPT_TEMPLATE.format(
                    search_results=build_search_results(s["ctxs"]),
                    question=s["question"],
                )
                ans = ask(prompt)
                em = best_subspan_em(ans, s["answers"])
                correct += em
                print(f"  [{n_docs}docs/{pos_name}] {s['question'][:40]}... EM={em} ans={ans[:40]!r}", flush=True)
            acc = correct / len(samples) if samples else 0
            results["position_results"][f"{n_docs}_{pos_name}"] = {"correct": correct, "total": len(samples), "accuracy": acc}
            print(f"== {n_docs} docs, pos={pos_name}: {correct}/{len(samples)} = {acc:.2f}", flush=True)
    out = os.path.join(OUT, "lost_in_the_middle_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("保存:", out)


if __name__ == "__main__":
    run()
