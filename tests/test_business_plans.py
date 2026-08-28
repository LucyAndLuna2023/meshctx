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
    t = store.create_team("统计组", "owner")
    tid = t.team_id  # record_usage 校验 team 存在 (002codex P2)
    assert store.record_usage(tid, model="deepseek:chat", tokens_in=100, tokens_out=50) is True
    assert store.record_usage(tid, model="deepseek:chat", tokens_in=200, tokens_out=80) is True
    assert store.record_usage(tid, model="openai:gpt-4o", tokens_in=300, tokens_out=120) is True
    assert store.record_usage("nonexistent_team", model="x") is False  # 伪造统计拒绝
    stats = store.usage_stats(tid, days=7)
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


# ═══ AI agent 企业协作痛点功能测试 (2026-08-27 全网调研落地) ═══

def test_rbac_roles_and_permissions(store):
    """RBAC: owner/admin 可管理, member 不可, viewer 只读 (atlan/腾讯权限管控痛点)。"""
    t = store.create_team("RBAC组", "owner1", "team")
    assert store.can_manage(t.team_id, "owner1") is True
    assert store.add_member(t.team_id, "admin1", "admin") is True
    assert store.add_member(t.team_id, "mem1", "member") is True
    assert store.add_member(t.team_id, "view1", "viewer") is True
    assert store.can_manage(t.team_id, "admin1") is True
    assert store.can_manage(t.team_id, "mem1") is False
    assert store.can_manage(t.team_id, "view1") is False
    assert store.can_view(t.team_id, "view1") is True
    assert store.can_view(t.team_id, "stranger") is False
    # 非法角色拒绝
    assert store.add_member(t.team_id, "x", "hacker") is False


def test_member_role_query(store):
    t = store.create_team("角色组", "owner", "team")
    store.add_member(t.team_id, "a", "admin")
    assert store.member_role(t.team_id, "owner") == "owner"
    assert store.member_role(t.team_id, "a") == "admin"
    assert store.member_role(t.team_id, "ghost") is None


def test_budget_control_and_alert(store):
    """成本预算: 设置/使用/超限告警 (cloudzero 账单失控痛点)。"""
    t = store.create_team("预算组", "owner", "team")
    assert store.set_budget(t.team_id, 1000.0) is True
    store.record_usage(t.team_id, model="deepseek:chat", tokens_in=400, tokens_out=200)
    st = store.budget_status(t.team_id)
    assert st["budget"] == 1000.0 and st["used"] == 600 and st["over_budget"] is False
    assert st["percent"] == 60.0
    # 超限 → 告警标记 + budget_status 返回 budget_alert (002codex 审计修正)
    store.record_usage(t.team_id, model="openai:gpt-4o", tokens_in=500, tokens_out=100)
    st2 = store.budget_status(t.team_id)
    assert st2["over_budget"] is True
    assert st2["used"] == 1200
    assert st2["budget_alert"] is True
    assert store.get_team(t.team_id).budget_alert is True
    # 重置预算清告警
    store.set_budget(t.team_id, 5000.0)
    assert store.get_team(t.team_id).budget_alert is False


def test_activity_log(store):
    """Agent 活动日志: 观察性 (splunk 痛点)。"""
    t = store.create_team("活动组", "owner")
    store.record_activity(t.team_id, agent="web_search", action="search", detail="meshctx")
    store.record_activity(t.team_id, agent="write_file", action="write", detail="/tmp/x", user_id="mem1")
    store.record_activity("other_team", agent="x", action="y")
    logs = store.activity_log(t.team_id)
    assert len(logs) == 2
    assert logs[0]["agent"] == "web_search"
    assert logs[1]["user_id"] == "mem1"
    assert store.activity_log("other_team")[0]["agent"] == "x"


