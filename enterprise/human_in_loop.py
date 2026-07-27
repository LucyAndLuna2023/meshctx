"""
human_in_loop.py — 人工审批中间件 (v1.0)

支持三通道:
  1. Slack:   slash command + interactive buttons
  2. 飞书:    卡片消息 + 回调
  3. Web:     polling-based approval page

工作流:
  Agent 请求审批 → HITL.send_approval() → 等待人工 → callback → Agent 继续

安全:
  - 审批超时自动拒绝 (默认 1h)
  - 审批链: 支持多级审批 (L1→L2→L3)
  - 审计: 所有审批记录写入 audit log
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.hitl")


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ApprovalLevel(Enum):
    L1_TEAM_LEAD = 1
    L2_MANAGER = 2
    L3_DIRECTOR = 3


@dataclass
class ApprovalRequest:
    """审批请求."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    title: str = ""
    description: str = ""
    risk_level: str = "low"  # low | medium | high | critical
    level: ApprovalLevel = ApprovalLevel.L1_TEAM_LEAD
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    approver: str = ""
    comment: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalChain:
    """多级审批链."""
    levels: List[ApprovalLevel]
    current: int = 0  # 当前审批层级索引

    def next(self) -> Optional[ApprovalLevel]:
        if self.current + 1 < len(self.levels):
            self.current += 1
            return self.levels[self.current]
        return None

    @property
    def current_level(self) -> Optional[ApprovalLevel]:
        if self.current < len(self.levels):
            return self.levels[self.current]
        return None


