"""
meshctx Session Archiver v3.50 — 会话归档与恢复系统
====================================================
将活跃会话序列化到磁盘，支持压缩归档、索引检索、
过期清理以及与 memory_v2 的联动提取。

核心流程:
  1. 归档: 活跃 Session → JSON 序列化 → gzip 压缩 → 磁盘文件
  2. 恢复: 磁盘文件 → gzip 解压 → JSON 反序列化 → Session 对象
  3. 索引: 元数据提取 → 日期/标签/重要性索引 → 快速检索
  4. 清理: 过期归档自动删除 (可配置保留天数)

与 memory_v2 联动:
  - 归档时将 session.messages 中的关键对话提取为 MemoryItem
  - 恢复时从 memory_v2 检索关联记忆以增强上下文

存储结构:
  ~/.hermes/profiles/meshctx/archives/
    ├── 2025-06/
    │   ├── session_abc123_20250619_143022.json.gz
    │   └── session_def456_20250619_150000.json.gz
    ├── index.json           # 归档索引
    └── config.json          # 归档配置
"""

import asyncio
import gzip
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.session_archiver")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ArchivedSession:
    """归档的会话对象"""
    session_id: str
    title: str = ""
    created_at: float = 0.0
    archived_at: float = 0.0
    message_count: int = 0
    total_tokens: int = 0
    duration_minutes: float = 0.0
    tags: List[str] = field(default_factory=list)
    importance: float = 1.0              # 1-10 重要性评分
    summary: str = ""                     # AI 生成摘要
    model: str = ""
    tools_used: List[str] = field(default_factory=list)
    outcome: str = ""                     # success / partial / failed / ongoing
    parent_session_id: str = ""           # 分叉来源
    fork_count: int = 0                   # 分叉数量
    path: str = ""                        # 归档文件路径
    compressed_size_bytes: int = 0
    original_size_bytes: int = 0

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "archived_at": self.archived_at,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "duration_minutes": self.duration_minutes,
            "tags": self.tags,
            "importance": self.importance,
            "summary": self.summary,
            "model": self.model,
            "tools_used": self.tools_used,
            "outcome": self.outcome,
            "parent_session_id": self.parent_session_id,
            "fork_count": self.fork_count,
            "path": self.path,
            "compressed_size_bytes": self.compressed_size_bytes,
            "original_size_bytes": self.original_size_bytes,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ArchivedSession":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class SessionData:
    """完整的会话数据 (序列化/反序列化用)"""
    session_id: str
    messages: List[Dict] = field(default_factory=list)    # [{role, content, ...}, ...]
    metadata: Dict = field(default_factory=dict)          # 自由元数据
    created_at: float = 0.0
    updated_at: float = 0.0
    version: int = 1


@dataclass
class ArchiveFilter:
    """归档查询过滤器"""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    min_importance: float = 0.0
    max_importance: float = 10.0
    outcome: str = ""                     # 空=全部
    model: str = ""
    search_text: str = ""                 # 全文搜索 (summary + title)
    limit: int = 50
    offset: int = 0
    sort_by: str = "archived_at"          # archived_at / importance / duration_minutes
    sort_order: str = "desc"              # asc / desc


# ═══════════════════════════════════════════════════════════
# SessionArchiver 核心
# ═══════════════════════════════════════════════════════════

