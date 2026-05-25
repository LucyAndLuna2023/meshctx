"""Real-time Notification Hub — v2.97"""
import json, logging, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

class NotifyLevel(Enum): INFO="info"; WARN="warn"; ERROR="error"; SUCCESS="success"

@dataclass
class Notification:
    id: str; title: str; message: str; level: NotifyLevel = NotifyLevel.INFO
    timestamp: float = field(default_factory=time.time); read: bool = False
    action_url: str = ""; source: str = "system"

class NotifyHub:
    def __init__(self, max_size: int = 200):
        self._notifications: deque = deque(maxlen=max_size)
        self._subscribers: List[callable] = []
    def notify(self, title: str, message: str, level: NotifyLevel = NotifyLevel.INFO, action: str = "", source: str = "system") -> Notification:
        n = Notification(id=f"notif-{int(time.time())}-{len(self._notifications)}", title=title, message=message, level=level, action_url=action, source=source)
        self._notifications.append(n)
        for cb in self._subscribers:
            try: cb(n)
            except: pass
        return n
    def subscribe(self, callback: callable): self._subscribers.append(callback)
    def get_unread(self) -> List[Notification]: return [n for n in self._notifications if not n.read]
    def mark_read(self, nid: str):
        for n in self._notifications:
            if n.id == nid: n.read = True; break
    def get_recent(self, n: int = 10) -> List[Dict]:
        return [{"id":n.id,"title":n.title,"level":n.level.value,"time":n.timestamp,"read":n.read} for n in list(self._notifications)[-n:]]
    def get_stats(self) -> Dict:
        unread = len(self.get_unread())
        return {"total": len(self._notifications), "unread": unread, "subscribers": len(self._subscribers)}

_hub: Optional[NotifyHub] = None
def get_notify_hub() -> NotifyHub:
    global _hub
    if _hub is None: _hub = NotifyHub()
    return _hub
