"""SSO state 管理 — OIDC 登录 CSRF 防护 (2026-08-28 002codex P2)。

authorize 时生成 state 存入内存, callback 时比对后消费 (一次性)。
进程内内存: 自托管单进程可接受; 多进程部署需共享存储 (后续).
"""
import threading
import time
from typing import Any, Dict, Optional

_lock = threading.Lock()
_STATES: Dict[str, Dict[str, Any]] = {}
_TTL = 600  # 10 分钟


def set_state(state: str, data: Optional[Dict[str, Any]] = None) -> None:
    with _lock:
        _cleanup()
        _STATES[state] = {"data": data or {}, "ts": time.time()}


def get_state(state: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _STATES.get(state)
        if entry is None:
            return None
        return entry.get("data")


def consume_state(state: str) -> bool:
    """校验并消费 state (一次性, 防重放)。"""
    with _lock:
        _cleanup()
        entry = _STATES.pop(state, None)
        if entry is None:
            return False
        return (time.time() - entry.get("ts", 0)) <= _TTL


def _cleanup() -> None:
    now = time.time()
    expired = [s for s, e in _STATES.items() if now - e.get("ts", 0) > _TTL]
    for s in expired:
        _STATES.pop(s, None)
