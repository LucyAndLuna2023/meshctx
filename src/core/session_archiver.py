"""
会话自动存档引擎 (Session Auto-Archiver)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
自动保存对话上下文、记忆快照、技术决策到持久化存储。
确保任何会话中断后都能完整恢复。

设计: 增量存档 + 全量快照 + 自动恢复
存储: ~/.meshctx/archives/
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path.home() / ".meshctx" / "archives"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


class SessionArchiver:
    """会话自动存档器"""
    
    def __init__(self):
        self._context: Dict[str, Any] = {
            "session_id": "",
            "started_at": time.time(),
            "version": "",
            "decisions": [],
            "rules": [],
            "memory_snapshot": {},
            "progress": [],
            "errors": [],
        }
        self._auto_save_interval = 300  # 5分钟自动保存
    
    def init_session(self, version: str = ""):
        """初始化新会话"""
        self._context["session_id"] = f"session_{int(time.time())}"
        self._context["started_at"] = time.time()
        self._context["version"] = version
        self.record("session_start", f"会话开始 v{version}")
    
    def record(self, event_type: str, detail: str, category: str = "info"):
        """记录事件"""
        entry = {
            "time": time.time(),
            "type": event_type,
            "detail": detail[:500],
            "category": category,
        }
        self._context["progress"].append(entry)
        
        # 分类存储
        if category == "decision":
            self._context["decisions"].append(entry)
        elif category == "rule":
            self._context["rules"].append(entry)
        elif category == "error":
            self._context["errors"].append(entry)
        
        # 限制条目数
        for key in ["progress", "decisions", "rules", "errors"]:
            if len(self._context[key]) > 200:
                self._context[key] = self._context[key][-100:]
    
    def snapshot_memory(self, memory_entries: List[Dict]):
        """保存记忆快照"""
        self._context["memory_snapshot"] = {
            "time": time.time(),
            "count": len(memory_entries),
            "entries": memory_entries[:20],  # 最近20条
        }
    
    def save(self, force: bool = False) -> str:
        """保存当前上下文到文件
        
        Returns: 存档文件路径
        """
        # 增量存档 (每次调用)
        inc_path = ARCHIVE_DIR / "latest.json"
        data = {
            **self._context,
            "saved_at": time.time(),
            "saved_at_human": datetime.now().isoformat(),
        }
        with open(inc_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 全量快照 (每5分钟或强制)
        if force or time.time() - self._last_full_save > self._auto_save_interval:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            full_path = ARCHIVE_DIR / f"snapshot_{ts}.json"
            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._last_full_save = time.time()
            
            # 保留最近10个快照
            snapshots = sorted(ARCHIVE_DIR.glob("snapshot_*.json"))
            for old in snapshots[:-10]:
                old.unlink()
        
        return str(inc_path)
    
    def load_latest(self) -> Optional[Dict]:
        """加载最近存档"""
        inc_path = ARCHIVE_DIR / "latest.json"
        if inc_path.exists():
            with open(inc_path, encoding="utf-8") as f:
                data = json.load(f)
            self._context = data
            return data
        return None
    
    def load_snapshot(self, snapshot_id: str = "") -> Optional[Dict]:
        """加载指定快照"""
        if snapshot_id:
            path = ARCHIVE_DIR / f"snapshot_{snapshot_id}.json"
        else:
            snapshots = sorted(ARCHIVE_DIR.glob("snapshot_*.json"))
            path = snapshots[-1] if snapshots else None
        
        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return None
    
    def list_archives(self) -> List[Dict]:
        """列出所有存档"""
        archives = []
        for p in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True):
            stat = p.stat()
            archives.append({
                "name": p.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "modified_human": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return archives[:20]
    
    def get_summary(self) -> Dict:
        """获取会话摘要"""
        ctx = self._context
        return {
            "session_id": ctx.get("session_id", ""),
            "version": ctx.get("version", ""),
            "duration_minutes": round((time.time() - ctx.get("started_at", time.time())) / 60, 1),
            "decisions_count": len(ctx.get("decisions", [])),
            "rules_count": len(ctx.get("rules", [])),
            "errors_count": len(ctx.get("errors", [])),
            "progress_count": len(ctx.get("progress", [])),
            "last_5_events": ctx.get("progress", [])[-5:],
            "archive_count": len(list(ARCHIVE_DIR.glob("*.json"))),
        }
    
    _last_full_save = 0


# 单例
_archiver: Optional[SessionArchiver] = None


def get_archiver() -> SessionArchiver:
    global _archiver
    if _archiver is None:
        _archiver = SessionArchiver()
    return _archiver
