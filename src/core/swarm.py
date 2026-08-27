#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Swarm 群审 — 5 模型并行 + 共识投票 (BP Team 版功能, 2026-08-27)

BP 定价矩阵: Team 版含 "Swarm 群审模式: 5 模型并行 + 共识投票 (含 API 费用)"。
实现: 从模型注册表选 N 个可用模型并行回答同一问题,
共识策略: majority(文本相似度投票) / judge(独立模型判定最优) / score(置信度加权)。
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.swarm")

DEFAULT_MODELS = ["deepseek:chat", "deepseek:reasoner", "openai:gpt-4o",
                  "anthropic:claude-sonnet", "google:gemini-pro"]
DEFAULT_TIMEOUT = 90


def _get_client(model_id: str):
    """从 model_registry 取客户端。"""
    try:
        from src.model_registry import get_registry
        reg = get_registry()
        return reg.get(model_id)
    except Exception as e:
        logger.warning(f"swarm 取客户端失败 {model_id}: {e}")
        return None


def _ask_model(model_id: str, question: str, system: str = "") -> Dict[str, Any]:
    """单模型回答。返回 {model, answer, ok, error}。"""
    try:
        client = _get_client(model_id)
        if client is None:
            return {"model": model_id, "answer": "", "ok": False, "error": "模型不可用"}
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": question})
        resp = client.chat(msgs, temperature=0.2, max_tokens=512)
        content = (resp or {}).get("content") or ""
        return {"model": model_id, "answer": content.strip(), "ok": bool(content.strip()),
                "error": ""}
    except Exception as e:
        return {"model": model_id, "answer": "", "ok": False, "error": str(e)}


def _normalize(text: str) -> str:
    """答案归一化 (投票相似度用)。"""
    import re
    return re.sub(r"\s+", " ", (text or "")).strip().lower()[:200]


def _consensus_majority(answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """多数投票: 按归一化答案聚类, 选出现最多的簇代表。"""
    from collections import defaultdict
    clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in answers:
        if not a.get("ok"):
            continue
        clusters[_normalize(a["answer"])].append(a)
    if not clusters:
        return {"strategy": "majority", "consensus": "", "votes": 0, "total": len(answers)}
    best = max(clusters.items(), key=lambda kv: len(kv[1]))
    return {"strategy": "majority", "consensus": best[1][0]["answer"],
            "votes": len(best[1]), "total": len(answers),
            "cluster_size": len(best[1])}


def _consensus_judge(answers: List[Dict[str, Any]], question: str) -> Dict[str, Any]:
    """独立 judge 模型从群审答案中选最优。"""
    ok = [a for a in answers if a.get("ok")]
    if not ok:
        return {"strategy": "judge", "consensus": "", "votes": 0, "total": len(answers)}
    numbered = "\n".join(f"[{i+1}] {a['answer'][:400]}" for i, a in enumerate(ok))
    judge_q = (f"以下是多个模型对同一问题的回答。选出一个最准确、最完整的作为最终答案。"
               f"只输出所选编号。\n\n问题: {question}\n\n{numbered}\n\n最佳答案编号:")
    judge = _ask_model(DEFAULT_MODELS[0], judge_q, system="你是群审仲裁者，只输出数字。")
    try:
        idx = int(''.join(c for c in judge.get("answer", "") if c.isdigit())[:1]) - 1
        if 0 <= idx < len(ok):
            return {"strategy": "judge", "consensus": ok[idx]["answer"],
                    "chosen": ok[idx]["model"], "votes": 1, "total": len(answers)}
    except (ValueError, IndexError):
        pass
    # 回退: 多数投票
    return _consensus_majority(answers)


def swarm_ask(question: str, models: Optional[List[str]] = None, top_k: int = 5,
              strategy: str = "majority", system: str = "",
              timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Swarm 群审: N 模型并行回答 + 共识。

    Args:
        question: 用户问题
        models: 模型列表 (默认 5 个跨厂商模型)
        top_k: 并行模型数
        strategy: majority(多数投票) / judge(独立仲裁)
        system: 可选 system prompt
        timeout: 总超时秒
    Returns:
        {question, models, strategy, consensus, answers, took_ms, ok}
    """
    pool = models or DEFAULT_MODELS
    pool = pool[:top_k]
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pool)) as ex:
        futures = {ex.submit(_ask_model, m, question, system): m for m in pool}
        answers = []
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=timeout):
                answers.append(fut.result())
        except concurrent.futures.TimeoutError:
            for fut in futures:
                fut.cancel()
            logger.warning("swarm 超时")
        answers = [a for a in answers]  # 保留已完成的

    ok_count = sum(1 for a in answers if a.get("ok"))
    if strategy == "judge":
        consensus = _consensus_judge(answers, question)
    else:
        consensus = _consensus_majority(answers)

    return {
        "question": question,
        "models": [a["model"] for a in answers],
        "strategy": strategy,
        "consensus": consensus.get("consensus", ""),
        "votes": consensus.get("votes", 0),
        "total_ok": ok_count,
        "answers": answers,
        "took_ms": int((time.time() - started) * 1000),
        "ok": ok_count > 0,
    }


def swarm_stats() -> Dict[str, Any]:
    """群审可用模型检查。"""
    usable = []
    for m in DEFAULT_MODELS:
        c = _get_client(m)
        if c is not None:
            usable.append(m)
    return {"configured": DEFAULT_MODELS, "usable": usable,
            "count": len(usable), "strategy": ["majority", "judge"]}
