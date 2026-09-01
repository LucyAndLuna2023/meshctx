# -*- coding: utf-8 -*-
"""meshctx Edition 检测与门控 (2026-08-31)。

三版本: personal (free) / team ($9) / enterprise ($29)。
由安装的私有库决定:
- personal: 无私有库 → enterprise 模块 stub, 企业路由隐藏
- team:     有 meshctx-team → 团队功能开放, 企业(SSO等)仍 stub
- enterprise: 有 team+enterprise → 全部开放
"""
import os

# 安装时把私有库 src/core/*.py 合并进 meshctx/src/core/,
# 检测: enterprise 专属模块 (sso) 是否存在且非 stub
def detect_edition() -> str:
    try:
        from src.core import sso as _sso_mod
        _sso_stub = bool(getattr(_sso_mod, "_IMPLEMENTATION_MOVED", False))
        if not _sso_stub:
            return "enterprise"
    except Exception:
        pass
    try:
        from src.core import team_memory as _tm_mod
        _tm_stub = bool(getattr(_tm_mod, "_IMPLEMENTATION_MOVED", False))
        if not _tm_stub:
            return "team"
    except Exception:
        pass
    return "personal"


def enterprise_available() -> bool:
    """企业版专属功能 (SSO/审计/SLA/私有化) 是否可用。"""
    return detect_edition() == "enterprise"


def team_available() -> bool:
    """团队版功能 (共享记忆/群审/仪表盘) 是否可用。"""
    return detect_edition() in ("team", "enterprise")
