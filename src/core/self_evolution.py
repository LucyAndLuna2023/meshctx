# -*- coding: utf-8 -*-
"""meshctx Self-Evolution Loop v1 (Phase-0, 零 LLM 依赖)

闭环: 执行 record() → 反思 reflect() → 注入 inject() → 归因 reinforce()
设计: docs/SELF_EVOLUTION_DESIGN.md (ExpeL 蒸馏 × FSRS 保持度 × 哈希链完整性)

- 经验层: 复用 web3_messaging.Web3MessagingLayer (JSONL + 哈希链防篡改)
- 洞见层: 统计蒸馏 (task_type×strategy 成功率差 > 阈值 → 自然语言规则),
  保持度复用 FSRS 公式 R=10^(-t/S) — 无用洞见自然衰减淘汰
- 安全: 只从本地执行轨迹生成 (零外部注入面); 洞见仅作上下文参考文本
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# FSRS 风格保持度: R(t) = 10^(-t/S)  (t=小时, S=stability 小时)
def _retention(last_used: float, stability_h: float, now: float) -> float:
    elapsed_h = max(0.0, (now - last_used) / 3600.0)
    s = max(0.5, stability_h)
    return max(0.0, min(1.0, 10.0 ** (-elapsed_h / s)))


class SelfEvolutionLoop:
    """自进化闭环 v1 — 统计蒸馏 + FSRS 保持度 + 哈希链经验层。"""

    WIN_DELTA_MIN = 0.15   # 成功率差阈值: 偏离总体 15pp 才值得成为洞见
    MIN_SAMPLES = 5        # 每策略最少样本
    AUTO_REFLECT_EVERY = 20  # 自优化: 每 N 条新经验自动反思 (无需人工触发)

    def __init__(self, data_dir: Optional[Path] = None):
        self.dir = Path(data_dir) if data_dir else (
            Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx")) / "self_evolution")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._insights_path = self.dir / "insights.json"
        self._lock = threading.Lock()
        self._journal = None          # 懒加载; False=已知不可用
        self.insights: Dict[str, Dict] = self._load_insights()
        self._exp_index: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
        self._exp_loaded = False
        self._since_reflect = 0

    # ── 存储 ──────────────────────────────────────────────
    def _load_insights(self) -> Dict[str, Dict]:
        try:
            if self._insights_path.exists():
                return json.loads(self._insights_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_insights(self) -> None:
        tmp = self._insights_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.insights, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, self._insights_path)

    def _journal_obj(self):
        if self._journal is None:
            try:
                from .web3_messaging import Web3MessagingLayer
                self._journal = Web3MessagingLayer("self_evolution", self.dir)
            except Exception:
                self._journal = False
        return self._journal or None

    # ── ① 记录执行经验 ────────────────────────────────────
    def record(self, task_type: str, strategy: str, outcome: bool,
               detail: str = "", duration_ms: float = 0.0) -> Dict[str, Any]:
        """任务执行后调用一次: task_type/strategy 任意字符串, outcome=成败。"""
        exp = {
            "task_type": (task_type or "general").strip()[:64],
            "strategy": (strategy or "default").strip()[:128],
            "outcome": bool(outcome),
            "detail": (detail or "")[:500],
            "duration_ms": round(float(duration_ms or 0.0), 1),
            "ts": time.time(),
        }
        j = self._journal_obj()
        if j is not None:
            try:
                entry = j.log_send("agent", uuid.uuid4().hex[:8],
                                   {"exp": exp}, kind="experience")
                # 注意: 不改动已入链的 exp 引用 (内存 ledger 共享该 dict,
                # 入链后再变更会使 entry_hash 失配 → verify False)
                out_exp = dict(exp)
                out_exp["chain_seq"] = entry.get("seq")
                auto = self._register_exp(exp)
                if auto:
                    try:
                        self.reflect()   # 自优化: 满 N 条自动反思, 闭环自转
                    except Exception:
                        pass
                return out_exp
            except Exception:
                pass
        exp_return = dict(exp)
        auto = self._register_exp(exp)
        if auto:
            try:
                self.reflect()
            except Exception:
                pass
        return exp_return

    def _register_exp(self, exp: Dict) -> bool:
        """入内存索引; 返回是否达到自动反思阈值。"""
        with self._lock:
            self._exp_index[exp["task_type"]][exp["strategy"]].append(exp)
            self._exp_loaded = True
            self._since_reflect += 1
            return self._since_reflect >= self.AUTO_REFLECT_EVERY

    def _ensure_history(self) -> None:
        """从 journal 重建历史经验 (进程重启后)。"""
        if self._exp_loaded:
            return
        j = self._journal_obj()
        if j is None:
            self._exp_loaded = True
            return
        try:
            for e in j.load_journal():
                exp = e.get("payload", {}).get("exp")
                if isinstance(exp, dict) and exp.get("task_type"):
                    self._exp_index[exp["task_type"]][exp["strategy"]].append(exp)
        except Exception:
            pass
        self._exp_loaded = True

    # ── ② 反思蒸馏 (ExpeL 统计路线) ───────────────────────
    def reflect(self, min_samples: Optional[int] = None,
                win_delta_min: Optional[float] = None) -> Dict[str, Any]:
        """扫描经验, 蒸馏洞见 (幂等: 同 key 只更新统计不重复创建)。"""
        self._ensure_history()
        ms = min_samples if min_samples is not None else self.MIN_SAMPLES
        wd = win_delta_min if win_delta_min is not None else self.WIN_DELTA_MIN
        created, updated = 0, 0
        with self._lock:
            for task_type, strategies in self._exp_index.items():
                total = [e for lst in strategies.values() for e in lst]
                n_total = len(total)
                if n_total < ms:
                    continue
                base_rate = sum(1 for e in total if e["outcome"]) / n_total
                for strategy, exps in strategies.items():
                    n = len(exps)
                    if n < ms:
                        continue
                    rate = sum(1 for e in exps if e["outcome"]) / n
                    delta = rate - base_rate
                    key = f"{task_type}::{strategy}"
                    if abs(delta) < wd:
                        continue
                    cur = self.insights.get(key)
                    if cur is None and delta > 0:
                        self.insights[key] = {
                            "id": uuid.uuid4().hex[:8],
                            "task_type": task_type,
                            "strategy": strategy,
                            "rule": f"任务[{task_type}]优先采用策略「{strategy}」"
                                    f" (成功率 {rate:.0%} vs 总体 {base_rate:.0%}, 样本 {n})",
                            "delta": round(delta, 3),
                            "stability": 24.0,
                            "created_at": time.time(),
                            "last_used": 0.0,
                            "hits": 0, "wins": 0,
                        }
                        created += 1
                    elif cur is not None:
                        old = float(cur.get("delta", 0.0))
                        cur["delta"] = round(delta, 3)
                        # 自优化: 效果变好→保持度升, 变差→降 (GEPA 式淘汰压力)
                        factor = 1.1 if delta > old else 0.9
                        cur["stability"] = round(
                            min(720.0, max(1.0, float(cur.get("stability", 24.0)) * factor)), 2)
                        cur["updated_at"] = time.time()
                        updated += 1
            self._save_insights()
        return {"created": created, "updated": updated,
                "insights_total": len(self.insights)}

    # ── ③ 注入 (检索 top-k, FSRS 保持度 × 效果差) ─────────
    def inject(self, task_type: Optional[str] = None, k: int = 3) -> List[str]:
        """返回 top-k 洞见规则文本 (供 SYSTEM_PROMPT/上下文注入)。

        task_type 给定 → 只取该类型; None/空 → 全类型 top-k (助手跨任务通用)。
        """
        self._ensure_history()
        now = time.time()
        scored = []
        for cur in self.insights.values():
            if task_type and cur.get("task_type") != task_type:
                continue
            lu = cur.get("last_used") or cur.get("created_at", now)
            ret = _retention(lu, float(cur.get("stability", 24.0)), now)
            score = ret * (0.5 + max(0.0, float(cur.get("delta", 0.0))))
            scored.append((score, cur))
        scored.sort(key=lambda x: -x[0])
        picked = [c for _, c in scored[:max(0, k)]]
        with self._lock:
            for c in picked:
                c["last_used"] = now
                c["hits"] = int(c.get("hits", 0)) + 1
            if picked:
                self._save_insights()
        return [c["rule"] for c in picked]

    # ── ④ 归因回灌 (命中洞见的任务结果 → 保持度增减) ──────
    def reinforce(self, task_type: str, rules: List[str], outcome: bool) -> int:
        """任务结束后回灌: 命中洞见且成功 → stability×1.3 (封顶 720h);
        命中但失败 → stability×0.7。返回更新的洞见数。"""
        now = time.time()
        n = 0
        rule_set = {r for r in rules if r}
        with self._lock:
            for cur in self.insights.values():
                if cur.get("task_type") != task_type or cur.get("rule") not in rule_set:
                    continue
                s = float(cur.get("stability", 24.0))
                cur["stability"] = round(min(720.0, s * 1.3) if outcome else max(1.0, s * 0.7), 2)
                cur["wins"] = int(cur.get("wins", 0)) + (1 if outcome else 0)
                cur["last_used"] = now
                n += 1
            if n:
                self._save_insights()
        return n

    # ── 健康度 ────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        self._ensure_history()
        n_exp = sum(len(lst) for st in self._exp_index.values() for lst in st.values())
        ok_chain = None
        j = self._journal_obj()
        if j is not None:
            try:
                ok_chain, bad = j.verify()
            except Exception:
                ok_chain = None
        return {
            "experiences": n_exp,
            "insights": len(self.insights),
            "chain_verified": ok_chain,
            "dir": str(self.dir),
        }


_loop: Optional[SelfEvolutionLoop] = None


def get_self_evolution() -> SelfEvolutionLoop:
    """单例 (进程内)。"""
    global _loop
    if _loop is None:
        _loop = SelfEvolutionLoop()
    return _loop
