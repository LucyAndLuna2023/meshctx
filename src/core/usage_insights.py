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

    def get_summary(self, days: int = 30) -> Dict:
        """兼容API的get_summary方法"""
        return self.insights()
    
    def get_today(self) -> Dict:
        """今日数据"""
        day = time.strftime("%Y-%m-%d")
        records = self._daily.get(day, [])
        return self._summarize_records(records, "today")
    
    def get_weekly(self) -> Dict:
        """本周数据"""
        import datetime
        cutoff = time.time() - 7 * 86400
        records = [r for r in self._records if r.timestamp >= cutoff]
        return self._summarize_records(records, "weekly")
    
    def get_monthly(self) -> Dict:
        """本月数据"""
        import datetime
        cutoff = time.time() - 30 * 86400
        records = [r for r in self._records if r.timestamp >= cutoff]
        return self._summarize_records(records, "monthly")
    
    def get_provider_stats(self) -> Dict:
        """Provider统计"""
        providers = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0, "errors": 0})
        for r in self._records:
            p = r.model.split("/")[0] if "/" in r.model else "unknown"
            providers[p]["calls"] += 1
            providers[p]["tokens"] += r.tokens
            providers[p]["cost"] += r.cost
            if not r.success:
                providers[p]["errors"] += 1
        return dict(providers)
    
    def get_model_stats(self) -> Dict:
        """Model统计"""
        models = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0, "errors": 0})
        for r in self._records:
            m = r.model or "unknown"
            models[m]["calls"] += 1
            models[m]["tokens"] += r.tokens
            models[m]["cost"] += r.cost
            if not r.success:
                models[m]["errors"] += 1
        return dict(models)
    
    def record_session_start(self):
        """记录会话开始"""
        self.record("session_start", tokens=0)
    
    def record_llm_call(self, model: str = "unknown", provider: str = "", 
                        tokens: int = 0, latency_ms: float = 0, error: bool = False):
        """记录LLM API调用"""
        self.record(action="llm_call", tokens=tokens, duration_ms=latency_ms,
                    model=model, success=not error)
    
    def _summarize_records(self, records: list, period: str) -> Dict:
        """汇总记录"""
        if not records:
            return {"period": period, "status": "no_data", "total_tokens": 0, "total_cost": 0}
        total_tokens = sum(r.tokens for r in records)
        total_cost = sum(r.cost for r in records)
        total_time = sum(r.duration_ms for r in records)
        success_rate = sum(1 for r in records if r.success) / len(records) * 100 if records else 0
        actions = defaultdict(int)
        for r in records:
            actions[r.action] += 1
        top = sorted(actions.items(), key=lambda x: -x[1])[:5]
        return {
            "period": period,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 3),
            "total_time_s": round(total_time / 1000, 1),
            "success_rate": f"{success_rate:.0f}%",
            "top_actions": top,
            "record_count": len(records),
        }

_insights = None
def get_usage_insights():
    global _insights
    if _insights is None: _insights = UsageInsights()
    return _insights
