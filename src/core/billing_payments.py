# -*- coding: utf-8 -*-
"""STUB — Enterprise 私有模块 (2026-08-31 迁移到 meshctx-enterprise 私有库)。
"""

_IMPLEMENTATION_MOVED = True


from ._enterprise_base import _enterprise_stub, EnterpriseFeatureError

logger = None
STRIPE_API = 'https://api.stripe.com/v1'
STRIPE_SECRET_KEY = None
STRIPE_WEBHOOK_SECRET = None
PRICES = {}
def stripe_enabled(*a, **k):
    return _enterprise_stub(*a, **k)
def create_checkout(*a, **k):
    return _enterprise_stub(*a, **k)
def verify_webhook(*a, **k):
    return _enterprise_stub(*a, **k)
def apply_checkout_event(*a, **k):
    return _enterprise_stub(*a, **k)
def payment_status(*a, **k):
    return _enterprise_stub(*a, **k)
