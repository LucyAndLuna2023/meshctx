#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEPA 非生成式预筛 v2 — 大池检索验证（模拟真实记忆库）

场景：记忆库 30+ 条 session，query 来了不开 LLM，用 JEPA 潜空间余弦捞相关记忆。
对每个问题：池 = 答案 session（正例，取 answer_session_ids[0]）+ 29 个随机干扰 session。
指标：recall@1 / recall@5 / mrr（随机基线 ≈ 1/30）。

对比 v1（候选池 avg 1.9 区分度弱）——v2 用 30 条大池，真实考验非生成式预筛。
"""
import json
import os as _os
import random
import sys
import time

import numpy as np

# 跨平台: MESHCTX_BENCH_EXT 环境变量覆盖, 默认 ~/benchmarks-ext (与 LongMemEval runner 一致)
_BENCH_EXT = _os.environ.get("MESHCTX_BENCH_EXT") or _os.path.expanduser("~/benchmarks-ext")
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # benchmarks/jepa/ → 仓库根

sys.path.insert(0, _ROOT)
sys.path.insert(0, _os.path.join(_ROOT, "src"))

from src.core.jepa_world_model import get_non_generative_router

DATA = _os.path.join(_BENCH_EXT, "LongMemEval/data/longmemeval_oracle.json")
OUT = _os.path.join(_BENCH_EXT, "results/jepa_pool_validation_results.json")

POOL_SIZE = 30


def msgs_to_text(msgs) -> str:
    return "\n".join(
        m.get("content", "")
        for m in msgs
        if isinstance(m, dict) and isinstance(m.get("content"), str) and m.get("content").strip()
    )[:2000]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    random.seed(42)
    router = get_non_generative_router()
    data = json.load(open(DATA, encoding="utf-8"))

    # 预计算所有 session 文本（复用池）
    all_sessions = []  # (q_idx, session_id, text)
    for q in data:
        ids = q.get("haystack_session_ids", [])
        for si, msgs in enumerate(q.get("haystack_sessions", [])):
            sid = ids[si] if si < len(ids) else f"idx{si}"
            t = msgs_to_text(msgs)
            if t.strip():
                all_sessions.append((sid, t))

    ranks = []
    for qi, q in enumerate(data[:n]):
        question = q.get("question", "")
        answer_ids = set(q.get("answer_session_ids", []))
        if not answer_ids:
            continue
        # 正例：第一个答案 session
        pos_sid = sorted(answer_ids)[0]
        pos_text = next((t for sid, t in all_sessions if sid == pos_sid), None)
        if not pos_text:
            continue
        # 负例：29 个随机其他 session
        others = [(sid, t) for sid, t in all_sessions if sid != pos_sid]
        negs = random.sample(others, min(POOL_SIZE - 1, len(others)))

        q_vec = np.asarray(router.embed_state(question), dtype=np.float64)
        scored = []
        for sid, t in [("__answer__", pos_text)] + [(f"neg{i}", t) for i, (_, t) in enumerate(negs)]:
            d_vec = np.asarray(router.embed_state(t), dtype=np.float64)
            cos = float(np.dot(q_vec, d_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(d_vec) + 1e-8))
            scored.append((sid, cos))
        scored.sort(key=lambda x: x[1], reverse=True)
        rank = next(i for i, (sid, _) in enumerate(scored) if sid == "__answer__")
        ranks.append(rank)

    nq = len(ranks)
    recall_1 = sum(1 for r in ranks if r == 0) / nq
    recall_5 = sum(1 for r in ranks if r < 5) / nq
    mrr = sum(1.0 / (r + 1) for r in ranks) / nq

    results = {
        "n_samples": nq,
        "pool_size": POOL_SIZE,
        "jepa_pool_recall@1": round(recall_1, 4),
        "jepa_pool_recall@5": round(recall_5, 4),
        "jepa_pool_mrr": round(mrr, 4),
        "random_baseline_recall@1": round(1.0 / POOL_SIZE, 4),
        "note": "30条大池（1正+29干扰），不开 LLM 潜空间余弦捞答案 session",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("归档:", OUT)


if __name__ == "__main__":
    main()
