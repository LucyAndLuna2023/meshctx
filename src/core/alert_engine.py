"""
meshctx v3.60 — Alert Engine (智能告警引擎)

功能:
  1. 多级告警: CRITICAL/HIGH/MEDIUM/LOW
  2. 多通道通知: 飞书/Webhook/Email/终端
  3. 告警抑制: 相同告警N秒内不重复
  4. 升级策略: 未处理自动升级优先级
"""
import logging, time, json, urllib.request
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Callable, Optional

logger = logging.getLogger("meshctx.alert_engine")

class AlertLevel(Enum):
    CRITICAL="critical"; HIGH="high"; MEDIUM="medium"; LOW="low"

@dataclass
class Alert:
    id: str=field(default_factory=lambda: f"alert-{int(time.time()*1000)}")
    level: AlertLevel=AlertLevel.MEDIUM; title: str=""; message: str=""
    source: str=""; timestamp: float=field(default_factory=time.time)
    acknowledged: bool=False; escalated: bool=False

class AlertEngine:
    def __init__(self, feishu_webhook: str=""):
        self._alerts: deque=deque(maxlen=200); self._suppressed: Dict[str,float]={}
        self._suppress_seconds=300; self._channels: Dict[str,Callable]={}
        self._feishu_webhook=feishu_webhook
        self._register_channels()
    
    def _register_channels(self):
        self._channels["terminal"] = lambda a: logger.warning(f"[{a.level.value.upper()}] {a.title}: {a.message}")
        if self._feishu_webhook:
            self._channels["feishu"] = self._send_feishu
    
    def alert(self, level: AlertLevel, title: str, message: str, source: str="") -> Alert:
        key = f"{level.value}:{title[:30]}"
        if key in self._suppressed and time.time()-self._suppressed[key] < self._suppress_seconds:
            return None
        self._suppressed[key] = time.time()
        
        a = Alert(level=level, title=title, message=message, source=source)
        self._alerts.append(a)
        for ch, fn in self._channels.items():
            try: fn(a)
            except Exception:
                logger.debug(f"Alert channel {ch} failed", exc_info=True)
        return a
    
    def _send_feishu(self, a: Alert):
        if not self._feishu_webhook: return
        data = json.dumps({"msg_type":"interactive","card":{"header":{"title":{"content":f"[{a.level.value.upper()}] {a.title}","tag":"red" if a.level==AlertLevel.CRITICAL else "yellow"}},"elements":[{"tag":"div","text":{"content":a.message}}]}}).encode()
        try: urllib.request.urlopen(urllib.request.Request(self._feishu_webhook, data=data, headers={"Content-Type":"application/json"}), timeout=5)
        except Exception:
            logger.debug("Failed to send feishu alert", exc_info=True)
    
    def acknowledge(self, alert_id: str) -> bool:
        for a in self._alerts:
            if a.id == alert_id: a.acknowledged=True; return True
        return False
    
    def escalate(self, alert_id: str) -> bool:
        for a in self._alerts:
            if a.id == alert_id and not a.escalated:
                levels = list(AlertLevel)
                idx = levels.index(a.level)
                if idx > 0: a.level=levels[idx-1]; a.escalated=True; return True
        return False
    
    def auto_escalate(self, timeout: int=3600) -> int:
        count=0; now=time.time()
        for a in self._alerts:
            if not a.acknowledged and not a.escalated and now-a.timestamp > timeout:
                if self.escalate(a.id): count+=1
        return count
    
    def get_stats(self) -> Dict:
        recent = list(self._alerts)[-50:]
        return {"total": len(self._alerts),
                "by_level": {l.value:sum(1 for a in recent if a.level==l) for l in AlertLevel},
                "unacknowledged": sum(1 for a in recent if not a.acknowledged)}

_alert_engine = None
def get_alert_engine(webhook=""):
    global _alert_engine
    if _alert_engine is None: _alert_engine = AlertEngine(webhook)
    return _alert_engine
