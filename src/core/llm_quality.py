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
