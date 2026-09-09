#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 集群通讯 v6 (CLUSTER-COMM-V6.md 线缆兼容实现)

身份: agent=zcode · machine=004 · project=meshctx (可用 MESHCTX_CLUSTER_* 环境变量覆盖)

⚠ zcode 多实例约定 (2026-09-09): zcode 共 3 个对话实例, 按项目区分
  (meshctx / 其他项目各自一个实例)。本实例负责 **meshctx** 项目。
  因此所有隔离维度均带项目: 通道 / 去重键 / 心跳键 / journal / 收件箱文件。
  其他 zcode 实例以 MESHCTX_CLUSTER_PROJECT=<各自项目> 启动本模块即可互不干扰。

权威规范: hermes profiles/admin/CLUSTER-COMM-V6.md (v6, 2026-08-30; v6.1 2026-09-01)
线缆协议与 WSL ~/.hermes/scripts/hub_client.py v6.1 保持字节级兼容:

  - 发送: 单通道 LPUSH + PUBLISH `hub:inbox:{target_mid}` (v5.1 起禁止双写)
  - 消息字段: msg_id/from/from_label/from_profile/to/to_profile/reply_channel/
    message/timestamp/project_id
  - 项目路由 (v6 §2): project_id 字段 > to_profile "profile:project" 后缀 >
    to_profile 原值 > from_profile > deepseek 汇聚
  - profile 白名单 (v6 §3): 注册表声明 或 [A-Za-z0-9_-]{1,64};
    拒绝纯数字/保留字 test/含 : / 空白 控制符
  - 回执路由 (v6.1 §8): 回执 to_profile = 发布者 from_profile (禁止固定 admin),
    reply_channel 优先 (hub:inbox:NNN 数字后缀可改投递机器)
  - 自杀防护 (v6.1 §9): 拒绝执行含 "hub_client.py listen"/"pkill" 的任务
  - Web3 记录层 (v6 §5): 收发写哈希链 journal (~/.meshctx/web3_journal/,
    复用 src/core/web3_messaging.py, Redis 挂后可重建)
  - 归档 TTL (v6 §1.4): hub:archive:* 30 天过期

与 hermes listener 的共存设计 (防消息盗窃):
  zcode 专属通道 `hub:inbox:004:zcode` — hermes listener 的 drain 逻辑跳过
  含 ":" 的 inbox 后缀, 不会消费本通道; 本模块绝不 RPOP hermes 拥有的
  hub:inbox:004 / hub:profile:004:* 队列。
  admin 文件队列方法 (WSL /tmp/admin_msgs/, admin_msg.py 格式) 以
  MESHCTX_ADMIN_MSG_DIR 选配互通, 默认关闭。

依赖: redis-py (可选, 缺失时优雅降级为 journal-only); 其余零依赖。
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 身份与配置 ──────────────────────────────────────────────

MACHINE_ID = os.environ.get("MESHCTX_CLUSTER_MACHINE_ID", "004")
AGENT = os.environ.get("MESHCTX_CLUSTER_AGENT", "zcode")
PROJECT = os.environ.get("MESHCTX_CLUSTER_PROJECT", "meshctx")
MACHINE_LABEL = os.environ.get("MESHCTX_CLUSTER_LABEL",
                               f"{MACHINE_ID}-{AGENT}-{PROJECT}")

REDIS_HOST = os.environ.get("HUB_REDIS_HOST",
                            os.environ.get("MESHCTX_CLUSTER_REDIS_HOST", "66.154.101.18"))
REDIS_PORT = int(os.environ.get("HUB_REDIS_PORT",
                                os.environ.get("MESHCTX_CLUSTER_REDIS_PORT", "6379")))
# 密钥与 hermes hub_client.py 同源 (env 覆盖优先)
REDIS_PASSWORD = os.environ.get("HUB_REDIS_PASSWORD",
                                os.environ.get("HUB_REDIS_PW",
                                               os.environ.get("MESHCTX_CLUSTER_REDIS_PASSWORD",
                                                              "Hm@2026!1ckwd3zx2i")))