def test_budget_persistence(tmp_path):
    """预算与活动跨重启持久化。"""
    p = tmp_path / "bp2.json"
    s1 = BusinessStore(str(p))
    t = s1.create_team("持久化预算", "owner", "team")
    s1.set_budget(t.team_id, 500)
    s1.record_usage(t.team_id, model="m", tokens_in=100, tokens_out=50)
    s1.record_activity(t.team_id, "agent", "run")
    s2 = BusinessStore(str(p))
    assert s2.get_team(t.team_id).monthly_budget == 500
    assert s2.budget_status(t.team_id)["used"] == 150
    assert len(s2.activity_log(t.team_id)) == 1


def test_memory_governance_files(tmp_path, monkeypatch):
    """团队记忆治理: 纠错/标记 (Tencent Team Memory 无治理痛点)。
    用 monkeypatch 改 HOME 隔离 team_memories 文件。"""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    store = reset_store(str(tmp_path / "bp3.json"))
    t = store.create_team("治理组", "owner", "team")
    # 模拟写入一条记忆 (走文件)
    from pathlib import Path
    p = Path.home() / ".meshctx" / "team_memories" / f"{t.team_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([{"ts": 1.0, "fact": "旧版本号是 1.0", "user": "u1",
                              "status": "active", "corrected_fact": "", "corrected_by": ""}],
                            ensure_ascii=False), encoding="utf-8")
    # 读取 (GET 返回治理统计)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data[0]["status"] == "active"
    # 治理: 标记过期 + 纠错
    data[0]["status"] = "deprecated"
    data[0]["marked_by"] = "owner"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    data2 = json.loads(p.read_text(encoding="utf-8"))
    assert data2[0]["status"] == "deprecated"
    # 纠错
    data2[0]["status"] = "error"
    data2[0]["corrected_fact"] = "新版本号是 2.0"
    data2[0]["corrected_by"] = "owner"
    p.write_text(json.dumps(data2, ensure_ascii=False), encoding="utf-8")
    data3 = json.loads(p.read_text(encoding="utf-8"))
    assert data3[0]["corrected_fact"] == "新版本号是 2.0"
    assert data3[0]["status"] == "error"


# ═══ backlog 功能测试 (2026-08-28: 支付/SSO/优先路由/L2-L3 记忆) ═══

def test_payment_simulated_flow():
    """支付模拟模式: checkout → webhook 开通 → 状态。"""
    import tempfile
    store = reset_store(tempfile.mktemp() + ".json")
    t = store.create_team("支付组", "owner")
    # 模拟 checkout 事件
    from src.core.billing_payments import apply_checkout_event
    event = {"type": "checkout.session.completed",
             "data": {"object": {"metadata": {"team_id": t.team_id, "plan": "team", "seats": 3}}}}
    r = apply_checkout_event(event)
    assert r["ok"] is True and r["plan"] == "team"
    t2 = store.get_team(t.team_id)
    assert t2.plan == "team" and t2.subscription_until > time.time()
    from src.core.billing_payments import payment_status
    st = payment_status(t.team_id)
    assert st["subscription_active"] is True and st["plan"] == "team"


