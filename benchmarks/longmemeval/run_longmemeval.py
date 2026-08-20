#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LongMemEval 基准 runner — 长对话记忆（多会话 + 长上下文）

标准: Wu et al. 2024 "LongMemEval" (ICLR 2025)
数据: xiaowu0162/LongMemEval oracle 500 样本（5 类能力）
模式: oracle = 全部会话历史进 prompt（测长上下文记忆）
评分: SQuAD 归一化子串匹配（与 lost-in-the-middle 一致口径）
模型: deepseek-chat
"""
import json
import os
import re
import string
import time


DATA = "/home/administrator/benchmarks-ext/LongMemEval/data/longmemeval_oracle.json"
OUT = "/home/administrator/benchmarks-ext/results"
MODEL = "deepseek-chat"
N_PER_TYPE = 8  # 每类取前 N 问

from model_io import ask as _ask_io, resolve_model_id as _resolve_mid
MODEL = _resolve_mid()  # 模型无关：MODEL_ID 切换任意主流模型（见 model_io.py）

ANSWER_TEMPLATE = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:"
)


def format_history(entry):
    parts = []
    for i, session in enumerate(entry["haystack_sessions"]):
        date = entry["haystack_dates"][i] if i < len(entry["haystack_dates"]) else ""
        content = json.dumps(session, ensure_ascii=False)
        parts.append(f"### Session {i+1}:\nSession Date: {date}\nSession Content:\n{content}")
    return "\n\n".join(parts)


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
    for gt in ground_truths if isinstance(ground_truths, list) else [ground_truths]:
        if normalize_answer(str(gt)) in npred:
            return 1.0
    return 0.0


def ask(prompt, max_tokens=80):
    """统一模型调用（模型无关：MODEL_ID 切换任意主流模型，见 model_io.py）"""
    return _ask_io(prompt, max_tokens=max_tokens, temperature=0.0)

def run():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)

    results = {"model": MODEL, "benchmark": "LongMemEval-oracle", "n_per_type": N_PER_TYPE, "per_type": {}, "samples": []}
    total_c, total_n = 0, 0
    for qtype, samples in by_type.items():
        sub = samples[:N_PER_TYPE]
        correct = 0
        for s in sub:
            prompt = ANSWER_TEMPLATE.format(format_history(s), s["question_date"], s["question"])
            ans = ask(prompt)
            em = best_subspan_em(ans, s["answer"])
            correct += em
            total_c += em
            total_n += 1
            print(f"  [{qtype}] {s['question'][:45]}... EM={em} ans={ans[:40]!r}", flush=True)
            results["samples"].append({
                "question_id": s["question_id"], "question": s["question"],
                "answer": s["answer"], "response": ans[:500], "em": em,
            })
        acc = correct / len(sub)
        results["per_type"][qtype] = {"correct": correct, "total": len(sub), "accuracy": acc}
        print(f"== {qtype}: {correct}/{len(sub)} = {acc:.2f}", flush=True)

    results["overall"] = {"correct": total_c, "total": total_n, "accuracy": total_c / total_n if total_n else 0}
    out = os.path.join(OUT, "longmemeval_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("保存:", out)


if __name__ == "__main__":
    run()