class SessionArchiver:
    """
    会话归档管理器

    职责:
      - 将会话序列化并压缩到磁盘
      - 从归档恢复会话
      - 维护归档索引
      - 过期归档清理
      - 与 memory_v2 联动
    """

    def __init__(
        self,
        archive_dir: str = None,
        retention_days: int = 90,
        max_archives: int = 10000,
        auto_cleanup: bool = True,
        compression_level: int = 6,       # gzip 1-9
        index_sync_interval: int = 60,    # 索引同步间隔 (秒)
    ):
        if archive_dir is None:
            archive_dir = os.path.expanduser(
                "~/.hermes/profiles/meshctx/archives"
            )
        self.archive_dir = Path(archive_dir)
        self.retention_days = retention_days
        self.max_archives = max_archives
        self.auto_cleanup = auto_cleanup
        self.compression_level = compression_level
        self.index_sync_interval = index_sync_interval

        # 索引: {session_id: ArchivedSession}
        self._index: Dict[str, ArchivedSession] = {}
        self._index_dirty = False
        self._last_index_sync = 0.0

        # 统计
        self._stats: Dict[str, Any] = {
            "total_archived": 0,
            "total_restored": 0,
            "total_deleted": 0,
            "total_disk_bytes": 0,
            "last_archive_at": 0.0,
            "last_restore_at": 0.0,
            "last_cleanup_at": 0.0,
            "errors": 0,
        }

        # Memory Manager 引用 (延迟绑定)
        self._memory_manager = None

        self._ensure_dirs()
        self._load_index()
        self._load_config()

        logger.info(f"SessionArchiver initialized: dir={self.archive_dir}, "
                   f"retention={retention_days}d, archives={len(self._index)} indexed")

    # ── 目录与配置 ────────────────────────────────────────

    def init_session(self, version: str = None):
        """兼容旧API"""
        return True

    def _ensure_dirs(self):
        """确保归档目录存在"""
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self):
        """加载归档配置"""
        config_path = self.archive_dir / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                self.retention_days = config.get("retention_days", self.retention_days)
                self.max_archives = config.get("max_archives", self.max_archives)
                self.compression_level = config.get("compression_level", self.compression_level)
            except Exception as e:
                logger.warning(f"Failed to load archive config: {e}")

    def _save_config(self):
        """持久化归档配置"""
        config_path = self.archive_dir / "config.json"
        config = {
            "retention_days": self.retention_days,
            "max_archives": self.max_archives,
            "compression_level": self.compression_level,
            "updated_at": time.time(),
        }
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save archive config: {e}")

    # ── 索引管理 ──────────────────────────────────────────

    def _load_index(self):
        """从磁盘加载归档索引"""
        index_path = self.archive_dir / "index.json"
        if not index_path.exists():
            logger.debug("No archive index found, starting fresh")
            return

        try:
            with open(index_path) as f:
                data = json.load(f)

            self._index = {}
            for item in data.get("archives", []):
                session = ArchivedSession.from_dict(item)
                self._index[session.session_id] = session

            self._stats["total_archived"] = data.get("total_archived", len(self._index))
            self._stats["total_restored"] = data.get("total_restored", 0)
            self._stats["total_deleted"] = data.get("total_deleted", 0)
            self._stats["total_disk_bytes"] = data.get("total_disk_bytes", 0)
            self._stats["last_cleanup_at"] = data.get("last_cleanup_at", 0)

            # 验证归档文件是否存在
            missing = []
            for sid, session in self._index.items():
                if session.path and not os.path.exists(session.path):
                    missing.append(sid)

            for sid in missing:
                logger.warning(f"Archive file missing for session {sid}, removing from index")
                del self._index[sid]

            if missing:
                self._index_dirty = True

            logger.info(f"Loaded archive index: {len(self._index)} entries")

        except Exception as e:
            logger.error(f"Failed to load archive index: {e}")
            self._index = {}

    def _save_index(self):
        """持久化归档索引到磁盘"""
        index_path = self.archive_dir / "index.json"
        data = {
            "archives": [s.to_dict() for s in self._index.values()],
            "total_archived": self._stats["total_archived"],
            "total_restored": self._stats["total_restored"],
            "total_deleted": self._stats["total_deleted"],
            "total_disk_bytes": self._stats["total_disk_bytes"],
            "last_cleanup_at": self._stats["last_cleanup_at"],
            "updated_at": time.time(),
        }
        try:
            # 原子写入
            tmp_path = index_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(index_path)
            self._index_dirty = False
            self._last_index_sync = time.time()
        except Exception as e:
            logger.error(f"Failed to save archive index: {e}")

    def _sync_index_if_needed(self):
        """按需同步索引"""
        if self._index_dirty or (time.time() - self._last_index_sync > self.index_sync_interval):
            self._save_index()

    # ── 归档 ──────────────────────────────────────────────

    def archive_session(
        self,
        session_id: str,
        messages: List[Dict] = None,
        metadata: Dict = None,
        title: str = "",
        tags: List[str] = None,
        importance: float = 1.0,
        summary: str = "",
        model: str = "",
        outcome: str = "completed",
        parent_session_id: str = "",
    ) -> str:
        """
        归档一个会话到磁盘

        Args:
            session_id: 会话ID
            messages: 消息列表 [{role, content, ...}, ...]
            metadata: 会话元数据
            title: 会话标题
            tags: 标签列表
            importance: 重要性 1-10
            summary: AI 摘要
            model: 使用的模型
            outcome: 会话结果
            parent_session_id: 父会话ID

        Returns:
            归档文件路径
        """
        now = time.time()

        # 构建归档目录 (按年月)
        date_str = datetime.fromtimestamp(now).strftime("%Y-%m")
        month_dir = self.archive_dir / date_str
        month_dir.mkdir(parents=True, exist_ok=True)

        # 生成归档文件名
        timestamp_str = datetime.fromtimestamp(now).strftime("%Y%m%d_%H%M%S")
        filename = f"session_{session_id}_{timestamp_str}.json.gz"
        filepath = month_dir / filename

        # 构建 SessionData
        session_data = SessionData(
            session_id=session_id,
            messages=messages or [],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
            version=1,
        )

        # 序列化并压缩
        json_str = json.dumps({
            "session_id": session_data.session_id,
            "messages": session_data.messages,
            "metadata": session_data.metadata,
            "created_at": session_data.created_at,
            "updated_at": session_data.updated_at,
            "version": session_data.version,
        }, ensure_ascii=False, default=str)

        original_size = len(json_str.encode("utf-8"))

        try:
            with gzip.open(str(filepath), "wt", encoding="utf-8",
                          compresslevel=self.compression_level) as f:
                f.write(json_str)
        except Exception as e:
            logger.error(f"Failed to write archive {filepath}: {e}")
            self._stats["errors"] += 1
            raise

        compressed_size = filepath.stat().st_size

        # 计算消息数 & Token 数 (近似)
        message_count = len(messages) if messages else 0
        total_tokens = sum(
            len(msg.get("content", "").split()) * 1.3  # ~1.3 tokens/word
            for msg in (messages or [])
        )
        duration = 0.0
        if session_data.metadata:
            start = session_data.metadata.get("started_at", 0)
            if start:
                duration = (now - float(start)) / 60.0

        # 创建归档记录
        archived = ArchivedSession(
            session_id=session_id,
            title=title,
            created_at=now,
            archived_at=now,
            message_count=int(message_count),
            total_tokens=int(total_tokens),
            duration_minutes=round(duration, 1),
            tags=tags or [],
            importance=importance,
            summary=summary,
            model=model,
            tools_used=metadata.get("tools_used", []) if metadata else [],
            outcome=outcome,
            parent_session_id=parent_session_id,
            path=str(filepath),
            compressed_size_bytes=compressed_size,
            original_size_bytes=original_size,
        )

        # 更新索引
        self._index[session_id] = archived
        self._index_dirty = True

        # 更新统计
        self._stats["total_archived"] += 1
        self._stats["total_disk_bytes"] += compressed_size
        self._stats["last_archive_at"] = now

        # 与 memory_v2 联动: 提取关键记忆
        self._extract_memories_from_archive(archived, messages)

        # 自动清理
        if self.auto_cleanup:
            self.cleanup_expired()

        logger.info(f"Archived session {session_id}: {filename} "
                   f"({original_size}→{compressed_size} bytes, "
                   f"ratio={compressed_size/max(original_size,1)*100:.0f}%)")

        self._sync_index_if_needed()
        return str(filepath)

    # ── 恢复 ──────────────────────────────────────────────

    def restore_session(self, session_id: str) -> Optional[SessionData]:
        """
        从归档恢复会话

        Args:
            session_id: 会话ID

        Returns:
            SessionData 或 None (未找到)
        """
        # 查找归档记录
        archived = self._index.get(session_id)
        if not archived or not archived.path:
            logger.warning(f"Archive not found for session {session_id}")
            return None

        filepath = Path(archived.path)
        if not filepath.exists():
            logger.warning(f"Archive file missing: {filepath}")
            del self._index[session_id]
            self._index_dirty = True
            return None

        try:
            with gzip.open(str(filepath), "rt", encoding="utf-8") as f:
                data = json.load(f)

            session_data = SessionData(
                session_id=data.get("session_id", session_id),
                messages=data.get("messages", []),
                metadata=data.get("metadata", {}),
                created_at=data.get("created_at", 0),
                updated_at=data.get("updated_at", 0),
                version=data.get("version", 1),
            )

            self._stats["total_restored"] += 1
            self._stats["last_restore_at"] = time.time()

            # 增强上下文: 从 memory_v2 检索关联记忆
            memories = self._recall_related_memories(session_data)
            if memories:
                session_data.metadata["recalled_memories"] = memories

            logger.info(f"Restored session {session_id}: "
                       f"{len(session_data.messages)} messages, "
                       f"{archived.compressed_size_bytes} bytes")

            return session_data

        except Exception as e:
            logger.error(f"Failed to restore session {session_id}: {e}")
            self._stats["errors"] += 1
            return None

    # ── 列表/检索 ─────────────────────────────────────────

    def list_archives(self, filter: ArchiveFilter = None) -> List[Dict]:
        """
        列出归档会话

        Args:
            filter: 查询过滤器 (None = 全部)

        Returns:
            匹配的归档会话列表
        """
        if filter is None:
            filter = ArchiveFilter()

        results = []

        for archived in self._index.values():
            # 日期范围过滤
            if filter.start_date:
                if archived.archived_at < filter.start_date.timestamp():
                    continue
            if filter.end_date:
                if archived.archived_at > filter.end_date.timestamp():
                    continue

            # 标签过滤 (AND)
            if filter.tags:
                if not all(t in archived.tags for t in filter.tags):
                    continue

            # 重要性范围
            if archived.importance < filter.min_importance:
                continue
            if archived.importance > filter.max_importance:
                continue

            # 结果过滤
            if filter.outcome and archived.outcome != filter.outcome:
                continue

            # 模型过滤
            if filter.model and archived.model != filter.model:
                continue

            # 全文搜索
            if filter.search_text:
                search_lower = filter.search_text.lower()
                if (search_lower not in archived.title.lower() and
                        search_lower not in archived.summary.lower()):
                    continue

            results.append(archived)

        # 排序
        reverse = filter.sort_order == "desc"
        if filter.sort_by == "importance":
            results.sort(key=lambda x: x.importance, reverse=reverse)
        elif filter.sort_by == "duration_minutes":
            results.sort(key=lambda x: x.duration_minutes, reverse=reverse)
        else:  # archived_at
            results.sort(key=lambda x: x.archived_at, reverse=reverse)

        # 分页
        total = len(results)
        results = results[filter.offset:filter.offset + filter.limit]

        return [
            {**r.to_dict(), "_total": total}
            for r in results
        ]

    def get_archive_info(self, session_id: str) -> Optional[Dict]:
        """获取单个归档的详细信息"""
        archived = self._index.get(session_id)
        if archived:
            return archived.to_dict()
        return None

    def count_archives(self, filter: ArchiveFilter = None) -> int:
        """获取归档数量"""
        if filter is None:
            return len(self._index)
        results = self.list_archives(filter)
        return len(results)

    # ── 删除与清理 ────────────────────────────────────────

    def delete_archive(self, session_id: str) -> bool:
        """
        删除单个归档

        Args:
            session_id: 会话ID

        Returns:
            是否成功
        """
        archived = self._index.get(session_id)
        if not archived:
            logger.warning(f"Archive not found: {session_id}")
            return False

        # 删除文件
        if archived.path:
            filepath = Path(archived.path)
            if filepath.exists():
                try:
                    filepath.unlink()
                    # 清理空目录
                    parent = filepath.parent
                    if parent != self.archive_dir and not any(parent.iterdir()):
                        parent.rmdir()
                except Exception as e:
                    logger.error(f"Failed to delete archive file {filepath}: {e}")

        # 更新统计
        self._stats["total_disk_bytes"] -= archived.compressed_size_bytes
        self._stats["total_deleted"] += 1

        # 从索引移除
        del self._index[session_id]
        self._index_dirty = True

        logger.info(f"Deleted archive: {session_id}")
        self._sync_index_if_needed()
        return True

    def cleanup_expired(self) -> int:
        """
        清理过期归档

        删除 archived_at 早于 retention_days 天的归档

        Returns:
            清理数量
        """
        if self.retention_days <= 0:
            return 0

        cutoff = time.time() - (self.retention_days * 86400)
        expired = []

        for sid, archived in self._index.items():
            if archived.archived_at < cutoff:
                expired.append(sid)

        deleted = 0
        for sid in expired:
            if self.delete_archive(sid):
                deleted += 1

        self._stats["last_cleanup_at"] = time.time()

        if deleted > 0:
            logger.info(f"Cleanup: deleted {deleted} expired archives "
                       f"(older than {self.retention_days} days)")

        # 如果归档数超过上限, 删除最旧的
        if len(self._index) > self.max_archives:
            sorted_archives = sorted(
                self._index.values(),
                key=lambda x: (x.importance, x.archived_at)
            )
            to_delete = len(self._index) - self.max_archives
            for archived in sorted_archives[:to_delete]:
                if self.delete_archive(archived.session_id):
                    deleted += 1

            logger.info(f"Cleanup: deleted {to_delete} archives exceeding max limit")

        self._sync_index_if_needed()
        return deleted

    def cleanup_orphaned_files(self) -> int:
        """
        清理孤立的归档文件 (不在索引中但文件存在)

        Returns:
            清理数量
        """
        removed = 0
        indexed_paths = {
            Path(a.path).resolve() for a in self._index.values() if a.path
        }

        for root, dirs, files in os.walk(str(self.archive_dir)):
            for fname in files:
                if fname in ("index.json", "config.json", "index.tmp"):
                    continue
                if fname.endswith(".json.gz"):
                    fpath = Path(root) / fname
                    if fpath.resolve() not in indexed_paths:
                        try:
                            fpath.unlink()
                            removed += 1
                            logger.info(f"Removed orphaned archive: {fpath}")
                        except Exception as e:
                            logger.error(f"Failed to remove orphan {fpath}: {e}")

        return removed

    # ── memory_v2 联动 ────────────────────────────────────

    def bind_memory_manager(self, memory_manager):
        """绑定 MemoryManager 实例以启用联动"""
        self._memory_manager = memory_manager
        logger.info("MemoryManager bound to SessionArchiver")

    def _extract_memories_from_archive(
        self, archived: ArchivedSession, messages: List[Dict]
    ):
        """
        从归档中提取关键记忆并存入 memory_v2

        提取规则:
          - 用户明确说"记住"的内容 → 高重要性
          - 用户表达偏好的内容 → 中等重要性
          - 长对话摘要 → 语义记忆
        """
        if not self._memory_manager or not messages:
            return

        try:
            from .memory_v2 import MemoryItem

            extracted_count = 0

            for msg in messages:
                content = msg.get("content", "")
                role = msg.get("role", "")

                if not content:
                    continue

                # 用户明确说"记住" → 高重要性
                if role == "user" and ("记住" in content or "remember" in content.lower()):
                    item = MemoryItem(
                        content=f"[用户记忆] {content[:500]}",
                        memory_type="episodic",
                        importance=8.0,
                        emotional_valence=0.0,
                        tags=archived.tags + ["user_memory", "explicit"],
                        source_session=archived.session_id,
                    )
                    self._memory_manager.store_episodic(item)
                    extracted_count += 1

                # 用户表达偏好 → 中等重要性
                elif role == "user" and any(kw in content for kw in
                        ["偏好", "喜欢", "prefer", "习惯", "always", "never", "常用"]):
                    item = MemoryItem(
                        content=f"[用户偏好] {content[:500]}",
                        memory_type="episodic",
                        importance=5.0,
                        emotional_valence=0.3,
                        tags=archived.tags + ["user_preference"],
                        source_session=archived.session_id,
                    )
                    self._memory_manager.store_episodic(item)
                    extracted_count += 1

                # AI 思考过程中的关键发现 → 中等重要性
                elif role == "assistant" and any(kw in content for kw in
                        ["发现", "关键", "重要", "found", "critical", "important"]):
                    item = MemoryItem(
                        content=f"[AI发现] {content[:500]}",
                        memory_type="episodic",
                        importance=4.0,
                        tags=archived.tags + ["ai_discovery"],
                        source_session=archived.session_id,
                    )
                    self._memory_manager.store_episodic(item)
                    extracted_count += 1

            # 如果有摘要，存入语义记忆
            if archived.summary and archived.importance >= 3.0:
                self._memory_manager.store_semantic(
                    key=f"session_summary_{archived.session_id}",
                    value=archived.summary,
                    confidence=0.7,
                    source=f"archive:{archived.session_id}",
                )
                extracted_count += 1

            if extracted_count > 0:
                logger.debug(f"Extracted {extracted_count} memories from archive {archived.session_id}")

        except ImportError:
            logger.debug("memory_v2 not available for memory extraction")
        except Exception as e:
            logger.warning(f"Memory extraction failed for {archived.session_id}: {e}")

    def _recall_related_memories(self, session_data: SessionData) -> List[Dict]:
        """
        从 memory_v2 检索与恢复会话相关的记忆

        Returns:
            关联记忆列表
        """
        if not self._memory_manager or not session_data.messages:
            return []

        try:
            # 从消息中提取关键词
            keywords = []
            for msg in session_data.messages[:5]:  # 只看前5条
                content = msg.get("content", "")
                words = content.split()
                keywords.extend([w for w in words if len(w) > 2][:10])

            if not keywords:
                return []

            query = " ".join(keywords[:20])
            memories = self._memory_manager.recall(query, limit=5)

            return [
                {
                    "content": m.content[:300],
                    "importance": m.importance,
                    "tags": m.tags,
                    "retention_score": round(m.retention_score, 3),
                }
                for m in memories
            ]
        except Exception as e:
            logger.debug(f"Memory recall failed: {e}")
            return []

    # ── 统计 ──────────────────────────────────────────────

    def get_archiver_stats(self) -> Dict:
        """获取归档器统计"""
        total_size = sum(a.compressed_size_bytes for a in self._index.values())
        # 按重要性分布
        importance_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for a in self._index.values():
            if a.importance >= 8:
                importance_dist["critical"] += 1
            elif a.importance >= 5:
                importance_dist["high"] += 1
            elif a.importance >= 3:
                importance_dist["medium"] += 1
            else:
                importance_dist["low"] += 1

        return {
            "total_archives": len(self._index),
            "total_archived": self._stats["total_archived"],
            "total_restored": self._stats["total_restored"],
            "total_deleted": self._stats["total_deleted"],
            "total_disk_bytes": total_size,
            "total_disk_mb": round(total_size / (1024 * 1024), 2),
            "retention_days": self.retention_days,
            "max_archives": self.max_archives,
            "archive_dir": str(self.archive_dir),
            "importance_distribution": importance_dist,
            "avg_compression_ratio": round(
                sum(a.compressed_size_bytes / max(a.original_size_bytes, 1)
                    for a in self._index.values()) / max(len(self._index), 1) * 100, 1
            ),
            "last_archive_at": self._stats["last_archive_at"],
            "last_restore_at": self._stats["last_restore_at"],
            "last_cleanup_at": self._stats["last_cleanup_at"],
            "errors": self._stats["errors"],
            "memory_bound": self._memory_manager is not None,
        }

    def get_archives_by_tag(self, tag: str) -> List[Dict]:
        """按标签获取归档"""
        results = []
        for archived in self._index.values():
            if tag in archived.tags:
                results.append(archived.to_dict())
        results.sort(key=lambda x: x["archived_at"], reverse=True)
        return results

    def get_archives_by_date(self, year: int = None, month: int = None) -> List[Dict]:
        """按日期获取归档"""
        results = []
        for archived in self._index.values():
            dt = datetime.fromtimestamp(archived.archived_at)
            if year and dt.year != year:
                continue
            if month and dt.month != month:
                continue
            results.append(archived.to_dict())
        results.sort(key=lambda x: x["archived_at"], reverse=True)
        return results

    def get_most_important(self, limit: int = 10) -> List[Dict]:
        """获取最重要的归档"""
        sorted_archives = sorted(
            self._index.values(),
            key=lambda x: (x.importance, x.archived_at),
            reverse=True,
        )
        return [a.to_dict() for a in sorted_archives[:limit]]

    def search_archives(self, query: str, limit: int = 20) -> List[Dict]:
        """
        全文搜索归档 (标题 + 摘要 + 标签)

        Args:
            query: 搜索关键词
            limit: 返回数量上限

        Returns:
            匹配的归档列表
        """
        query_lower = query.lower()
        results = []

        for archived in self._index.values():
            score = 0
            if query_lower in archived.title.lower():
                score += 10
            if query_lower in archived.summary.lower():
                score += 5
            for tag in archived.tags:
                if query_lower in tag.lower():
                    score += 3
            if score > 0:
                results.append((score, archived))

        results.sort(key=lambda x: -x[0])
        return [
            {**a.to_dict(), "_relevance_score": s}
            for s, a in results[:limit]
        ]


