"""
meshctx Webhook 订阅系统 (对标 OpenClaw)
支持: 事件订阅/过滤/路由/重试/webhook密钥验证
"""
import asyncio, hashlib, hmac, json, logging, time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from urllib.request import Request, urlopen

try:
    from .kernel import Event, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, Plugin, PluginInfo

logger = logging.getLogger("meshctx.webhook")

@dataclass
class WebhookSubscription:
    id: str; url: str; events: List[str] = field(default_factory=list)
    secret: str = ""; active: bool = True
    retry_count: int = 3; timeout: int = 10
    created_at: float = field(default_factory=time.time)
    last_sent: float = 0; failure_count: int = 0

class WebhookManager:
    def __init__(self):
        self._subs: Dict[str, WebhookSubscription] = {}
    
    def subscribe(self, id: str, url: str, events: List[str], secret: str = ""):
        self._subs[id] = WebhookSubscription(id=id, url=url, events=events, secret=secret)
        logger.info(f"Webhook订阅: {id} → {url} ({len(events)}个事件)")
    
    def unsubscribe(self, id: str): self._subs.pop(id, None)
    
    def match(self, event_type: str) -> List[WebhookSubscription]:
        return [s for s in self._subs.values() if s.active and (
            "*" in s.events or event_type in s.events or
            any(event_type.startswith(e.replace("*","")) for e in s.events if "*" in e)
        )]
    
    async def deliver(self, event: Event):
        subs = self.match(event.type)
        for sub in subs:
            await self._send(sub, {"type":event.type,"source":event.source,"data":event.data,"timestamp":event.timestamp})
    
    async def _send(self, sub: WebhookSubscription, payload: dict):
        body = json.dumps(payload).encode()
        headers = {"Content-Type":"application/json"}
        if sub.secret:
            sig = hmac.new(sub.secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={sig}"
        
        for attempt in range(sub.retry_count):
            try:
                req = Request(sub.url, data=body, headers=headers)
                urlopen(req, timeout=sub.timeout)
                sub.last_sent = time.time(); sub.failure_count = 0
                return
            except Exception as e:
                if attempt == sub.retry_count - 1:
                    sub.failure_count += 1
                    logger.warning(f"Webhook发送失败 [{sub.id}]: {e}")
                await asyncio.sleep(2 ** attempt)
    
    def stats(self) -> Dict:
        return {"subscriptions":len(self._subs),"active":sum(1 for s in self._subs.values() if s.active),
                "details":[{"id":s.id,"url":s.url[:50],"events":len(s.events),"failures":s.failure_count} for s in self._subs.values()]}


class WebhookPlugin(Plugin):
    info = PluginInfo(name="webhook", version="1.0.0",
        description="Webhook订阅管理 — 事件过滤+路由+重试+签名验证", author="meshctx")
    
    def __init__(self):
        self.manager = WebhookManager()
    
    async def on_load(self):
        self.kernel.bus.subscribe("*", self._on_any_event, plugin_name="webhook")
        self.kernel.bus.subscribe("webhook.subscribe", self._on_sub, plugin_name="webhook")
        logger.info("Webhook订阅系统已加载")
    
    async def on_unload(self): pass
    
    async def _on_any_event(self, event: Event):
        await self.manager.deliver(event)
    
    async def _on_sub(self, event: Event):
        d = event.data
        action = d.get("action","subscribe")
        if action == "subscribe":
            self.manager.subscribe(d["id"], d["url"], d.get("events",["*"]), d.get("secret",""))
        elif action == "unsubscribe":
            self.manager.unsubscribe(d["id"])
