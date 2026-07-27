"""
MeshCtx Context Portal — Predictive Context Pre-Loading
========================================================

预测性上下文门户 — 在你提问之前就加载好相关上下文。

核心承诺: <50ms 上下文装配。

工作原理:
  1. 学习用户行为模式 (哪些文件常一起访问、哪些记忆常一起召回)
  2. 当用户开始输入 / 触发上下文切换时, 预测下一步需要什么
  3. MPT (Memory Pre-fetch Table) — 关联记忆的预取表
  4. 上下文装配: 从预取池中挑选最相关的, 50ms 内完成

与大脑集成:
  - 杏仁核 → 标记高频模式为 CRITICAL
  - 海马体 → 提供历史访问模式
  - 丘脑门 → 过滤预取结果
  - 镜像神经元 → 预测用户下一步意图

License: MIT
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.context_portal")


# ---------------------------------------------------------------------------
# Context Item
# ---------------------------------------------------------------------------

@dataclass
class ContextItem:
    """上下文项"""
    id: str
    type: str                    # memory / file / skill / config / knowledge
    content: str
    relevance: float = 0.5
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MPT — Memory Pre-fetch Table
# ---------------------------------------------------------------------------

class MemoryPrefetchTable:
    """
    记忆预取表 — 学习哪些记忆常一起被访问。

    类似 CPU 的预取器: 看到模式 A, 自动预取 B, C, D。
    """

    def __init__(self, max_associations: int = 10000):
        # memory_id → {associated_memory_id → co_occurrence_count}
        self._co_occurrence: Dict[str, Counter] = defaultdict(Counter)
        self._access_sequence: deque = deque(maxlen=20)
        self._total_associations = 0
        self.max_associations = max_associations

    def record_access(self, memory_id: str):
        """
        记录一次记忆访问, 更新共现关系。
        最近访问的 N 个记忆都与此记忆建立关联。
        """
        for prev_id in self._access_sequence:
            self._co_occurrence[prev_id][memory_id] += 1
            self._co_occurrence[memory_id][prev_id] += 1
            self._total_associations += 2

        self._access_sequence.append(memory_id)

        # 限制大小
        if self._total_associations > self.max_associations:
            self._prune()

    def predict(self, current_memories: List[str],
                top_k: int = 10) -> List[Tuple[str, float]]:
        """
        基于当前访问的记忆, 预测下一步需要的记忆。

        Returns:
            [(memory_id, confidence), ...] 按置信度排序
        """
        if not current_memories:
            return []

        scores: Dict[str, float] = defaultdict(float)

        for mem_id in current_memories:
            co_occurs = self._co_occurrence.get(mem_id, {})
            total = sum(co_occurs.values()) or 1
            for assoc_id, count in co_occurs.items():
                if assoc_id not in current_memories:
                    scores[assoc_id] += count / total

        # 排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    def _prune(self):
        """清理低频关联"""
        for mem_id in list(self._co_occurrence.keys()):
            counter = self._co_occurrence[mem_id]
            # 删除计数为 1 的弱关联
            weak = [k for k, v in counter.items() if v <= 1]
            for k in weak:
                del counter[k]
            if not counter:
                del self._co_occurrence[mem_id]

    def get_stats(self) -> Dict:
        return {
            "memory_nodes": len(self._co_occurrence),
            "total_associations": self._total_associations,
        }


# ---------------------------------------------------------------------------
# Pattern Learner — 用户行为模式学习
# ---------------------------------------------------------------------------

class PatternLearner:
    """
    学习用户行为模式:
    - 什么时间做什么
    - 哪些工具/文件常一起用
    - 任务序列模式
    """

    def __init__(self, max_patterns: int = 500):
        self.max_patterns = max_patterns
        # pattern_key → {count, last_seen, avg_interval, ...}
        self._patterns: Dict[str, Dict] = {}
        # session 序列记录
        self._session_actions: deque = deque(maxlen=100)

    def observe(self, action: str, context: Dict = None):
        """观察一个用户行为"""
        context = context or {}
        self._session_actions.append({
            "action": action,
            "context": context,
            "timestamp": time.time(),
        })

    def discover_patterns(self) -> List[Dict]:
        """从观察到的行为中发现模式"""
        if len(self._session_actions) < 3:
            return []

        patterns = []

        # 1. 频繁动作对 (A → B)
        transitions = defaultdict(Counter)
        for i in range(len(self._session_actions) - 1):
            a = self._session_actions[i]["action"]
            b = self._session_actions[i + 1]["action"]
            transitions[a][b] += 1

        for a, next_actions in transitions.items():
            total = sum(next_actions.values())
            for b, count in next_actions.most_common(3):
                if count >= 2 and count / total > 0.3:
                    key = f"transition:{a}→{b}"
                    self._patterns[key] = {
                        "type": "transition",
                        "from": a, "to": b,
                        "confidence": count / total,
                        "count": count,
                    }
                    patterns.append(self._patterns[key])

        # 2. 时间模式 (上午 vs 下午的行为差异)
        morning_actions = [a["action"] for a in self._session_actions
                          if time.localtime(a["timestamp"]).tm_hour < 12]
        afternoon_actions = [a["action"] for a in self._session_actions
                            if time.localtime(a["timestamp"]).tm_hour >= 12]

        if morning_actions:
            am_counter = Counter(morning_actions)
            for action, count in am_counter.most_common(3):
                if count >= 2:
                    key = f"time:morning:{action}"
                    self._patterns[key] = {
                        "type": "time_pattern",
                        "time": "morning",
                        "action": action,
                        "count": count,
                    }
                    patterns.append(self._patterns[key])

        if afternoon_actions:
            pm_counter = Counter(afternoon_actions)
            for action, count in pm_counter.most_common(3):
                if count >= 2:
                    key = f"time:afternoon:{action}"
                    self._patterns[key] = {
                        "type": "time_pattern",
                        "time": "afternoon",
                        "action": action,
                        "count": count,
                    }
                    patterns.append(self._patterns[key])

        return patterns

    def predict_next(self, current_action: str) -> List[Tuple[str, float]]:
        """预测下一步可能做什么"""
        predictions = []
        for key, pattern in self._patterns.items():
            if pattern["type"] == "transition" and pattern["from"] == current_action:
                predictions.append((pattern["to"], pattern["confidence"]))
        return sorted(predictions, key=lambda x: x[1], reverse=True)

    def get_stats(self) -> Dict:
        return {
            "patterns": len(self._patterns),
            "observed_actions": len(self._session_actions),
        }


# ---------------------------------------------------------------------------
# Context Portal — 主入口
# ---------------------------------------------------------------------------

class ContextPortal:
    """
    预测性上下文门户

    用法:
      portal = ContextPortal()
      
      # 预取
      preloaded = portal.prefetch(["file:main.py", "memory:bugfix_rule"])
      
      # 记录用户行为
      portal.observe("read_file", {"file": "src/main.py"})
      
      # 预测下一步
      next_items = portal.predict_next()
    """

    def __init__(self, preload_limit: int = 20,
                 assembly_timeout_ms: float = 50.0):
        self.preload_limit = preload_limit
        self.assembly_timeout_ms = assembly_timeout_ms

        # 子系统
        self.mpt = MemoryPrefetchTable()
        self.patterns = PatternLearner()

        # 上下文存储
        self._item_store: Dict[str, ContextItem] = {}
        self._item_index: Dict[str, List[str]] = defaultdict(list)  # tag → item_ids

        # 热缓存 — 最近预取的
        self._hot_cache: deque = deque(maxlen=50)
        self._cache_hits = 0
        self._cache_misses = 0

        # 统计
        self._total_assembly_time = 0.0
        self._assembly_count = 0

    # ── 上下文管理 ──

    def add_item(self, item: ContextItem):
        """添加一个上下文项"""
        self._item_store[item.id] = item
        for tag in item.tags:
            self._item_index[tag].append(item.id)

    def add_items(self, items: List[ContextItem]):
        for item in items:
            self.add_item(item)

    def get_item(self, item_id: str) -> Optional[ContextItem]:
        return self._item_store.get(item_id)

    def search_by_tags(self, tags: List[str],
                       limit: int = 10) -> List[ContextItem]:
        """按标签搜索"""
        candidates: Dict[str, int] = defaultdict(int)
        for tag in tags:
            for item_id in self._item_index.get(tag, []):
                candidates[item_id] += 1

        ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        return [self._item_store[i] for i, _ in ranked[:limit] if i in self._item_store]

    # ── 预取 ──

    def prefetch(self, active_items: List[str]) -> List[ContextItem]:
        """
        预取: 基于当前活跃项, 预测并加载下一步需要的上下文。

        必须在 50ms 内完成装配。

        Args:
            active_items: 当前活跃的上下文 ID 列表

        Returns:
            预取的上下文项列表
        """
        t0 = time.perf_counter()

        # 1. MPT 预取
        predicted_ids = self.mpt.predict(active_items, top_k=self.preload_limit)

        # 2. 行为模式预测
        if active_items:
            last_item = self._item_store.get(active_items[-1])
            if last_item:
                pattern_preds = self.patterns.predict_next(last_item.type)
                for pred_type, confidence in pattern_preds:
                    matching = self.search_by_tags([pred_type], limit=3)
                    for item in matching:
                        if item.id not in [p[0] for p in predicted_ids]:
                            predicted_ids.append((item.id, confidence * 0.5))

        # 3. 装配
        result = []
        for item_id, confidence in predicted_ids:
            item = self._item_store.get(item_id)
            if item and item not in result:
                item.relevance = confidence
                item.access_count += 1
                result.append(item)
            if len(result) >= self.preload_limit:
                break

        # 4. 记录访问 → 更新 MPT
        for item_id in active_items:
            self.mpt.record_access(item_id)

        # 5. 更新热缓存
        for item in result:
            self._hot_cache.append(item.id)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        self._total_assembly_time += elapsed_ms
        self._assembly_count += 1

        if elapsed_ms > 10:
            logger.debug(f"Context assembly: {len(result)} items in {elapsed_ms:.2f}ms")

        return result

    # ── 行为观察 ──

    def observe(self, action: str, context: Dict = None):
        """观察用户/agent 行为"""
        self.patterns.observe(action, context)

    def predict_next(self) -> List[Tuple[str, float]]:
        """预测下一步可能需要什么"""
        if not self.patterns._session_actions:
            return []
        last = self.patterns._session_actions[-1]["action"]
        return self.patterns.predict_next(last)

    # ── 统计 ──

    def get_stats(self) -> Dict:
        avg_time = (self._total_assembly_time / max(self._assembly_count, 1))
        within_budget = avg_time <= self.assembly_timeout_ms
        return {
            "items_stored": len(self._item_store),
            "tags_indexed": len(self._item_index),
            "mpt": self.mpt.get_stats(),
            "patterns": self.patterns.get_stats(),
            "hot_cache_size": len(self._hot_cache),
            "avg_assembly_time_ms": round(avg_time, 2),
            "within_50ms_budget": within_budget,
            "prefetch_count": self._assembly_count,
        }


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def get_context_portal() -> ContextPortal:
    return ContextPortal()


# ---------------------------------------------------------------------------
# Backward-compat (for test_v54_breakthrough_memory.py)
# ---------------------------------------------------------------------------

class PredictiveMemoryActivator:
    """预测性记忆激活 — 基于 ContextPortal 的内存预取"""

    def __init__(self):
        self._access_map: Dict[str, Counter] = defaultdict(Counter)
        self._preloads: List[str] = []
        self._hits: int = 0
        self._misses: int = 0

    def record_access(self, context: str, memory_id: str):
        self._access_map[context][memory_id] += 1

    def predict(self, context: str, top_k: int = 3) -> List[str]:
        counter = self._access_map.get(context, Counter())
        return [mem for mem, _ in counter.most_common(top_k)]

    def preload(self, context: str, top_k: int = 3):
        predicted = self.predict(context, top_k=top_k)
        self._preloads = predicted
        return predicted

    def get_hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / max(total, 1)
