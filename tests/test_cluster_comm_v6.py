# -*- coding: utf-8 -*-
"""meshctx 集群通讯 v6 单元测试 (zcode@004/meshctx)

权威规范: hermes CLUSTER-COMM-V6.md (v6 + v6.1)
全部用 FakeRedis 注入, 不依赖网络/真实 hub。
覆盖: 身份默认值 · B1 profile 白名单 · 项目路由优先级 (§2.3) · 单通道发送
(v5.1 禁双写) · v6.1 回执路由 (§8) · 自杀防护 (§9) · Web3 journal (§5) ·
归档 TTL (§1.4) · 跨轮询去重 · admin 文件队列互通。
"""
import importlib
from pathlib import Path
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
    # zcode 三实例按项目隔离: 通道带项目维度 (v6.1: +profile 主通道)
    assert mod.inbox_channels() == ["hub:inbox:004:zcode:meshctx",
                                    "hub:profile:004:zcode"]


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
    assert m.inbox_channels() == ["hub:inbox:004:zcode:meshctx",
                                  "hub:profile:004:zcode"]
    fr1 = FakeRedis()
    m.heartbeat(r=fr1)
    assert "004:zcode:meshctx" in fr1.hashes["hub:workers"]

    # ② quant 实例 (另一个 zcode 对话): 通道/心跳键不同
    m = load("quant", tmp_path / "h2")
    assert m.inbox_channels() == ["hub:inbox:004:zcode:quant",
                                  "hub:profile:004:zcode"]
    fr2 = FakeRedis()
    m.heartbeat(r=fr2)
    assert "004:zcode:quant" in fr2.hashes["hub:workers"]
    assert "004:zcode:meshctx" not in fr2.hashes["hub:workers"]

    # ③ 去重键隔离: quant 实例标记 dup1 后, meshctx 实例收同 id 消息不受影响
    fr3 = FakeRedis()
    fr3.lpush("hub:inbox:004:zcode:quant", json.dumps(
        {"msg_id": "dup1", "from": "002", "from_profile": "meshctx", "message": "x"}))
    assert len(m.poll_once(r=fr3, timeout=0.05)) == 1

    # ④ 回到 meshctx 实例: 同 msg_id 走 meshctx 通道, 不被 quant 的去重标记拦截
    m = load("meshctx", tmp_path / "h1")
    fr3.lpush("hub:inbox:004:zcode:meshctx",
              json.dumps({"msg_id": "dup1", "from": "002",
                          "from_profile": "meshctx", "message": "y"}))
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


# ── 发送: 双通道 + 项目路由 (v6.1d 演进: 主通道+机器兜底; 原v5.1单通道
#    因 I-6 事故废弃 — 只投机器通道时 001 类节点永远收不到, 8条堆积6天) ──

def test_send_dm_single_channel_and_fields(v6):
    mod, fr = v6
    mid = mod.send_dm("002", "hello", to_profile="meshctx:quant", r=fr)
    assert mid and mid != "rejected"
    # v6.1d 双通道: profile 主通道优先 + 机器兜底 (接收方 msg_id NX 去重防重复)
    assert "hub:profile:002:meshctx" in fr.lists, "主通道必须收到"
    assert "hub:inbox:002" in fr.lists, "机器兜底通道保留"
    assert fr.published[0][0] == "hub:profile:002:meshctx"
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
    """P0 回归: 源码零凭据 — cluster_comm_v6.py 不得内嵌 hub 密码/IP 默认值。"""
    src = (Path(__file__).resolve().parent.parent / "cluster" / "cluster_comm_v6.py").read_text(encoding="utf-8")
    assert "Hm@2026" not in src, "hub 密码不得出现在源码"
    assert "66.154.101.18" not in src, "hub 地址默认值不得出现在源码 (env/hub_env 注入)"


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
    m1 = {"msg_id": "aaa", "from": "002", "from_profile": "meshctx", "message": "q1"}
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


# ── v6.1: 信封完整性校验 (空壳拒收不占去重坑) ───────────────

