"""
meshctx 跨平台存储层
支持 Windows/Linux/macOS 的统一 JSON 文件持久化
"""
import json
import os
import platform
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path


class CrossPlatformStorage:
    """跨平台 JSON 文件存储实现"""

    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            # 跨平台默认路径
            if platform.system() == "Windows":
                base_path = os.path.join(
                    os.environ.get("APPDATA", ""), "meshctx", "data"
                )
            elif platform.system() == "Darwin":  # macOS
                base_path = os.path.join(
                    os.path.expanduser("~"),
                    "Library", "Application Support", "meshctx", "data",
                )
            else:  # Linux and others
                base_path = os.path.join(os.path.expanduser("~"), ".meshctx", "data")

        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ── Entity 保存 ──────────────────────────────────────────

    def save_project(self, project):
        self._save_entity("projects", project.id, project.model_dump())

    def save_conversation(self, conversation):
        self._save_entity(
            "conversations", conversation.id, conversation.model_dump()
        )

    def save_message(self, message):
        self._save_entity("messages", message.id, message.model_dump())

    def save_memory(self, memory):
        self._save_entity("memories", memory.id, memory.model_dump())

    def save_agent(self, agent):
        self._save_entity("agents", agent.id, agent.model_dump())

    def _save_entity(self, entity_type: str, entity_id: str, data: dict):
        file_path = self.base_path / entity_type / f"{entity_id}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        # 2026-08-25 004meshctx: 实体变更后使索引缓存失效 (目录指纹不可靠检测内容修改)
        self.invalidate_index(entity_type)

    # ── 数据查询 ─────────────────────────────────────────────

    def get_messages(self, conversation_id: str, limit: int = 10) -> list:
        """获取会话消息（从磁盘加载, 带索引缓存）

        2026-08-25 004meshctx 性能修复: 原实现每次调用 glob 扫描全部消息文件
        + 逐文件 json.load — 项目列表页 29 万次 json.load / 17s。改为索引缓存。
        """
        messages = self._load_indexed("messages", "conversation_id", conversation_id)
        messages.sort(key=lambda x: x.timestamp)
        return messages[-limit:]

    def get_project_memories(self, project_id: str) -> list:
        """获取项目的所有记忆（从磁盘加载, 带索引缓存）

        2026-08-25 004meshctx 性能修复: 同上, 原 O(文件数) 每次 → O(1) 缓存命中。
        """
        return self._load_indexed("memories", "project_id", project_id)

    # ── 索引缓存 (2026-08-25 004meshctx 性能修复) ─────────────
    # 原 get_messages/get_project_memories 每次全量 glob+json.load, 页面 17s/29万次。
    # 类级索引: {entity_type: {key_value: [obj, ...]}}, mtime 变化时重建, 命中 O(1)。
    _index_cache: Dict[str, Dict[str, list]] = {}
    _index_mtimes: Dict[str, Dict[str, float]] = {}

    def _load_indexed(self, entity_type: str, key_field: str, key_value: str) -> list:
        """按字段值加载实体, 带 mtime 索引缓存 (O(1) 命中)。

        2026-08-25 004meshctx 性能修复 v2: 原实现每次调用都 glob 扫描目录
        (292K 次 pathlib 构造), 即使缓存命中。改为目录级 mtime 指纹:
        目录本身未变化则直接命中缓存, 不逐文件扫描。
        """
        entity_dir = self.base_path / entity_type
        if not entity_dir.exists():
            return []
        if entity_type == "memories":
            from .models import Memory as Model
        elif entity_type == "messages":
            from .models import Message as Model
        else:
            from .models import Memory as Model  # fallback
        cache_key = f"{self.base_path}:{entity_type}"
        # 目录级指纹: (dir_mtime, 文件数) — 比逐文件 glob 快得多
        try:
            dir_stat = entity_dir.stat()
            entry_count = len(list(entity_dir.iterdir()))
            fingerprint = (dir_stat.st_mtime_ns, entry_count)
        except Exception:
            fingerprint = None
        cache = self._index_cache.get(cache_key)
        cached_fp = self._index_mtimes.get(cache_key)
        if cache is not None and (fingerprint is None or cached_fp == fingerprint):
            return list(cache.get(str(key_value), []))
        # 重建索引: 一次全量加载, 按 key_field 分组
        new_cache: Dict[str, list] = {}
        try:
            for p in entity_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    obj = Model(**data)
                    k = str(data.get(key_field, ""))
                    new_cache.setdefault(k, []).append(obj)
                except Exception:
                    continue
        except Exception:
            pass
        self._index_cache[cache_key] = new_cache
        self._index_mtimes[cache_key] = fingerprint
        return list(new_cache.get(str(key_value), []))

    def invalidate_index(self, entity_type: str):
        """实体变更后使缓存失效 (save/delete 时调用)。"""
        for key in list(self._index_cache.keys()):
            if key.endswith(f":{entity_type}"):
                self._index_cache.pop(key, None)
                self._index_mtimes.pop(key, None)

    def load_all_entities(self, entity_type: str, model_class) -> List:
        """通用加载：从磁盘加载指定类型的所有实体"""
        entity_dir = self.base_path / entity_type
        if not entity_dir.exists():
            return []

        entities = []
        for file_path in entity_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    entities.append(model_class(**data))
            except Exception:
                continue

        return entities

    def delete_entity(self, entity_type: str, entity_id: str) -> bool:
        """删除指定实体的持久化文件"""
        file_path = self.base_path / entity_type / f"{entity_id}.json"
        if file_path.exists():
            file_path.unlink()
            # 2026-08-25 004meshctx: 删除后使索引缓存失效
            self.invalidate_index(entity_type)
            return True
        return False


# ── 系统工具 ────────────────────────────────────────────────────


def get_system_info() -> dict:
    """获取系统信息"""
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }
