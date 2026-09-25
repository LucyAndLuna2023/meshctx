# -*- coding: utf-8 -*-
"""v6.2 组通道守门 — 企业版/团队版协作核心 (部门/项目共享信息通道).

用户定稿 (2026-09-22): 同部门共享通道 + 同项目共享通道; 界定权限:
member 可发, auditor 只读, 加/踢人 owner/manager+, 跨租户 org 隔离。
"""
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


class FakeRedis:
    """最小 Hash/Set/List/PubSub 仿真 (与 v6 测试同风格)."""

    def __init__(self):
        self.hashes, self.sets, self.lists, self.published = {}, {}, {}, []

    def hget(self, k, f):
        return self.hashes.get(k, {}).get(f)

    def hset(self, k, f, v):
        self.hashes.setdefault(k, {})[f] = v

    def hgetall(self, k):
        return self.hashes.get(k, {})

    def sadd(self, k, v):
        s = self.sets.setdefault(k, set())
        n = len(s)
        s.add(v)
        return len(s) - n

    def srem(self, k, v):
        s = self.sets.get(k, set())
        if v in s:
            s.discard(v)
            return 1
        return 0

    def smembers(self, k):
        return set(self.sets.get(k, set()))

    def scard(self, k):
        return len(self.sets.get(k, set()))

    def lpush(self, k, v):
        self.lists.setdefault(k, []).insert(0, v)

    def publish(self, k, v):
        self.published.append((k, v))


@pytest.fixture()
def groups(monkeypatch):
    monkeypatch.setenv("MESHCTX_ORG", "default")
    monkeypatch.setenv("MESHCTX_CLUSTER_MACHINE_ID", "004")
    monkeypatch.setenv("MESHCTX_CLUSTER_AGENT", "deepseek")
    sys.path.insert(0, str(_ROOT / "cluster"))
    import cluster_groups as g
    importlib_reload(g)
    return g, FakeRedis()


def importlib_reload(m):
    import importlib
    importlib.reload(m)
    return m


ME = "004:deepseek"
ALICE = "002:meshctx"
BOB = "001:geo"
EVE = "003:qa"


def test_create_dept_and_project_groups(groups):
    g, fr = groups
    assert g.create_group(fr, "eng", "dept", name="工程部")["ok"]
    assert g.create_group(fr, "apollo", "project", name="Apollo 项目")["ok"]
    assert not g.create_group(fr, "bad:type", "dept")["ok"]      # gtype 非法
    assert not g.create_group(fr, "a:b", "dept")["ok"]           # gid 禁冒号 (通道注入)
    assert not g.create_group(fr, "eng", "dept")["ok"]           # 重复创建
    assert set(g.list_groups(fr)) == {"eng", "apollo"}


def test_membership_permissions(groups):
    g, fr = groups
    g.create_group(fr, "eng", "dept")
    # owner 自动入组
    assert ME in g.group_members(fr, "eng")
    # 拉 2 人
    assert g.add_member(fr, "eng", ALICE)["ok"]
    assert g.add_member(fr, "eng", EVE, role="auditor")["ok"]
    assert len(g.group_members(fr, "eng")) == 3
    # 非 owner 不可拉人
    assert not g.add_member(fr, "eng", BOB, actor=ALICE)["ok"]
    # owner 不可被移除
    assert not g.remove_member(fr, "eng", ME)["ok"]
    assert g.remove_member(fr, "eng", EVE)["ok"]
    # owner 不可退出
    assert not g.leave_group(fr, "eng")["ok"]


def test_group_send_fanout_each_member_one_copy(groups):
    """核心语义: 同部门/同项目的人各收一份 — fanout 到各自 profile 主通道."""
    g, fr = groups
    g.create_group(fr, "apollo", "project")
    g.add_member(fr, "apollo", ALICE)
    g.add_member(fr, "apollo", BOB)
    out = g.group_send(fr, "apollo", "项目周会改到周四 15:00")
    assert out["ok"] and out["delivered"] == "3/3"   # 本人+2 成员
    # 每个成员的 profile 主通道各一份 (信封完整)
    for chan in ("hub:profile:004:deepseek", "hub:profile:002:meshctx",
                 "hub:profile:001:geo"):
        assert fr.lists.get(chan), chan
        msg = json.loads(fr.lists[chan][0])
        assert msg["group"] == "apollo" and msg["group_type"] == "project"
        assert msg["message"].startswith("项目周会")


def test_non_member_cannot_send(groups):
    g, fr = groups
    g.create_group(fr, "eng", "dept")
    assert not g.group_send(fr, "eng", "hi", sender=EVE)["ok"]


def test_auditor_readonly(groups):
    """auditor 只读: 在组内收副本, 但不可发送 (企业版 RBAC 界定)."""
    g, fr = groups
    g.create_group(fr, "eng", "dept", actor=ME)
    g.add_member(fr, "eng", EVE)
    # stub: 非 owner 经 ROLE_PROVIDER 未配置时按 owner 组外角色 member 处理;
    # auditor 界定通过成员身份+企业版 provider — 这里验证 provider 覆写路径
    g.ROLE_PROVIDER = "tests.test_cluster_groups:auditor_role_provider"
    try:
        out = g.group_send(fr, "eng", "audit write attempt", sender=EVE)
        assert not out["ok"] and "只读" in out["error"]
    finally:
        g.ROLE_PROVIDER = ""


def auditor_role_provider(actor, group, action):
    return "auditor" if actor == EVE else "owner"


def test_org_isolation(groups):
    """跨租户隔离: default 与 acme 的同名组互不可见/互不可发."""
    g, fr = groups
    g.create_group(fr, "eng", "dept", org="default")
    assert not g._group_meta(fr, "eng", "acme")
    out = g.group_send(fr, "eng", "cross tenant?", org="acme")
    assert not out["ok"]


def test_send_bad_route_key_skipped_and_logged(groups):
    """成员身份坏键 (I-6 铁律): fanout 跳过并留痕, 不炸整批."""
    g, fr = groups
    g.create_group(fr, "eng", "dept")
    g.add_member(fr, "eng", ALICE)
    fr.sets[g._member_key("default", "eng")].add("004:bad profile")  # 含空格=坏键
    out = g.group_send(fr, "eng", "deliver to valid only")
    assert out["ok"] and out["delivered"] == "2/3"  # 坏键跳过, 合法成员照收
