"""Org Governance (组织架构/部门/授权 RBAC) API — /api/org (2026-09 用户需求).

端内鉴权: owner 归因 + 写操作拒匿名 + 管理操作需对应权限
(manage_depts/manage_members/manage_roles); 个人版单用户自举 (ensure_self_bootstrap);
数据权限跨用户放行由 org_governance.visible_owner_ids 驱动 (team/enterprise 价值,
free 单用户天然 self scope)。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("meshctx.org_api")

router = APIRouter(prefix="/api/org", tags=["Org Governance"])


async def _owner(request: Request) -> str:
    try:
        from src.main import _current_user_id
        return await _current_user_id(request)
    except Exception:
        from src.core.auth_v2 import _authenticate, _is_loopback_client
        try:
            identity, is_admin = await _authenticate(request)
            if identity:
                return "admin" if is_admin else f"key:{identity}"
            if _is_loopback_client(request):
                return "local"
        except Exception:
            pass
    return ""


async def _reject_anon(owner: str):
    if not owner:
        raise HTTPException(401, "需要登录 (本机回环可免登录使用)")


def _svc():
    from src.core.org_governance import get_org_service
    return get_org_service()


def _require(owner: str, perm: str):
    svc = _svc()
    svc.ensure_self_bootstrap(owner)     # 组织为空时才可能自举 owner
    if not svc.has(owner, perm):
        raise HTTPException(403, f"缺少权限 {perm} (角色不足)")


def _must_member(owner: str):
    """P2-1: 组织非空后, 未入册用户一律 403 (不再自愈为 owner)。"""
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
    m = svc.member(owner)
    if m is None:
        raise HTTPException(403, "非组织成员 (需管理员邀请加入部门)")
    return m, svc


def _can_manage_role(actor_role: str, target_role: str, target_existing: bool) -> bool:
    """RBAC 变更授权 (P2-2): owner>admin>manager>member>auditor; 不得授予高于自身。"""
    from src.core.org_governance import role_rank
    ar = role_rank(actor_role)
    if target_role in ("owner", "admin"):
        return actor_role == "owner"          # 仅 owner 可设 owner/admin
    if actor_role == "owner":
        return True
    if actor_role == "admin":
        return target_role in ("manager", "member", "auditor")
    if actor_role == "manager":
        return target_role in ("member", "auditor")
    return False                              # member/auditor 不可管理人


def _can_remove_role(actor_role: str, target_role: str) -> bool:
    """移除授权: 不得移除高于自身等级; 仅 owner 可移 owner/admin。"""
    from src.core.org_governance import role_rank
    if actor_role == "owner":
        return True
    if target_role in ("owner", "admin"):
        return False
    if actor_role == "admin":
        return True
    if actor_role == "manager":
        return target_role in ("member", "auditor")
    return False


@router.get("/me")
async def org_me(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)          # 组织为空首访 → owner; 否则如实返回 member=None
    m = svc.member(owner)
    return {"user": owner, "member": m,
            "permissions": sorted(svc.permissions(owner)) if m else [],
            "data_scope": svc.data_scope(owner) if m else "none"}


@router.get("/depts")
async def org_depts(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _, svc = _must_member(owner)
    if not svc.has(owner, "view_org"):
        raise HTTPException(403, "缺少权限 view_org")
    return {"depts": svc.list_depts()}


@router.post("/depts")
async def org_dept_create(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _require(owner, "manage_depts")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    try:
        d = _svc().upsert_dept(str(body.get("name") or ""),
                              str(body.get("parent_id") or ""),
                              str(body.get("id") or ""), actor=owner)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return d


def _purge_dept_memories(dept_ids):
    """P3-7: 部门删除/记忆整删后清理 dept:{id} 孤儿共享记忆。"""
    from src.core.memory_api import get_memory_service
    ms = get_memory_service()
    for did in dept_ids:
        try:
            ms.delete_namespace(_dept_mem_key(did))
        except Exception:
            pass


@router.delete("/depts/{dept_id}")
async def org_dept_delete(dept_id: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _require(owner, "manage_depts")
    svc = _svc()
    subtree = svc.dept_subtree_ids(dept_id)
    if not subtree:
        raise HTTPException(404, "部门不存在")
    try:
        svc.remove_dept(dept_id, actor=owner)
    except ValueError as e:                      # P3-7 根保护 → 400
        raise HTTPException(400, str(e))
    _purge_dept_memories(subtree)                # P3-7 孤儿部门记忆
    return {"ok": True, "purged_depts": len(subtree)}


@router.post("/import")
async def org_import(request: Request):
    """批量导入部门: body {"format":"json|csv","items":[{name,parent?}]}"""
    owner = await _owner(request)
    await _reject_anon(owner)
    _require(owner, "manage_depts")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    fmt = str(body.get("format") or "json")
    items = []
    if fmt == "csv":
        import csv as _csv, io as _io
        raw = str(body.get("csv") or "")
        for row in _csv.reader(_io.StringIO(raw)):
            row = [c.strip() for c in row]
            if not row or not row[0]:
                continue
            if row[0].lstrip("#").lower() in ("name", "部门", "dept"):
                continue                          # 表头跳过 (中英)
            items.append({"name": row[0], "parent": row[1] if len(row) > 1 else ""})
    elif fmt == "json":
        items = body.get("items") or []
        if not isinstance(items, list):
            raise HTTPException(400, "items 需为数组")
    else:
        raise HTTPException(400, "format 仅 json|csv")
    if not items:
        raise HTTPException(400, "无有效条目")
    res = _svc().import_depts(items, actor=owner)
    return {"ok": True, **res, "imported": len(items)}


@router.get("/members")
async def org_members(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    m0, svc = _must_member(owner)
    if not svc.has(owner, "manage_members"):
        # 普通成员可见同部门成员 (用于协作视图)
        m = svc.member(owner)
        if m and m.get("dept_id"):
            depts = svc.dept_subtree_ids(m["dept_id"])
            rows = [mm for mm in svc.list_members() if mm.get("dept_id") in depts]
            return {"members": rows}
        raise HTTPException(403, "缺少权限 manage_members")
    return {"members": svc.list_members()}


@router.post("/members")
async def org_member_assign(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    me, svc = _must_member(owner)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    _require(owner, "manage_members")
    t_uid = str(body.get("user_id") or "")
    t_role = str(body.get("role") or "member")
    t_dept = str(body.get("dept_id") or "")
    target_m = svc.member(t_uid)
    t_existing = target_m is not None
    old_role = target_m.get("role", "") if target_m else ""
    # 授权: 设置的目标角色受 actor 等级约束 (P2-2)
    if not _can_manage_role(me["role"], t_role, t_existing):
        raise HTTPException(403, "无权授予该角色 (不得高于自身/仅 owner 可设 owner-admin)")
    # 降级已有高等级成员 (owner/admin 变更) 仅 owner
    if t_existing and old_role in ("owner", "admin") and me["role"] != "owner":
        raise HTTPException(403, "仅 owner 可变更 owner/admin 成员")
    # 不得提升自己等级 (P2-2)
    from src.core.org_governance import role_rank
    if t_uid == owner and role_rank(t_role) > role_rank(me["role"]):
        raise HTTPException(403, "不能提升自己等级")
    try:
        m = svc.set_member(t_uid, t_dept, t_role, actor=owner)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return m


@router.delete("/members/{user_id}")
async def org_member_remove(user_id: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    me, svc = _must_member(owner)
    _require(owner, "manage_members")
    if user_id == owner:
        raise HTTPException(400, "不能移除自己")
    tm = svc.member(user_id)
    if tm is None:
        raise HTTPException(404, "成员不存在")
    if not _can_remove_role(me["role"], tm.get("role", "member")):
        raise HTTPException(403, "无权移除该等级成员 (仅 owner 可移 owner/admin)")
    svc.remove_member(user_id, actor=owner)
    return {"ok": True}


@router.get("/roles")
async def org_roles(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _, svc = _must_member(owner)
    if not svc.has(owner, "view_org"):
        raise HTTPException(403, "缺少权限 view_org")
    return {"roles": {r: svc.role_permissions(r) for r in
                      ("owner", "admin", "manager", "member", "auditor")}}


@router.get("/visible-owners")
async def org_visible_owners(request: Request):
    """数据权限辅助: 当前用户可见的 owner 集合 (供任务卡/值守 dept 视图)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    _, svc = _must_member(owner)
    return {"owner": owner, "scope": svc.data_scope(owner),
            "owners": svc.visible_owner_ids(owner)}


