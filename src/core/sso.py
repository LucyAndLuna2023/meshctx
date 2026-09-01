# -*- coding: utf-8 -*-
"""STUB — Enterprise 私有模块 (2026-08-31 迁移到 meshctx-enterprise 私有库)。
"""

_IMPLEMENTATION_MOVED = True


from ._enterprise_base import _enterprise_stub, EnterpriseFeatureError

logger = None
SSO_ISSUER = None
SSO_CLIENT_ID = None
SSO_CLIENT_SECRET = None
SSO_REDIRECT = None
def sso_enabled(*a, **k):
    return _enterprise_stub(*a, **k)
def parse_jwt(*a, **k):
    return _enterprise_stub(*a, **k)
def build_authorize_url(*a, **k):
    return _enterprise_stub(*a, **k)
def exchange_code(*a, **k):
    return _enterprise_stub(*a, **k)
def get_userinfo_from_token(*a, **k):
    return _enterprise_stub(*a, **k)
def sso_config(*a, **k):
    return _enterprise_stub(*a, **k)