def test_v61_shell_rejected_and_does_not_block_full_payload(tmp_path, monkeypatch):
    """空壳事故根修: {msg_id,to_profile} 裸壳先到 → 拒收且不占 msg_id;
    随后同 msg_id 全量件必须正常收取 (首版事故: 全量件被去重误杀)。"""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    monkeypatch.setenv("MESHCTX_CLUSTER_PROJECT", "meshctx")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cluster"))
    try:
        mod = importlib.import_module("cluster_comm_v6")
        mod = importlib.reload(mod)
    finally:
        sys.path.remove(str(Path(__file__).resolve().parent.parent / "cluster"))
    mod._journal = None
    fr = FakeRedis()
    chan = mod.inbox_channels()[0]
    shell = {"msg_id": "V61SHELL", "to_profile": "zcode"}  # 裸壳: 缺 from/from_profile/message
    full = {"msg_id": "V61SHELL", "from": "002", "from_profile": "codex",
            "to": "004", "to_profile": "zcode", "message": "full payload"}
    fr.lpush(chan, json.dumps(shell))
    fr.lpush(chan, json.dumps(full))  # RPOP 后进先出: full 先被处理
    got = mod.poll_once(r=fr, timeout=0.05)
    assert [g["msg_id"] for g in got] == ["V61SHELL"]
    assert got[0].get("message") == "full payload", "全量件必须存活, 空壳不得占坑"
    # 再单独投壳: 必须 0 收取 (拒收), 且 journal 留 rejected_malformed 痕迹
    fr2 = FakeRedis()
    fr2.lpush(chan, json.dumps(shell))
    assert mod.poll_once(r=fr2, timeout=0.05) == []
    jdir = tmp_path / "web3_journal"
    traces = " ".join(f.read_text(errors="replace") for f in jdir.rglob("*") if f.is_file()) \
        if jdir.exists() else ""
    assert "rejected_malformed" in traces, "空壳拒收必须留 journal 痕迹"
    mod._journal = None


def test_v61_envelope_valid_unit():
    m = importlib.import_module("cluster_comm_v6")
    assert m.envelope_valid({"msg_id": "x", "from": "002", "from_profile": "codex", "message": "hi"})
    for bad in (
        {"msg_id": "x", "to_profile": "z"},                     # 裸通知壳 (事故原型)
        {"msg_id": "x", "message": "hi"},                        # from 与 from_profile 全空 (v6.1c 拒)
        {"msg_id": "", "from": "002", "from_profile": "c", "message": "hi"},
        {"msg_id": "x", "from": "002", "from_profile": "c", "message": "  "},
        "not-a-dict",
    ):
        assert not m.envelope_valid(bad), bad


def test_v61_inbox_channels_include_profile_main(v6):
    """v6.1: listener 必须兼订 hub:profile:{mid}:{agent} 主通道 (003 部署发现)."""
    mod, _ = v6
    chans = mod.inbox_channels()
    assert f"hub:profile:{mod.MACHINE_ID}:{mod.AGENT}" in chans
    assert mod.zcode_inbox_channel() in chans


def test_v61_poll_once_receives_from_profile_main_channel(v6):
    """v6.1b: LPUSH 到 hub:profile:{mid}:{agent} 主通道的消息必须被 poll_once 收到
    (003 部署端到端发现: poll_once 原写死 chans[0], 主通道消息永远收不到)."""
    mod, fr = v6
    main_chan = f"hub:profile:{mod.MACHINE_ID}:{mod.AGENT}"
    fr.lpush(main_chan, json.dumps({"msg_id": "MAIN1", "from": "004",
                                    "from_profile": "deepseek",
                                    "to": mod.MACHINE_ID,
                                    "to_profile": mod.AGENT,
                                    "message": "e2e via main channel"}))
    got = mod.poll_once(r=fr, timeout=0.05)
    assert [g["msg_id"] for g in got] == ["MAIN1"]


def test_v61c_hermes_minimal_envelope_accepted():
    """002admin P2: hermes CLI 漏 -f → from_profile="" 但 from 有值 — 必须可收,
    静默拒收即跨生态丢件; 同时壳防护不减弱 (三项全缺仍拒)."""
    m = importlib.import_module("cluster_comm_v6")
    assert m.envelope_valid({"msg_id": "h1", "from": "002",
                             "from_profile": "", "message": "hermes DM no -f"})
    # 壳原型仍拒 (I-1 防护不回退)
    assert not m.envelope_valid({"msg_id": "s1", "to_profile": "zcode"})


# ── v6.1d: 路由键白名单 + send_dm 双通道 (INCIDENTS I-6 根修) ──

def test_v61d_validate_route_key():
    m = importlib.import_module("cluster_comm_v6")
    assert m.validate_route_key("hub:inbox:004")
    assert m.validate_route_key("hub:profile:002:meshctx")
    assert m.validate_route_key("hub:inbox:004:zcode:quant")   # zcode 项目实例键合法
    for bad in ("hub:profile:004:zcode:meshctx",               # I-6 真实污染键 (四段)
                "hub:inbox:004:zcode",                          # 两段不完整
                "hub:dm:004", "random", "", None,
                "hub:profile:004:", "hub:profile::meshctx"):
        assert not m.validate_route_key(bad), bad