ARCHIVE_TTL_SEC = int(os.environ.get("MESHCTX_CLUSTER_ARCHIVE_TTL", str(30 * 86400)))

# meshctx 数据根 (与 web3_messaging 的 ~/.meshctx/web3_journal/ 同根)
MESHCTX_HOME = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
INBOX_DIR = MESHCTX_HOME / "cluster" / "inbox"
JOURNAL_DIR = MESHCTX_HOME / "web3_journal"

# admin 文件队列 (WSL admin_msg.py 方法) — 选配互通
ADMIN_MSG_DIR = os.environ.get("MESHCTX_ADMIN_MSG_DIR", "")  # 例: \\wsl.localhost\Ubuntu\tmp\admin_msgs

# v6 §2.1 项目路由表 (与 WSL hub_client.py PROJECT_PROFILES 一致)
PROJECT_PROFILES = {
    "quant": "quant",
    "meshctx": "meshctx",
    "geo": "geo",
    "crypto": "crypto",
    "crypto-v1": "crypto-v1",
    "crypto-v2": "crypto-v2",
    "admin": "admin",
    "deepseek": "deepseek",
}
DEFAULT_PROJECT_PROFILE = "deepseek"  # 未知项目汇聚

# v6 §1 已知机器号 (hub 侧过滤依据)
KNOWN_MACHINE_IDS = {"001", "002", "003", "004"}

_PROFILE_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
_RESERVED_PROFILES = {"test"}
_PROJECT_FORBIDDEN = re.compile(r"[\s:/\x00-\x1f]")

# zcode 项目作用域实例标识 (三实例按项目隔离的根基)
# 通道: hub:inbox:004:zcode:meshctx — hermes listener 的 drain 跳过所有含 ":" 的
# inbox 后缀, 既不盗窃本项目通道, 也不受其他 zcode 项目实例影响
_INSTANCE = f"{MACHINE_ID}:{AGENT}:{PROJECT}"


def zcode_inbox_channel(project: str = "") -> str:
    """某 zcode 项目实例的专属收信通道 (缺省 = 本实例项目)。"""
    return f"hub:inbox:{MACHINE_ID}:{AGENT}:{project or PROJECT}"


def inbox_channels() -> List[str]:
    return [zcode_inbox_channel()]


def resolve_project_profile(project_id: str) -> str:
    """项目路由: project_id → profile (v6 §2.1, 大小写/连字符容错)。"""
    if not project_id:
        return DEFAULT_PROJECT_PROFILE
    if project_id in PROJECT_PROFILES:
        return PROJECT_PROFILES[project_id]
    low = project_id.lower().replace(" ", "-")
    return PROJECT_PROFILES.get(low, DEFAULT_PROJECT_PROFILE)


def validate_profile_name(name: str) -> bool:
    """profile 名白名单 (v6 §3): 非空、非纯数字、非保留字、合法字符集。"""
    if not name or not isinstance(name, str):
        return False
    if name in _RESERVED_PROFILES or name.isdigit():
        return False
    return bool(_PROFILE_RE.fullmatch(name))


def validate_project_id(project: str) -> bool:
    """项目名校验 (v6 §3.2 项目部分放宽): 允许 Unicode, 禁空白/:/斜杠/控制符, ≤128。"""
    if project is None:
        return True
    p = str(project).strip()
    if not p or len(p) > 128:
        return False
    return not _PROJECT_FORBIDDEN.search(p)


def split_to_profile(to_profile: str):
    """拆分 "profile:project" / "profile/project" → (base_profile, project|None)。"""
    if not to_profile:
        return "", None
    if ":" in to_profile or "/" in to_profile:
        parts = re.split(r"[:/]", to_profile, maxsplit=1)
        return parts[0], (parts[1] if len(parts) > 1 else None)
    return to_profile, None