class HumanInTheLoop:
    """人工审批中间件.

    Usage:
      hitl = HumanInTheLoop(
        slack_webhook="https://hooks.slack.com/...",
        feishu_webhook="https://open.feishu.cn/...",
        approval_timeout=3600,
      )
      approved = await hitl.request_approval(
          agent_id="devops-001",
          title="生产环境部署 v3.115.31",
          description="更新 brain.py, 影响 11 脑区",
          risk_level="high",
      )
      if approved:
          await deploy()
    """

    def __init__(
        self,
        slack_webhook: str = "",
        slack_signing_secret: str = "",
        feishu_webhook: str = "",
        feishu_app_secret: str = "",
        approval_timeout: int = 3600,
        web_approval_url: str = "",
    ):
        self.slack_webhook = slack_webhook
        self.slack_signing_secret = slack_signing_secret
        self.feishu_webhook = feishu_webhook
        self.feishu_app_secret = feishu_app_secret
        self.approval_timeout = approval_timeout
        self.web_approval_url = web_approval_url

        self._pending: Dict[str, ApprovalRequest] = {}
        self._futures: Dict[str, asyncio.Future] = {}
        self._audit_log: List[Dict] = []

    # ── Request Approval ────────────────────────────────────

    async def request_approval(
        self,
        agent_id: str,
        title: str,
        description: str,
        risk_level: str = "low",
        chain: Optional[ApprovalChain] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """请求人工审批，返回 T/F."""
        req = ApprovalRequest(
            agent_id=agent_id,
            title=title,
            description=description,
            risk_level=risk_level,
            level=chain.current_level if chain else ApprovalLevel.L1_TEAM_LEAD,
            metadata=metadata or {},
        )

        self._pending[req.id] = req
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._futures[req.id] = fut

        # 发送通知到所有通道
        await self._notify_all(req)

        try:
            await asyncio.wait_for(fut, timeout=self.approval_timeout)
            result: ApprovalRequest = fut.result()
            return result.status == ApprovalStatus.APPROVED
        except asyncio.TimeoutError:
            req.status = ApprovalStatus.TIMEOUT
            self._audit(req, "timeout")
            return False
        finally:
            self._futures.pop(req.id, None)

    # ── Resolve (由 webhook 回调调用) ──────────────────────

    def resolve(self, request_id: str, approved: bool, approver: str = "", comment: str = ""):
        """解析审批结果."""
        req = self._pending.get(request_id)
        if not req:
            logger.warning(f"unknown request: {request_id}")
            return False

        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        req.resolved_at = time.time()
        req.approver = approver
        req.comment = comment

        self._audit(req, "resolved")

        fut = self._futures.get(request_id)
        if fut and not fut.done():
            fut.set_result(req)
        return True

    # ── Slack integration ───────────────────────────────────

    async def _notify_slack(self, req: ApprovalRequest):
        """发送 Slack Interactive Message."""
        if not self.slack_webhook:
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"🔔 审批请求: {req.title}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": req.description}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Agent:* {req.agent_id}"},
                {"type": "mrkdwn", "text": f"*风险:* {req.risk_level}"},
                {"type": "mrkdwn", "text": f"*级别:* {req.level.name}"},
                {"type": "mrkdwn", "text": f"*超时:* {self.approval_timeout}s"},
            ]},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✅ 批准"}, "style": "primary", "value": f"approve:{req.id}"},
                {"type": "button", "text": {"type": "plain_text", "text": "❌ 拒绝"}, "style": "danger", "value": f"reject:{req.id}"},
            ]},
        ]
        # 通过 webhook 发送 (简化版)
        import urllib.request
        body = json.dumps({"blocks": blocks}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(self.slack_webhook, data=body, headers={"Content-Type": "application/json"}))
        except Exception as e:
            logger.error(f"slack notify failed: {e}")

    # ── 飞书 integration ────────────────────────────────────

    async def _notify_feishu(self, req: ApprovalRequest):
        """发送飞书卡片消息."""
        if not self.feishu_webhook:
            return
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": f"🔔 {req.title}"}},
                "elements": [
                    {"tag": "markdown", "content": req.description},
                    {"tag": "div", "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**Agent:** {req.agent_id}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**风险:** {req.risk_level}"}},
                    ]},
                    {"tag": "action", "actions": [
                        {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 批准"}, "type": "primary", "value": json.dumps({"action": "approve", "id": req.id})},
                        {"tag": "button", "text": {"tag": "plain_text", "content": "❌ 拒绝"}, "type": "danger", "value": json.dumps({"action": "reject", "id": req.id})},
                    ]},
                ],
            },
        }
        import urllib.request
        body = json.dumps(card).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(self.feishu_webhook, data=body, headers={"Content-Type": "application/json"}))
        except Exception as e:
            logger.error(f"feishu notify failed: {e}")

    # ── Web Approval ─────────────────────────────────────────

    def get_web_approval_url(self, req_id: str) -> str:
        if self.web_approval_url:
            return f"{self.web_approval_url}?id={req_id}"
        return f"/approve?id={req_id}"

    # ── Audit ───────────────────────────────────────────────

    def _audit(self, req: ApprovalRequest, event: str):
        entry = {
            "event": event,
            "request_id": req.id,
            "agent_id": req.agent_id,
            "title": req.title,
            "status": req.status.value,
            "risk_level": req.risk_level,
            "approver": req.approver,
            "timestamp": time.time(),
        }
        self._audit_log.append(entry)
        logger.info(f"📝 HITL audit: {event} → {req.status.value} ({req.id})")

    async def _notify_all(self, req: ApprovalRequest):
        await asyncio.gather(
            self._notify_slack(req),
            self._notify_feishu(req),
            return_exceptions=True,
        )

    def list_pending(self) -> List[ApprovalRequest]:
        return [r for r in self._pending.values() if r.status == ApprovalStatus.PENDING]


# ═══════════════════════════════════════════════════════════════
# Webhook Handler (FastAPI example)
# ═══════════════════════════════════════════════════════════════

def create_webhook_handler(hitl: HumanInTheLoop):
    """创建 FastAPI webhook 路由 (Slack + 飞书)."""

    async def slack_webhook(request: dict):
        """处理 Slack interactive payload."""
        payload = json.loads(request.get("payload", "{}"))
        action = payload.get("actions", [{}])[0]
        value = action.get("value", "")
        if ":" in value:
            act, req_id = value.split(":", 1)
            hitl.resolve(req_id, approved=(act == "approve"), approver=payload.get("user", {}).get("id", ""))
        return {"text": "ok"}

    async def feishu_webhook(request: dict):
        """处理飞书卡片回调."""
        action = json.loads(request.get("action", {}).get("value", "{}"))
        if action.get("action") == "approve":
            hitl.resolve(action["id"], approved=True, approver=request.get("open_id", ""))
        elif action.get("action") == "reject":
            hitl.resolve(action["id"], approved=False, approver=request.get("open_id", ""))
        return {"code": 0}

    return slack_webhook, feishu_webhook
