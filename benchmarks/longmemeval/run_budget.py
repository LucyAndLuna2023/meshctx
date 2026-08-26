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

BUDGET = 16 * 1000  # 16KB


def ask(prompt, max_tokens=80):
    """统一模型调用（模型无关：MODEL_ID 切换任意主流模型，见 model_io.py）"""
    return _ask_io(prompt, max_tokens=max_tokens, temperature=0.0)


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


def p2_budget(msgs, question):
    """P2 检索注入: 10底FSRS×T3相关性×M1分类 排序后累积到 BUDGET

    P2 优化管线（004 P2-1~P2-4）在预算场景的对照：
    - _memory_item_score 同口径（10底 + per-item stability）
    - T3 相关性（question 词命中）优先
    - M1 分类（preference/decision→core 加成, fact→semantic）
    """
    from run_meshctx_memory import p2_item_score, calc_salience
    tagger_import = __import__("src.core.super_brain", fromlist=["SalienceTagger"])
    SalienceTagger = tagger_import.SalienceTagger
    try:
        from src.core.memory_hierarchy import classify_memory
    except Exception:
        def classify_memory(t):
            return "other"
    tagger = SalienceTagger()
    now = time.time()
    n = len(msgs)
    scored = []
    for i, (si, role, content) in enumerate(msgs):
        s = calc_salience(content, question, tagger)
        s_score = float(getattr(s, "score", s)) if not isinstance(s, (int, float)) else float(s)
        imp = min(1.0, 0.25 + s_score * 0.75)
        q = (question or "").lower()
        try:
            from src.chat_tools import _split_query_terms
        except Exception:
            def _split_query_terms(t):
                return [w for w in (t or "").lower().split() if len(w) >= 2]
        qterms = _split_query_terms(q)
        hay = content.lower()
        rel = sum(1 for w in qterms if w in hay) + (2 if q and q in hay else 0)
        cat = classify_memory(content)
        layer = "core" if cat in ("preference", "decision") else ("semantic" if cat == "fact" else "episodic")
        # 模拟 FSRS：importance 高→stability 高；会话越早→复习次数越多→更稳定
        stability = 24.0 + imp * 96.0 + (n - i) * 6.0
        created = now - (n - i) * 3600.0
        scored.append({"key": f"s{si}", "value": content, "importance": imp,
                       "last_reviewed": 0.0, "created_at": created, "stability": stability,
                       "schema_layer": layer, "_rel": rel, "_si": si, "_role": role})
    scored.sort(key=lambda r: (r["_rel"], p2_item_score(r)), reverse=True)
    parts, total = [], 0
    for r in scored:
        block = (f"### Session {r['_si'] + 1}:\nSession Content:\n"
                 f"{json.dumps({'role': r['_role'], 'content': r['value']}, ensure_ascii=False)}")
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
    for mode, builder in [("full_truncated", full_truncated), ("brain_budget", brain_budget),
                          ("p2_budget", p2_budget), ("full", None)]:
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
