# -*- coding: utf-8 -*-
"""STUB — Enterprise 私有模块 (2026-08-31 迁移到 meshctx-enterprise 私有库)。
"""

_IMPLEMENTATION_MOVED = True


from ._enterprise_base import _enterprise_stub, EnterpriseFeatureError

logger = None
DEFAULT_MODELS = ['deepseek:chat', 'deepseek:reasoner', 'openai:gpt-4o', 'anthropic:claude-sonnet', 'google:gemini-pro']
DEFAULT_TIMEOUT = 90
def swarm_ask(*a, **k):
    return _enterprise_stub(*a, **k)
def swarm_stats(*a, **k):
    return _enterprise_stub(*a, **k)
