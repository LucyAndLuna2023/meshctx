#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组织架构与授权治理 (Org Governance, 2026-09 用户需求: 团队/企业版).

加法式核心 (open, 个人版亦可用单用户基线; 跨用户部门数据权限为团队/企业价值):
- Department: 树形组织架构 (name/parent_id), 支持 JSON/CSV 批量导入
- Member: user_id → dept_id + role (owner/admin/manager/member/auditor)
- RBAC: 角色-权限矩阵 (manage_depts/manage_members/manage_roles/data_scope_dept/
  data_scope_org/audit_view), 权限沿部门向上继承
- 数据权限: data scope = self|dept(含子部门)|org, 依角色授予;
  dept_owner_ids(user) 供任务卡/值守等 owner 字段资源做部门聚合
- 持久化: ~/.meshctx/org_governance.json 原子写 (真相源), 与 routines 同模式
edition 注: 个人版 plan=free 走单用户自举 (创建即 owner); 多用户跨部门读写放行
要求 team/enterprise plan 或拥有 data_scope_* 权限 — 门控在 API/服务层执行。
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.org_governance")

ORG_PATH = pathlib.Path.home() / ".meshctx" / "org_governance.json"

ROLES = ("owner", "admin", "manager", "member", "auditor")

PERMISSIONS = (
    "view_org", "manage_depts", "manage_members", "manage_roles",
    "data_scope_self", "data_scope_dept", "data_scope_org",
    "audit_view", "export_audit",
)

DEFAULT_ROLE_PERMS: Dict[str, set] = {
    "owner": set(PERMISSIONS),
    "admin": set(PERMISSIONS) - {"export_audit"},
    "manager": {"view_org", "manage_members", "data_scope_self",
                "data_scope_dept", "audit_view"},
    "member": {"view_org", "data_scope_self", "audit_view"},
    "auditor": {"view_org", "audit_view", "data_scope_org"},
}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _esc(part: str) -> str:
    return part or ""


