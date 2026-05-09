"""
meshctx v1.0 预测引擎 — Predictive Context Engine

核心差异化能力（无人做到）：
- 时间模式学习 (工作日9点→股票, 10点→开发)
- 用户行为预测模型
- 预测性上下文预加载 (Pre-fetch → L1工作记忆)
- 冷却期管理 (避免过度预加载)

架构:
  L1 预测层 → 模式识别 → 预加载决策 → 上下文注入
"""
import asyncio
import json
import logging
import math
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.predictor")


# ═══════════════════════════════════════════════════════════
# 时间模式模型
# ═══════════════════════════════════════════════════════════

class TimeSlot(Enum):
    """时间段划分"""
    EARLY_MORNING = 0   # 0-6
    MORNING = 1         # 6-9
    WORK_START = 2      # 9-11
    LATE_MORNING = 3    # 11-12
    AFTERNOON = 4       # 12-14
    WORK_PEAK = 5       # 14-17
    EVENING = 6         # 17-20
    NIGHT = 7           # 20-24


@dataclass
class ActivityPattern:
    """用户活动模式"""
    # 时间特征
    hour: int = 0
    day_of_week: int = 0         # 0=Mon, 6=Sun
    time_slot: TimeSlot = TimeSlot.WORK_START
    
    # 任务特征
    task_type: str = ""          # coding/research/deployment/review/chat
    project_id: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    
    # 统计
    frequency: int = 0           # 出现次数
    last_seen: float = 0.0       # 最后出现时间戳
    avg_duration: float = 0.0    # 平均耗时(秒)
    success_rate: float = 1.0    # 成功率
    
    # 预测
    confidence: float = 0.0      # 预测置信度
    next_expected: float = 0.0   # 预期下次出现时间戳


@dataclass 
class PredictionResult:
    """预测结果"""
    task_type: str
    project_id: Optional[str]
    confidence: float
    expected_time: float
    preload_context: Dict[str, Any]
    keywords: List[str]
    reason: str


# ═══════════════════════════════════════════════════════════
# 时间模式学习器
# ═══════════════════════════════════════════════════════════

