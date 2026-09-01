# -*- coding: utf-8 -*-
"""STUB — Enterprise 私有模块 (2026-08-31 迁移到 meshctx-enterprise 私有库)。
"""

_IMPLEMENTATION_MOVED = True


from ._enterprise_base import _enterprise_stub, EnterpriseFeatureError

class AgentRole:
    def __init__(self, *a, **k):
        _enterprise_stub(*a, **k)
    CODER = 'coder'
    REVIEWER = 'reviewer'
    ARCHITECT = 'architect'
    TESTER = 'tester'
    RESEARCHER = 'researcher'
    DEVOPS = 'devops'
    CUSTOM = 'custom'
class AgentProfile:
    def __init__(self, *a, **k):
        _enterprise_stub(*a, **k)
class AgentTask:
    def __init__(self, *a, **k):
        _enterprise_stub(*a, **k)
class TeamResult:
    def __init__(self, *a, **k):
        _enterprise_stub(*a, **k)
BUILTIN_AGENTS = {}
class AgentTeamManager:
    def __init__(self, *a, **k):
        _enterprise_stub(*a, **k)
_global_teams = None
def get_teams(*a, **k):
    return _enterprise_stub(*a, **k)