def test_sso_jwt_parse():
    """SSO JWT 解析 (HS256 签名验证 + 过期检查)。"""
    import base64, hashlib, hmac, json as _json
    from src.core import sso as sso_mod
    # 构造测试 JWT (HS256, 用 client_secret)
    import os
    os.environ["MESHCTX_SSO_CLIENT_SECRET"] = "test-secret"
    import importlib
    importlib.reload(sso_mod)
    header = base64.urlsafe_b64encode(_json.dumps({"alg": "HS256"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(_json.dumps(
        {"sub": "u1", "email": "a@b.com", "exp": time.time() + 3600}).encode()).rstrip(b"=")
    signing = f"{header.decode()}.{payload.decode()}".encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(b"test-secret", signing, hashlib.sha256).digest()).rstrip(b"=")
    token = f"{header.decode()}.{payload.decode()}.{sig.decode()}"
    parsed = sso_mod.parse_jwt(token)
    assert parsed is not None and parsed["email"] == "a@b.com"
    # 过期 token
    exp_payload = base64.urlsafe_b64encode(_json.dumps(
        {"sub": "u2", "exp": time.time() - 100}).encode()).rstrip(b"=")
    exp_sig = base64.urlsafe_b64encode(hmac.new(b"test-secret",
        f"{header.decode()}.{exp_payload.decode()}".encode(), hashlib.sha256).digest()).rstrip(b"=")
    exp_token = f"{header.decode()}.{exp_payload.decode()}.{exp_sig.decode()}"
    assert sso_mod.parse_jwt(exp_token) is None  # 过期拒绝


def test_sso_config_modes():
    """SSO 配置状态: 未配置 = dev-simulated。"""
    import os
    old = os.environ.pop("MESHCTX_SSO_ISSUER", None)
    from src.core.sso import sso_config, sso_enabled
    assert sso_enabled() is False
    cfg = sso_config()
    assert cfg["mode"] == "dev-simulated"
    if old: os.environ["MESHCTX_SSO_ISSUER"] = old


def test_team_memory_l2l3(tmp_path, monkeypatch):
    """团队记忆 L2/L3: save → list (schema_layer) → correct → mark。"""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    from src.core.team_memory import save_fact, list_facts, correct_fact, mark_fact
    r = save_fact("a1b2c3d4e5f6", "团队规范: 生产部署走 CI")
    assert r["schema_layer"] in ("episodic", "semantic")
    facts = list_facts("a1b2c3d4e5f6")
    assert len(facts) == 1 and facts[0]["status"] == "active"
    mid = facts[0]["id"]
    assert correct_fact("a1b2c3d4e5f6", mid, "修正版") is True
    facts2 = list_facts("a1b2c3d4e5f6")
    assert facts2[0]["status"] == "error"
    assert mark_fact("a1b2c3d4e5f6", mid, deprecated=True) is True


def test_priority_routing_gate():
    """优先路由门控: team 有 / free 无。"""
    from src.core.business_plans import feature_enabled
    assert feature_enabled("team", "priority_routing") is True
    assert feature_enabled("free", "priority_routing") is False


def test_webhook_fail_closed():
    """002codex P1: 未配置 STRIPE_WEBHOOK_SECRET 时 webhook 必须拒绝 (防支付伪造)。"""
    import os
    old = os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
    from src.core.billing_payments import verify_webhook
    event = {"type": "checkout.session.completed",
             "data": {"object": {"metadata": {"team_id": "x", "plan": "enterprise"}}}}
    import json as _json
    assert verify_webhook(_json.dumps(event).encode(), "") is None, "无 secret 必须 fail-closed"
    if old: os.environ["STRIPE_WEBHOOK_SECRET"] = old


def test_sso_fail_closed_without_secret():
    """002codex P2: 未配置 CLIENT_SECRET 时 parse_jwt 拒绝 (fail-open 修复)。"""
    import os, base64, json as _json, time
    old_sec = os.environ.pop("MESHCTX_SSO_CLIENT_SECRET", None)
    old_iss = os.environ.pop("MESHCTX_SSO_ISSUER", None)
    from src.core import sso as sso_mod
    import importlib
    importlib.reload(sso_mod)
    header = base64.urlsafe_b64encode(_json.dumps({"alg": "HS256"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(_json.dumps({"sub": "u", "exp": time.time() + 100}).encode()).rstrip(b"=")
    token = f"{header.decode()}.{payload.decode()}.sig"
    assert sso_mod.parse_jwt(token) is None, "无 secret 必须拒绝"
    if old_sec: os.environ["MESHCTX_SSO_CLIENT_SECRET"] = old_sec
    if old_iss: os.environ["MESHCTX_SSO_ISSUER"] = old_iss


def test_mark_deprecated_reflected():
    """002codex P2: mark deprecated 后 list_facts 状态反映。"""
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    import src.core.team_memory as tm
    old_home = pathlib.Path.home
    pathlib.Path.home = staticmethod(lambda: tmp)
    try:
        r = tm.save_fact("aabbccddeeff", "旧规范内容")
        facts = tm.list_facts("aabbccddeeff")
        assert facts[0]["status"] == "active"
        tm.mark_fact("aabbccddeeff", facts[0]["id"], deprecated=True)
        facts2 = tm.list_facts("aabbccddeeff")
        assert facts2[0]["status"] == "deprecated", "mark 后应显示 deprecated"
    finally:
        pathlib.Path.home = old_home


# ═══ 学习能力测试 (2026-08-28: 渐进披露 + 遥测) ═══

def test_progressive_retrieve():
    """记忆渐进披露: full/summary/title 分级 (claude-mem 模式)。"""
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    import src.core.memory_hierarchy as mh
    old_path = mh.Path.home if hasattr(mh, "Path") else None
    store = mh.HierarchicalMemoryStore()
    for i, txt in enumerate(["用户喜欢网球, 每周三打球",
                            "项目部署规范: CI 优先, 生产走 docker",
                            "记忆测试条目 A 描述内容", "记忆测试条目 B 描述内容",
                            "团队约定: 周会周二下午"]):
        it = mh.MemoryItem(value=txt, content=txt, importance=0.5 + i * 0.05,
                           schema_layer="episodic")
        store.store(it)
    res = store.progressive_retrieve("部署规范", top_k=5)
    assert len(res) > 0
    disclosures = [r["disclosure"] for r in res]
    assert "full" in disclosures or "summary" in disclosures
    # 高相关应为 full
    top = res[0]
    assert top["disclosure"] == "full" and "CI" in top["snippet"]


def test_telemetry_record_and_stats():
    """Agent 遥测: 记录 → 统计 (pi telemetry 模式)。"""
    import tempfile
    from src.core.telemetry import reset_telemetry
    t = reset_telemetry(tempfile.mktemp() + ".jsonl")
    t.record("chat", "turn_start", model="deepseek:chat")
    t.record("chat", "token", model="deepseek:chat", tokens_in=100, tokens_out=50,
             latency_ms=800)
    t.record("chat", "tool_call", tool="web_search", latency_ms=300)
    t.record("chat", "error", detail="API 超时")
    evs = t.events(agent="chat")
    assert len(evs) == 4
    st = t.stats(window_hours=24)
    assert st["tokens_in"] == 100 and st["tokens_out"] == 50
    assert st["tool_calls"].get("web_search") == 1
    assert st["errors"] == 1
    assert st["avg_latency_ms"] == 550  # 只算 latency>0: (800+300)/2


# ═══ 痛点攻克测试 (2026-08-28: 信任备份回滚 + 可靠性验证) ═══

def test_write_file_backup_and_rollback(tmp_path, monkeypatch):
    """信任攻克: overwrite 自动备份 + manifest 定位 + 回滚恢复。"""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    from src.chat_tools import _write_file
    f = tmp_path / "app.py"
    f.write_text("版本1内容")
    r = _write_file(str(f), "版本2内容", if_exists="overwrite")
    assert "备份" in r, "overwrite 应提示备份"
    assert f.read_text() == "版本2内容"
    # manifest + 备份文件
    backup_dir = tmp_path / ".meshctx" / "backups"
    assert backup_dir.exists()
    baks = list(backup_dir.glob("*.bak"))
    assert len(baks) == 1
    manifest = backup_dir / "manifest.json"
    assert manifest.exists()
    import json
    mdata = json.loads(manifest.read_text())
    assert mdata[baks[0].name]["orig"].endswith("app.py")
    # 模拟回滚: 备份内容写回
    f.write_bytes(baks[0].read_bytes())
    assert f.read_text() == "版本1内容", "回滚后应恢复原内容"


def test_sandbox_verify_endpoint():
    """可靠性攻克: /api/sandbox/verify 沙箱验证。"""
    from fastapi.testclient import TestClient
    from src.main import app
    from src.core.auth_v2 import _hash_session
    c = TestClient(app)
    c.cookies.set("meshctx_session", _hash_session())
    r = c.post("/api/sandbox/verify", json={"cmd": "echo ok", "timeout": 10})
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True and "ok" in d.get("stdout", "")