# ── 自杀防护 (v6.1 §9) ─────────────────────────────────────

_SELFKILL_PATTERNS = ("hub_client.py listen", "pkill", "killall")


def is_selfkill_command(cmd: str) -> bool:
    """listener 自杀类命令识别 (v6.1 §9 铁律)。"""
    if not cmd:
        return False
    low = str(cmd).lower()
    return any(p in low for p in _SELFKILL_PATTERNS)


# ── Redis 连接 (可选依赖, 优雅降级) ────────────────────────

_redis_mod = None
try:
    import redis as _redis_mod  # type: ignore
except ImportError:
    _redis_mod = None


def redis_available() -> bool:
    return _redis_mod is not None


def get_redis():
    """获取 hub Redis 连接 (每次 ping 校验)。redis-py 缺失时抛 RuntimeError。"""
    if _redis_mod is None:
        raise RuntimeError("redis-py 未安装 — 集群通讯降级为 journal-only (pip install redis)")
    r = _redis_mod.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
        decode_responses=True, socket_connect_timeout=5,
        socket_keepalive=True, health_check_interval=30,
    )
    r.ping()
    return r


# ── Web3 记录层 (v6 §5) ────────────────────────────────────

_journal = None


def get_journal():
    """哈希链 journal (Web3MessagingLayer = LocalJournal + HashChainLedger, 懒加载)。"""
    global _journal
    if _journal is None:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from src.core.web3_messaging import Web3MessagingLayer
            JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
            _journal = Web3MessagingLayer(f"{AGENT}_{PROJECT}", JOURNAL_DIR)
        except Exception:
            return None
    return _journal


def journal_record(kind: str, payload: Dict[str, Any]) -> Optional[Dict]:
    """收发写哈希链 journal (失败不影响主流程)。

    Web3MessagingLayer API: log_send (发送方记录) / log_receive (接收方记录)。
    """
    j = get_journal()
    if j is None:
        return None
    msg_id = payload.get("msg_id", f"{kind}_{int(time.time()*1000)}")
    try:
        if kind == "send":
            return j.log_send(AGENT, msg_id, payload, kind=kind)
        return j.log_receive(AGENT, msg_id, payload, kind=kind)
    except Exception:
        return None


def journal_verify():
    """journal 完整性校验 (v6 §5 verify)。"""
    j = get_journal()
    if j is None:
        return {"ok": False, "error": "journal 不可用"}
    ok, bad = j.verify()
    return {"ok": ok, "first_bad": bad, "entries": len(j.ledger)}


# ── 收件箱 (本地文件) ──────────────────────────────────────

def _inbox_file() -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return INBOX_DIR / f"{AGENT}_{PROJECT}.jsonl"


