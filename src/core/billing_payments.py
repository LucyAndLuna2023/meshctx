#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Billing 支付 — Stripe Checkout 订阅 (Team/Enterprise, 2026-08-28)

设计:
- STRIPE_SECRET_KEY 设置时 → 真实 Stripe Checkout Session
- 未设置 (开发/自托管) → 模拟模式: checkout 直接返回模拟确认, webhook 可手动触发
- 支付成功后通过 webhook 调 BusinessStore.set_plan 开通订阅

纯 HTTP (requests) 实现, 无 Stripe SDK 依赖。
"""
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("meshctx.billing")

STRIPE_API = "https://api.stripe.com/v1"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# 定价 (USD/人/月) — 与 BP 一致
PRICES = {"team": {"price_id": os.environ.get("STRIPE_PRICE_TEAM", ""), "amount": 900},
          "enterprise": {"price_id": os.environ.get("STRIPE_PRICE_ENTERPRISE", ""), "amount": 2900}}


def stripe_enabled() -> bool:
    """是否配置了真实 Stripe。"""
    return bool(STRIPE_SECRET_KEY)


def _stripe_post(path: str, data: Dict[str, str]) -> Dict[str, Any]:
    r = requests.post(f"{STRIPE_API}/{path}", auth=(STRIPE_SECRET_KEY, ""),
                      data=data, timeout=30)
    if r.status_code != 200:
        logger.warning(f"Stripe API 错误 ({r.status_code}): {r.text[:200]}")
        return {"error": r.text[:200], "status": r.status_code}
    return r.json()


def create_checkout(plan: str, team_id: str, seats: int,
                    success_url: str, cancel_url: str) -> Dict[str, Any]:
    """创建 Checkout Session。未配置 Stripe 时返回模拟模式。"""
    if not stripe_enabled():
        # 模拟模式: 本地直接返回模拟确认 (自托管/开发)
        return {
            "mode": "simulated",
            "team_id": team_id, "plan": plan, "seats": seats,
            "amount_usd": PRICES.get(plan, {}).get("amount", 0) * seats / 100,
            "checkout_url": "",
            "session_id": f"sim_{uuid.uuid4().hex[:12]}",
            "note": "模拟模式 (未配置 STRIPE_SECRET_KEY) — 开发/自托管使用",
        }
    price = PRICES.get(plan, {}).get("price_id", "")
    if not price:
        return {"error": f"plan {plan} 未配置 STRIPE_PRICE_{plan.upper()}"}
    data = {
        "mode": "subscription",
        "line_items[0][price]": price,
        "line_items[0][quantity]": str(seats),
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata[team_id]": team_id,
        "metadata[plan]": plan,
        "metadata[seats]": str(seats),
    }
    sess = _stripe_post("checkout/sessions", data)
    if "error" in sess:
        return {"error": sess["error"]}
    return {"mode": "stripe", "session_id": sess.get("id", ""),
            "checkout_url": sess.get("url", ""), "team_id": team_id, "plan": plan}


def verify_webhook(payload: bytes, sig_header: str) -> Optional[Dict[str, Any]]:
    """验证 Stripe webhook 签名并解析事件。

    MVP: 未配置 STRIPE_WEBHOOK_SECRET 时直接解析 (自托管可接受),
    配置后校验签名 (timestamp + HMAC-SHA256)。
    """
    try:
        event = json.loads(payload)
    except Exception:
        return None
    # 签名校验 (配置了 secret 时)
    if STRIPE_WEBHOOK_SECRET:
        import hashlib
        import hmac
        try:
            ts, sigs = sig_header.split(",", 1)
            ts = ts.split("=")[1]
            signed = f"{ts}.{payload.decode('utf-8', 'replace')}"
            expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(),
                                signed.encode(), hashlib.sha256).hexdigest()
            if expected not in sigs:
                logger.warning("Stripe webhook 签名不匹配")
                return None
        except Exception as e:
            logger.warning(f"webhook 签名解析失败: {e}")
            return None
    return event


def apply_checkout_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """应用支付事件到 BusinessStore (checkout.session.completed → 开通订阅)。"""
    from src.core.business_plans import get_store
    store = get_store()
    event_type = event.get("type", "")
    if event_type not in ("checkout.session.completed",
                          "invoice.paid", "customer.subscription.updated"):
        return {"ok": False, "reason": f"忽略事件 {event_type}"}
    data = event.get("data", {}).get("object", {})
    meta = data.get("metadata", {}) or {}
    team_id = meta.get("team_id", "")
    plan = meta.get("plan", "team")
    seats = int(meta.get("seats", 5))
    if not team_id or store.get_team(team_id) is None:
        return {"ok": False, "reason": "team not found"}
    months = 1 if event_type == "invoice.paid" else 12
    if not store.set_plan(team_id, plan, seats=seats, months=months):
        return {"ok": False, "reason": "set_plan 失败"}
    store.audit("stripe", "billing.paid", f"team={team_id} plan={plan} seats={seats}",
                team_id=team_id)
    return {"ok": True, "team_id": team_id, "plan": plan}


def payment_status(team_id: str) -> Dict[str, Any]:
    """订阅支付状态。"""
    from src.core.business_plans import get_store
    team = get_store().get_team(team_id)
    if team is None:
        return {"error": "team not found"}
    active = team.subscription_until > time.time() if team.plan != "free" else False
    return {"team_id": team_id, "plan": team.plan,
            "subscription_until": team.subscription_until,
            "subscription_active": active,
            "payment_mode": "stripe" if stripe_enabled() else "simulated",
            "days_left": int((team.subscription_until - time.time()) / 86400) if active else 0}
