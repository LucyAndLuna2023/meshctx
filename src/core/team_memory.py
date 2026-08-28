#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""团队共享记忆 — L2/L3 记忆引擎封装 (2026-08-28)

基于 HierarchicalMemoryStore (schema_layer: episodic→semantic→core 收敛) 做团队记忆:
- save: 存 MemoryItem (分类 + store_with_merge 去重) → save_to_file
- list: 从持久化文件反序列化 (HierarchicalMemoryStore 无 load, 手动读 json)
- correct/mark: 记忆治理 (is_corrected / correction_history)

存储: ~/.meshctx/team_memories/{team_id}.memory.json
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.team_memory")


def _mem_path(team_id: str) -> Path:
    d = (Path.home() / ".meshctx" / "team_memories").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{team_id}.memory.json"


def _load_items(path: Path) -> List[Dict[str, Any]]:
    """从 memory.json 反序列化条目 (HierarchicalMemoryStore 持久化格式)。"""
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])
    except Exception as e:
        logger.warning(f"团队记忆加载失败: {e}")
        return []


def save_fact(team_id: str, fact: str) -> Dict[str, Any]:
    """保存团队事实 (L2/L3 记忆引擎 + 分类收敛)。"""
    from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
    try:
        from src.core.memory_hierarchy import classify_memory
    except Exception:
        def classify_memory(t): return "other"
    path = _mem_path(team_id)
    store = HierarchicalMemoryStore()
    cat = classify_memory(fact)
    item = MemoryItem(
        value=fact,
        content=fact,
        source=f"team:{team_id}",
        importance=0.6,
        schema_layer="semantic" if cat in ("preference", "decision") else "episodic",
        tags=["team", team_id[:6], "shared"],
        category=cat,
    )
    saved = store.store_with_merge(item)
    store.save_to_file(str(path))
    return {"id": saved.id, "schema_layer": item.schema_layer, "category": cat}


def list_facts(team_id: str) -> List[Dict[str, Any]]:
    """列出团队记忆 (含 L2/L3 层级 + 治理状态)。"""
    items = _load_items(_mem_path(team_id))
    facts = []
    for it in items:
        tags = it.get("tags") or []
        if it.get("is_corrected"):
            status = "error"
        elif "deprecated" in tags:
            status = "deprecated"     # 002codex P2: mark 后 list 必须反映
        else:
            status = "active"
        facts.append({
            "ts": it.get("created_at", 0) or 0,
            "fact": it.get("value") or it.get("content") or "",
            "user": it.get("source", "") or "",
            "status": status,
            "schema_layer": it.get("schema_layer", "episodic"),
            "id": it.get("id", ""),
            "corrected_fact": (it.get("correction_history") or [{}])[-1].get("corrected_fact", "")
            if it.get("correction_history") else "",
        })
    return facts


def correct_fact(team_id: str, memory_id: str, corrected: str) -> bool:
    """记忆纠错: 标记 is_corrected + correction_history (治理)。"""
    path = _mem_path(team_id)
    items = _load_items(path)
    found = False
    for it in items:
        if it.get("id") == memory_id:
            history = it.get("correction_history") or []
            history.append({"ts": time.time(), "corrected_fact": corrected})
            it["is_corrected"] = True
            it["correction_history"] = history
            found = True
            break
    if not found:
        return False
    _write_items(path, items)
    return True


def mark_fact(team_id: str, memory_id: str, deprecated: bool = True) -> bool:
    """标记废弃 (tag 层标记 deprecated)。"""
    path = _mem_path(team_id)
    items = _load_items(path)
    found = False
    for it in items:
        if it.get("id") == memory_id:
            tags = it.get("tags") or []
            if deprecated and "deprecated" not in tags:
                tags.append("deprecated")
                it["tags"] = tags
            elif not deprecated and "deprecated" in tags:
                tags.remove("deprecated")
                it["tags"] = tags
            found = True
            break
    if not found:
        return False
    _write_items(path, items)
    return True


def _write_items(path: Path, items: List[Dict[str, Any]]):
    """写回 memory.json (保持 store 格式)。"""
    data = {
        "version": 1,
        "meta": {"saved_at": time.time(), "total_items": len(items)},
        "items": items,
        "vector_index": {},
        "knowledge_graph": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
