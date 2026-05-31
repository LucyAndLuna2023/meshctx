"""
meshctx v3.52 — Intent Prediction Engine v2 (意图预测引擎v2)

v1问题: 仅基于时间模式, 无跨session学习
v2: SubconsciousObserver模式 + FeedbackLoop历史 + 知识图谱 → 多维度预测

预测维度:
  1. 时间模式: 工作日/周末/时段
  2. 上下文链: 上次做了什么→下一步可能做什么
  3. 知识图谱: 相关概念激活→预加载
  4. 跨Agent: 其他Profile做了什么→本Profile可能需要
  5. 外部信号: 竞品动态/安全告警→主动提醒

输出: 预测意图列表(置信度排序) → Preloader预加载上下文
"""
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger("meshctx.intent_predictor")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class IntentCategory(Enum):
    """意图类别"""
    CODE = "code"               # 写代码
    DEBUG = "debug"             # 调试
    DEPLOY = "deploy"           # 部署
    REVIEW = "review"           # 审查
    RESEARCH = "research"       # 研究
    CONFIG = "config"           # 配置
    MONITOR = "monitor"         # 监控
    DOCUMENT = "document"       # 文档
    TEST = "test"               # 测试
    UNKNOWN = "unknown"         # 未知


class PredictionSource(Enum):
    """预测来源"""
    TEMPORAL = "temporal"           # 时间模式
    CONTEXTUAL = "contextual"       # 上下文链
    KNOWLEDGE = "knowledge"         # 知识图谱
    CROSS_AGENT = "cross_agent"     # 跨Agent
    EXTERNAL = "external"           # 外部信号
    PATTERN = "pattern"             # Subconscious模式


@dataclass
class IntentPrediction:
    """意图预测"""
    category: IntentCategory = IntentCategory.UNKNOWN
    description: str = ""
    confidence: float = 0.0          # 0-1
    sources: List[PredictionSource] = field(default_factory=list)
    trigger: str = ""                # 触发条件
    suggested_action: str = ""       # 建议行动
    preload_keys: List[str] = field(default_factory=list)  # 预加载上下文key
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0


@dataclass
class ContextChain:
    """上下文链: A→B→C 行为序列"""
    sequence: List[str] = field(default_factory=list)
    frequency: int = 0
    last_seen: float = 0
    avg_interval_seconds: float = 0


# ═══════════════════════════════════════════════════════════
# Prediction Engine
# ═══════════════════════════════════════════════════════════

