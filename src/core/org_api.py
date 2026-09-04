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
    svc.ensure_self_bootstrap(owner)
    if not svc.has(owner, perm):
        raise HTTPException(403, f"缺少权限 {perm} (角色不足)")


@router.get("/me")
async def org_me(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
    m = svc.member(owner)
    return {"user": owner, "member": m,
            "permissions": sorted(svc.permissions(owner)),
            "data_scope": svc.data_scope(owner)}


@router.get("/depts")
async def org_depts(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
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
                              str(body.get("id") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return d


@router.delete("/depts/{dept_id}")
async def org_dept_delete(dept_id: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _require(owner, "manage_depts")
    if not _svc().remove_dept(dept_id):
        raise HTTPException(404, "部门不存在")
    return {"ok": True}


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
        raw = str(body.get("csv") or "")
        for line in raw.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith("name,parent"):
                continue
            parts = [p.strip() for p in line.split(",")]
            items.append({"name": parts[0], "parent": parts[1] if len(parts) > 1 else ""})
    elif fmt == "json":
        items = body.get("items") or []
        if not isinstance(items, list):
            raise HTTPException(400, "items 需为数组")
    else:
        raise HTTPException(400, "format 仅 json|csv")
    if not items:
        raise HTTPException(400, "无有效条目")
    res = _svc().import_depts(items)
    return {"ok": True, **res, "imported": len(items)}


@router.get("/members")
async def org_members(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
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
    _require(owner, "manage_members")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    try:
        m = _svc().set_member(str(body.get("user_id") or ""),
                              str(body.get("dept_id") or ""),
                              str(body.get("role") or "member"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return m


@router.delete("/members/{user_id}")
async def org_member_remove(user_id: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    _require(owner, "manage_members")
    if user_id == owner:
        raise HTTPException(400, "不能移除自己")
    if not _svc().remove_member(user_id):
        raise HTTPException(404, "成员不存在")
    return {"ok": True}


@router.get("/roles")
async def org_roles(request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
    if not svc.has(owner, "view_org"):
        raise HTTPException(403, "缺少权限 view_org")
    return {"roles": {r: svc.role_permissions(r) for r in
                      ("owner", "admin", "manager", "member", "auditor")}}


@router.get("/visible-owners")
async def org_visible_owners(request: Request):
    """数据权限辅助: 当前用户可见的 owner 集合 (供任务卡/值守 dept 视图)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    svc = _svc()
    svc.ensure_self_bootstrap(owner)
    return {"owner": owner, "scope": svc.data_scope(owner),
            "owners": svc.visible_owner_ids(owner)}


__all__ = ["router"]
