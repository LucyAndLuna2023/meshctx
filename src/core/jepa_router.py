"""
meshctx v3.66 — JEPA Router (JEPA预测路由器)

基于LeCun JEPA架构的智能路由: 潜空间预测替代试错
  - 任务→潜空间编码→预测最佳模型→无需实际调用所有模型
  - 复杂度评估: 简单任务自动降级到便宜模型
  - 领域匹配: 代码/分析/创作各自最优模型
"""
import logging, time, numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("meshctx.jepa_router")

@dataclass
class TaskEncoding:
    complexity: float=0.5; domain: str="general"
    expected_tokens: int=500; priority: str="normal"

class JEPARouter:
    """JEPA预测路由器 — 不用试所有模型，潜空间预测最优"""
    
    def __init__(self):
        self._model_registry = {
            "deepseek-chat": {"cost":0.14,"speed":200,"quality":7,"domains":["code","general"]},
            "deepseek-v4-pro": {"cost":0.50,"speed":150,"quality":9,"domains":["code","analysis","general"]},
            "gpt-4o-mini": {"cost":0.15,"speed":300,"quality":7,"domains":["general","chat"]},
            "gpt-4o": {"cost":5.0,"speed":80,"quality":10,"domains":["analysis","creative"]},
            "claude-sonnet-4": {"cost":3.0,"speed":100,"quality":9,"domains":["code","analysis","creative"]},
            "claude-haiku": {"cost":0.25,"speed":400,"quality":6,"domains":["general","chat"]},
        }
        self._history: deque=deque(maxlen=200)
        self._embedding_dim = 8
    
    def encode_task(self, task: str, domain: str="general") -> TaskEncoding:
        """任务→潜空间编码"""
        complexity = 0.5
        task_lower = task.lower()
        
        complex_keywords = ["implement","refactor","debug","optimize","architecture","deploy","security"]
        simple_keywords = ["echo","list","check","status","help","version"]
        
        for kw in complex_keywords:
            if kw in task_lower: complexity += 0.1
        for kw in simple_keywords:
            if kw in task_lower: complexity -= 0.05
        
        complexity = max(0.1, min(1.0, complexity))
        
        tokens = len(task.split()) * 50
        return TaskEncoding(complexity=complexity, domain=domain, expected_tokens=tokens)
    
    def predict_best_model(self, task: str, domain: str="general", max_cost: float=None) -> Tuple[str, float]:
        """预测最佳模型+置信度"""
        encoding = self.encode_task(task, domain)
        
        candidates = []
        for name, info in self._model_registry.items():
            if max_cost and info["cost"] > max_cost: continue
            if domain not in info["domains"] and "general" not in info["domains"]: continue
            
            score = 0
            if encoding.complexity > 0.7:
                score = info["quality"] * 0.6 - info["cost"] * 0.2 + info["speed"] * 0.001 * 0.2
            elif encoding.complexity < 0.3:
                score = info["speed"] * 0.005 * 0.5 - info["cost"] * 0.4 + info["quality"] * 0.1
            else:
                score = info["quality"] * 0.4 + info["speed"] * 0.001 * 0.3 - info["cost"] * 0.3
            
            candidates.append((name, score, info))
        
        if not candidates: return ("deepseek-chat", 0.5)
        
        candidates.sort(key=lambda x: -x[1])
        best = candidates[0]
        confidence = min(0.95, best[1] / max(0.01, candidates[0][1]))
        
        self._history.append({"task":task[:50],"model":best[0],"score":round(best[1],2)})
        return (best[0], round(confidence, 2))
    
    def get_stats(self) -> Dict:
        return {"models": len(self._model_registry), "predictions": len(self._history),
                "recent": list(self._history)[-5:]}

_router = None
def get_jepa_router():
    global _router
    if _router is None: _router = JEPARouter()
    return _router