class TemporalPatternLearner:
    """
    时间模式学习器
    
    学习用户在不同时间段的典型行为模式。
    使用指数加权移动平均 + 周期检测算法。
    """
    
    def __init__(self, window_days: int = 30):
        self.window_days = window_days
        # (hour, day_of_week, task_type) → ActivityPattern
        self._patterns: Dict[Tuple[int, int, str], ActivityPattern] = {}
        # 原始事件记录
        self._history: deque = deque(maxlen=10000)
        # 周期性检测
        self._periodic_signals: Dict[str, List[float]] = defaultdict(list)
        
    def record(self, task_type: str, project_id: Optional[str] = None,
               keywords: List[str] = None, duration: float = 0,
               success: bool = True):
        """记录一次用户活动"""
        now = time.time()
        dt = datetime.fromtimestamp(now)
        hour = dt.hour
        dow = dt.weekday()
        slot = self._hour_to_slot(hour)
        
        key = (hour, dow, task_type)
        
        if key not in self._patterns:
            self._patterns[key] = ActivityPattern(
                hour=hour,
                day_of_week=dow,
                time_slot=slot,
                task_type=task_type,
                project_id=project_id,
                keywords=keywords or [],
            )
        
        pattern = self._patterns[key]
        pattern.frequency += 1
        pattern.last_seen = now
        
        # 指数加权更新平均耗时
        alpha = 0.3
        pattern.avg_duration = (
            alpha * duration + (1 - alpha) * pattern.avg_duration
            if pattern.avg_duration > 0 else duration
        )
        
        # 更新成功率
        old_total = pattern.frequency - 1
        if old_total > 0:
            pattern.success_rate = (
                pattern.success_rate * old_total + (1.0 if success else 0.0)
            ) / pattern.frequency
        
        # 更新关键词
        if keywords:
            existing = set(pattern.keywords)
            existing.update(keywords)
            pattern.keywords = list(existing)[:20]
        
        # 记录历史
        self._history.append({
            "task_type": task_type,
            "project_id": project_id,
            "hour": hour,
            "dow": dow,
            "timestamp": now,
            "duration": duration,
            "success": success,
        })
        
        # 检测周期性
        self._detect_periodicity(task_type, now)
        
    def _hour_to_slot(self, hour: int) -> TimeSlot:
        if hour < 6:    return TimeSlot.EARLY_MORNING
        elif hour < 9:  return TimeSlot.MORNING
        elif hour < 11: return TimeSlot.WORK_START
        elif hour < 12: return TimeSlot.LATE_MORNING
        elif hour < 14: return TimeSlot.AFTERNOON
        elif hour < 17: return TimeSlot.WORK_PEAK
        elif hour < 20: return TimeSlot.EVENING
        else:           return TimeSlot.NIGHT
    
    def _detect_periodicity(self, task_type: str, now: float):
        """检测任务的周期性模式"""
        signals = self._periodic_signals[task_type]
        signals.append(now)
        
        if len(signals) < 3:
            return
        
        # 保留最近30天
        cutoff = now - 86400 * 30
        self._periodic_signals[task_type] = [
            t for t in signals if t > cutoff
        ]
        
        # 计算间隔
        recent = sorted(signals[-10:])
        if len(recent) < 3:
            return
        
        intervals = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
        mean_interval = sum(intervals) / len(intervals)
        
        # 检测日周期 (~86400秒)
        if abs(mean_interval - 86400) < 7200:  # ±2小时容差
            logger.debug(f"检测到日周期: {task_type}")
        elif abs(mean_interval - 604800) < 43200:  # 周周期 ±12小时
            logger.debug(f"检测到周周期: {task_type}")
    
    def predict(self, now: float = None, top_k: int = 3) -> List[PredictionResult]:
        """预测用户接下来可能做什么"""
        if now is None:
            now = time.time()
        
        dt = datetime.fromtimestamp(now)
        current_hour = dt.hour
        current_dow = dt.weekday()
        
        predictions = []
        
        # 1. 精确匹配当前时间
        for (hour, dow, task_type), pattern in self._patterns.items():
            if hour == current_hour and dow == current_dow:
                confidence = self._calculate_confidence(pattern, now)
                if confidence > 0.3:
                    predictions.append(PredictionResult(
                        task_type=task_type,
                        project_id=pattern.project_id,
                        confidence=confidence,
                        expected_time=now,
                        preload_context={
                            "keywords": pattern.keywords[:5],
                            "project_id": pattern.project_id,
                        },
                        keywords=pattern.keywords[:5],
                        reason=f"历史模式: 工作日{current_hour}时经常{task_type}",
                    ))
        
        # 2. 时间窗口模糊匹配 (±1小时)
        for offset in [-1, 1]:
            adj_hour = (current_hour + offset) % 24
            for (hour, dow, task_type), pattern in self._patterns.items():
                if hour == adj_hour and dow == current_dow:
                    confidence = self._calculate_confidence(pattern, now) * 0.7
                    if confidence > 0.2:
                        predictions.append(PredictionResult(
                            task_type=task_type,
                            project_id=pattern.project_id,
                            confidence=confidence,
                            expected_time=now + offset * 3600,
                            preload_context={"keywords": pattern.keywords[:5]},
                            keywords=pattern.keywords[:5],
                            reason=f"相近时间模式 (+{offset}h)",
                        ))
        
        # 3. 基于最近活动序列预测 (马尔可夫链)
        if len(self._history) >= 2:
            last_tasks = [h["task_type"] for h in list(self._history)[-3:]]
            transition_preds = self._markov_predict(last_tasks, now)
            predictions.extend(transition_preds)
        
        # 去重排序
        seen = set()
        unique = []
        for p in sorted(predictions, key=lambda x: -x.confidence):
            key = (p.task_type, p.project_id or "")
            if key not in seen:
                seen.add(key)
                unique.append(p)
        
        return unique[:top_k]
    
    def _calculate_confidence(self, pattern: ActivityPattern, now: float) -> float:
        """计算预测置信度"""
        if pattern.frequency < 2:
            return 0.0
        
        # 频率因子
        freq_score = math.log(1 + pattern.frequency) / math.log(10)
        
        # 新鲜度因子 (最近出现的加权)
        hours_since = (now - pattern.last_seen) / 3600
        recency = math.exp(-hours_since / 168)  # 一周衰减到~37%
        
        # 成功率因子
        success_factor = 0.5 + pattern.success_rate * 0.5
        
        confidence = freq_score * recency * success_factor
        return min(1.0, confidence)
    
    def _markov_predict(self, recent_tasks: List[str], now: float) -> List[PredictionResult]:
        """基于马尔可夫链的序列预测"""
        predictions = []
        
        # 构建转换矩阵
        transitions = defaultdict(lambda: defaultdict(int))
        history = list(self._history)
        
        for i in range(len(history) - 1):
            t1 = history[i]["task_type"]
            t2 = history[i + 1]["task_type"]
            transitions[t1][t2] += 1
        
        # 预测下一步
        last_task = recent_tasks[-1]
        if last_task in transitions:
            total = sum(transitions[last_task].values())
            for next_task, count in transitions[last_task].items():
                prob = count / total if total > 0 else 0
                if prob > 0.15:
                    predictions.append(PredictionResult(
                        task_type=next_task,
                        project_id=None,
                        confidence=prob * 0.5,  # 马尔可夫置信度降低
                        expected_time=now,
                        preload_context={},
                        keywords=[],
                        reason=f"序列预测: {last_task} → {next_task}",
                    ))
        
        return predictions
    
    def get_stats(self) -> Dict[str, Any]:
        """获取学习统计"""
        return {
            "patterns_learned": len(self._patterns),
            "total_events": len(self._history),
            "periodic_signals": {
                k: len(v) for k, v in self._periodic_signals.items()
            },
            "top_patterns": [
                {
                    "task_type": p.task_type,
                    "hour": p.hour,
                    "dow": p.day_of_week,
                    "frequency": p.frequency,
                    "success_rate": round(p.success_rate, 2),
                }
                for p in sorted(
                    self._patterns.values(),
                    key=lambda x: -x.frequency,
                )[:5]
            ],
        }


