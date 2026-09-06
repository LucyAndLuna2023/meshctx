#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对外 Memory API 服务 (WP3, MCTX-PLAN-2026-0903 P0-3 记忆产品化).

复用 memory_v2 检索内核 (TfidfVectorizer/VectorStore), 加"商品化外衣":
- 每命名空间持久化 (~/.meshctx/memories_api/<owner>:<ns>/entries.json, 原子写)
- HTTP 路由 /api/v1/memory (auth_v2 白名单; 端内 owner 归因 → 跨 owner 隔离 404)
- 对外检索: TF-IDF top_k; 删除/GDPR 整命名空间删除 (002meshctx P3③)
MCP 工具 (WP5) 经本服务线程安全接口接入。
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

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("meshctx.memory_api")

router = APIRouter(prefix="/api/v1/memory", tags=["Memory API"])

MEMORIES_DIR = pathlib.Path.home() / ".meshctx" / "memories_api"
MAX_ENTRY_TEXT = 20000


_NS_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,80}$")


def _valid_ns(ns: str) -> bool:
    """ns 字符白名单 (P2-W3-1/002meshctx): 禁 ':'/空白 → key 无歧义可解析。"""
    return bool(_NS_RE.match(ns or ""))


def _split_key(key: str) -> tuple:
    """owner:ns 拆分 — ns 已禁 ':', 以最后一个 ':' 拆分唯一确定 owner/ns。"""
    owner, _, ns = key.rpartition(":")
    return owner, ns


def _esc(part: str) -> str:
    """路径段转义 (P3-A/004meshctx: 分层路径 + 转义, 防 sanitize 碰撞)。"""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in part) or "_"