# ═══════════════════════════════════════════════════════════
# Plugin 适配
# ═══════════════════════════════════════════════════════════

class SessionArchiverPlugin:
    """meshctx Plugin 适配器"""
    info = type('Info', (), {
        'name': 'session_archiver',
        'version': '3.50',
        'dependencies': ['memory_v2'],
        'category': 'infrastructure',
        'description': '会话归档系统 — 压缩存储、索引检索、过期清理、记忆联动',
    })()
    state = "inactive"

    def __init__(self):
        self.archiver: Optional[SessionArchiver] = None

    async def on_load(self, kernel) -> bool:
        try:
            self.archiver = SessionArchiver()
            kernel.session_archiver = self.archiver

            # 绑定 memory_v2 (如果已加载)
            if hasattr(kernel, "memory_manager"):
                self.archiver.bind_memory_manager(kernel.memory_manager)

            self.state = "active"
            # 注册全局实例
            global _archiver
            _archiver = self.archiver
            logger.info("SessionArchiverPlugin activated")
            return True
        except Exception as e:
            logger.error(f"SessionArchiverPlugin load failed: {e}")
            return False

    async def on_unload(self, kernel) -> bool:
        self.archiver._save_index()
        self.state = "inactive"
        return True

    def generate_report(self) -> Dict:
        if self.archiver:
            return self.archiver.get_archiver_stats()
        return {"status": "not_initialized"}


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_archiver: Optional[SessionArchiver] = None


def get_session_archiver() -> SessionArchiver:
    """获取 SessionArchiver 全局实例，自动创建"""
    global _archiver
    if _archiver is None:
        _archiver = SessionArchiver()
    return _archiver


def init_session_archiver(
    archive_dir: str = None,
    retention_days: int = 90,
    max_archives: int = 10000,
) -> SessionArchiver:
    """
    初始化 SessionArchiver 全局单例

    Args:
        archive_dir: 归档目录路径
        retention_days: 保留天数
        max_archives: 最大归档数

    Returns:
        SessionArchiver 实例
    """
    global _archiver
    if _archiver is None:
        _archiver = SessionArchiver(
            archive_dir=archive_dir,
            retention_days=retention_days,
            max_archives=max_archives,
        )
    return _archiver