# ═══════════════════════════════════════════════════════════
# 上下文预加载器
# ═══════════════════════════════════════════════════════════

class ContextPreloader:
    """
    上下文预加载器
    
    在用户提出请求之前，将预测的上下文预先加载到L1工作记忆。
    支持冷却期管理，避免过度预加载消耗资源。
    """
    
    def __init__(self, max_preloads: int = 5, cooldown_seconds: int = 300):
        self.max_preloads = max_preloads
        self.cooldown_seconds = cooldown_seconds
        self._preloaded: Dict[str, float] = {}  # preload_key → timestamp
        self._preload_history: deque = deque(maxlen=100)
        
    def should_preload(self, prediction: PredictionResult) -> bool:
        """判断是否应该预加载"""
        key = f"{prediction.task_type}:{prediction.project_id or ''}"
        
        # 置信度太低不预加载
        if prediction.confidence < 0.4:
            return False
        
        # 冷却期检查
        if key in self._preloaded:
            elapsed = time.time() - self._preloaded[key]
            if elapsed < self.cooldown_seconds:
                return False
        
        # 数量限制
        active_preloads = sum(
            1 for t in self._preloaded.values()
            if time.time() - t < self.cooldown_seconds
        )
        if active_preloads >= self.max_preloads:
            return False
        
        return True
    
    def preload(self, prediction: PredictionResult) -> Dict[str, Any]:
        """执行预加载，返回待注入的上下文"""
        key = f"{prediction.task_type}:{prediction.project_id or ''}"
        self._preloaded[key] = time.time()
        
        context = {
            "type": "predicted_preload",
            "prediction": {
                "task_type": prediction.task_type,
                "project_id": prediction.project_id,
                "confidence": prediction.confidence,
                "reason": prediction.reason,
            },
            "suggested_context": prediction.preload_context,
            "preloaded_at": time.time(),
        }
        
        self._preload_history.append(context)
        
        logger.info(
            f"预加载: {prediction.task_type} "
            f"(置信度={prediction.confidence:.0%}, "
            f"原因={prediction.reason})"
        )
        
        return context
    
    def get_preloaded(self) -> List[Dict]:
        """获取当前活跃的预加载"""
        now = time.time()
        return [
            h for h in self._preload_history
            if now - h["preloaded_at"] < self.cooldown_seconds * 2
        ]


# ═══════════════════════════════════════════════════════════
# 预测引擎插件
# ═══════════════════════════════════════════════════════════

