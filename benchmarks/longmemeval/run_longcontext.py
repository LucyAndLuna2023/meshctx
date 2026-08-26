#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长上下文压力测试 — 展示 17脑区增强在超长上下文下的优势

论文依据: lost-in-the-middle 显示上下文越长/干扰越多, 全量基线准确率衰减。
本实验把 LongMemEval 历史加长(插入干扰 session 到中段)到 ~60KB,
对比: 基线全量 vs MeshCtx 脑区增强(记忆要点前置, 保持时序) vs 脑区精选(截断)。

预期: 超长上下文下基线衰减, 脑区增强(记忆要点前置 + 全量)更稳定。
"""
import json
import os
import random
import re
import string
import time


from run_meshctx_memory import flatten_sessions, build_history, normalize_answer, best_subspan_em, calc_salience

import os as _os
_BENCH_EXT = _os.environ.get("MESHCTX_BENCH_EXT") or _os.path.expanduser("~/benchmarks-ext")
DATA = _os.path.join(_BENCH_EXT, "LongMemEval/data/longmemeval_oracle.json")
OUT = _os.path.join(_BENCH_EXT, "results")

from model_io import ask as _ask_io, resolve_model_id as _resolve_mid
MODEL = _resolve_mid()  # 模型无关：MODEL_ID 切换任意主流模型（见 model_io.py）

ANSWER_TEMPLATE = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:"
)

# 干扰文本池（与问题无关的随机英文段落）
WORDS = ["apple", "bicycle", "cloud", "dolphin", "elevator", "forest", "guitar", "harbor",
         "island", "jungle", "kettle", "lantern", "mountain", "notebook", "ocean", "pencil",
         "quartz", "river", "sunflower", "telescope", "umbrella", "volcano", "window", "yacht"]


def make_noise(n_chars=8000):
    random.seed(42)
    parts = []
    while sum(len(p) for p in parts) < n_chars:
        n = random.randint(8, 20)
        parts.append(" ".join(random.choice(WORDS) for _ in range(n)))
    return ". ".join(parts)[:n_chars] + "."


def inflate_history(msgs, noise_kb=16):
    """把干扰 session 插入历史中段，制造超长上下文"""
    noise = make_noise(noise_kb * 1000)
    noise_msgs = [(999, "assistant", noise[:4000]), (999, "user", noise[4000:8000]),
                  (999, "assistant", noise[8000:12000]), (999, "user", noise[12000:16000])]
    mid = len(msgs) // 2
    return msgs[:mid] + noise_msgs + msgs[mid:]


def ask(prompt, max_tokens=80):
    """统一模型调用（模型无关：MODEL_ID 切换任意主流模型，见 model_io.py）"""
    return _ask_io(prompt, max_tokens=max_tokens, temperature=0.0)

def main():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    # 每类前 2 = 12 样本
    samples = [e for s in by_type.values() for e in s[:2]]
    print(f"长上下文压力测试: {len(samples)} 样本, 干扰 ~16KB 插入中段\n", flush=True)

    results = {"modes": {}}
    for mode in ["full", "brainv2", "brain"]:
        correct, total = 0, 0
        print(f"== 模式: {mode} ==", flush=True)
        for e in samples:
            msgs = flatten_sessions(e)
            long_msgs = inflate_history(msgs)
            hist = build_history(long_msgs, mode=mode, top_k=12, gate_openness=0.8, question=e["question"])
            prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
            ans = ask(prompt)
            em = best_subspan_em(ans, e["answer"])
            correct += em
            total += 1
            print(f"  [{mode}] {e['question'][:38]}... EM={em} hist_len={len(hist)//1000}KB", flush=True)
        acc = correct / total if total else 0
        results["modes"][mode] = {"correct": correct, "total": total, "accuracy": acc}
        print(f"== {mode}: {correct}/{total} = {acc:.1%}\n", flush=True)

    # judge 重评
    from run_judge import judge
    print("== judge 语义重评 ==", flush=True)
    for mode in ["full", "brainv2", "brain"]:
        correct, total = 0, 0
        for e in samples:
            msgs = flatten_sessions(e)
            long_msgs = inflate_history(msgs)
            hist = build_history(long_msgs, mode=mode, top_k=12, gate_openness=0.8, question=e["question"])
            prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
            ans = ask(prompt)
            v = judge(e["question"], e["answer"], ans)
            correct += v
            total += 1
        results["modes"][mode]["judge_accuracy"] = correct / total if total else 0
        print(f"  {mode} judge: {correct}/{total} = {correct/total:.1%}", flush=True)

    out = os.path.join(OUT, "longcontext_pressure_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n保存:", out)


if __name__ == "__main__":
    main()
