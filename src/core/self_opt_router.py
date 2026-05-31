"""
meshctx v3.53 — Self-Optimizing Router (自优化路由器)

闭环: FeedbackLoop数据 → 路由策略自适应 → 成本/性能最优

功能:
  1. 模型成功率追踪: 哪个模型对哪类任务最有效
  2. 动态成本优化: 简单任务自动降级到便宜模型
  3. 延迟自适应: 超时→切换更快的模型
  4. 错误恢复: 某模型连续失败→自动切换备选
"""
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.self_opt_router")


@dataclass
class ModelPerformance:
    """模型表现追踪"""
    model_name: str = ""
    total_calls: int = 0
    success: int = 0
    failed: int = 0
    avg_latency_ms: float = 0
    total_cost: float = 0.0
    error_types: Dict[str, int] = field(default_factory=dict)
    last_used: float = 0
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        return self.success / self.total_calls if self.total_calls > 0 else 1.0
    
    @property
    def avg_cost_per_call(self) -> float:
        return self.total_cost / self.total_calls if self.total_calls > 0 else 0
    
    @property
    def health_score(self) -> float:
        """综合健康分 0-100"""
        if self.total_calls < 3:
            return 50
        sr = self.success_rate * 60
        lat = max(0, 20 - self.avg_latency_ms / 500) if self.avg_latency_ms > 0 else 20
        cf = max(0, 20 - self.consecutive_failures * 10)
        return min(100, sr + lat + cf)


class SelfOptimizingRouter:
    """
    自优化路由器
    
    利用FeedbackLoop的执行数据:
    - 模型A对代码任务95%成功→优先路由代码任务到A
    - 模型B平均延迟2000ms→降级, 用模型C(500ms)
    - 模型D连续失败3次→自动排除
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._performances: Dict[str, ModelPerformance] = {}
        self._routing_rules: Dict[str, str] = {}  # task_type → preferred_model
        self._excluded_models: set = set()
        self._routing_history: deque = deque(maxlen=100)
        
        # 模型价格($/1M tokens)
        self._model_costs = {
            "deepseek-chat": 0.14,
            "deepseek-v4-pro": 0.50,
            "gpt-4o": 5.00,
            "gpt-4o-mini": 0.15,
            "claude-sonnet-4": 3.00,
            "claude-haiku": 0.25,
        }
        
        self._consecutive_fail_threshold = 3
        self._health_threshold = 30
    
    def record_call(self, model_name: str, task_type: str, 
                    success: bool, latency_ms: float, cost: float = 0,
                    error_type: str = ""):
        """记录一次模型调用"""
        perf = self._performances.get(model_name)
        if perf is None:
            perf = ModelPerformance(model_name=model_name)
            self._performances[model_name] = perf
        
        perf.total_calls += 1
        if success:
            perf.success += 1
            perf.consecutive_failures = 0
        else:
            perf.failed += 1
            perf.consecutive_failures += 1
            if error_type:
                perf.error_types[error_type] = perf.error_types.get(error_type, 0) + 1
        
        perf.avg_latency_ms = (perf.avg_latency_ms * (perf.total_calls - 1) + latency_ms) / perf.total_calls
        perf.total_cost += cost
        perf.last_used = time.time()
        
        # 自动更新路由规则
        self._update_rules(model_name, task_type)
        
        # 连续失败→排除
        if perf.consecutive_failures >= self._consecutive_fail_threshold:
            self._excluded_models.add(model_name)
            logger.warning(f"Excluded {model_name}: {perf.consecutive_failures} consecutive failures")
        
        # 恢复检查
        if model_name in self._excluded_models and perf.consecutive_failures == 0:
            self._excluded_models.discard(model_name)
            logger.info(f"Restored {model_name}: recovered")
    
    def _update_rules(self, model_name: str, task_type: str):
        """更新路由规则"""
        perf = self._performances.get(model_name)
        if not perf or perf.total_calls < 5:
            return
        
        # 当前最佳模型
        current_best = self._routing_rules.get(task_type)
        
        if current_best is None:
            self._routing_rules[task_type] = model_name
            return
        
        current_perf = self._performances.get(current_best)
        if current_perf and perf.health_score > current_perf.health_score:
            self._routing_rules[task_type] = model_name
            logger.info(f"Route updated: {task_type} → {model_name} (score: {perf.health_score:.0f} > {current_perf.health_score:.0f})")
    
    def route(self, task_type: str, complexity: str = "medium", 
              max_cost: Optional[float] = None) -> str:
        """
        路由决策
        Returns: model_name
        """
        # 1. 优先用路由规则
        preferred = self._routing_rules.get(task_type)
        if preferred and preferred not in self._excluded_models:
            perf = self._performances.get(preferred)
            if perf and perf.health_score >= self._health_threshold:
                return preferred
        
        # 2. 按复杂度选择
        candidates = [m for m in self._performances.keys() 
                     if m not in self._excluded_models]
        
        if not candidates:
            # 全部被排除 → 用第一个可用的
            candidates = list(self._performances.keys())
            if not candidates:
                return "deepseek-chat"  # fallback
        
        # 根据复杂度+成本筛选
        if complexity == "simple":
            # 找最便宜且健康的
            cheap = [(m, self._model_costs.get(m, 1.0)) for m in candidates]
            cheap.sort(key=lambda x: x[1])
            for m, _ in cheap:
                perf = self._performances.get(m)
                if perf and perf.health_score >= self._health_threshold:
                    return m
            return cheap[0][0] if cheap else candidates[0]
        
        elif complexity == "complex":
            # 找最高健康分的
            scored = [(m, self._performances[m].health_score) 
                     for m in candidates if m in self._performances]
            scored.sort(key=lambda x: -x[1])
            if scored:
                best_m, best_s = scored[0]
                if best_s >= self._health_threshold:
                    return best_m
        
        # 3. 成本限制
        if max_cost is not None:
            within_budget = [m for m in candidates 
                           if self._model_costs.get(m, 1.0) <= max_cost]
            if within_budget:
                return within_budget[0]
        
        # 4. Fallback: 第一个健康的
        for m in candidates:
            perf = self._performances.get(m)
            if perf and perf.health_score >= self._health_threshold:
                return m
        
        return candidates[0] if candidates else "deepseek-chat"
    
    def get_best_for_task(self, task_type: str) -> Optional[str]:
        """获取某任务类型的最佳模型"""
        best_model = None
        best_score = -1
        
        for name, perf in self._performances.items():
            if name in self._excluded_models:
                continue
            if task_type in self._routing_rules and self._routing_rules[task_type] == name:
                return name
            if perf.health_score > best_score and perf.total_calls >= 3:
                best_score = perf.health_score
                best_model = name
        
        return best_model
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "models_tracked": len(self._performances),
            "routing_rules": dict(self._routing_rules),
            "excluded": list(self._excluded_models),
            "performances": {
                name: {
                    "calls": p.total_calls,
                    "success_rate": f"{p.success_rate*100:.1f}%",
                    "avg_latency": f"{p.avg_latency_ms:.0f}ms",
                    "health_score": f"{p.health_score:.0f}",
                    "consecutive_fails": p.consecutive_failures,
                }
                for name, p in self._performances.items()
            },
            "routing_history": len(self._routing_history),
        }


_router: Optional[SelfOptimizingRouter] = None

def get_self_opt_router() -> SelfOptimizingRouter:
    global _router
    if _router is None:
        _router = SelfOptimizingRouter()
    return _router
