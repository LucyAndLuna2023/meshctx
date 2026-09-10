# -*- coding: utf-8 -*-
"""meshctx 集群通讯 v6 单元测试 (zcode@004/meshctx)

权威规范: hermes CLUSTER-COMM-V6.md (v6 + v6.1)
全部用 FakeRedis 注入, 不依赖网络/真实 hub。
覆盖: 身份默认值 · B1 profile 白名单 · 项目路由优先级 (§2.3) · 单通道发送
(v5.1 禁双写) · v6.1 回执路由 (§8) · 自杀防护 (§9) · Web3 journal (§5) ·
归档 TTL (§1.4) · 跨轮询去重 · admin 文件队列互通。
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ── FakeRedis (内存实现, 仅覆盖本模块用到的子集) ─────────────

class FakePubSub:
    def __init__(self, hub):
        self.hub = hub
        self.channels = []

    def subscribe(self, *chans):
        self.channels.extend(chans)

    def get_message(self, timeout=0):
        return None  # 测试中不模拟 pubsub 实时流

    def close(self):
        pass


class FakeRedis:
    """内存 Redis: list/hash/set/expire/publish 最小子集。"""

    def __init__(self):
        self.lists = {}      # key -> [str]  (左端为新)
        self.hashes = {}     # key -> {field: str}
        self.kv = {}         # dedup set-nx
        self.ttls = {}       # key -> ttl
        self.published = []  # (channel, payload)

    def lpush(self, key, val):
        self.lists.setdefault(key, []).insert(0, val)

    def rpop(self, key):
        lst = self.lists.get(key)
        return lst.pop() if lst else None

    def ltrim(self, key, a, b):
        if key in self.lists:
            self.lists[key] = self.lists[key][a:b + 1]

    def llen(self, key):
        return len(self.lists.get(key, []))

    def hset(self, key, field, val):
        self.hashes.setdefault(key, {})[field] = val

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.kv:
            return None  # 已存在 → 未设置 (redis 语义)
        self.kv[key] = val
        if ex:
            self.ttls[key] = ex
        return True

    def expire(self, key, ttl):
        self.ttls[key] = ttl

    def publish(self, chan, payload):
        self.published.append((chan, payload))

    def pubsub(self):
        return FakePubSub(self)


@pytest.fixture()
def v6(tmp_path, monkeypatch):
    """以隔离的 MESHCTX_HOME 重载模块, 返回 (module, fakeredis)。"""
    home = tmp_path / ".meshctx"
    monkeypatch.setenv("MESHCTX_HOME", str(home))
    monkeypatch.setenv("MESHCTX_CLUSTER_ARCHIVE_TTL", "60")  # 短 TTL 便于断言
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "cluster"))
    try:
        mod = importlib.import_module("cluster_comm_v6")
        importlib.reload(mod)
    finally:
        sys.path.remove(str(root / "cluster"))
    fr = FakeRedis()
    yield mod, fr
    # 还原全局 journal, 避免污染其它测试
    mod._journal = None


# ── 身份 ───────────────────────────────────────────────────

def test_identity_defaults(v6):
    mod, _ = v6
    assert mod.MACHINE_ID == "004"
    assert mod.AGENT == "zcode"
    assert mod.PROJECT == "meshctx"
    # zcode 三实例按项目隔离: 通道带项目维度
    assert mod.inbox_channels() == ["hub:inbox:004:zcode:meshctx"]


def test_zcode_project_isolation(tmp_path, monkeypatch):
    """zcode 三个项目实例互不干扰: 通道/去重键/心跳键全部按项目隔离。

    注意 importlib.reload 复用同一模块对象 — 采用顺序快照式断言
    (加载 meshctx → 捕获/断言 → 加载 quant → 捕获/断言 → 回到 meshctx)。
    """
    root = Path(__file__).resolve().parent.parent

    def load(project, home):
        monkeypatch.setenv("MESHCTX_HOME", str(home))
        monkeypatch.setenv("MESHCTX_CLUSTER_PROJECT", project)
        sys.path.insert(0, str(root / "cluster"))
        try:
            mod = importlib.import_module("cluster_comm_v6")
            return importlib.reload(mod)
        finally:
            sys.path.remove(str(root / "cluster"))

    # ① meshctx 实例
    m = load("meshctx", tmp_path / "h1")
    assert m.inbox_channels() == ["hub:inbox:004:zcode:meshctx"]
    fr1 = FakeRedis()
    m.heartbeat(r=fr1)
    assert "004:zcode:meshctx" in fr1.hashes["hub:workers"]

    # ② quant 实例 (另一个 zcode 对话): 通道/心跳键不同
    m = load("quant", tmp_path / "h2")
    assert m.inbox_channels() == ["hub:inbox:004:zcode:quant"]
    fr2 = FakeRedis()
    m.heartbeat(r=fr2)
    assert "004:zcode:quant" in fr2.hashes["hub:workers"]
    assert "004:zcode:meshctx" not in fr2.hashes["hub:workers"]

    # ③ 去重键隔离: quant 实例标记 dup1 后, meshctx 实例收同 id 消息不受影响
    fr3 = FakeRedis()
    fr3.lpush("hub:inbox:004:zcode:quant", json.dumps({"msg_id": "dup1", "message": "x"}))
    assert len(m.poll_once(r=fr3, timeout=0.05)) == 1

    # ④ 回到 meshctx 实例: 同 msg_id 走 meshctx 通道, 不被 quant 的去重标记拦截
    m = load("meshctx", tmp_path / "h1")
    fr3.lpush("hub:inbox:004:zcode:meshctx",
              json.dumps({"msg_id": "dup1", "message": "y"}))
    got = m.poll_once(r=fr3, timeout=0.05)
    assert [g["msg_id"] for g in got] == ["dup1"]
    m._journal = None


def test_send_to_zcode_targets_project_channel(v6):
    mod, fr = v6
    out = mod.send_to_zcode("quant", "量化数据已更新", r=fr)
    assert isinstance(out, str) and out
    assert "hub:inbox:004:zcode:quant" in fr.lists
    msg = json.loads(fr.lists["hub:inbox:004:zcode:quant"][0])
    assert msg["to_project"] == "quant"
    assert msg["reply_channel"] == "hub:inbox:004:zcode:quant"


def test_zcode_channel_not_consumed_by_hermes_drain(v6):
    """共存安全: zcode 通道含冒号后缀 — hermes listener drain 会跳过 (不盗窃)。"""
    mod, _ = v6
    chan = mod.inbox_channels()[0]
    suffix = chan.split("hub:inbox:")[1]
    assert ":" in suffix            # hermes drain: 含 ":" 的 inbox suffix 一律跳过
    assert not suffix.isdigit()     # 且非纯机器号


# ── B1 profile 白名单 (v6 §3) ──────────────────────────────

@pytest.mark.parametrize("name,ok", [
    ("meshctx", True), ("zcode", True), ("crypto-v2", True), ("A_b-9", True),
    ("test", False),        # 保留字
    ("004", False),         # 纯数字 (机器号)
    ("", False), ("a:b", False), ("bad name", False), ("中文名", False),
    ("x" * 65, False),      # >64
])
def test_validate_profile_name(v6, name, ok):
    mod, _ = v6
    assert mod.validate_profile_name(name) is ok


@pytest.mark.parametrize("proj,ok", [
    ("meshctx", True), ("quant-2", True), ("项目A", True),
    ("", False), (None, True), ("a b", False), ("a:b", False), ("x" * 129, False),
])
def test_validate_project_id(v6, proj, ok):
    mod, _ = v6
    assert mod.validate_project_id(proj) is ok


def test_split_to_profile(v6):
    mod, _ = v6
    assert mod.split_to_profile("meshctx:quant") == ("meshctx", "quant")
    assert mod.split_to_profile("meshctx/quant") == ("meshctx", "quant")
    assert mod.split_to_profile("meshctx") == ("meshctx", None)
    assert mod.split_to_profile("") == ("", None)


# ── 发送: 单通道 + 项目路由 (v5.1 禁双写 / v6 §2) ──────────

def test_send_dm_single_channel_and_fields(v6):
    mod, fr = v6
    mid = mod.send_dm("002", "hello", to_profile="meshctx:quant", r=fr)
    assert mid and mid != "rejected"
    # 单通道: 只写 hub:inbox:002
    assert list(fr.lists.keys()) == ["hub:inbox:002"]
    assert fr.published[0][0] == "hub:inbox:002"
    msg = json.loads(fr.lists["hub:inbox:002"][0])
    assert msg["from"] == "004" and msg["from_profile"] == "zcode"
    assert msg["to_profile"] == "meshctx:quant"
    assert msg["project_id"] == "quant"           # 拆分注入
    assert msg["from_agent"] == "zcode"
    assert "timestamp" in msg and "reply_channel" in msg


def test_send_dm_project_id_field(v6):
    mod, fr = v6
    mod.send_dm("001", "m", to_profile="admin", project_id="meshctx", r=fr)
    msg = json.loads(fr.lists["hub:inbox:001"][0])
    assert msg["project_id"] == "meshctx"


def test_send_dm_rejects_bad_profile(v6):
    mod, fr = v6
    assert mod.send_dm("002", "m", to_profile="test", r=fr) == "rejected"
    assert mod.send_dm("002", "m", to_profile="004", r=fr) == "rejected"
    assert mod.send_dm("002", "m", to_profile="bad name:x", r=fr) == "rejected"
    assert mod.send_dm("002", "m", to_profile="meshctx:bad project", r=fr) == "rejected"
    assert not fr.lists  # 拒绝时不产生任何投递


def test_send_dm_redis_unavailable_graceful(v6):
    mod, _ = v6

    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("no redis")

    out = mod.send_dm("002", "m", r=FakeRedis())  # FakeRedis 正常
    assert out  # 注入正常连接时可用
    out2 = mod.send_dm.__wrapped__ if hasattr(mod.send_dm, "__wrapped__") else None
    # 未装 redis-py 的降级路径: 直接传 None 且 get_redis 抛错
    orig = mod.get_redis
    mod.get_redis = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        out3 = mod.send_dm("002", "m", r=None)
        assert isinstance(out3, dict) and out3["ok"] is False
    finally:
        mod.get_redis = orig


# ── v6.1 §8 回执路由 ───────────────────────────────────────

def test_send_reply_routes_to_publisher(v6):
    mod, fr = v6
    original = {
        "msg_id": "abc", "from": "002", "from_profile": "meshctx",
        "project_id": "meshctx", "reply_channel": "",
    }
    mod.send_reply(original, "收到", r=fr)
    msg = json.loads(fr.lists["hub:inbox:002"][0])
    # 铁律: to_profile = 发布者 from_profile (非 admin/自己)
    assert msg["to_profile"] == "meshctx:meshctx"
    assert msg["project_id"] == "meshctx"


def test_send_reply_reply_channel_digit_override(v6):
    mod, fr = v6
    original = {
        "msg_id": "d1", "from": "001", "from_profile": "admin",
        "reply_channel": "hub:inbox:003",
    }
    mod.send_reply(original, "ack", r=fr)
    # reply_channel 的数字后缀改写投递机器 (hub:inbox:003)
    assert "hub:inbox:003" in fr.lists
    msg = json.loads(fr.lists["hub:inbox:003"][0])
    assert msg["to_profile"] == "admin"


def test_send_reply_no_publisher_profile_returns_empty(v6):
    mod, fr = v6
    assert mod.send_reply({"from": "002"}, "x", r=fr) == ""


# ── 自杀防护 (v6.1 §9) ─────────────────────────────────────

def test_selfkill_guard(v6):
    mod, _ = v6
    assert mod.is_selfkill_command("pkill -f hub_client.py listen")
    assert mod.is_selfkill_command("killall python3")
    assert not mod.is_selfkill_command("systemctl restart hermes-listener-admin")
    assert not mod.is_selfkill_command("")
    assert not mod.is_selfkill_command("ls -la")


# ── Web3 journal (v6 §5) ───────────────────────────────────

def test_journal_records_send_and_verifies(v6, monkeypatch):
    mod, fr = v6
    monkeypatch.setattr(mod, "get_redis", lambda: fr)
    mod.send_dm("002", "journal-me", to_profile="meshctx:meshctx")
    rep = mod.journal_verify()
    assert rep["ok"] is True and rep["entries"] >= 1
    # journal 落在 MESHCTX_HOME/web3_journal/ 且按项目隔离 (v6 §5 + zcode 多实例)
    journal_file = Path(mod.JOURNAL_DIR) / "zcode_meshctx.jsonl"
    assert journal_file.exists()


# ── 归档 TTL (v6 §1.4) ─────────────────────────────────────

def test_archive_ttl_applied(v6):
    mod, fr = v6
    mod._archive(fr, {"msg_id": "m1", "to_profile": "meshctx:meshctx"})
    # v3.131.1: 归档键取路由后基础 profile (to_profile 去项目后缀), 与 v6 §1.4 口径一致
    assert fr.ttls.get("hub:archive:meshctx") == 60  # MESHCTX_CLUSTER_ARCHIVE_TTL=60
    # 无 to_profile → 回退 agent
    mod._archive(fr, {"msg_id": "m2"})
    assert fr.ttls.get("hub:archive:zcode") == 60


def test_send_reply_direct_to_dedicated_channel(v6):
    """v3.131.1: reply_channel 为冒号专属通道时直投该通道 (原只认纯数字尾)。"""
    mod, fr = v6
    original = {
        "msg_id": "x1", "from": "002", "from_profile": "deepseek",
        "project_id": "meshctx",
        "reply_channel": "hub:inbox:004:zcode:meshctx",
    }
    mod.send_reply(original, "收到", r=fr)
    chan = "hub:inbox:004:zcode:meshctx"
    assert chan in fr.lists, "专属通道应直接收到回执"
    msg = json.loads(fr.lists[chan][0])
    assert msg["from_profile"] == "zcode"
    assert msg["project_id"] == "meshctx"


def test_hub_credentials_not_in_source():
    """P0 回归: 源码零凭据 — cluster/ 全部模块不得内嵌 hub 密码/IP 默认值。"""
    base = Path(__file__).resolve().parent.parent / "cluster"
    for name in ("cluster_comm_v6.py", "hub_client.py"):
        src = (base / name).read_text(encoding="utf-8")
        assert "Hm@2026" not in src, f"hub 密码不得出现在源码 ({name})"
        assert "66.154.101.18" not in src, f"hub 地址默认值不得出现在源码 ({name}) (env/hub_env 注入)"


def test_get_redis_requires_config(v6, monkeypatch):
    """未配置 host/密码时 get_redis 明确报错并给配置指引 (优雅降级前置)。"""
    mod, _ = v6
    monkeypatch.setattr(mod, "REDIS_HOST", "")
    monkeypatch.setattr(mod, "REDIS_PASSWORD", "")
    with pytest.raises(RuntimeError, match="hub 未配置"):
        mod.get_redis()


# ── 收取: 队列 drain + 跨轮询去重 ──────────────────────────

def test_poll_once_drains_queue_dedups(v6):
    mod, fr = v6
    chan = mod.inbox_channels()[0]
    m1 = {"msg_id": "aaa", "from": "002", "message": "q1"}
    fr.lpush(chan, json.dumps(m1))
    got = mod.poll_once(r=fr, timeout=0.05)
    assert [g["msg_id"] for g in got] == ["aaa"]
    inbox = mod.read_inbox()
    assert inbox[0]["message"] == "q1"
    # 同消息再入队 (pubsub+队列双投递场景) → 去重不重复写
    fr.lpush(chan, json.dumps(m1))
    got2 = mod.poll_once(r=fr, timeout=0.05)
    assert got2 == []
    assert len(mod.read_inbox()) == 1


def test_poll_once_redis_down_reports_error(v6):
    mod, _ = v6
    orig = mod.get_redis
    mod.get_redis = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        got = mod.poll_once(r=None, timeout=0.01)
        assert got and got[0].get("_error")
    finally:
        mod.get_redis = orig


# ── 心跳: 共存键, 不覆盖 hermes 的 004 条目 ────────────────

def test_heartbeat_uses_agent_project_scoped_key(v6):
    mod, fr = v6
    out = mod.heartbeat(r=fr)
    assert out["ok"] is True
    # zcode 多实例: 心跳键带项目维度, 不与 hermes["004"] / 其他 zcode 项目冲突
    assert "004:zcode:meshctx" in fr.hashes["hub:workers"]
    fr.hset("hub:workers", "004", json.dumps({"label": "WSL-New", "source": "hermes"}))
    fr.hset("hub:workers", "004:zcode:quant",
            json.dumps({"label": "other-zcode", "source": "meshctx-cluster-v6"}))
    mod.heartbeat(r=fr)
    workers = fr.hashes["hub:workers"]
    assert json.loads(workers["004"])["source"] == "hermes"
    assert json.loads(workers["004:zcode:quant"])["label"] == "other-zcode"
    assert json.loads(workers["004:zcode:meshctx"])["agent"] == "zcode"


def test_heartbeat_redis_down_graceful(v6):
    mod, _ = v6
    orig = mod.get_redis
    mod.get_redis = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        out = mod.heartbeat(r=None)
        assert out["ok"] is False and "redis" in out["error"].lower()
    finally:
        mod.get_redis = orig


# ── admin 文件队列互通 (WSL admin_msg.py 格式) ─────────────

def test_admin_msg_file_queue_format(v6, tmp_path):
    mod, _ = v6
    qdir = tmp_path / "admin_msgs"
    out = mod.send_admin_msg("qa", "请检查测试", msg_dir=str(qdir))
    assert out["ok"] is True
    files = list((qdir / "qa").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    # admin_msg.py 消费格式: {from, to, time, message}
    assert data["from"] == "zcode" and data["to"] == "qa"
    assert data["message"] == "请检查测试"


def test_admin_msg_disabled_by_default(v6, monkeypatch):
    mod, _ = v6
    monkeypatch.setattr(mod, "ADMIN_MSG_DIR", "")
    out = mod.send_admin_msg("qa", "x", msg_dir="")
    assert out["ok"] is False


# ── 项目路由表 (v6 §2.1) ───────────────────────────────────

def test_resolve_project_profile(v6):
    mod, _ = v6
    assert mod.resolve_project_profile("meshctx") == "meshctx"
    assert mod.resolve_project_profile("Quant") == "quant"   # 大小写容错
    assert mod.resolve_project_profile("crypto v2") == "crypto-v2"
    assert mod.resolve_project_profile("unknown-proj") == "deepseek"
    assert mod.resolve_project_profile("") == "deepseek"
