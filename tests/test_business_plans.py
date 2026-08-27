"""Business Plans (Team/Enterprise) 单元测试 — BP v3.117 开发 (2026-08-27)

覆盖: Plan 模型/功能门控/组织 CRUD/成员/升级/审计日志/使用统计/Swarm 门控。
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.core.business_plans import (
    Plan, PLAN_FEATURES, PLAN_PRICES, BusinessStore,
    feature_enabled, upgrade_path, reset_store,
)


@pytest.fixture()
def store(tmp_path):
    return reset_store(str(tmp_path / "bp_test.json"))


def test_plan_features_matrix():
    """BP 功能矩阵: free 无团队功能, team 有共享/群审/仪表盘, enterprise 全功能。"""
    assert feature_enabled("free", "shared_memory") is False
    assert feature_enabled("free", "swarm_review") is False
    assert feature_enabled("free", "audit_log") is False
    assert feature_enabled("team", "shared_memory") is True
    assert feature_enabled("team", "swarm_review") is True
    assert feature_enabled("team", "team_dashboard") is True
    assert feature_enabled("team", "sso") is False          # SSO 仅 Enterprise
    assert feature_enabled("team", "audit_log") is False
    assert feature_enabled("enterprise", "sso") is True
    assert feature_enabled("enterprise", "audit_log") is True
    assert feature_enabled("enterprise", "private_deploy") is True


def test_pricing():
    """BP 定价: free 0 / team $9 / enterprise $29。"""
    assert PLAN_PRICES["free"] == 0
    assert PLAN_PRICES["team"] == 9
    assert PLAN_PRICES["enterprise"] == 29


def test_upgrade_path():
    assert upgrade_path("free") == ["free", "team", "enterprise"]
    assert upgrade_path("team") == ["team", "enterprise"]
    assert upgrade_path("enterprise") == ["enterprise"]


def test_team_create_and_get(store):
    t = store.create_team("研发组", "user1", "team", seats=5)
    assert t.plan == "team"
    assert t.owner == "user1"
    assert "user1" in t.members and t.members["user1"].role == "owner"
    got = store.get_team(t.team_id)
    assert got.name == "研发组"
    # 非法 plan 回退 free
    t2 = store.create_team("默认", "user2", "hacker", seats=2)
    assert t2.plan == "free"


def test_team_members_and_seats(store):
    t = store.create_team("团队", "owner1", "team", seats=2)
    assert store.add_member(t.team_id, "m1") is True
    assert store.add_member(t.team_id, "m2") is False   # 席位满
    assert store.remove_member(t.team_id, "m1") is True
    assert store.remove_member(t.team_id, "owner1") is False  # owner 不可移除
    # 成员查询
    teams = store.list_teams_of_user("m1")
    assert len(teams) == 0  # 已被移除
    assert len(store.list_teams_of_user("owner1")) == 1


def test_upgrade_and_subscription(store):
    t = store.create_team("企业组", "admin1")
    assert t.plan == "free"
    assert store.set_plan(t.team_id, "enterprise", seats=20, months=12) is True
    t2 = store.get_team(t.team_id)
    assert t2.plan == "enterprise"
    assert t2.seats == 20
    assert t2.subscription_until > time.time()
    assert store.set_plan("nonexistent", "team") is False


def test_audit_log(store):
    store.audit("u1", "team.create", "team=t1")
    store.audit("u1", "team.upgrade", "team=t1 plan=enterprise", "10.0.0.1")
    store.audit("u2", "team.memory_save", "team=t1 fact=密码")
    logs = store.audit_log()
    assert len(logs) == 3
    assert logs[-1]["action"] == "team.memory_save"
    assert logs[-1]["ip"] == ""
    # limit
    assert len(store.audit_log(limit=1)) == 1


def test_usage_stats(store):
    store.record_usage("t1", model="deepseek:chat", tokens_in=100, tokens_out=50)
    store.record_usage("t1", model="deepseek:chat", tokens_in=200, tokens_out=80)
    store.record_usage("t1", model="openai:gpt-4o", tokens_in=300, tokens_out=120)
    stats = store.usage_stats("t1", days=7)
    assert stats["total"]["requests"] == 3
    assert stats["total"]["tokens_in"] == 600
    assert stats["total"]["tokens_out"] == 250
    days = stats["days"]
    day_key = list(days.keys())[0]
    assert days[day_key]["model_calls"]["deepseek:chat"] == 2
    assert days[day_key]["model_calls"]["openai:gpt-4o"] == 1


def test_persistence(tmp_path):
    """存储持久化: 重启后组织/审计/统计仍在。"""
    p = tmp_path / "persist.json"
    s1 = BusinessStore(str(p))
    t = s1.create_team("持久化组", "owner", "team")
    s1.audit("owner", "team.create", f"team={t.team_id}")
    s1.record_usage(t.team_id, model="deepseek:chat", tokens_in=10, tokens_out=5)
    # 新实例加载
    s2 = BusinessStore(str(p))
    t2 = s2.get_team(t.team_id)
    assert t2 is not None and t2.plan == "team"
    assert len(s2.audit_log()) == 1
    assert s2.usage_stats(t.team_id)["total"]["requests"] == 1


def test_swarm_module_import_and_gate():
    """Swarm 模块可导入, 门控与 BP 矩阵一致。"""
    from src.core.swarm import DEFAULT_MODELS, swarm_stats
    assert len(DEFAULT_MODELS) == 5
    assert feature_enabled("team", "swarm_review") is True
    assert feature_enabled("free", "swarm_review") is False