def _write_inbox(data: Dict[str, Any]) -> None:
    fp = _inbox_file()
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps({**data, "received_at":
                            datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")


def read_inbox(count: int = 20) -> List[Dict[str, Any]]:
    """读取本地收件箱 (最新在前)。"""
    fp = _inbox_file()
    if not fp.exists():
        return []
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    out = []
    for line in reversed(lines[-count:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ── 发送 (v6 线缆协议) ─────────────────────────────────────

def send_dm(target_mid: str, message: str, from_profile: str = "",
            to_profile: str = "", reply_channel: str = "",
            project_id: str = "", r=None):
    """点对点消息 (v6 单通道协议 + B1 白名单 + 项目路由)。

    返回 msg_id; profile 非法返回 "rejected"; redis 不可用返回 {"ok": False,...}。
    """
    if r is None:
        try:
            r = get_redis()
        except Exception as e:
            return {"ok": False, "error": f"redis 不可用: {e}"}

    # B1: profile 白名单 + 项目路由拆分
    if to_profile:
        base, proj = split_to_profile(to_profile)
        if proj is not None and not validate_project_id(proj):
            return "rejected"
        if not validate_profile_name(base):
            return "rejected"
        if project_id and not validate_project_id(project_id):
            return "rejected"

    msg_id = str(uuid.uuid4())[:8]
    msg = {
        "msg_id": msg_id,
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "from_agent": AGENT,
        "from_profile": from_profile or AGENT,
        "to": target_mid,
        "to_profile": to_profile,
        "reply_channel": reply_channel,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # C: 项目路由 — to_profile="profile:project" 拆分优先; 显式 project_id 次之
    proj2 = split_to_profile(to_profile)[1] if to_profile else None
    if proj2:
        msg["project_id"] = proj2
    elif project_id:
        msg["project_id"] = project_id

    # v5.1 铁律: 单通道 LPUSH + PUBLISH, 不双写 hub:profile:*
    raw = json.dumps(msg, ensure_ascii=False)
    r.lpush(f"hub:inbox:{target_mid}", raw)
    r.publish(f"hub:inbox:{target_mid}", raw)
    journal_record("send", msg)
    return msg_id


def send_reply(original_msg: Dict[str, Any], reply_text: str,
               from_profile: str = "", project_id: str = "", r=None):
    """v6.1 §8 回执路由: 回执回给发布者 (from_profile), 禁止固定 admin。"""
    publisher_profile = original_msg.get("from_profile", "")
    publisher_mid = original_msg.get("from", "") or original_msg.get("from_label", "")
    if not publisher_profile:
        return ""
    if not project_id:
        project_id = original_msg.get("project_id", "")
    reply_channel = original_msg.get("reply_channel", "")
    target_mid = publisher_mid
    if reply_channel and str(reply_channel).startswith("hub:inbox:"):
        tail = str(reply_channel).split(":")[-1]
        if tail.isdigit():
            target_mid = tail
    target = publisher_profile
    if project_id:
        target = f"{publisher_profile}:{project_id}"
    return send_dm(target_mid, reply_text, from_profile=from_profile or AGENT,
                   to_profile=target, reply_channel=reply_channel, r=r)


def announce(text: str, r=None):
    """入网通告: 向本机 meshctx profile 收件箱投递 (经 hub:inbox:004, hermes listener 落盘)。"""
    return send_dm(MACHINE_ID, text, from_profile=AGENT,
                   to_profile=f"meshctx:{PROJECT}", r=r)


def send_to_zcode(project: str, message: str, target_mid: str = "", r=None):
    """zcode↔zcode 跨项目投递: 直达目标项目实例的专属通道 (不经 hermes listener)。

    例: send_to_zcode("quant", "量化数据已更新") → hub:inbox:004:zcode:quant,
    仅 MESHCTX_CLUSTER_PROJECT=quant 的 zcode 实例消费。
    """
    mid = target_mid or MACHINE_ID
    if r is None:
        try:
            r = get_redis()
        except Exception as e:
            return {"ok": False, "error": f"redis 不可用: {e}"}
    msg_id = str(uuid.uuid4())[:8]
    msg = {
        "msg_id": msg_id,
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "from_agent": AGENT,
        "from_profile": AGENT,
        "to": mid,
        "to_profile": f"{AGENT}:{project}",
        "to_project": project,
        "reply_channel": zcode_inbox_channel(project),
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chan = zcode_inbox_channel(project)
    raw = json.dumps(msg, ensure_ascii=False)
    r.lpush(chan, raw)
    r.publish(chan, raw)
    journal_record("send", msg)
    return msg_id


# ── 心跳 (与 hermes 共存, 不覆盖其 004 条目) ───────────────

def heartbeat(r=None) -> Dict[str, Any]:
    """心跳: hub:workers hash 以 f"{mid}:{agent}" 为键 (hermes 的纯数字条目不被覆盖)。"""
    info = {
        "machine_id": MACHINE_ID,
        "agent": AGENT,
        "project": PROJECT,
        "label": MACHINE_LABEL,
        "hostname": socket.gethostname(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "worker_key": f"{_INSTANCE}",
        "source": "meshctx-cluster-v6",
    }
    if r is None:
        try:
            r = get_redis()
        except Exception as e:
            return {"ok": False, "error": f"redis 不可用: {e}", **info}
    try:
        r.hset("hub:workers", _INSTANCE, json.dumps(info))
        r.publish("hub:status", json.dumps(info))
        r.lpush("hub:logs", json.dumps({"ts": info["timestamp"], "type": "heartbeat",
                                        "from": f"{MACHINE_ID}:{AGENT}"}))
        r.ltrim("hub:logs", 0, 499)
        return {"ok": True, **info}
    except Exception as e:
        return {"ok": False, "error": str(e), **info}


def get_workers(r=None) -> Dict[str, Any]:
    try:
        if r is None:
            r = get_redis()
        return {k: json.loads(v) for k, v in r.hgetall("hub:workers").items()}
    except Exception as e:
        return {"_error": str(e)}


# ── 接收 (专属通道 + drain) ────────────────────────────────

def _seen(r, msg_id: str) -> bool:
    """跨轮询去重 (v6 hermes 同款语义): SET NX EX 300 — 新消息 True。"""
    if not msg_id:
        return False
    try:
        return not r.set(f"hub:dedup:{_INSTANCE}:{msg_id}", "1", nx=True, ex=300)
    except Exception:
        return False


def poll_once(r=None, timeout: float = 1.0) -> List[Dict[str, Any]]:
    """单次收取: 先 RPOP 队列 (pubsub 离线期间的消息), 再消费 pubsub 实时消息。

    每条消息: 去重 → 写本地收件箱 jsonl + Web3 journal + 归档 (30 天 TTL)。
    """
    if r is None:
        try:
            r = get_redis()
        except Exception as e:
            return [{"_error": f"redis 不可用: {e}"}]
    got: List[Dict[str, Any]] = []
    chan = inbox_channels()[0]

    def _accept(data: Dict[str, Any]) -> bool:
        """去重通过则 journal→收件箱→归档, 返回 True。(NX 先行保证单投递;
        journal 先于收件箱, 最小化 hermes P0 'zombie dedup' 丢失窗口)"""
        if _seen(r, data.get("msg_id", "")):
            return False
        journal_record("recv", data)
        _write_inbox(data)
        _archive(r, data)
        got.append(data)
        return True

    while True:
        raw = r.rpop(chan)
        if not raw:
            break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _accept(data)
    ps = r.pubsub()
    ps.subscribe(chan)
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        remain = max(0.0, deadline - time.perf_counter())
        m = ps.get_message(timeout=min(remain, 0.5) or 0.01)
        if not m or m.get("type") != "message":
            continue
        try:
            data = json.loads(m["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        _accept(data)
    ps.close()
    return got


def _archive(r, data: Dict[str, Any]) -> None:
    """归档 (v6 §1.4: 30 天 TTL, key 用路由后 profile)。"""
    try:
        prof = data.get("to_profile") or f"{AGENT}:{PROJECT}"
        key = f"hub:archive:{prof}"
        r.lpush(key, json.dumps({**data, "received_at":
                                 datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
        r.ltrim(key, 0, 499)
        r.expire(key, ARCHIVE_TTL_SEC)
    except Exception:
        pass


def listen(poll_interval: float = 10.0, heartbeat_interval: float = 60.0):
    """常驻监听循环 (Ctrl+C 退出)。心跳与收信互不阻塞。"""
    r = get_redis()
    last_hb = 0.0
    print(f"[meshctx-v6] listening machine={MACHINE_ID} agent={AGENT} "
          f"project={PROJECT} channel={inbox_channels()[0]}", flush=True)
    while True:
        now = time.perf_counter()
        if now - last_hb >= heartbeat_interval:
            hb = heartbeat(r=r)
            last_hb = now
            if hb.get("ok"):
                print(f"[meshctx-v6] heartbeat ok", flush=True)
        msgs = poll_once(r=r, timeout=min(poll_interval, 5.0))
        for m in msgs:
            print(f"[meshctx-v6] ← {m.get('from','?')}/{m.get('from_profile','?')}: "
                  f"{str(m.get('message',''))[:80]}", flush=True)


# ── admin 文件队列互通 (WSL admin_msg.py 方法, 选配) ───────

def send_admin_msg(target: str, message: str, msg_dir: str = "") -> Dict[str, Any]:
    """按 WSL admin_msg.py 格式写文件队列 (MESHCTX_ADMIN_MSG_DIR 指向 WSL 的 /tmp/admin_msgs)。"""
    d = msg_dir or ADMIN_MSG_DIR
    if not d:
        return {"ok": False, "error": "MESHCTX_ADMIN_MSG_DIR 未配置 (admin 文件队列互通关闭)"}
    try:
        target_dir = Path(d) / target
        target_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seq = len(list(target_dir.glob("*.json"))) + 1
        fp = target_dir / f"{ts}_{seq:03d}.json"
        payload = {"from": AGENT, "to": target, "time": ts, "message": message}
        fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        journal_record("admin_send", payload)
        return {"ok": True, "file": str(fp)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── CLI ────────────────────────────────────────────────────

def _cli(argv: List[str]):
    import argparse
    ap = argparse.ArgumentParser(description="meshctx 集群通讯 v6 (zcode@004/meshctx)")
    ap.add_argument("action", choices=[
        "heartbeat", "workers", "send", "reply", "inbox", "listen",
        "announce", "verify", "admin-msg", "selfcheck",
    ])
    ap.add_argument("--target", "-t", default="", help="目标机器 ID (001-004)")
    ap.add_argument("--to-profile", "-tp", default="", help='目标 profile, 支持 "profile:project"')
    ap.add_argument("--message", "-m", default="", help="消息内容")
    ap.add_argument("--project", "-p", default="", help="project_id (项目路由)")
    ap.add_argument("--reply-channel", default="", help="回执通道")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _cli(argv or sys.argv[1:])
    if args.action == "heartbeat":
        print(json.dumps(heartbeat(), ensure_ascii=False, indent=2))
    elif args.action == "workers":
        print(json.dumps(get_workers(), ensure_ascii=False, indent=2))
    elif args.action == "send":
        if not args.target or not args.message:
            print("用法: send -t <mid> -m <msg> [-tp profile:project] [-p project_id] [--reply-channel ch]")
            return 1
        out = send_dm(args.target, args.message, to_profile=args.to_profile,
                      project_id=args.project, reply_channel=args.reply_channel)
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "reply":
        inbox = read_inbox(1)
        if not inbox:
            print("(收件箱为空, 无消息可回)")
            return 1
        print(json.dumps(send_reply(inbox[0], args.message), ensure_ascii=False))
    elif args.action == "inbox":
        msgs = read_inbox(20)
        if not msgs:
            print("(inbox empty)")
        for m in msgs:
            print(f"[{m.get('received_at', m.get('timestamp', ''))[:19]}] "
                  f"{m.get('from','?')}/{m.get('from_profile','?')}: {str(m.get('message',''))[:100]}")
    elif args.action == "announce":
        out = announce(args.message or
                       f"[meshctx-v6] {AGENT}@{MACHINE_ID} ({PROJECT}) 已接入集群通讯 v6")
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "verify":
        print(json.dumps(journal_verify(), ensure_ascii=False))
    elif args.action == "admin-msg":
        out = send_admin_msg(args.target or "admin", args.message)
        print(json.dumps(out, ensure_ascii=False))
    elif args.action == "selfcheck":
        report = {
            "identity": {"machine": MACHINE_ID, "agent": AGENT, "project": PROJECT},
            "redis_py": redis_available(),
            "inbox_channel": inbox_channels(),
            "journal": journal_verify(),
            "selfkill_guard": is_selfkill_command("pkill -f hub_client.py listen"),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.action == "listen":
        listen()
    return 0


if __name__ == "__main__":
    sys.exit(main())
