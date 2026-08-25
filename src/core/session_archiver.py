"""
会话自动存档引擎 (Session Auto-Archiver) — 开源真实实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
自动保存对话上下文、记忆快照、技术决策到持久化存储 (JSON)。
确保任何会话中断后都能完整恢复。

设计: 增量记录 + 全量快照 + 自动恢复
存储: ~/.meshctx/sessions/

- SessionArchiver: init_session / record / snapshot_memory / save /
  load_latest / load_snapshot / list_archives / get_summary
- get_archiver(): 全局单例

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.archiver")

# 存档目录 (任务要求: ~/.meshctx/sessions/)
ARCHIVE_DIR = Path.home() / ".meshctx" / "sessions"

# 允许通过 _context 注入的键 (main.py 写入 version/decisions/rules/progress)
_CONTEXT_KEYS = ("version", "decisions", "rules", "progress")


class SessionArchiver:
    """会话自动存档器 — JSON 持久化到 ~/.meshctx/sessions/。"""

    def __init__(self, **kw):
        self._archive_dir: Path = Path(kw.get("archive_dir", ARCHIVE_DIR))
        self._context: Dict[str, Any] = {}
        self._events: List[Dict[str, Any]] = []
        self._memory: List[Dict[str, Any]] = []
        self._session_id: Optional[str] = kw.get("session_id")
        self._version: str = ""
        self._started_at: Optional[float] = None
        self._last_full_save: float = 0.0          # 实例属性 (v35 测试要求)
        self._save_counter: int = 0
        self._lock = threading.RLock()

    # ── 会话生命周期 ──────────────────────────────────────

    def init_session(self, version: str = '', **kw) -> str:
        """初始化新会话。"""
        with self._lock:
            if self._session_id is None:
                self._session_id = kw.get("session_id") or uuid.uuid4().hex
            self._version = str(version or kw.get("version", ""))
            if self._started_at is None:
                self._started_at = time.time()
            self._context.setdefault("version", self._version)
            self._context.setdefault("session_id", self._session_id)
        self.record("session_init", f"会话初始化 v{self._version or '?'}", "info")
        return self._session_id

    # ── 记录 ──────────────────────────────────────────────

    def record(self, event_type: str, detail: str, category: str = 'info', **kw) -> dict:
        """记录事件。"""
        entry = {
            "ts": time.time(),
            "type": str(event_type),
            "detail": str(detail),
            "category": str(category),
        }
        for k, v in kw.items():
            if k not in entry:
                entry[k] = v
        with self._lock:
            self._events.append(entry)
        return entry

    def snapshot_memory(self, memory_entries: List[Dict], **kw) -> int:
        """保存记忆快照 (追加到记忆列表)。"""
        if not memory_entries:
            return 0
        now = time.time()
        with self._lock:
            for entry in memory_entries:
                if isinstance(entry, dict):
                    snap = dict(entry)
                    snap.setdefault("ts", now)
                    self._memory.append(snap)
                else:
                    self._memory.append({"ts": now, "value": str(entry)})
            return len(memory_entries)

    # ── 持久化 ────────────────────────────────────────────

    def _payload(self) -> dict:
        with self._lock:
            return {
                "session_id": self._session_id,
                "version": self._version,
                "started_at": self._started_at,
                "saved_at": time.time(),
                "save_count": self._save_counter + 1,
                "context": dict(self._context),
                "events": list(self._events),
                "memory": list(self._memory),
            }

    def save(self, force: bool = False, **kw) -> str:
        """保存当前上下文到文件 (全量 JSON 快照), 返回文件路径。

        每次保存都写入完整快照 (增量记录在内存, 快照全量落盘),
        同时更新 latest.json 指向最近存档。
        """
        if not self._session_id:
            self.init_session(kw.get("version", ""))
        with self._lock:
            self._save_counter += 1
            payload = self._payload()
            self._last_full_save = time.time()
        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            filename = f"session_{self._session_id[:8]}_{int(payload['saved_at'])}.json"
            path = self._archive_dir / filename
            tmp = self._archive_dir / f".{filename}.tmp"
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, path)  # 原子替换
            # latest 指针
            latest = self._archive_dir / "latest.json"
            latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            logger.info("会话存档: %s", path)
            return str(path)
        except Exception as e:  # noqa: BLE001
            logger.error("会话存档失败: %s", e)
            raise

    # ── 加载 ──────────────────────────────────────────────

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:  # noqa: BLE001
            logger.warning("读取存档失败 %s: %s", path, e)
            return None

    def _latest_path(self) -> Optional[Path]:
        latest = self._archive_dir / "latest.json"
        if latest.exists():
            return latest
        candidates = sorted(
            self._archive_dir.glob("session_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        return candidates[0] if candidates else None

    def load_latest(self, **kw) -> Optional[Dict]:
        """加载最近存档。"""
        if not self._archive_dir.exists():
            return None
        path = self._latest_path()
        return self._read_json(path) if path is not None else None

    def load_snapshot(self, snapshot_id: str = '', **kw) -> Optional[Dict]:
        """加载指定快照 (按 snapshot_id 或文件名片段匹配)。"""
        if not self._archive_dir.exists():
            return None
        target = str(snapshot_id or "").strip()
        if not target:
            return self.load_latest(**kw)
        for path in sorted(self._archive_dir.glob("session_*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            if target in path.name:
                return self._read_json(path)
            data = self._read_json(path)
            if data and (data.get("session_id") == target or
                         str(data.get("saved_at", "")) == target):
                return data
        return None

    def list_archives(self, **kw) -> List[Dict]:
        """列出所有存档 (按时间倒序)。"""
        if not self._archive_dir.exists():
            return []
        archives = []
        for path in sorted(self._archive_dir.glob("session_*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = path.stat()
            except OSError:
                continue
            data = self._read_json(path) or {}
            archives.append({
                "id": path.stem,
                "path": str(path),
                "timestamp": stat.st_mtime,
                "size": stat.st_size,
                "session_id": data.get("session_id"),
                "events": len(data.get("events", [])),
                "memory": len(data.get("memory", [])),
            })
        return archives

    def get_summary(self, **kw) -> Dict:
        """获取会话摘要。"""
        with self._lock:
            return {
                "session_id": self._session_id,
                "version": self._version,
                "started_at": self._started_at,
                "events": len(self._events),
                "memory_entries": len(self._memory),
                "context_keys": sorted(self._context.keys()),
                "last_saved": self._last_full_save,
                "save_count": self._save_counter,
                "archive_dir": str(self._archive_dir),
                "archive_count": len(self.list_archives()),
            }


# ── 全局单例 ───────────────────────────────────────────────

_archiver: Optional[SessionArchiver] = None
_archiver_lock = threading.Lock()


def get_archiver() -> SessionArchiver:
    global _archiver
    with _archiver_lock:
        if _archiver is None:
            _archiver = SessionArchiver()
        return _archiver


# ── 模块级便捷函数 (与 stub 的 __all__ 保持一致) ──────────

def init_session(version: str = '', **kw) -> str:
    return get_archiver().init_session(version, **kw)


def record(event_type: str, detail: str, category: str = 'info', **kw) -> dict:
    return get_archiver().record(event_type, detail, category, **kw)


def snapshot_memory(memory_entries: List[Dict], **kw) -> int:
    return get_archiver().snapshot_memory(memory_entries, **kw)


def save(force: bool = False, **kw) -> str:
    return get_archiver().save(force=force, **kw)


def load_latest(**kw) -> Optional[Dict]:
    return get_archiver().load_latest(**kw)


def load_snapshot(snapshot_id: str = '', **kw) -> Optional[Dict]:
    return get_archiver().load_snapshot(snapshot_id, **kw)


def list_archives(**kw) -> List[Dict]:
    return get_archiver().list_archives(**kw)


def get_summary(**kw) -> Dict:
    return get_archiver().get_summary(**kw)


__all__ = ["SessionArchiver", "init_session", "record", "snapshot_memory", "save", "load_latest", "load_snapshot", "list_archives", "get_summary", "get_archiver"]