def test_v61d_send_dm_delivers_to_profile_main_channel(v6):
    """I-6 根修: send_dm 必须送达 profile 主通道 (只投机器通道 = 001 类节点永远收不到)."""
    mod, fr = v6
    mod.send_dm("004", "route fix verify", from_profile="deepseek",
                to_profile="zcode", r=fr)
    assert fr.lists.get("hub:profile:004:zcode"), "主通道必须收到"
    assert fr.lists.get("hub:inbox:004"), "机器兜底通道仍保留"


# ── clusterv6_audit P2-A: 项目实例专属通道发送面 ──────────

def test_p2a_send_dm_third_delivery_to_project_channel(v6):
    """P2-A: to_profile 含项目后缀 + target_agent 声明 → 第三投递 5 段键."""
    mod, fr = v6
    mod.send_dm("004", "p2a third delivery", from_profile="deepseek",
                to_profile="meshctx:meshctx", target_agent="zcode", r=fr)
    assert fr.lists.get("hub:profile:004:meshctx"), "profile 主通道 (v6.1d)"
    assert fr.lists.get("hub:inbox:004"), "机器兜底通道 (v6.1d)"
    assert fr.lists.get("hub:inbox:004:zcode:meshctx"), "项目实例专属通道 (P2-A 第三投递)"
    a = json.loads(fr.lists["hub:profile:004:meshctx"][0])
    b = json.loads(fr.lists["hub:inbox:004:zcode:meshctx"][0])
    assert a["msg_id"] == b["msg_id"], "三通道同一信封 (接收方 NX 去重)"


def test_p2a_send_dm_without_target_agent_stays_dual(v6):
    """P2-A: 未声明 target_agent 保持 v6.1d 双投, 不误投 5 段键."""
    mod, fr = v6
    mod.send_dm("004", "dual only", from_profile="deepseek",
                to_profile="meshctx:meshctx", r=fr)
    assert fr.lists.get("hub:profile:004:meshctx")
    assert fr.lists.get("hub:inbox:004")
    assert not fr.lists.get("hub:inbox:004:zcode:meshctx"), "未声明 target_agent 不应三投"


def test_p2a_send_dm_rejects_bad_target_agent(v6):
    """P2-A: 非法 target_agent 走 B1 拒绝路径."""
    mod, fr = v6
    out = mod.send_dm("004", "x", from_profile="deepseek",
                      to_profile="meshctx:meshctx", target_agent="bad agent!", r=fr)
    assert out == "rejected"
    assert not fr.lists, "拒绝路径不得产生任何投递"


def test_v61e_send_dm_third_delivery_project_instance(v6):
    """002meshctx P2-A: to_profile 含 :project → 第三投递项目实例通道 (发收对称)."""
    mod, fr = v6
    mod.send_dm("002", "project instance delivery", to_profile="meshctx:quant", r=fr)
    assert "hub:inbox:002:meshctx:quant" in fr.lists, "项目实例通道必须收到"
    # 三通道去重靠接收方 msg_id NX; 发送面三键全部白名单合法 (assert 已在 send 内)


def test_v61e_conftest_env_immunity(monkeypatch):
    """002meshctx P3-E: 测试不免疫 MESHCTX_CLUSTER_MACHINE_ID env 的守门固化."""
    monkeypatch.setenv("MESHCTX_CLUSTER_MACHINE_ID", "999")
    monkeypatch.setenv("MESHCTX_CLUSTER_AGENT", "someone")
    monkeypatch.setenv("MESHCTX_CLUSTER_PROJECT", "other")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cluster"))
    try:
        import importlib
        mod = importlib.import_module("cluster_comm_v6")
        mod = importlib.reload(mod)
        assert mod.MACHINE_ID == "999"  # 模块自身尊重 env (行为正确)
    finally:
        sys.path.remove(str(Path(__file__).resolve().parent.parent / "cluster"))
    # 守门套件对 env 的免疫由 conftest delenv 固化 (本次提交同补)


def test_v61f_combined_path_no_duplicate_delivery(v6):
    """002codex 95869942 唯一阻断: 组合路径 (v6.1e third == P2-A 键) 不得重复投递.
    复现原样: send_dm("999", to_profile="meshctx:quant") → hub:inbox:999:meshctx:quant 恰 1 份."""
    mod, fr = v6
    mod.send_dm("999", "combined path", from_profile="sender",
                to_profile="meshctx:quant", r=fr)
    key = "hub:inbox:999:meshctx:quant"
    assert fr.lists.get(key, []).count(fr.lists[key][0]) == 1 if key in fr.lists else False
    # 全部通道各自恰一份 (保序去重)
    for k, lst in fr.lists.items():
        assert len(set(lst)) == len(lst), f"{k} 重复投递"
