"""API Gateway Rate Limiter — v3.01"""
import time, logging
from collections import defaultdict, deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_rpm: int = 100, max_concurrent: int = 10):
        self.max_rpm = max_rpm; self.max_concurrent = max_concurrent
        self._window: deque = deque(); self._concurrent: int = 0
        self._blocked: int = 0; self._by_ip: Dict[str, deque] = defaultdict(deque)

    def allow(self, ip: str = "default") -> bool:
        now = time.time()
        # 清理旧记录
        while self._window and self._window[0] < now - 60:
            self._window.popleft()
        while self._by_ip[ip] and self._by_ip[ip][0] < now - 60:
            self._by_ip[ip].popleft()

        if len(self._window) >= self.max_rpm or len(self._by_ip[ip]) >= self.max_rpm / 2:
            self._blocked += 1; return False
        if self._concurrent >= self.max_concurrent:
            self._blocked += 1; return False

        self._window.append(now); self._by_ip[ip].append(now); return True

    def acquire(self): self._concurrent += 1
    def release(self): self._concurrent = max(0, self._concurrent - 1)

    def get_stats(self) -> Dict:
        return {"rpm_limit": self.max_rpm, "current_rpm": len(self._window),
                "concurrent": self._concurrent, "blocked_total": self._blocked,
                "ips_tracked": len(self._by_ip)}

_limiter: Optional[RateLimiter] = None
def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None: _limiter = RateLimiter()
    return _limiter
