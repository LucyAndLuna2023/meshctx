#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 集群组通道 v6.2 — 企业版/团队版协作核心 (部门/项目共享信息通道)

需求 (用户 2026-09-22 定稿):
  · 同一部门的人共享一个信息通道   → hub:group:{org}:dept:{dept_id}
  · 同一项目的人共享一个信息通道   → hub:group:{org}:project:{project_id}

设计:
  · 组注册表  hub:groups:{org}            Hash: group_id → JSON 元数据
  · 成员表    hub:group:{org}:{gid}:members  Set: "{mid}:{profile}"
  · 投递语义  fanout — 逐成员投递到其 profile 主通道 hub:profile:{mid}:{profile}
    (竞争队列 RPOP 不能组播; fanout 复用 v6.1 全链: 信封校验/msg_id NX 去重/
     收件箱/journal/归档, 且 **零 listener 改动** — 每人各收一份, 天然审计友好)
  · 权限 (对齐企业版 RBAC 五角色 owner/admin/manager/member/auditor):
      发消息   member 及以上 (auditor 只读)
      加/踢人  组 owner 或 org admin/manager
      创建组   org admin+
      读       成员 (auditor 以只读身份入组收副本)
  · 企业版插拔点: MESHCTX_GROUP_ROLE_PROVIDER 指向闭源 core 的 RBAC provider
    (开源 stub: 本机单租户全 owner — 团队版 ≤5 人足够; 组织级权限由企业版覆写)
  · 跨租户隔离: org 强制前缀, 开源默认 "default"; 跨 org 组互不可见

