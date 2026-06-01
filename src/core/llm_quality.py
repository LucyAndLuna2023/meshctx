"""
meshctx v3.73 — LLM Quality Evaluator (LLM质量评估器)

评估模型输出质量: 相关性/完整性/准确性/安全性
"""
import logging, time, re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.llm_quality")

@dataclass
class QualityScore:
    relevance: float=0.0; completeness: float=0.0; accuracy: float=0.0
    safety: float=0.0; overall: float=0.0

class LLMQualityEvaluator:
    def evaluate(self, prompt: str, response: str) -> QualityScore:
        score = QualityScore()
        
        # Handle empty input
        if not prompt.strip() or not response.strip():
            score.overall = 0.0
            return score
        
        # Relevance: 回复是否包含prompt关键词
        prompt_words = set(re.findall(r'\w+', prompt.lower()))
        resp_words = set(re.findall(r'\w+', response.lower()))
        if prompt_words:
            score.relevance = len(prompt_words & resp_words) / len(prompt_words)
        
        # Completeness: 回复长度是否足够
        if len(prompt) > 10:
            score.completeness = min(1.0, len(response) / max(1, len(prompt) * 2))
        else:
            score.completeness = 0.5
        
        # Accuracy: 是否包含幻觉标记
        hallucination_markers = ["as an AI","I don't know","I cannot","I'm not able","unfortunately"]
        markers_found = sum(1 for m in hallucination_markers if m.lower() in response.lower())
        score.accuracy = max(0.0, 1.0 - markers_found * 0.2)
        
        # Safety: 是否包含危险内容
        unsafe = ["hack","exploit","bypass","illegal","malware","phishing"]
        unsafe_found = sum(1 for u in unsafe if u in response.lower())
        score.safety = max(0.0, 1.0 - unsafe_found * 0.3)
        
        score.overall = round((score.relevance+score.completeness+score.accuracy+score.safety)/4, 2)
        return score

    def compare_models(self, prompt: str, responses: Dict[str,str]) -> Dict:
        results = {}
        for model, resp in responses.items():
            results[model] = self.evaluate(prompt, resp)
        return results

_quality = None
def get_quality_evaluator():
    global _quality
    if _quality is None: _quality = LLMQualityEvaluator()
    return _quality


class LLMQualityMonitor:
    """LLM调用质量实时监控 (v3.83 兼容别名)"""
    def __init__(self, max_history: int=100):
        self._calls: List[Dict] = []
    
    def record_call(self, model: str="", prompt_tokens: int=0, 
                    completion_tokens: int=0, latency_ms: float=0, success: bool=True):
        self._calls.append({
            "model": model, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "latency_ms": latency_ms,
            "success": success, "time": time.time()
        })
    
    def get_stats(self) -> Dict:
        if not self._calls:
            return {"total_calls": 0, "total_prompt_tokens": 0, 
                    "total_completion_tokens": 0, "avg_latency_ms": 0}
        success_calls = [c for c in self._calls if c["success"]]
        return {
            "total_calls": len(self._calls),
            "total_prompt_tokens": sum(c["prompt_tokens"] for c in self._calls),
            "total_completion_tokens": sum(c["completion_tokens"] for c in self._calls),
            "avg_latency_ms": sum(c["latency_ms"] for c in success_calls) / max(1, len(success_calls)),
            "error_count": sum(1 for c in self._calls if not c["success"])
        }
    
    def get_token_waste_ratio(self) -> float:
        if not self._calls: return 0
        wasted = sum(1 for c in self._calls 
                    if c["completion_tokens"] > c["prompt_tokens"] * 3)
        return wasted / len(self._calls)
    
    def get_error_rate(self) -> float:
        if not self._calls: return 0
        return sum(1 for c in self._calls if not c["success"]) / len(self._calls)
    
    def get_latency_trend(self) -> float:
        """返回延迟趋势斜率，正=上升，负=下降"""
        latencies = [c["latency_ms"] for c in self._calls[-10:]]
        if len(latencies) < 2: return 0.0
        n = len(latencies)
        x_avg = (n - 1) / 2
        y_avg = sum(latencies) / n
        num = sum((i - x_avg) * (latencies[i] - y_avg) for i in range(n))
        den = sum((i - x_avg) ** 2 for i in range(n))
        return num / den if den else 0.0
