"""Time Series Predictor — v3.21"""
import logging, time
from collections import deque
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class TimeSeriesPredictor:
    def __init__(self, window: int = 20):
        self.window = window; self._series: Dict[str, deque] = {}
    
    def add(self, name: str, value: float):
        if name not in self._series: self._series[name] = deque(maxlen=self.window)
        self._series[name].append((time.time(), value))
    
    def predict(self, name: str, steps: int = 1) -> Dict:
        series = self._series.get(name)
        if not series or len(series) < 3:
            return {"name": name, "prediction": None, "error": "需要至少3个数据点"}
        
        values = [v for _, v in series]
        # Simple linear regression
        n = len(values); x = list(range(n))
        x_mean = (n-1)/2; y_mean = sum(values)/n
        slope = sum((x[i]-x_mean)*(values[i]-y_mean) for i in range(n)) / max(0.001, sum((xi-x_mean)**2 for xi in x))
        intercept = y_mean - slope * x_mean
        
        predictions = [round(intercept + slope * (n + i), 2) for i in range(steps)]
        trend = "up" if slope > 0.01 else "down" if slope < -0.01 else "flat"
        
        return {"name": name, "slope": round(slope, 4), "intercept": round(intercept, 4),
                "prediction": predictions, "trend": trend, "data_points": n}
    
    def get_stats(self) -> Dict:
        return {"series": len(self._series), "names": list(self._series.keys())[:10]}

_predictor: Optional[TimeSeriesPredictor] = None
def get_time_series_predictor() -> TimeSeriesPredictor:
    global _predictor
    if _predictor is None: _predictor = TimeSeriesPredictor()
    return _predictor