class PredictorPlugin(Plugin):
    """
    预测引擎插件
    
    独有杀手锏能力:
    1. 学习用户时间模式
    2. 预测下一步任务
    3. 预先加载上下文到工作记忆
    4. 定期扫描并更新预测
    """
    
    info = PluginInfo(
        name="predictor",
        version="1.0.0",
        description="预测引擎 — 时间模式学习 + 上下文预加载 (世界首创)",
        author="meshctx",
    )
    
    def __init__(self):
        self.learner = TemporalPatternLearner()
        self.preloader = ContextPreloader()
        self._scan_task: Optional[asyncio.Task] = None
        self._prediction_interval = 300  # 5分钟扫描一次
        
    async def on_load(self):
        """注册事件处理器，启动定期扫描"""
        bus = self.kernel.bus
        
        # 监听用户活动
        bus.subscribe("user.activity", self._on_user_activity,
                      plugin_name="predictor")
        bus.subscribe("task.completed", self._on_task_completed,
                      plugin_name="predictor")
        bus.subscribe("predictor.predict", self._on_predict_request,
                      plugin_name="predictor")
        bus.subscribe("predictor.report", self._on_report_request,
                      plugin_name="predictor")
        
        # 启动定期预测扫描
        self._scan_task = asyncio.create_task(self._prediction_loop())
        
        logger.info("预测引擎已加载 (世界首创: 时间模式学习+上下文预加载)")
    
    async def on_unload(self):
        if self._scan_task:
            self._scan_task.cancel()
        logger.info("预测引擎已卸载")
    
    # ── 事件处理器 ────────────────────────────────────────
    
    async def _on_user_activity(self, event: Event):
        """用户活动 → 学习模式"""
        data = event.data
        self.learner.record(
            task_type=data.get("task_type", "general"),
            project_id=data.get("project_id"),
            keywords=data.get("keywords", []),
            duration=data.get("duration", 0),
            success=data.get("success", True),
        )
    
    async def _on_task_completed(self, event: Event):
        """任务完成 → 提取模式"""
        data = event.data
        task_type = data.get("task_type", data.get("description", "general")[:30])
        
        self.learner.record(
            task_type=task_type,
            project_id=data.get("project_id"),
            keywords=data.get("keywords", []),
            duration=data.get("duration_seconds", 0),
            success=data.get("status") == "success",
        )
        
        # 触发即时预测
        predictions = self.learner.predict(top_k=2)
        for pred in predictions:
            if self.preloader.should_preload(pred):
                ctx = self.preloader.preload(pred)
                await self.kernel.bus.publish(Event(
                    type="context.preloaded",
                    source="predictor",
                    data=ctx,
                ))
    
    async def _on_predict_request(self, event: Event):
        """显式预测请求"""
        predictions = self.learner.predict(top_k=5)
        await self.kernel.bus.publish(Event(
            type="predictor.result",
            source="predictor",
            correlation_id=event.id,
            data={
                "predictions": [
                    {
                        "task_type": p.task_type,
                        "confidence": round(p.confidence, 3),
                        "reason": p.reason,
                        "keywords": p.keywords,
                    }
                    for p in predictions
                ],
            },
        ))
    
    async def _on_report_request(self, event: Event):
        """生成预测报告"""
        stats = self.learner.get_stats()
        preloaded = self.preloader.get_preloaded()
        
        await self.kernel.bus.publish(Event(
            type="predictor.report_result",
            source="predictor",
            correlation_id=event.id,
            data={
                "stats": stats,
                "active_preloads": len(preloaded),
                "recent_preloads": [
                    {
                        "task_type": p["prediction"]["task_type"],
                        "confidence": p["prediction"]["confidence"],
                        "reason": p["prediction"]["reason"],
                    }
                    for p in list(preloaded)[-5:]
                ],
            },
        ))
    
    async def _prediction_loop(self):
        """定期预测扫描循环"""
        while True:
            try:
                await asyncio.sleep(self._prediction_interval)
                
                predictions = self.learner.predict(top_k=3)
                
                for pred in predictions:
                    if self.preloader.should_preload(pred):
                        ctx = self.preloader.preload(pred)
                        
                        # 将预加载上下文注入记忆系统
                        await self.kernel.bus.publish(Event(
                            type="context.preloaded",
                            source="predictor",
                            priority=EventPriority.LOW,
                            data=ctx,
                        ))
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"预测循环错误: {e}")
    
    def generate_report(self) -> Dict[str, Any]:
        """生成可读报告"""
        stats = self.learner.get_stats()
        predictions = self.learner.predict(top_k=5)
        preloaded = self.preloader.get_preloaded()
        
        return {
            "patterns_learned": stats["patterns_learned"],
            "total_events": stats["total_events"],
            "top_patterns": stats["top_patterns"],
            "current_predictions": [
                {
                    "task": p.task_type,
                    "confidence": f"{p.confidence:.0%}",
                    "reason": p.reason,
                }
                for p in predictions
            ],
            "active_preloads": [
                {
                    "task": p["prediction"]["task_type"],
                    "confidence": f"{p['prediction']['confidence']:.0%}",
                }
                for p in preloaded
            ],
        }
