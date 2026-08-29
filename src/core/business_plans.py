#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商业订阅层 — Team/Enterprise 版 (BP v3.117 开发, 2026-08-27)

BP 定价: Free(永久免费) / Team($9/人/月) / Enterprise($29/人/月)
Team: 团队共享记忆 + Swarm 群审 + 团队仪表盘
Enterprise: Team 全部 + 私有化 + SSO/SAML + 审计日志 + SLA

本模块: Plan 模型 + 功能门控 + 组织(TeamOrg)管理 + 成员 + 审计日志 + 使用统计。
存储: ~/.meshctx/business_plans.json (JSON 持久化, 无外部依赖)。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.business_plans")

# ── Plan 模型 ──────────────────────────────────────────────

class Plan(str, Enum):
    FREE = "free"
    TEAM = "team"
    ENTERPRISE = "enterprise"

    def __str__(self):
        return self.value


# 各 Plan 的功能开关 (BP v3.117 定价功能矩阵)
PLAN_FEATURES: Dict[str, Dict[str, bool]] = {
    Plan.FREE.value: {
        "shared_memory": False,     # 团队共享记忆 (Team)
        "swarm_review": False,      # Swarm 群审 (Team)
        "team_dashboard": False,    # 团队仪表盘 (Team)
        "priority_routing": False,  # 优先模型路由 (Team)
        "private_deploy": False,    # 私有化部署 (Enterprise)
        "sso": False,               # SSO/SAML (Enterprise)
        "audit_log": False,         # 审计日志 (Enterprise)
        "sla": False,               # SLA 保障 (Enterprise)
    },
    Plan.TEAM.value: {
        "shared_memory": True,
        "swarm_review": True,
        "team_dashboard": True,
        "priority_routing": True,
        "private_deploy": False,
        "sso": False,
        "audit_log": False,
        "sla": False,
    },
    Plan.ENTERPRISE.value: {
        "shared_memory": True,
        "swarm_review": True,
        "team_dashboard": True,
        "priority_routing": True,
        "private_deploy": True,
        "sso": True,
        "audit_log": True,
        "sla": True,
    },
}

PLAN_PRICES = {  # BP 定价 (USD/人/月)
    Plan.FREE.value: 0,
    Plan.TEAM.value: 9,
    Plan.ENTERPRISE.value: 29,
}


def feature_enabled(plan: str, feature: str) -> bool:
    """功能门控: 指定 plan 是否开放某功能。"""
    return bool(PLAN_FEATURES.get(plan, {}).get(feature, False))


def upgrade_path(plan: str) -> List[str]:
    """升级路径: free → team → enterprise。"""
    order = [Plan.FREE.value, Plan.TEAM.value, Plan.ENTERPRISE.value]
    try:
        idx = order.index(plan)
    except ValueError:
        return []
    return order[idx:]


# ── 组织/团队 (用户维度) ──────────────────────────────────

# RBAC 角色 (2026-08-27 AI agent 企业协作痛点: 权限管控 — atlan/腾讯调研)
# owner: 全部管理权 | admin: 管理成员/预算/记忆治理 | member: 使用团队功能 | viewer: 只读
VALID_ROLES = ("owner", "admin", "member", "viewer")
MANAGE_ROLES = ("owner", "admin")   # 管理操作 (成员/预算/升级/治理) 需 owner/admin
READ_ROLES = ("owner", "admin", "member", "viewer")


@dataclass
class Member:
    user_id: str
    role: str = "member"          # owner / admin / member / viewer (RBAC)
    joined_at: float = field(default_factory=time.time)


@dataclass
class TeamOrg:
    """一个 B2B 组织 (对应 BP Team/Enterprise 订阅)。"""
    team_id: str
    name: str
    plan: str = Plan.FREE.value
    owner: str = ""
    members: Dict[str, Member] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    seats: int = 5                # 席位 (Team 默认 5, Enterprise 可扩)
    subscription_until: float = 0.0  # 订阅到期时间戳 (0=免费)
    monthly_budget: float = 0.0   # 月度 token 预算 (0=不限, 成本控制)
    budget_alert: bool = False    # 是否已触发超预算告警 (去重)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "plan": self.plan,
            "owner": self.owner,
            "members": {uid: {"role": m.role, "joined_at": m.joined_at}
                        for uid, m in self.members.items()},
            "created_at": self.created_at,
            "seats": self.seats,
            "subscription_until": self.subscription_until,
            "monthly_budget": self.monthly_budget,
            "budget_alert": self.budget_alert,
            "features": PLAN_FEATURES.get(self.plan, {}),
        }


