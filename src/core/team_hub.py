# -*- coding: utf-8 -*-
"""STUB — Team/Enterprise 私有模块 (2026-09-02 规划, Agent Hub 组织级治理)。

Agent 派活中心 (Agent Hub) 的开源核心 (task_cards.py / task_cards_api.py /
task_card_runner.py) 已在 meshctx-public 完整实现, 个人版免费全功能。

本模块承载 **组织级治理扩展** (Team $9 / Enterprise $29 卖点), 已规划迁移
至私有库 meshctx-team / meshctx-enterprise:

- 团队共享任务队列 / 看板 / 跨成员委派 (team)
- admin 配额预算与超限策略、Always-approve 域管理 (team/enterprise)
- 审批审计日志 (挂 audit_logger, enterprise)、SSO 集成 (enterprise)

机制 (与既有 stub 一致): 私有安装器物理覆盖 src/core/team_hub.py,
install-edition 合并白名单已含 src/core/*.py → 无需改安装器。
"""

_IMPLEMENTATION_MOVED = True

from ._enterprise_base import _enterprise_stub, EnterpriseFeatureError


def team_hub_available(*a, **k):
    """团队派活中心可用性 — 开源个人版不提供 (返回 False, 不抛错)。"""
    return False


def get_team_hub(*a, **k):
    """获取团队派活中心 (开源个人版不可用)。"""
    return _enterprise_stub(*a, **k)


def shared_queue(*a, **k):
    return _enterprise_stub(*a, **k)


def quota_policy(*a, **k):
    return _enterprise_stub(*a, **k)


def approval_domain(*a, **k):
    return _enterprise_stub(*a, **k)


logger = None

__all__ = ["team_hub_available", "get_team_hub", "shared_queue",
           "quota_policy", "approval_domain"]