class MemoryService:
    """线程安全命名空间记忆服务 (owner 隔离由 key=owner:ns 保证)。"""

    def __init__(self, base_dir: str | os.PathLike = ""):
        self._base = pathlib.Path(base_dir) if base_dir else MEMORIES_DIR
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Dict[str, Any]]] = {}   # key -> {id: entry}

    # ── 持久化 (分层 <owner>/<ns>.json — P3-A 防路径碰撞) ──
    def _path(self, key: str) -> pathlib.Path:
        owner, ns = _split_key(key)
        return self._base / _esc(owner) / f"{_esc(ns)}.json"

    def _load(self, key: str) -> Dict[str, Dict[str, Any]]:
        if key in self._entries:
            return self._entries[key]
        d: Dict[str, Dict[str, Any]] = {}
        try:
            p = self._path(key)
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                for e in data.get("entries", []) or []:
                    if e.get("id"):
                        d[e["id"]] = e
        except Exception:
            logger.debug("memory load failed %s", key, exc_info=True)
        self._entries[key] = d
        return d

    def _save(self, key: str) -> None:
        try:
            p = self._path(key)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f".{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps({"namespace": key,
                                       "entries": list(self._entries.get(key, {}).values())},
                                      ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except Exception:
            logger.exception("memory save failed %s", key)

    # ── 审计 (P3-1/002codex: 记忆写属敏感数据, 逐操作落盘) ──
    def _audit(self, action: str, key: str, entry_id: str = "") -> None:
        try:
            owner, ns = _split_key(key)
            ap = self._base / ".audit" / "memory.jsonl"
            ap.parent.mkdir(parents=True, exist_ok=True)
            with open(ap, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "action": action,
                                    "owner": owner, "namespace": ns,
                                    "entry_id": entry_id}, ensure_ascii=False) + "\n")
        except Exception:
            logger.debug("memory audit write failed", exc_info=True)

    # ── 业务 ────────────────────────────────────────────────
    def store(self, key: str, text: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            d = self._load(key)
            eid = uuid.uuid4().hex[:16]
            entry = {"id": eid, "text": text, "ts": time.time(),
                     "meta": dict(meta or {})}
            d[eid] = entry
            self._save(key)
            self._audit("store", key, eid)
            return entry

    @staticmethod
    def _cjk_tokens(text: str) -> set:
        """零依赖 CJK 感知分词: 连续汉字 2-gram + 拉丁/数字词 (jieba 缺失兜底)。"""
        import re as _re
        out = set()
        for m in _re.finditer(r"[\u4e00-\u9fff]+", text):
            seg = m.group()
            if len(seg) == 1:
                out.add(seg)
            else:
                out.update(seg[i:i + 2] for i in range(len(seg) - 1))
                out.add(seg)
        out.update(_re.findall(r"[a-z0-9]{2,}", text.lower()))
        return out

    def search(self, key: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """轻量召回: CJK bigram + 拉丁词 token 重叠打分 (零依赖, 无 jieba 可用)。

        分数 = 交集/查询词数; 归一化查询为文档子串时 +0.5 加成。
        深度检索质量 (LongMemEval_S 级) 由 benchmarks 跑分驱动迭代 — MVP 口径明确。
        """
        with self._lock:
            d = self._load(key)
            if not d:
                return []
            docs = list(d.values())
            q_norm = "".join(query.lower().split())
            q_toks = self._cjk_tokens(query)
            scored = []
            for x in docs:
                text = x["text"]
                inter = len(q_toks & self._cjk_tokens(text))
                if not inter:
                    continue
                score = inter / max(1, len(q_toks))
                if q_norm and q_norm in "".join(text.lower().split()):
                    score += 0.5
                scored.append((score, x))
            scored.sort(key=lambda p: -p[0])
            n = max(1, min(int(top_k), 20))
            return [{"id": x["id"], "text": x["text"],
                     "score": round(s, 4), "ts": x.get("ts")}
                    for s, x in scored[:n]]

    def list_entries(self, key: str) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self._load(key).values(), key=lambda e: -e["ts"])

    def delete_entry(self, key: str, entry_id: str) -> bool:
        with self._lock:
            d = self._load(key)
            if entry_id not in d:
                return False
            del d[entry_id]
            self._save(key)
            self._audit("delete_entry", key, entry_id)
            return True

    def delete_namespace(self, key: str) -> bool:
        """GDPR 删除 (002meshctx P3③): 整命名空间删除。"""
        with self._lock:
            p = self._path(key)
            removed = p.exists()
            try:
                if removed:
                    p.unlink()
            except Exception:
                logger.debug("ns delete file", exc_info=True)
            self._entries.pop(key, None)
            self._audit("delete_namespace", key)
            return removed


_default_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    global _default_service
    if _default_service is None:
        _default_service = MemoryService()
    return _default_service


def reset_memory_service_for_tests():
    global _default_service
    _default_service = None


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


# 3.125-P2: dept/system 为内部 owner 段 (部门共享记忆/系统预留), 公共 API 一律拒绝
RESERVED_MEM_OWNERS = ("dept", "system")


def _guard_reserved_owner(owner: str):
    base = str(owner or "").split(":", 1)[0].lower()
    if base in RESERVED_MEM_OWNERS:
        raise HTTPException(400, f"保留命名空间 ({base}) 仅内部使用, 公共 API 不可用")


def _ns_key(owner: str, ns: str) -> str:
    """内部键 = owner:ns → 跨 owner 天然隔离。"""
    return f"{owner}:{ns}"


def _checked_ns(ns: str) -> str:
    """白名单校验 (P2-W3-1): [A-Za-z0-9._-] 1-80; 禁 ':'/空白。"""
    ns = (ns or "default").strip()
    if not _valid_ns(ns):
        raise HTTPException(400, "namespace 仅允许字母数字._- (≤80)")
    return ns


def _parse_body_ns(body: dict, owner: str) -> str:
    return _ns_key(owner, _checked_ns(str(body.get("namespace") or "default")))


# ── 路由 ─────────────────────────────────────────────────────
@router.post("")
async def memory_store(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    owner = await _owner(request)
    await _reject_anon(owner)
    _guard_reserved_owner(owner)
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    if len(text) > MAX_ENTRY_TEXT:
        raise HTTPException(400, f"text 过长 (> {MAX_ENTRY_TEXT})")
    key = _parse_body_ns(body, owner)
    entry = get_memory_service().store(key, text, body.get("meta"))
    return {"ok": True, "id": entry["id"], "namespace": key.split(":", 1)[1]}


@router.get("/search")
async def memory_search(request: Request, q: str = "", top_k: int = 5,
                        namespace: str = "default"):
    owner = await _owner(request)
    await _reject_anon(owner)
    _guard_reserved_owner(owner)
    if not q.strip():
        raise HTTPException(400, "q 不能为空")
    ns = _checked_ns(namespace)
    key = _ns_key(owner, ns)
    return {"namespace": ns, "results":
            get_memory_service().search(key, q.strip(), top_k)}


@router.get("")
async def memory_list(request: Request, namespace: str = "default"):
    owner = await _owner(request)
    await _reject_anon(owner)
    _guard_reserved_owner(owner)
    ns = _checked_ns(namespace)
    key = _ns_key(owner, ns)
    return {"namespace": ns, "entries": get_memory_service().list_entries(key)}


@router.delete("/{entry_id}")
async def memory_delete_entry(entry_id: str, request: Request,
                              namespace: str = "default"):
    owner = await _owner(request)
    await _reject_anon(owner)
    _guard_reserved_owner(owner)
    ns = _checked_ns(namespace)
    key = _ns_key(owner, ns)
    if not get_memory_service().delete_entry(key, entry_id):
        raise HTTPException(404, "entry 不存在")
    return {"ok": True, "id": entry_id}


@router.delete("")
async def memory_delete_namespace(request: Request, namespace: str = "default"):
    owner = await _owner(request)
    await _reject_anon(owner)
    _guard_reserved_owner(owner)
    ns = _checked_ns(namespace)
    key = _ns_key(owner, ns)
    removed = get_memory_service().delete_namespace(key)
    return {"ok": True, "namespace": ns, "removed": removed}


__all__ = ["MemoryService", "get_memory_service",
           "reset_memory_service_for_tests", "router"]