# ── 审计日志 (Enterprise) ─────────────────────────────────

@dataclass
class AuditEntry:
    ts: float
    user_id: str
    action: str
    detail: str
    ip: str = ""
    team_id: str = ""          # 所属团队 (002codex P1-4: 审计按租户隔离)

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "user_id": self.user_id,
                "action": self.action, "detail": self.detail, "ip": self.ip,
                "team_id": self.team_id}


# ── Agent 活动日志 (观察性, 2026-08-27 splunk/cloudzero 痛点) ──
# 与 AuditEntry 区别: audit=合规操作(谁做了什么), activity=Agent 运行活动(哪个 agent 干了什么)
@dataclass
class ActivityEntry:
    ts: float
    team_id: str
    agent: str                # agent/工具名
    action: str               # 动作
    detail: str = ""
    user_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "team_id": self.team_id, "agent": self.agent,
                "action": self.action, "detail": self.detail, "user_id": self.user_id}


# ── 使用统计 (团队仪表盘) ─────────────────────────────────

@dataclass
class UsageStats:
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model_calls: Dict[str, int] = field(default_factory=dict)
    day: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"requests": self.requests, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "model_calls": self.model_calls,
                "day": self.day}


# ── 存储 ──────────────────────────────────────────────────

class BusinessStore:
    """JSON 持久化: 组织 + 审计 + 统计。线程安全。"""

    def __init__(self, storage_path: str = ""):
        self._lock = threading.Lock()
        self._path = Path(storage_path or (Path.home() / ".meshctx" / "business_plans.json"))
        self._teams: Dict[str, TeamOrg] = {}
        self._audit: List[AuditEntry] = []
        self._activity: List[ActivityEntry] = []
        self._usage: Dict[str, Dict[str, UsageStats]] = {}  # team_id -> day -> stats
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for t in data.get("teams", []):
                    org = TeamOrg(**{k: v for k, v in t.items()
                                     if k not in ("members", "features")})
                    org.members = {uid: Member(user_id=uid, **m)
                                    for uid, m in t.get("members", {}).items()}
                    self._teams[org.team_id] = org
                self._audit = [AuditEntry(**a) for a in data.get("audit", [])]
                self._usage = {tid: {d: UsageStats(**u) for d, u in days.items()}
                               for tid, days in data.get("usage", {}).items()}
                self._activity = [ActivityEntry(**a) for a in data.get("activity", [])]
        except Exception as e:
            logger.warning(f"business_plans 加载失败: {e}")

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "teams": [t.to_dict() for t in self._teams.values()],
                "audit": [a.to_dict() for a in self._audit[-5000:]],  # 保留最近 5000 条
                "usage": {tid: {d: u.to_dict() for d, u in days.items()}
                          for tid, days in self._usage.items()},
                "activity": [a.to_dict() for a in self._activity[-3000:]],
            }
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"business_plans 保存失败: {e}")

    # ── 组织 ──
    def create_team(self, name: str, owner: str, plan: str = Plan.FREE.value,
                    seats: int = 5) -> TeamOrg:
        with self._lock:
            team = TeamOrg(team_id=uuid.uuid4().hex[:12], name=name,
                           plan=plan if plan in PLAN_FEATURES else Plan.FREE.value,
                           owner=owner, seats=seats)
            team.members[owner] = Member(user_id=owner, role="owner")
            self._teams[team.team_id] = team
            self._save()
            return team

    def get_team(self, team_id: str) -> Optional[TeamOrg]:
        with self._lock:
            return self._teams.get(team_id)

    def list_teams(self) -> List[TeamOrg]:
        with self._lock:
            return list(self._teams.values())

    def list_teams_of_user(self, user_id: str) -> List[TeamOrg]:
        with self._lock:
            return [t for t in self._teams.values()
                    if user_id in t.members or t.owner == user_id]

    def add_member(self, team_id: str, user_id: str, role: str = "member") -> bool:
        with self._lock:
            team = self._teams.get(team_id)
            if team is None:
                return False
            if role not in VALID_ROLES:
                return False
            if len(team.members) >= team.seats:
                return False
            team.members[user_id] = Member(user_id=user_id, role=role)
            self._save()
            return True

    def member_role(self, team_id: str, user_id: str) -> Optional[str]:
        """成员角色 (RBAC 权限判定)。非成员返回 None。"""
        with self._lock:
            team = self._teams.get(team_id)
            if team is None:
                return None
            m = team.members.get(user_id)
            return m.role if m else None

    def can_manage(self, team_id: str, user_id: str) -> bool:
        """管理操作权限: owner/admin (RBAC)。"""
        return self.member_role(team_id, user_id) in MANAGE_ROLES

    def can_view(self, team_id: str, user_id: str) -> bool:
        """查看权限: 所有角色。"""
        return self.member_role(team_id, user_id) in READ_ROLES

    def set_budget(self, team_id: str, monthly_budget: float) -> bool:
        """设置月度 token 预算 (成本控制, cloudzero 痛点)。"""
        with self._lock:
            team = self._teams.get(team_id)
            if team is None:
                return False
            team.monthly_budget = max(0.0, float(monthly_budget))
            team.budget_alert = False
            self._save()
            return True

    def remove_member(self, team_id: str, user_id: str) -> bool:
        with self._lock:
            team = self._teams.get(team_id)
            if team is None or user_id == team.owner:
                return False
            if team.members.pop(user_id, None):
                self._save()
                return True
            return False

    def set_plan(self, team_id: str, plan: str, seats: int = 5,
                 months: int = 12) -> bool:
        """订阅升级: 设置 plan + 席位 + 到期时间。"""
        with self._lock:
            team = self._teams.get(team_id)
            if team is None or plan not in PLAN_FEATURES:
                return False
            team.plan = plan
            team.seats = max(seats, len(team.members))  # 席位不可小于现有成员
            team.subscription_until = time.time() + months * 30 * 24 * 3600
            self._save()
            return True

    # ── 审计 ──
    def audit(self, user_id: str, action: str, detail: str = "", ip: str = "",
              team_id: str = "") -> None:
        with self._lock:
            self._audit.append(AuditEntry(ts=time.time(), user_id=user_id,
                                          action=action, detail=detail, ip=ip,
                                          team_id=team_id))
            self._save()

    def audit_log(self, team_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """按团队精确过滤 (002codex P1-4: 跨租户隔离, 不再子串匹配)。"""
        with self._lock:
            logs = [a.to_dict() for a in self._audit]
        if team_id:
            logs = [a for a in logs if a.get("team_id") == team_id]
        return logs[-limit:]

    # ── Agent 活动日志 ──
    def record_activity(self, team_id: str, agent: str, action: str,
                        detail: str = "", user_id: str = "") -> None:
        """记录 Agent 运行活动 (观察性, 团队仪表盘活动流)。"""
        with self._lock:
            self._activity.append(ActivityEntry(ts=time.time(), team_id=team_id,
                                                agent=agent, action=action,
                                                detail=detail, user_id=user_id))
            self._save()

    def activity_log(self, team_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            logs = [a.to_dict() for a in self._activity if a.team_id == team_id]
        return logs[-limit:]

    def budget_status(self, team_id: str) -> Dict[str, Any]:
        """预算使用状态: 已用/预算/超限 (成本控制)。"""
        with self._lock:
            team = self._teams.get(team_id)
            if team is None:
                return {"error": "team not found"}
            budget = team.monthly_budget
        month_start = time.strftime("%Y-%m-01")
        used = 0
        with self._lock:
            for d, u in self._usage.get(team_id, {}).items():
                if d >= month_start:
                    used += u.tokens_in + u.tokens_out
        pct = (used / budget * 100) if budget > 0 else 0.0
        with self._lock:
            alert = bool(self._teams.get(team_id).budget_alert) if team_id in self._teams else False
        return {"team_id": team_id, "budget": budget, "used": used,
                "percent": round(pct, 1),
                "over_budget": budget > 0 and used > budget,
                "budget_alert": alert}  # 告警状态可读 (002codex 审计修正)

    # ── 使用统计 ──
    def record_usage(self, team_id: str, model: str = "",
                     tokens_in: int = 0, tokens_out: int = 0) -> bool:
        """记录使用。team_id 必须存在 (002codex P2: 防伪造统计)。"""
        with self._lock:
            if team_id and team_id not in self._teams:
                return False
        day = time.strftime("%Y-%m-%d")
        with self._lock:
            days = self._usage.setdefault(team_id, {})
            st = days.setdefault(day, UsageStats(day=day))
            st.requests += 1
            st.tokens_in += tokens_in
            st.tokens_out += tokens_out
            if model:
                st.model_calls[model] = st.model_calls.get(model, 0) + 1
            # 预算告警 (首次超限标记, 去重; 仅当月累计 — 002codex 审计修正)
            team = self._teams.get(team_id)
            if team is not None and team.monthly_budget > 0 and not team.budget_alert:
                _month = time.strftime("%Y-%m-01")
                _used = sum((self._usage.get(team_id, {}).get(dd, UsageStats()).tokens_in
                             + self._usage.get(team_id, {}).get(dd, UsageStats()).tokens_out)
                            for dd in self._usage.get(team_id, {}) if dd >= _month)
                if _used > team.monthly_budget:
                    team.budget_alert = True
            self._save()
            return True

    def usage_stats(self, team_id: str, days: int = 7) -> Dict[str, Any]:
        with self._lock:
            days_map = self._usage.get(team_id, {})
        recent = {d: u.to_dict() for d, u in sorted(days_map.items())[-days:]}
        total = {"requests": sum(u["requests"] for u in recent.values()),
                 "tokens_in": sum(u["tokens_in"] for u in recent.values()),
                 "tokens_out": sum(u["tokens_out"] for u in recent.values())}
        return {"days": recent, "total": total}


# 默认单例
_default_store: Optional[BusinessStore] = None


def get_store() -> BusinessStore:
    global _default_store
    if _default_store is None:
        _default_store = BusinessStore()
    return _default_store


def reset_store(path: str = "") -> BusinessStore:
    """测试用: 重置单例。"""
    global _default_store
    _default_store = BusinessStore(storage_path=path)
    return _default_store


# ═══ Token 按量计费层 (2026-08-28, 借鉴云知声 Token 业务 +760% 模式) ═══

# Token 定价 (USD/百万 token, 参考主流 API 价)
TOKEN_RATES = {
    "deepseek:chat": {"in": 0.27, "out": 1.10},     # $/1M token
    "openai:gpt-4o": {"in": 2.50, "out": 10.00},
    "default": {"in": 0.50, "out": 1.50},
}


def estimate_token_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Token 用量 → 估算成本 (USD)。"""
    rate = TOKEN_RATES.get(model, TOKEN_RATES["default"])
    cost = tokens_in / 1e6 * rate["in"] + tokens_out / 1e6 * rate["out"]
    return round(cost, 4)


def plan_token_allowance(plan: str) -> int:
    """各 plan 每月免费 token 配额 (超额按量计费 — 云知声模式)。"""
    return {"free": 1_000_000, "team": 20_000_000, "enterprise": 100_000_000}.get(plan, 1_000_000)


def billing_usage(team_id: str, days: int = 30) -> Dict[str, Any]:
    """团队 token 用量 → 计费账单 (已用/配额/超额/估算金额)。"""
    store = get_store()
    team = store.get_team(team_id)
    if team is None:
        return {"error": "team not found"}
    stats = store.usage_stats(team_id, days)
    used = stats["total"]["tokens_in"] + stats["total"]["tokens_out"]
    allowance = plan_token_allowance(team.plan)
    over = max(0, used - allowance)
    est_cost = estimate_token_cost("deepseek:chat",
                                   stats["total"]["tokens_in"],
                                   stats["total"]["tokens_out"])
    return {
        "team_id": team_id,
        "plan": team.plan,
        "tokens_used": used,
        "allowance": allowance,
        "over_allowance": over,
        "estimated_cost_usd": est_cost,
        "billing_model": "包月配额 + 超额按量 (云知声 Token 模式)",
        "days": days,
    }