CLI: python3 cluster_groups.py {create,add,remove,send,members,list} ...
"""
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from cluster_comm_v6 import (  # 复用 v6.1 全部基础设施
        AGENT, MACHINE_ID, get_redis, journal_record,
        validate_profile_name, validate_route_key, envelope_valid,
    )
except ImportError:  # 直接脚本执行时
    sys_path = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from cluster_comm_v6 import (
        AGENT, MACHINE_ID, get_redis, journal_record,
        validate_profile_name, validate_route_key, envelope_valid,
    )

ORG = os.environ.get("MESHCTX_ORG", "default")
ROLE_PROVIDER = os.environ.get("MESHCTX_GROUP_ROLE_PROVIDER", "")

# 企业版 RBAC 五角色 (与 BP/企业版文档一致); 数值越大权限越高
ROLE_LEVEL = {"auditor": 0, "member": 1, "manager": 2, "admin": 3, "owner": 4}


def _role_for(actor: str, group: Dict[str, Any], action: str) -> str:
    """actor 在 group 内对 action 的有效角色。企业版覆写点 (ROLE_PROVIDER)。"""
    if ROLE_PROVIDER:
        try:
            mod_name, fn_name = ROLE_PROVIDER.split(":", 1)
            fn = getattr(__import__(mod_name, fromlist=[fn_name]), fn_name)
            return fn(actor, group, action)
        except Exception:
            pass
    # 开源 stub: 单机/≤5人团队 — 仅本机身份 owner; 其他 actor 默认 member
    # (可发消息, 不可管理组) — 企业版经 ROLE_PROVIDER 按部门树覆写
    if actor == f"{MACHINE_ID}:{AGENT}":
        return "owner"
    return "member"


def _member_key(org: str, gid: str) -> str:
    return f"hub:group:{org}:{gid}:members"


def _registry_key(org: str) -> str:
    return f"hub:groups:{org}"


def _valid_gid(gid: str) -> bool:
    """组 id 复用项目名校验 (禁空白/:/斜杠/控制符) — 防通道键注入 (I-6 教训)."""
    return bool(gid) and validate_route_key(f"hub:group:{ORG}:{gid}") or (
        bool(gid) and ":" not in gid and "/" not in gid and len(gid) <= 128
        and not any(c.isspace() for c in gid))


def create_group(r, gid: str, gtype: str, name: str = "",
                 actor: str = "", org: str = "") -> Dict[str, Any]:
    """创建组 (部门 dept / 项目 project)。org admin+ (stub: 本机全权)。"""
    org = org or ORG
    if gtype not in ("dept", "project"):
        return {"ok": False, "error": "gtype 必须是 dept 或 project"}
    if not _valid_gid(gid):
        return {"ok": False, "error": f"非法组 id: {gid}"}
    role = _role_for(actor or f"{MACHINE_ID}:{AGENT}", {}, "create_group")
    if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL["admin"]:
        return {"ok": False, "error": f"创建组需要 admin+, 当前 {role}"}
    gkey = _registry_key(org)
    if r.hget(gkey, gid):
        return {"ok": False, "error": f"组已存在: {gid}"}
    meta = {"type": gtype, "name": name or gid, "org": org,
            "owner": actor or f"{MACHINE_ID}:{AGENT}",
            "min_write": "member", "created_at": time.time()}
    r.hset(gkey, gid, json.dumps(meta, ensure_ascii=False))
    # 创建者自动入组
    r.sadd(_member_key(org, gid), f"{MACHINE_ID}:{AGENT}")
    journal_record("group_create", {"group": gid, "org": org, "type": gtype})
    return {"ok": True, "group": gid, "type": gtype, "org": org}


def add_member(r, gid: str, member: str, actor: str = "",
               role: str = "member", org: str = "") -> Dict[str, Any]:
    """拉人入组: 组 owner 或 org admin/manager。member 身份 = {mid}:{profile}。"""
    org = org or ORG
    member = str(member).strip()
    if ":" not in member or not all(validate_profile_name(p) or p.isdigit()
                                    for p in member.split(":", 1)):
        return {"ok": False, "error": f"成员身份格式须为 {{mid}}:{{profile}}: {member}"}
    meta = _group_meta(r, gid, org)
    if not meta:
        return {"ok": False, "error": f"组不存在: {gid}"}
    role = role if role in ROLE_LEVEL else "member"
    me = actor or f"{MACHINE_ID}:{AGENT}"
    if me != meta.get("owner") and ROLE_LEVEL.get(_role_for(me, meta, "add"), 0) < ROLE_LEVEL["manager"]:
        return {"ok": False, "error": "加人需要组 owner 或 org manager+"}
    added = r.sadd(_member_key(org, gid), member)
    journal_record("group_add", {"group": gid, "member": member, "by": me})
    return {"ok": True, "group": gid, "member": member, "new": bool(added)}


def remove_member(r, gid: str, member: str, actor: str = "",
                  org: str = "") -> Dict[str, Any]:
    """踢人: 组 owner 或 org admin/manager; owner 不可被移除。"""
    org = org or ORG
    meta = _group_meta(r, gid, org)
    if not meta:
        return {"ok": False, "error": f"组不存在: {gid}"}
    me = actor or f"{MACHINE_ID}:{AGENT}"
    if me != meta.get("owner") and ROLE_LEVEL.get(_role_for(me, meta, "remove"), 0) < ROLE_LEVEL["manager"]:
        return {"ok": False, "error": "踢人需要组 owner 或 org manager+"}
    if member == meta.get("owner"):
        return {"ok": False, "error": "组 owner 不可被移除"}
    removed = r.srem(_member_key(org, gid), member)
    journal_record("group_remove", {"group": gid, "member": member, "by": me})
    return {"ok": True, "removed": bool(removed)}


def leave_group(r, gid: str, actor: str = "", org: str = "") -> Dict[str, Any]:
    me = actor or f"{MACHINE_ID}:{AGENT}"
    meta = _group_meta(r, gid, org or ORG)
    if meta and me == meta.get("owner"):
        return {"ok": False, "error": "owner 不可退出 (先转让或删组)"}
    n = r.srem(_member_key(org or ORG, gid), me)
    return {"ok": True, "left": bool(n)}


def _group_meta(r, gid: str, org: str) -> Optional[Dict[str, Any]]:
    raw = r.hget(_registry_key(org), gid)
    return json.loads(raw) if raw else None


def group_members(r, gid: str, org: str = "") -> List[str]:
    return sorted(r.smembers(_member_key(org or ORG, gid)) or [])


def list_groups(r, org: str = "") -> Dict[str, Any]:
    org = org or ORG
    out = {}
    for gid, raw in (r.hgetall(_registry_key(org)) or {}).items():
        try:
            meta = json.loads(raw)
            meta["members"] = r.scard(_member_key(org, gid))
            out[gid] = meta
        except Exception:
            continue
    return out


def group_send(r, gid: str, message: str, sender: str = "",
               org: str = "", msg_type: str = "group_msg") -> Dict[str, Any]:
    """组播: 权限检查 → fanout 到每个成员的 profile 主通道。

    · sender 必须是成员且非 auditor (auditor 只读)
    · 信封复用 v6.1 envelope_valid 全字段; 接收方 NX 去重天然防重复
    · 同组内本人也收一份 (信息流一致, 审计友好)
    """
    org = org or ORG
    me = sender or f"{MACHINE_ID}:{AGENT}"
    meta = _group_meta(r, gid, org)
    if not meta:
        return {"ok": False, "error": f"组不存在: {gid}"}
    members = group_members(r, gid, org)
    if me not in members:
        return {"ok": False, "error": "非成员不可发送 (先加入组)"}
    # 角色: owner 全权; 其余 stub member; auditor 只读 (企业版经 ROLE_PROVIDER 覆写)
    if me == meta.get("owner"):
        my_role = "owner"
    else:
        my_role = _role_for(me, meta, "send")
    if ROLE_LEVEL.get(my_role, 1) < ROLE_LEVEL["member"]:
        return {"ok": False, "error": f"auditor 只读, 不可发送 ({my_role})"}
    if not str(message or "").strip():
        return {"ok": False, "error": "message 为空"}

    msg_id = str(uuid.uuid4())[:8]
    delivered = []
    for member in members:
        try:
            mid, profile = member.split(":", 1)
        except ValueError:
            continue
        channel = f"hub:profile:{mid}:{profile}"
        if not validate_route_key(channel):  # I-6 铁律: 键白名单强制
            journal_record("group_send_badroute",
                           {"group": gid, "member": member, "channel": channel})
            continue
        msg = {"msg_id": msg_id, "from": MACHINE_ID, "from_agent": AGENT,
               "from_profile": me, "to": mid, "to_profile": profile,
               "group": gid, "group_type": meta.get("type"), "org": org,
               "msg_type": msg_type, "reply_channel": f"hub:profile:{MACHINE_ID}:{AGENT}",
               "message": str(message),
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        assert envelope_valid(msg)
        raw = json.dumps(msg, ensure_ascii=False)
        r.lpush(channel, raw)
        r.publish(channel, raw)
        delivered.append(member)
    journal_record("group_send", {"group": gid, "msg_id": msg_id,
                                  "members": len(members), "delivered": len(delivered)})
    return {"ok": True, "msg_id": msg_id, "group": gid,
            "delivered": f"{len(delivered)}/{len(members)}", "to": delivered}