class OrgService:
    """组织/成员/角色存储与服务 (线程安全, JSON 原子落盘)。"""

    def __init__(self, path: str | os.PathLike = ""):
        self._lock = threading.RLock()
        self._path = pathlib.Path(path) if path else ORG_PATH
        self._depts: Dict[str, Dict[str, Any]] = {}      # id -> {id,name,parent_id}
        self._members: Dict[str, Dict[str, Any]] = {}    # user_id -> {user_id,dept_id,role}
        self._role_perms: Dict[str, set] = {r: set(p) for r, p in DEFAULT_ROLE_PERMS.items()}
        self._load()

    # ── 持久化 ──────────────────────────────────────────────
    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._depts = data.get("depts") or {}
                self._members = data.get("members") or {}
                rp = data.get("roles") or {}
                for r in ROLES:
                    self._role_perms[r] = set(rp.get(r, list(DEFAULT_ROLE_PERMS[r])))
        except Exception:
            logger.debug("org load failed", exc_info=True)

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps({
                "depts": self._depts, "members": self._members,
                "roles": {r: sorted(self._role_perms[r]) for r in ROLES}},
                ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("org save failed")
            try: tmp.unlink(missing_ok=True)
            except Exception: pass

    # ── 部门 ────────────────────────────────────────────────
    def list_depts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self._depts.values(), key=lambda d: d.get("name", ""))

    def get_dept(self, dept_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._depts.get(dept_id)

    def upsert_dept(self, name: str, parent_id: str = "", dept_id: str = "") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("部门名无效")
        with self._lock:
            if dept_id and dept_id in self._depts:
                d = self._depts[dept_id]
                d["name"] = name
                d["parent_id"] = parent_id or d.get("parent_id", "")
            else:
                d = {"id": _new_id(), "name": name, "parent_id": parent_id or ""}
                self._depts[d["id"]] = d
            if d.get("parent_id") and d["parent_id"] not in self._depts:
                raise ValueError("父部门不存在")
            self._save()
            return d

    def remove_dept(self, dept_id: str) -> bool:
        with self._lock:
            if dept_id not in self._depts:
                return False
            # 子部门与成员一并移除 (级联)
            removed = {dept_id}
            changed = True
            while changed:
                changed = False
                for d in list(self._depts.values()):
                    if d.get("parent_id") in removed and d["id"] not in removed:
                        removed.add(d["id"]); changed = True
            for rid in removed:
                self._depts.pop(rid, None)
            for uid, m in list(self._members.items()):
                if m.get("dept_id") in removed:
                    self._members.pop(uid, None)
            self._save()
            return True

    def import_depts(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量导入: 每项 {name, parent?} — parent 用名称解析或显式 parent_id。
        先建全部再连父, 允许乱序。返回 {created, updated, failed}。"""
        created = updated = failed = 0
        by_name: Dict[str, str] = {}
        with self._lock:
            for d in self._depts.values():
                by_name.setdefault(d["name"], d["id"])
            staged = []
            for it in items:
                name = str(it.get("name") or "").strip()
                if not name:
                    failed += 1; continue
                pid = str(it.get("parent_id") or it.get("parent") or "").strip()
                staged.append((name, pid))
            # 两遍: 先注册名称, 再连父
            created_ids: Dict[str, str] = {}
            for name, _ in staged:
                if name in by_name:
                    continue
                did = _new_id()
                self._depts[did] = {"id": did, "name": name, "parent_id": ""}
                by_name[name] = did
                created_ids[name] = did
                created += 1
            for name, pid in staged:
                did = by_name.get(name)
                if did is None:
                    continue
                parent_did = by_name.get(pid) if pid else ""
                if pid and parent_did is None:
                    failed += 1
                    continue
                cur = self._depts[did]
                if cur.get("parent_id") != parent_did:
                    cur["parent_id"] = parent_did
                    updated += 1
            self._save()
        return {"created": created, "updated": updated, "failed": failed}

    # ── 成员 / 角色 ─────────────────────────────────────────
    def set_member(self, user_id: str, dept_id: str = "", role: str = "member") -> Dict[str, Any]:
        user_id = (user_id or "").strip()
        if not user_id:
            raise ValueError("user_id 无效")
        role = role or "member"
        if role not in ROLES:
            raise ValueError(f"角色须为 {ROLES}")
        with self._lock:
            if dept_id and dept_id not in self._depts:
                raise ValueError("部门不存在")
            m = {"user_id": user_id, "dept_id": dept_id, "role": role}
            self._members[user_id] = m
            self._save()
            return m

    def remove_member(self, user_id: str) -> bool:
        with self._lock:
            if user_id not in self._members:
                return False
            self._members.pop(user_id, None)
            self._save()
            return True

    def list_members(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self._members.values(), key=lambda m: m["user_id"])

    def member(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._members.get(user_id)

    def ensure_self_bootstrap(self, user_id: str) -> None:
        """单用户自举: 该用户已是 owner 或已有角色时不动; 否则建根部门 + owner。"""
        if not user_id:
            return
        with self._lock:
            if user_id in self._members:
                return
            root = next((d for d in self._depts.values() if not d.get("parent_id")), None)
            if root is None:
                root = self.upsert_dept("总部")
            self.set_member(user_id, root["id"], "owner")

    # ── RBAC / 数据权限 ─────────────────────────────────────
    def permissions(self, user_id: str) -> set:
        m = self.member(user_id)
        role = m.get("role", "member") if m else "member"
        return set(self._role_perms.get(role, set()))

    def has(self, user_id: str, perm: str) -> bool:
        return perm in self.permissions(user_id)

    def role_permissions(self, role: str) -> list:
        return sorted(self._role_perms.get(role, set()))

    def set_role_permissions(self, role: str, perms: list) -> None:
        if role not in ROLES:
            raise ValueError("角色无效")
        bad = [p for p in perms if p not in PERMISSIONS]
        if bad:
            raise ValueError(f"未知权限 {bad}")
        with self._lock:
            self._role_perms[role] = set(perms)
            self._save()

    def data_scope(self, user_id: str) -> str:
        """self | dept | org — 按角色最高权限决定 (org>dept>self)。"""
        perms = self.permissions(user_id)
        if "data_scope_org" in perms:
            return "org"
        if "data_scope_dept" in perms:
            return "dept"
        return "self"

    def dept_subtree_ids(self, dept_id: str) -> List[str]:
        if not dept_id:
            return []
        with self._lock:
            out = {dept_id}
            changed = True
            while changed:
                changed = False
                for d in self._depts.values():
                    if d.get("parent_id") in out and d["id"] not in out:
                        out.add(d["id"]); changed = True
            return sorted(out)

    def visible_owner_ids(self, user_id: str) -> List[str]:
        """数据权限: 该用户可见的 owner 集合 (供任务卡/值守 owner 过滤)。

        scope=self → 仅自己; dept → 本部门(含子部门)全部成员; org → 全体成员。
        """
        m = self.member(user_id)
        scope = self.data_scope(user_id)
        if scope == "self":
            return [user_id]
        if scope == "org":
            with self._lock:
                return list(self._members.keys())
        # dept
        if m and m.get("dept_id"):
            depts = self.dept_subtree_ids(m["dept_id"])
            with self._lock:
                return [uid for uid, mm in self._members.items()
                        if mm.get("dept_id") in depts]
        return [user_id]


_default: Optional[OrgService] = None


def get_org_service() -> OrgService:
    global _default
    if _default is None:
        _default = OrgService()
    return _default


def reset_org_service_for_tests():
    global _default
    _default = None


__all__ = ["OrgService", "get_org_service", "reset_org_service_for_tests",
           "ORG_PATH", "ROLES", "PERMISSIONS", "DEFAULT_ROLE_PERMS"]
