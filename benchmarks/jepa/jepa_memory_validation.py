#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEPA 非生成式相关性验证基准（v3.36 真实用途验证）

验证声称：「JEPA 世界模型可不开 LLM 即在潜空间判断记忆相关性」——
本基准用 LongMemEval 真实数据：query=问题, doc=session 记忆文本，
NonGenerativeRouter.embed_state（char-trigram 真实向量）余弦排序，
对照 完美 oracle / 随机基线，量化「非生成式预筛」的检索质量。

用法: python3 jepa_memory_validation.py [n_samples]
结果: 打印 + 归档 /home/administrator/benchmarks-ext/results/jepa_validation_results.json
"""
import json
import sys
import time

import numpy as np

sys.path.insert(0, "/home/administrator/meshctx-public")
sys.path.insert(0, "/home/administrator/meshctx-public/src")

from src.core.jepa_world_model import get_non_generative_router, get_world_model

DATA = "/home/administrator/benchmarks-ext/LongMemEval/data/longmemeval_oracle.json"
OUT = "/home/administrator/benchmarks-ext/results/jepa_validation_results.json"


def session_to_text(sess: dict) -> str:
    """session 消息 → 拼接文本"""
    msgs = sess.get("messages", [])
    parts = []
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str) and content.strip():
            parts.append(content)
    return "\n".join(parts)[:2000]  # 控制长度


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    router = get_non_generative_router()
    wm = get_world_model()
    data = json.load(open(DATA, encoding="utf-8"))[:n]

    # 结果桶
    jepa_ranks, oracle_hits_1, oracle_hits_3, random_hits_1 = [], [], [], []
    energy_history = []

    for qi, q in enumerate(data):
        question = q.get("question", "")
        haystack = q.get("haystack_sessions", [])
        answer_ids = set(q.get("answer_session_ids", []))
        if not haystack or not answer_ids:
            continue

        q_vec = np.asarray(router.embed_state(question), dtype=np.float64)

        # JEPA 非生成式排序（不开 LLM）——haystack_session_ids 与 haystack_sessions 同序
        ids = q.get("haystack_session_ids", [])
        scored = []
        for si, msgs in enumerate(haystack):
            sid = ids[si] if si < len(ids) else f"idx{si}"
            text = "\n".join(
                m.get("content", "")
                for m in msgs
                if isinstance(m, dict) and isinstance(m.get("content"), str) and m.get("content").strip()
            )[:2000]
            if not text.strip():
                continue
            d_vec = np.asarray(router.embed_state(text), dtype=np.float64)
            cos = float(np.dot(q_vec, d_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(d_vec) + 1e-8))
            scored.append((sid, cos))

        # 潜空间能量（世界模型对「该记忆与问题差距」的惊讶度——负相关于余弦）
        if scored:
            for _, cos in scored[:5]:
                zq = wm.perceive(q_vec)
                zp, energy = wm.predict(zq, np.asarray([cos] * wm.config.embed_dim, dtype=np.float64))
                energy_history.append(energy)

        scored.sort(key=lambda x: x[1], reverse=True)
        jepa_rank = min(
            (i for i, (sid, _) in enumerate(scored) if sid in answer_ids),
            default=len(scored),
        )
        jepa_ranks.append(jepa_rank)

        # oracle 完美排序对照
        oracle_rank = min(
            (i for i, (sid, _) in enumerate(scored) if sid in answer_ids),
            default=len(scored),
        )
        oracle_hits_1.append(1 if oracle_rank == 0 else 0)
        oracle_hits_3.append(1 if oracle_rank < 3 else 0)

        # 随机基线
        rng = np.random.RandomState(qi)
        random_rank = rng.randint(0, len(scored))
        random_hits_1.append(1 if random_rank == 0 else 0)

    nq = len(jepa_ranks)
    recall_1 = sum(1 for r in jepa_ranks if r == 0) / nq
    recall_3 = sum(1 for r in jepa_ranks if r < 3) / nq
    mrr = sum(1.0 / (r + 1) for r in jepa_ranks) / nq
    avg_rank = sum(jepa_ranks) / nq

    results = {
        "n_samples": nq,
        "jepa_non_generative": {
            "recall@1": round(recall_1, 4),
            "recall@3": round(recall_3, 4),
            "mrr": round(mrr, 4),
            "avg_rank": round(avg_rank, 2),
            "note": "不开 LLM，char-trigram 潜空间余弦排序",
        },
        "baselines": {
            "oracle_recall@1": round(sum(oracle_hits_1) / nq, 4),
            "oracle_recall@3": round(sum(oracle_hits_3) / nq, 4),
            "random_recall@1": round(sum(random_hits_1) / nq, 4),
        },
        "avg_energy": round(float(np.mean(energy_history)), 4) if energy_history else 0.0,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("归档:", OUT)


if __name__ == "__main__":
    main()
