"""
meshctx v3.70 — Usage Insights Engine (用量洞察引擎)

分析Agent使用模式→生成优化建议
"""
import logging, time, json
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.usage_insights")

@dataclass
class UsageRecord:
    action: str; tokens: int=0; duration_ms: float=0; cost: float=0.0
    model: str=""; success: bool=True; timestamp: float=field(default_factory=time.time)

class UsageInsights:
    def __init__(self):
        self._records: deque=deque(maxlen=500)
        self._daily: Dict[str,List]=defaultdict(list)
    
    def record(self, action: str, tokens: int=0, duration_ms: float=0, 
               cost: float=0.0, model: str="", success: bool=True):
        r = UsageRecord(action=action, tokens=tokens, duration_ms=duration_ms, 
                         cost=cost, model=model, success=success)
        self._records.append(r)
        day = time.strftime("%Y-%m-%d")
        self._daily[day].append(r)
    
    def insights(self) -> Dict:
        if not self._records: return {"status":"no_data"}
        recent = list(self._records)[-50:]
        total_tokens = sum(r.tokens for r in recent)
        total_cost = sum(r.cost for r in recent)
        total_time = sum(r.duration_ms for r in recent)
        success_rate = sum(1 for r in recent if r.success)/len(recent)*100
        
        actions = defaultdict(int)
        for r in recent: actions[r.action] += 1
        top = sorted(actions.items(), key=lambda x:-x[1])[:5]
        
        suggestions = []
        if total_cost > 1.0: suggestions.append(f"High cost (${total_cost:.2f}), consider cheaper models")
        if total_time > 60000: suggestions.append(f"High latency ({total_time/1000:.0f}s), consider caching")
        if success_rate < 90: suggestions.append(f"Low success rate ({success_rate:.0f}%), review failing actions")
        
        return {"total_tokens": total_tokens, "total_cost": round(total_cost,3),
                "total_time_s": round(total_time/1000,1), "success_rate": f"{success_rate:.0f}%",
                "top_actions": top, "suggestions": suggestions}

_insights = None
def get_usage_insights():
    global _insights
    if _insights is None: _insights = UsageInsights()
    return _insights
