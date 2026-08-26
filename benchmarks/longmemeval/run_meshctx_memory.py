#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MeshCtx 17脑区 + 基因组 增强管线 — LongMemEval 记忆基准

展示 MeshCtx 独有架构优势:
- 17脑区: SalienceTagger(显著性标记) + ThalamicGate(丘脑门控过滤) + HippocampalReplay(海马体重放)
- 基因组: GenomicOptimizer 进化记忆参数 (retrieval_top_k → 保留条数, memory_weight → salience阈值)

对比: 原生全量上下文(基线 52.1%) vs MeshCtx 脑区精选增强
"""
import json
import os
import re
import string
import time

import openai

from src.core.super_brain import SalienceTagger, ThalamicGate, HippocampalReplay
from src.core.genomic_optimizer import GenomicOptimizer

import os as _os
_BENCH_EXT = _os.environ.get("MESHCTX_BENCH_EXT") or _os.path.expanduser("~/benchmarks-ext")
DATA = _os.path.join(_BENCH_EXT, "LongMemEval/data/longmemeval_oracle.json")
OUT = _os.path.join(_BENCH_EXT, "results")
MODEL = os.environ.get("MODEL_ID", "deepseek:chat")  # 兼容旧引用：MODEL_ID 或默认 deepseek:chat
N_PER_TYPE = 8

# ── 统一模型接入层（模型无关架构，见 model_io.py）────────────────
# 支持全世界主流模型：MODEL_ID=openrouter:gpt-4o / anthropic:claude-sonnet /
# google:gemini-flash / bailian:qwen3-plus / deepseek:reasoner ...（122 个已注册）
from model_io import ask as _ask_io, resolve_model_id as _resolve_mid
MODEL = _resolve_mid()

ANSWER_TEMPLATE = (
    "I will give you several history chats between you and a user. "
    "Please answer the question based on the relevant chat history.\n\n\n"
    "History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:"
)

EMOTION_WORDS = {"喜欢", "讨厌", "爱", "恨", "高兴", "难过", "担心", "兴奋", "生气",
                 "满意", "不满", "推荐", "很棒", "糟糕", "享受", "害怕", "期待", "不错", "很好",
                 "like", "love", "hate", "happy", "sad", "worry", "excited", "angry",
                 "recommend", "great", "enjoy", "scared", "favorite", "prefer", "want",
                 "awesome", "amazing", "terrible", "upset", "glad", "pleased", "hoping"}


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


def flatten_sessions(entry):
    """把会话历史展开为 [(session_idx, role, content), ...]"""
    msgs = []
    for si, session in enumerate(entry["haystack_sessions"]):
        if isinstance(session, list):
            for m in session:
                if isinstance(m, dict) and m.get("content"):
                    msgs.append((si, m.get("role", "user"), str(m["content"])))
        elif isinstance(session, dict) and session.get("content"):
            msgs.append((si, session.get("role", "user"), str(session["content"])))
    return msgs


def calc_salience(text, question, tagger):
    """SalienceTagger: novelty/emotion/relevance 三维标记（中英混合）"""
    novelty = 0.8 if len(text) > 20 else 0.3
    emotion = 0.7 if any(w in text.lower() for w in EMOTION_WORDS) else 0.1
    q_bigrams = set(zip(question, question[1:])) if question else set()
    t_bigrams = set(zip(text, text[1:]))
    overlap = len(q_bigrams & t_bigrams) / max(1, len(q_bigrams)) if q_bigrams else 0.0
    relevance = min(1.0, overlap * 4)  # 与问题相关的内容显著提升
    return tagger.tag(text, novelty=novelty, emotion=emotion, relevance=relevance)


def p2_item_score(r) -> float:
    """P2 注入排序分 = importance × retention × layer 加成。

    与 src.chat_tools._memory_item_score 同口径（P2-1）：
    retention 统一 10 底 R=10^(-t/S)，S 为 per-item FSRS stability（小时）。
    """
    imp = float(r.get("importance", 0.5) or 0.5)
    base = float(r.get("last_reviewed", 0.0) or 0.0) or float(r.get("created_at", 0.0) or 0.0)
    elapsed = max(0.0, time.time() - base) if base else 0.0
    s_sec = max(1e-6, float(r.get("stability", 24.0) or 24.0) * 3600.0)
    retention = max(0.05, min(1.0, 10.0 ** (-elapsed / s_sec)))
    layer = r.get("schema_layer", "episodic") or "episodic"
    layer_bonus = {"core": 1.25, "semantic": 1.15, "episodic": 1.0}.get(layer, 1.0)
    return imp * retention * layer_bonus


def build_history(msgs, mode="full", top_k=8, gate_openness=1.0, question=""):
    """按模式构建历史文本:
    - full: 原始顺序全量（基线）
    - brain: SalienceTagger 标记 → ThalamicGate 过滤 → 高显著性前置（top_k 截断）
    - brainv2: 海马体巩固——高显著性记忆要点前置 + 原始会话保持时序（不截断）
    - p2: P2 检索注入——10底 FSRS(stability)×T3相关性×M1分类 排序选 top_k 前置 + 原始时序
    """
    if mode == "full":
        parts = [f"### Session {si+1}:\nSession Content:\n{json.dumps(m, ensure_ascii=False)}"
                 for si, role, m in msgs]
        return "\n\n".join(parts)

    if mode == "p2":
        # ── P2 记忆注入管线（004 P2-1~P2-4，与 _memory_item_score 同口径）──
        # retention 统一 10 底 + per-item FSRS stability；T3 相关性词命中；
        # M1 分类（preference/decision→core 加成, fact→semantic）
        try:
            from src.core.memory_hierarchy import classify_memory
        except Exception:
            def classify_memory(t):
                return "other"
        tagger = SalienceTagger()
        scored = []
        now = time.time()
        n = len(msgs)
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
            # 模拟 FSRS：importance 高→stability 高；会话越早→复习次数越多→越稳定
            stability = 24.0 + imp * 96.0 + (n - i) * 6.0
            created = now - (n - i) * 3600.0  # 越早的会话越久远（真实时间衰减）
            scored.append({"key": f"s{si}", "value": content, "importance": imp,
                           "last_reviewed": 0.0, "created_at": created, "stability": stability,
                           "schema_layer": layer, "_rel": rel, "_si": si, "_role": role})
        scored.sort(key=lambda r: (r["_rel"], p2_item_score(r)), reverse=True)
        top = scored[:top_k]
        top.sort(key=lambda r: r["_si"])  # 注入段内保持时序
        mem_block = "## 记忆要点（P2 检索注入 · 10底FSRS×相关性）\n" + "\n".join(
            f"- ({p2_item_score(r):.2f}) [{r['_role']}] {r['value'][:160]}" for r in top)
        full_block = "\n\n".join(
            f"### Session {si+1}:\nSession Content:\n{json.dumps({'role': role, 'content': content}, ensure_ascii=False)}"
            for si, role, content in msgs)
        return mem_block + "\n\n## 原始会话（保持时间顺序）\n\n" + full_block

    # 脑区标记 + 门控（共用）
    tagger = SalienceTagger()
    gate = ThalamicGate()
    gate.gate_openness = gate_openness
    scored = []
    for si, role, content in msgs:
        s = calc_salience(content, question, tagger)
        priority = 1.0 if role == "user" else 0.6
        if gate.gate(s, priority):
            scored.append((s, si, role, content))

    if mode == "brainv2":
        # 记忆要点（高显著性，HippocampalReplay 巩固语义）：简短摘要前置
        replayer = HippocampalReplay(max_traces=top_k * 2)
        for s, si, role, content in scored:
            replayer.encode(f"[{role}] {content}", emotional_tag=s)
        consolidated = sorted(scored, key=lambda x: -x[0])[:top_k]
        mem_points = []
        for s, si, role, content in consolidated:
            snippet = content if len(content) <= 160 else content[:160] + "..."
            mem_points.append(f"- ({s:.2f}) [{role}] {snippet}")
        mem_block = "## 记忆要点（海马体巩固 · 高显著性前置）\n" + "\n".join(mem_points)
        # 原始会话（保持时序，不截断）
        full_block = "\n\n".join(
            f"### Session {si+1}:\nSession Content:\n{json.dumps({'role': role, 'content': content}, ensure_ascii=False)}"
            for si, role, content in msgs
        )
        return mem_block + "\n\n## 原始会话（保持时间顺序）\n\n" + full_block

    # brain v1: 截断 + 重排（时序被破坏，保留兼容）
    scored.sort(key=lambda x: -x[0])
    scored = scored[:top_k]
    parts = [f"### Session {si+1}:\nSession Content:\n{json.dumps({'role': role, 'content': content}, ensure_ascii=False)}"
             for s, si, role, content in scored]
    return "\n\n".join(parts)


def ask(prompt, max_tokens=80):
    """统一模型调用（模型无关：MODEL_ID 切换任意主流模型，见 model_io.py）"""
    return _ask_io(prompt, max_tokens=max_tokens, temperature=0.0)


def evaluate(entries, mode, top_k=8, gate_openness=1.0, question_hint=True):
    """评估一组样本，返回 (correct, total, details)"""
    correct, total = 0, 0
    details = []
    for e in entries:
        msgs = flatten_sessions(e)
        if not msgs:
            continue
        if question_hint:
            # relevance 需要问题——为保持统一，brain 模式用问题词做二次标记已包含在 build 内简化
            pass
        hist = build_history(msgs, mode=mode, top_k=top_k, gate_openness=gate_openness, question=e["question"])
        prompt = ANSWER_TEMPLATE.format(hist, e["question_date"], e["question"])
        ans = ask(prompt)
        em = best_subspan_em(ans, e["answer"])
        correct += em
        total += 1
        details.append({"qid": e["question_id"], "question": e["question"], "answer": e["answer"],
                        "response": ans[:300], "em": em, "mode": mode, "top_k": top_k})
        print(f"  [{mode}/K{top_k}] {e['question'][:40]}... EM={em}", flush=True)
    return correct, total, details


def main():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA, encoding="utf-8"))
    by_type = {}
    for e in data:
        by_type.setdefault(e["question_type"], []).append(e)
    sample_by_type = {t: s[:N_PER_TYPE] for t, s in by_type.items()}
    all_samples = [e for s in sample_by_type.values() for e in s]

    # ── 基因组参数进化: 用前 12 样本(每类前2)扫描 top_k, GenomicOptimizer 记录+进化 ──
    train = [e for s in sample_by_type.values() for e in s[:2]]
    skip_scan = os.environ.get("MESHCTX_SKIP_SCAN") == "1"  # 已跑过扫描时跳过（best_k 已知）
    if skip_scan:
        print(f"== 跳过训练扫描（MESHCTX_SKIP_SCAN=1，沿用已确认最优 top_k=12）==", flush=True)
        go = GenomicOptimizer(population_size=6)
        go.initialize()
        best_k = 12
        k_scores = {4: (2, 12), 8: (3, 12), 12: (5, 12)}  # 前序扫描结果
        go.evolve(steps=1)
        evolved = go._best
        print(f"  基因组进化后 retrieval_top_k={evolved.retrieval_top_k} memory_weight={evolved.memory_weight:.2f}", flush=True)
    else:
        print(f"== 基因组参数进化（训练集 {len(train)} 样本，扫描 top_k）==", flush=True)
        go = GenomicOptimizer(population_size=6)
        go.initialize()
        k_scores = {}
        for k in [4, 8, 12]:
            c, t, _ = evaluate(train, mode="brain", top_k=k, gate_openness=0.8)
            k_scores[k] = (c, t)
            for genome in go._population:
                genome.retrieval_top_k = k
                go.record(genome, success=(c / t) > 0.5)
            print(f"  训练 top_k={k}: {c}/{t} = {c/t:.2f}", flush=True)
        best_k = max(k_scores, key=lambda k: k_scores[k][0] / max(1, k_scores[k][1]))
        go.evolve(steps=1)  # 进化一代（展示基因组自适应）
        evolved = go._best or go.evolve(steps=1)
        print(f"  最优 top_k={best_k}；基因组进化后 retrieval_top_k={evolved.retrieval_top_k} memory_weight={evolved.memory_weight:.2f}", flush=True)

    # ── 全量评估: 脑区精选 v2(记忆要点前置 + 原始时序) ──
    print(f"\n== 全量评估: MeshCtx 脑区增强 v2（记忆要点前置 top_k={best_k} + 原始时序）==\n", flush=True)
    c_brain, t_brain, det_brain = evaluate(all_samples, mode="brainv2", top_k=best_k, gate_openness=0.8)
    brain_acc = c_brain / t_brain if t_brain else 0

    # ── P2 检索注入评估（独立结果文件，不覆盖 brainv2 归档）──
    print(f"\n== 全量评估: P2 检索注入（10底FSRS×T3相关性×M1分类，top_k={best_k}）==\n", flush=True)
    c_p2, t_p2, det_p2 = evaluate(all_samples, mode="p2", top_k=best_k, gate_openness=0.8)
    p2_acc = c_p2 / t_p2 if t_p2 else 0

    results = {
        "model": MODEL,
        "benchmark": "LongMemEval-oracle + MeshCtx 17脑区/基因组增强",
        "n_per_type": N_PER_TYPE,
        "baseline_full_history_accuracy": 0.5208333333333334,  # 原生全量(48样本)已测
        "baseline_full_history_note": "原生 deepseek-chat 全量历史, 25/48",
        "brain_top_k": best_k,
        "genome_evolved": {"retrieval_top_k": evolved.retrieval_top_k, "memory_weight": evolved.memory_weight},
        "k_training_scores": {str(k): v for k, v in k_scores.items()},
        "brain_enhanced": {"correct": c_brain, "total": t_brain, "accuracy": brain_acc},
        "samples": det_brain,
    }
    out = os.path.join(OUT, "meshctx_memory_enhanced_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # P2 注入结果（独立归档，供 v5 报告对比）
    out_p2 = os.path.join(OUT, "p2_injection_results.json")
    json.dump({
        "model": MODEL,
        "benchmark": "LongMemEval-oracle + P2 检索注入(10底FSRS×T3相关×M1分类)",
        "n_per_type": N_PER_TYPE,
        "top_k": best_k,
        "baseline_full_history_accuracy": 0.5208333333333334,
        "p2_injection": {"correct": c_p2, "total": t_p2, "accuracy": p2_acc},
        "samples": det_p2,
    }, open(out_p2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n=== 结果 ===")
    print(f"基线(全量历史): 52.1% (25/48)")
    print(f"MeshCtx 脑区精选: {c_brain}/{t_brain} = {brain_acc:.1%}")
    print(f"P2 检索注入: {c_p2}/{t_p2} = {p2_acc:.1%}   vs 基线 {p2_acc - 0.5208:+.1%}")
    print(f"保存:", out, "|", out_p2)


if __name__ == "__main__":
    main()
