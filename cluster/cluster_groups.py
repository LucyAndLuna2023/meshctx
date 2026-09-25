# -*- coding: utf-8 -*-
"""[Team Edition 功能] 部门/项目共享信息通道 v6.2 — 完整实现已迁 meshctx-team 私有库。

_ENTERPRISE_FEATURE_MOVED (与 src/core stub 同款 fail-closed 口径)

归属: github.com/LucyAndLuna2023/meshctx-team (Proprietary, 团队版 $9 协作核心)
依据: docs/ENTERPRISE_MIGRATION.md — 团队/企业协作功能开源库只留 stub;
     本文件保留 API 形态 (可 import), 调用即抛 TeamFeatureError。
安装: install-edition.sh team / enterprise 自动合并私有库恢复完整功能。
"""
_ORG = "default"


class TeamFeatureError(ImportError):
    """团队版功能在开源库不可用 (501 team_feature_moved)."""


def __getattr__(name):
    """PEP 562: 任何符号访问都提示迁移 — 防半实现漂移."""
    if name.startswith("__"):
        raise AttributeError(name)
    raise TeamFeatureError(
        f"cluster_groups.{name} 属团队版功能 (部门/项目共享信息通道), "
        f"完整实现见 github.com/LucyAndLuna2023/meshctx-team — "
        f"安装: install-edition.sh team")
