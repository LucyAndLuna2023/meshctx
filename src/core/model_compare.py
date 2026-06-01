"""
meshctx v3.67 — Cross-Model Compare Engine (多模型对比引擎)

同一问题发给多个模型→对比结果→评分→选最优
"""
import logging, time, concurrent.futures
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional

logger = logging.getLogger("meshctx.model_compare")

@dataclass
class ModelResponse:
    model: str; response: str; latency_ms: float; tokens: int=0
    cost: float=0.0; score: float=0.0; error: str=""

class ModelCompareEngine:
    def __init__(self):
        self._compare_history: List[Dict]=[]
    
    def compare(self, prompt: str, models: List[str]=None, 
                executor: Callable=None) -> List[ModelResponse]:
        """多模型对比"""
        if models is None:
            models = ["deepseek-chat","deepseek-v4-pro","gpt-4o-mini"]
        
        results = []
        for model in models:
            t0 = time.perf_counter()
            try:
                resp = executor(prompt, model) if executor else f"[{model}] response to: {prompt[:30]}..."
                latency = (time.perf_counter()-t0)*1000
                results.append(ModelResponse(model=model, response=str(resp)[:200], latency_ms=latency))
            except Exception as e:
                results.append(ModelResponse(model=model, response="", error=str(e), latency_ms=0))
        
        return results
    
    def score_responses(self, responses: List[ModelResponse], criteria: List[str]=None) -> List[ModelResponse]:
        """评分"""
        if criteria is None: criteria = ["length","speed"]
        for r in responses:
            if r.error: r.score=0; continue
            s=50
            if "speed" in criteria: s+=max(0,30-r.latency_ms/100)
            if "length" in criteria: s+=min(20,len(r.response)/10)
            r.score=min(100,s)
        return sorted(responses, key=lambda r:-r.score)
    
    def get_stats(self) -> Dict:
        return {"comparisons": len(self._compare_history)}

_compare = None
def get_compare_engine():
    global _compare
    if _compare is None: _compare = ModelCompareEngine()
    return _compare

# Backward compat
def compare_models(prompt, models=None, executor=None):
    return get_compare_engine().compare(prompt, models, executor)

def compare_models_stream(prompt, models=None, executor=None):
    return get_compare_engine().compare(prompt, models, executor)