__all__ = ["router"]


def _member_or_admin(user_id: str, dept_id: str) -> bool:
    """部门访问门槛: 本部门(含子)成员 或 组织级角色 (owner/admin/auditor)。"""
    svc = _svc()
    m = svc.member(user_id)
    if m is None:
        return False
    if m.get("role") in ("owner", "admin", "auditor"):
        return True
    depts = svc.dept_subtree_ids(m.get("dept_id") or "")
    return dept_id in depts


def _dept_writer(user_id: str, dept_id: str) -> bool:
    """P3-2: 写门槛须属目标部门子树 (防跨部门内容注入)。"""
    svc = _svc()
    m = svc.member(user_id)
    if m is None:
        return False
    if m.get("role") in ("owner", "admin"):
        return True
    if m.get("role") != "manager":
        return False
    return dept_id in svc.dept_subtree_ids(m.get("dept_id") or "")


@router.get("/audit")
async def org_audit(request: Request, limit: int = 100):
    """组织操作审计轨迹 (授权可追溯)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    me, svc = _must_member(owner)
    if not (svc.has(owner, "audit_view") or svc.has(owner, "manage_members")):
        raise HTTPException(403, "缺少权限 audit_view/manage_members")
    rows = svc.audit_trail(limit=limit)
    # P3-3: 非组织级角色仅见本部门范围审计 (按 actor 归因过滤)
    if (me["role"] not in ("owner", "admin", "auditor")
            and svc.data_scope(owner) != "org"):
        visible = set(svc.visible_owner_ids(owner))
        rows = [t for t in rows if t.get("user") in visible or t.get("user") == "system"]
    return {"audit": rows}


# ── 部门共享记忆 (数据权限落地: 部门成员可见/可协作) ──────────
def _dept_mem_key(dept_id: str) -> str:
    return f"dept:{dept_id}"


@router.post("/memory")
async def org_memory_store(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    dept_id = str(body.get("dept_id") or "")
    text = str(body.get("text") or "").strip()
    if not dept_id or not text:
        raise HTTPException(400, "dept_id/text 必填")
    if not _dept_writer(owner, dept_id):
        raise HTTPException(403, "仅本部门经理/管理员/owner 可写入部门记忆")
    if len(text) > 20000:
        raise HTTPException(400, "text 过长 (>20000)")
    from src.core.memory_api import get_memory_service
    e = get_memory_service().store(_dept_mem_key(dept_id), text, body.get("meta"))
    return {"ok": True, "id": e["id"]}


@router.get("/memory/search")
async def org_memory_search(request: Request, q: str = "", dept_id: str = "",
                            top_k: int = 5):
    owner = await _owner(request)
    await _reject_anon(owner)
    if not q.strip() or not dept_id:
        raise HTTPException(400, "q/dept_id 必填")
    if not _member_or_admin(owner, dept_id):
        raise HTTPException(403, "非本部门成员")
    from src.core.memory_api import get_memory_service
    res = get_memory_service().search(_dept_mem_key(dept_id), q.strip(), top_k)
    return {"results": res}


@router.get("/memory")
async def org_memory_list(request: Request, dept_id: str = ""):
    owner = await _owner(request)
    await _reject_anon(owner)
    if not dept_id:
        raise HTTPException(400, "dept_id 必填")
    if not _member_or_admin(owner, dept_id):
        raise HTTPException(403, "非本部门成员")
    from src.core.memory_api import get_memory_service
    return {"entries": get_memory_service().list_entries(_dept_mem_key(dept_id))}


@router.delete("/memory/{dept_id}")
async def org_memory_purge(dept_id: str, request: Request):
    """P3-7: 整删部门共享记忆 (含子树) — 仅本部门经理/管理员/owner; 防孤儿残留。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    if not _dept_writer(owner, dept_id):
        raise HTTPException(403, "仅本部门经理/管理员/owner 可删除部门记忆")
    svc = _svc()
    subtree = svc.dept_subtree_ids(dept_id)
    if not subtree:
        raise HTTPException(404, "部门不存在")
    _purge_dept_memories(subtree)
    return {"ok": True, "purged_depts": len(subtree)}


@router.get("/export")
async def org_export(request: Request):
    """治理审计导出 (SOC2 型证据包, JSONL): 组织快照 + 操作审计轨迹。
    门控: export_audit 或 audit_view+manage_members (企业版面向合规归档)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    me, svc = _must_member(owner)
    # P3-4: auditor 合规角色可导出 (矩阵一致性)
    ok = (me["role"] in ("owner", "admin", "auditor")
          or svc.has(owner, "export_audit"))
    if not ok:
        raise HTTPException(403, "缺少权限 export_audit (审计导出)")
    import json as _json
    from fastapi.responses import PlainTextResponse
    lines = []
    lines.append(_json.dumps({
        "type": "org_snapshot", "ts": __import__("time").time(),
        "depts": svc.list_depts(), "members": svc.list_members(),
        "roles": {r: svc.role_permissions(r) for r in
                  ("owner", "admin", "manager", "member", "auditor")}},
        ensure_ascii=False))
    for t in svc.audit_trail(limit=200):
        lines.append(_json.dumps({"type": "org_audit", **t}, ensure_ascii=False))
    return PlainTextResponse("\n".join(lines) + "\n",
                             media_type="application/x-ndjson")
