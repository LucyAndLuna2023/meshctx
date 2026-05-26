"""Date/Time Utilities — v3.33"""
import logging, time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class DateTimeUtils:
    def now_iso(self) -> str: return datetime.now().isoformat()
    def now_unix(self) -> float: return time.time()
    def format(self, ts: float = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return datetime.fromtimestamp(ts or time.time()).strftime(fmt)
    def parse(self, s: str, fmt: str = "%Y-%m-%d") -> Optional[datetime]:
        try: return datetime.strptime(s, fmt)
        except: return None
    def ago(self, seconds: int) -> str:
        for unit, secs in [("d",86400),("h",3600),("m",60),("s",1)]:
            if seconds >= secs: return f"{seconds//secs}{unit}前"
        return "刚刚"
    def between(self, start: str, end: str) -> float:
        s = self.parse(start); e = self.parse(end)
        return (e-s).total_seconds() if s and e else 0
    def get_stats(self) -> Dict: return {"tz": time.tzname, "module":"datetime_utils"}

_dt: Optional[DateTimeUtils] = None
def get_datetime_utils() -> DateTimeUtils:
    global _dt
    if _dt is None: _dt = DateTimeUtils()
    return _dt