class IntentPredictionEngine:
    """
    意图预测引擎v2
    
    多源融合:
    - 时间模式权重: 0.3
    - 上下文链权重: 0.35
    - 知识图谱权重: 0.15
    - 跨Agent权重: 0.1
    - 外部信号权重: 0.1
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 权重配置
        self._weights = {
            PredictionSource.TEMPORAL: self.config.get("weight_temporal", 0.30),
            PredictionSource.CONTEXTUAL: self.config.get("weight_contextual", 0.35),
            PredictionSource.KNOWLEDGE: self.config.get("weight_knowledge", 0.15),
            PredictionSource.CROSS_AGENT: self.config.get("weight_cross_agent", 0.10),
            PredictionSource.EXTERNAL: self.config.get("weight_external", 0.10),
        }
        
        # 时间模式: (weekday, hour) → IntentCategory
        self._temporal_patterns: Dict[Tuple[int, int], Dict[IntentCategory, float]] = {}
        
        # 上下文链: prev_action → [next_action, frequency]
        self._context_chains: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        
        # 动作历史
        self._action_history: deque = deque(maxlen=200)
        
        # 知识图谱意图映射
        self._kg_intent_map: Dict[str, IntentCategory] = {}
        
        # 跨Agent信号缓存
        self._cross_agent_signals: deque = deque(maxlen=50)
        
        self._min_confidence = self.config.get("min_confidence", 0.3)
        self._max_predictions = self.config.get("max_predictions", 5)
    
    # ═══ 输入: 记录动作 ═══
    
    def record_action(self, action: str, category: Optional[IntentCategory] = None,
                      metadata: Optional[Dict] = None):
        """记录用户动作"""
        now = datetime.now()
        entry = {
            "action": action,
            "category": category.value if category else "unknown",
            "weekday": now.weekday(),
            "hour": now.hour,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self._action_history.append(entry)
        
        # 更新时间模式
        key = (entry["weekday"], entry["hour"])
        if key not in self._temporal_patterns:
            self._temporal_patterns[key] = {}
        
        cat = category or self._classify_action(action)
        self._temporal_patterns[key][cat] = self._temporal_patterns[key].get(cat, 0) + 1
        
        # 更新上下文链
        if len(self._action_history) >= 2:
            prev = self._action_history[-2]["action"]
            prev_cat = self._action_history[-2].get("category", "unknown")
            chain_key = f"{prev_cat}:{prev[:30]}"
            found = False
            for i, (next_act, freq) in enumerate(self._context_chains.get(chain_key, [])):
                if next_act == action[:30]:
                    self._context_chains[chain_key][i] = (next_act, freq + 1)
                    found = True
                    break
            if not found:
                self._context_chains[chain_key].append((action[:30], 1))
    
    def _classify_action(self, action: str) -> IntentCategory:
        """根据动作文本分类意图"""
        action_lower = action.lower()
        
        classifiers = {
            IntentCategory.CODE: ["write", "code", "implement", "build", "create", "add"],
            IntentCategory.DEBUG: ["debug", "fix", "bug", "error", "traceback", "crash"],
            IntentCategory.DEPLOY: ["deploy", "push", "release", "ship", "publish"],
            IntentCategory.REVIEW: ["review", "check", "inspect", "audit"],
            IntentCategory.RESEARCH: ["research", "search", "find", "look", "explore"],
            IntentCategory.CONFIG: ["config", "setup", "install", "configure"],
            IntentCategory.MONITOR: ["monitor", "watch", "check", "status", "health"],
            IntentCategory.DOCUMENT: ["document", "readme", "changelog", "doc"],
            IntentCategory.TEST: ["test", "pytest", "coverage", "assert"],
        }
        
        scores = {}
        for cat, keywords in classifiers.items():
            scores[cat] = sum(1 for kw in keywords if kw in action_lower)
        
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                return best
        
        return IntentCategory.UNKNOWN
    
    # ═══ 预测 ═══
    
    def predict(self, context: Optional[Dict] = None) -> List[IntentPrediction]:
        """多维度预测用户意图"""
        predictions = []
        
        # 1. 时间模式预测
        temporal_preds = self._predict_temporal()
        predictions.extend(temporal_preds)
        
        # 2. 上下文链预测
        contextual_preds = self._predict_contextual()
        predictions.extend(contextual_preds)
        
        # 3. 知识图谱预测
        kg_preds = self._predict_knowledge()
        predictions.extend(kg_preds)
        
        # 4. 跨Agent预测
        cross_preds = self._predict_cross_agent()
        predictions.extend(cross_preds)
        
        # 5. 外部信号预测
        external_preds = self._predict_external()
        predictions.extend(external_preds)
        
        # 融合: 加权合并
        merged = self._merge_predictions(predictions)
        
        # 过滤低置信度
        filtered = [p for p in merged if p.confidence >= self._min_confidence]
        
        # 按置信度排序
        filtered.sort(key=lambda p: -p.confidence)
        
        return filtered[:self._max_predictions]
    
    def _predict_temporal(self) -> List[IntentPrediction]:
        """时间模式预测"""
        now = datetime.now()
        key = (now.weekday(), now.hour)
        
        patterns = self._temporal_patterns.get(key, {})
        if not patterns:
            return []
        
        total = sum(patterns.values())
        predictions = []
        
        for cat, count in sorted(patterns.items(), key=lambda x: -x[1])[:3]:
            confidence = (count / total) * self._weights[PredictionSource.TEMPORAL]
            predictions.append(IntentPrediction(
                category=cat,
                description=f"Time-based: usually does {cat.value} at this time ({count}/{total})",
                confidence=min(0.95, confidence),
                sources=[PredictionSource.TEMPORAL],
                trigger=f"Weekday {now.weekday()}, Hour {now.hour}",
            ))
        
        return predictions
    
    def _predict_contextual(self) -> List[IntentPrediction]:
        """上下文链预测"""
        if len(self._action_history) < 2:
            return []
        
        last = self._action_history[-1]
        last_cat = last.get("category", "unknown")
        chain_key = f"{last_cat}:{last['action'][:30]}"
        
        chains = self._context_chains.get(chain_key, [])
        if not chains:
            return []
        
        total = sum(freq for _, freq in chains)
        predictions = []
        
        for next_act, freq in sorted(chains, key=lambda x: -x[1])[:3]:
            cat = self._classify_action(next_act)
            confidence = (freq / total) * self._weights[PredictionSource.CONTEXTUAL]
            predictions.append(IntentPrediction(
                category=cat,
                description=f"After '{last['action'][:30]}', usually does: {next_act} ({freq}/{total})",
                confidence=min(0.95, confidence),
                sources=[PredictionSource.CONTEXTUAL],
                trigger=f"Previous action: {last['action'][:50]}",
            ))
        
        return predictions
    
    def _predict_knowledge(self) -> List[IntentPrediction]:
        """知识图谱预测"""
        predictions = []
        # Placeholder: 从知识图谱获取相关概念
        # 在v3.53中与KnowledgeGraph深度集成
        return predictions
    
    def _predict_cross_agent(self) -> List[IntentPrediction]:
        """跨Agent预测"""
        predictions = []
        for signal in list(self._cross_agent_signals)[-5:]:
            predictions.append(IntentPrediction(
                category=IntentCategory.UNKNOWN,
                description=f"Cross-agent signal: {signal.get('title', '')}",
                confidence=0.3 * self._weights[PredictionSource.CROSS_AGENT],
                sources=[PredictionSource.CROSS_AGENT],
                trigger=signal.get("source", "unknown"),
            ))
        return predictions
    
    def _predict_external(self) -> List[IntentPrediction]:
        """外部信号预测"""
        # Placeholder: 竞品动态/安全告警
        return []
    
    def _merge_predictions(self, predictions: List[IntentPrediction]) -> List[IntentPrediction]:
        """融合多源预测"""
        merged: Dict[IntentCategory, IntentPrediction] = {}
        
        for p in predictions:
            if p.category in merged:
                existing = merged[p.category]
                existing.confidence = min(0.99, existing.confidence + p.confidence * 0.5)
                existing.sources.extend(p.sources)
                if p.confidence > existing.confidence * 1.5:
                    existing.description = p.description
            else:
                merged[p.category] = p
        
        return list(merged.values())
    
    # ═══ 外部信号注入 ═══
    
    def inject_cross_agent_signal(self, title: str, source: str, action: str = ""):
        """注入跨Agent信号"""
        self._cross_agent_signals.append({
            "title": title, "source": source, "action": action,
            "timestamp": time.time(),
        })
    
    def inject_external_signal(self, title: str, urgency: str = "medium"):
        """注入外部信号"""
        # Placeholder
        pass
    
    # ═══ 统计+配置 ═══
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "temporal_patterns": len(self._temporal_patterns),
            "context_chains": len(self._context_chains),
            "action_history": len(self._action_history),
            "cross_agent_signals": len(self._cross_agent_signals),
            "weights": {s.value: w for s, w in self._weights.items()},
        }
    
    def adjust_weights(self, source: PredictionSource, delta: float):
        """根据反馈调整权重"""
        if source in self._weights:
            self._weights[source] = max(0.05, min(0.5, self._weights[source] + delta))
            # 归一化
            total = sum(self._weights.values())
            for s in self._weights:
                self._weights[s] /= total


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_engine: Optional[IntentPredictionEngine] = None


def get_intent_engine(config: Optional[Dict] = None) -> IntentPredictionEngine:
    global _engine
    if _engine is None:
        _engine = IntentPredictionEngine(config)
    return _engine
