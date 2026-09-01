# -*- coding: utf-8 -*-
"""STUB — Enterprise 私有模块 (2026-08-31 迁移)。
完整实现: 私有库 meshctx-enterprise。
"""

_IMPLEMENTATION_MOVED = True

from src.core._enterprise_base import _enterprise_stub, EnterpriseFeatureError

from fastapi import APIRouter
router = APIRouter(prefix="/ui/crews", tags=["crews"])  # STUB: 空路由, 企业功能 501

@router.get("/")
async def _crews_stub():
    from src.core._enterprise_base import EnterpriseFeatureError
    raise EnterpriseFeatureError()

logger = None
def crews_page(*a, **k):
    return _enterprise_stub(*a, **k)
def crews_clone(*a, **k):
    return _enterprise_stub(*a, **k)
def crews_run(*a, **k):
    return _enterprise_stub(*a, **k)
def crews_dag(*a, **k):
    return _enterprise_stub(*a, **k)
def crews_feed(*a, **k):
    return _enterprise_stub(*a, **k)
def agents_page(*a, **k):
    return _enterprise_stub(*a, **k)
def agents_create(*a, **k):
    return _enterprise_stub(*a, **k)
def agents_clone(*a, **k):
    return _enterprise_stub(*a, **k)
def agents_delete(*a, **k):
    return _enterprise_stub(*a, **k)
def tuning_page(*a, **k):
    return _enterprise_stub(*a, **k)
def tuning_loop(*a, **k):
    return _enterprise_stub(*a, **k)
