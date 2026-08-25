"""Session Resume — 真实开源实现（v3.83 API 兼容）

保存 / 恢复 / 列出 / 清理会话存档（JSON 文件存储，原子写入）。
并提供高层 _SessionResume 引擎：自动检测上次会话、恢复上下文、
注入内核、生成恢复报告与跨会话时间线。纯 stdlib。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.session_resume")

_DEFAULT_STORAGE = Path.home() / ".meshctx" / "sessions"


class SessionState:
    """Represents a stored session state."""

    def __init__(self, id, profile, messages):
        self.id = id
        self.profile = profile
        self.messages = messages


class SessionResumeEngine:
    """Engine for saving and resuming sessions using file-based storage."""

    def __init__(self, storage):
        self.storage = Path(storage)
        self._lock = threading.RLock()

    # ── 路径 ──────────────────────────────────────────────
    def _session_path(self, session_id):
        # 防止路径穿越：只允许安全的 session id
        safe = "".join(
            c for c in str(session_id) if c.isalnum() or c in "-_."
        )
        return self.storage / f"{safe}.json"

    def _ensure_dir(self):
        self.storage.mkdir(parents=True, exist_ok=True)

    # ── 保存 / 恢复 ───────────────────────────────────────
    def save(self, session_id, data):
        """Save session data to disk."""
        with self._lock:
            self._ensure_dir()
            path = self._session_path(session_id)
            payload = {
                "id": str(session_id),
                "saved_at": time.time(),
                "data": data if isinstance(data, dict) else {"payload": data},
            }
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except OSError as e:
                # 清理可能的 .tmp 残留
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                raise OSError(f"session save failed: {path}: {e}")
            return str(path)

    def resume(self, session_id):
        """Resume a session. Returns session data dict or None if not found."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("session 存档损坏 %s: %s", path, e)
            return None
        except OSError as e:
            logger.warning("session 读取失败 %s: %s", path, e)
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            data.setdefault("id", payload.get("id", str(session_id)))
            data.setdefault("saved_at", payload.get("saved_at", 0.0))
        return data

    # ── 列表 / 统计 ───────────────────────────────────────
    def list_recent(self, limit):
        """List up to `limit` most recently modified sessions."""
        with self._lock:
            if not self.storage.exists():
                return []
            files = sorted(
                self.storage.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            result = []
            for path in files[: max(0, limit)]:
                try:
                    with open(path, encoding="utf-8") as f:
                        payload = json.load(f)
                    data = payload.get("data") or {}
                    if isinstance(data, dict):
                        data.setdefault("id", payload.get("id", path.stem))
                    result.append(data if isinstance(data, dict) else {"id": path.stem})
                except (OSError, json.JSONDecodeError):
                    continue
            return result

    def get_stats(self):
        """Return statistics about stored sessions."""
        with self._lock:
            if not self.storage.exists():
                return {"sessions": 0, "total_bytes": 0, "storage": str(self.storage)}
            files = list(self.storage.glob("*.json"))
            total_bytes = sum(p.stat().st_size for p in files)
            newest = max((p.stat().st_mtime for p in files), default=0.0)
            return {
                "sessions": len(files),
                "total_bytes": total_bytes,
                "newest": newest,
                "storage": str(self.storage),
            }


class _SessionResume:
    """高层会话恢复引擎（单例，供 main.py / web 端点使用）。

    负责：检测上次会话 → 恢复上下文 → 注入内核 → 生成恢复报告 /
    时间线 / 清理旧存档。
    """

    def __init__(self, storage=None, **kw):
        self.engine = SessionResumeEngine(storage or _DEFAULT_STORAGE)
        self._lock = threading.RLock()
        self._last_report: Optional[Dict[str, Any]] = None

    # ── SessionResumeEngine 兼容 ──────────────────────────
    def resume(self, *a, **kw):
        return self.engine.resume(*a, **kw)

    def stats(self):
        return self.engine.get_stats()

    # ── 检测 / 恢复 ───────────────────────────────────────
    def detect_previous_session(self, **kw):
        """检测是否存在上次会话存档。返回最近会话 id（dict 时返回 dict），无则 None。"""
        recent = self.engine.list_recent(1)
        if not recent:
            return None
        return recent[0].get("id") or None

    def restore(self, session_id, **kw):
        """恢复指定会话：读取存档并生成恢复报告。"""
        data = self.engine.resume(session_id)
        if data is None:
            return {
                "restored": False,
                "session_id": str(session_id),
                "context_continuity": 0.0,
                "items_restored": {"decisions": 0, "rules": 0, "memories": 0},
                "resume_time_ms": 0.0,
            }
        t0 = time.time()
        messages = data.get("messages") or []
        decisions = data.get("decisions") or []
        rules = data.get("rules") or []
        memories = data.get("memories") or []
        # 上下文连续性：可恢复的上下文片段占比（启发式）
        expected = max(
            1,
            len(messages) + len(decisions) + len(rules) + len(memories),
        )
        restored = len(messages) + len(decisions) + len(rules) + len(memories)
        continuity = min(100.0, 100.0 * restored / expected)
        report = {
            "restored": True,
            "session_id": str(session_id),
            "context_continuity": round(continuity, 2),
            "items_restored": {
                "messages": len(messages),
                "decisions": len(decisions),
                "rules": len(rules),
                "memories": len(memories),
            },
            "resume_time_ms": round((time.time() - t0) * 1000.0, 2),
            "data": data,
        }
        with self._lock:
            self._last_report = report
        return report

    def apply_to_kernel(self, kernel, **kw):
        """将会话上下文注入内核。返回注入报告列表。"""
        reports: List[Dict[str, Any]] = []
        if kernel is None:
            return reports
        try:
            ctx = getattr(kernel, "context", None)
            if ctx is not None and hasattr(ctx, "update"):
                data = kw.get("data") or {}
                if data:
                    ctx.update(data)
                    reports.append({
                        "target": "kernel.context",
                        "injected": len(data),
                        "status": "ok",
                    })
            else:
                reports.append({
                    "target": "kernel.context",
                    "injected": 0,
                    "status": "skipped",
                    "reason": "kernel 无 context 槽位",
                })
        except NotImplementedError:
            reports.append({
                "target": "kernel.context",
                "injected": 0,
                "status": "skipped",
                "reason": "kernel 为 stub 模式",
            })
        return reports

    def get_resume_report(self) -> Dict[str, Any]:
        """返回最近一次恢复报告（无则返回未恢复状态）。"""
        if self._last_report is None:
            return {"restored": False, "message": "尚未执行会话恢复"}
        return dict(self._last_report)

    def get_timeline(self) -> List[Dict[str, Any]]:
        """跨会话时间线：按修改时间倒序的所有存档摘要。"""
        with self._lock:
            recent = self.engine.list_recent(1000)
            timeline = []
            for entry in recent:
                saved_at = entry.get("saved_at", 0.0)
                timeline.append({
                    "session_id": entry.get("id", ""),
                    "saved_at": saved_at,
                    "messages": len(entry.get("messages") or []),
                    "decisions": len(entry.get("decisions") or []),
                    "rules": len(entry.get("rules") or []),
                })
            return timeline

    def clear_archives(self, older_than_days: int = 30) -> int:
        """清理超过 N 天的存档，返回删除数量。"""
        cutoff = time.time() - max(0, float(older_than_days)) * 86400.0
        deleted = 0
        with self._lock:
            if not self.engine.storage.exists():
                return 0
            for path in self.engine.storage.glob("*.json"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        deleted += 1
                except OSError as e:
                    logger.warning("清理存档失败 %s: %s", path, e)
        return deleted


_resume: Optional[_SessionResume] = None
_resume_lock = threading.Lock()


def get_session_resume():
    """获取全局会话恢复引擎单例。"""
    global _resume
    if _resume is None:
        with _resume_lock:
            if _resume is None:
                _resume = _SessionResume()
    return _resume


# ── 模块级便捷函数（__all__ 兼容）───────────────────────────
def save(session_id, data):
    return get_session_resume().engine.save(session_id, data)


def resume(session_id):
    return get_session_resume().resume(session_id)


def list_recent(limit):
    return get_session_resume().engine.list_recent(limit)


def get_stats():
    return get_session_resume().stats()


def stats():
    return get_session_resume().stats()


def detect_previous_session(**kw):
    return get_session_resume().detect_previous_session(**kw)


def restore(session_id, **kw):
    return get_session_resume().restore(session_id, **kw)


def apply_to_kernel(kernel, **kw):
    return get_session_resume().apply_to_kernel(kernel, **kw)


__all__ = [
    "SessionState", "SessionResumeEngine", "save", "resume", "list_recent",
    "get_stats", "stats", "detect_previous_session", "restore",
    "apply_to_kernel", "get_session_resume",
]
