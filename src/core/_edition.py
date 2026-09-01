# -*- coding: utf-8 -*-
"""meshctx Edition 检测与门控 (2026-08-31)。

三版本: personal (free) / team ($9) / enterprise ($29)。
由安装的私有库决定:
- personal: 无私有库 → enterprise 模块 stub, 企业路由隐藏
- team:     有 meshctx-team → 团队功能开放, 企业(SSO等)仍 stub
- enterprise: 有 team+enterprise → 全部开放

P2-2 (002meshctx 审计): 用 __file__ 定位模块, 不依赖 cwd —
systemd/非项目根启动也正确检测 (此前 from src.core import sso 依赖 cwd)。
"""
import importlib.util
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _module_is_stub(mod_name: str) -> bool:
    """按路径检查模块文件是否 stub (含 _IMPLEMENTATION_MOVED)。"""
    path = os.path.join(_THIS_DIR, f"{mod_name}.py")
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
        return "_IMPLEMENTATION_MOVED" in head
    except Exception:
        return True  # 文件缺失 → 视为 stub (fail-closed)


def detect_edition() -> str:
    # sso 完整 (非 stub) → enterprise
    if not _module_is_stub("sso"):
        return "enterprise"
    # team_memory 完整 → team
    if not _module_is_stub("team_memory"):
        return "team"
    return "personal"


def enterprise_available() -> bool:
    return detect_edition() == "enterprise"


def team_available() -> bool:
    return detect_edition() in ("team", "enterprise")
