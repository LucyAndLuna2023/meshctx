"""
MeshCtx v3.35 — Session Auto-Resume Engine
服务器重启后自动恢复会话上下文、内存状态、决策历史。

存储: ~/.meshctx/archives/
架构: SessionArchiver (持久化) + SessionResumeEngine (恢复逻辑) + API
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path.home() / ".meshctx" / "archives"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


class SessionResumeEngine:
    """会话自动恢复引擎
    
    启动时自动检测并恢复上次会话的:
    - 上下文 (decisions, rules, errors, progress)
    - 内存快照
    - 版本信息
    - 时间线
    """
    
    def __init__(self):
        self._resumed: bool = False
        self._previous_session: Optional[Dict[str, Any]] = None
        self._resume_errors: List[str] = []
        self._resume_time: float = 0.0
        self._snapshots_loaded: int = 0
    
    def detect_previous_session(self) -> Optional[Dict[str, Any]]:
        """检测是否有可恢复的上次会话"""
        latest = ARCHIVE_DIR / "latest.json"
        if not latest.exists():
            logger.info("SessionResume: 无历史会话存档")
            return None
        
        try:
            with open(latest, encoding="utf-8") as f:
                data = json.load(f)
            age_seconds = time.time() - data.get("saved_at", 0)
            if age_seconds > 86400 * 7:  # 7天前的认为过期
                logger.info(f"SessionResume: 上次会话已过期 ({age_seconds/3600:.1f}h前)")
                return None
            
            logger.info(f"SessionResume: 检测到上次会话 ({age_seconds/60:.0f}分钟前)")
            return data
        except Exception as e:
            logger.warning(f"SessionResume: 读取存档失败: {e}")
            return None
    
    def restore(self, previous: Dict[str, Any]) -> Dict[str, Any]:
        """恢复会话上下文
        
        Returns: 恢复摘要 {resumed, session_id, items_restored, ...}
        """
        start = time.time()
        resume_report = {
            "resumed": False,
            "previous_session_id": previous.get("session_id", "unknown"),
            "previous_version": previous.get("version", "unknown"),
            "previous_started": previous.get("started_at", 0),
            "previous_saved": previous.get("saved_at", 0),
            "items_restored": {},
            "errors": [],
            "snapshots_available": len(list(ARCHIVE_DIR.glob("snapshot_*.json"))),
            "archive_total": len(list(ARCHIVE_DIR.glob("*.json"))),
        }
        
        try:
            # 1. 恢复决策历史
            decisions = previous.get("decisions", [])
            resume_report["items_restored"]["decisions"] = len(decisions)
            
            # 2. 恢复规则
            rules = previous.get("rules", [])
            resume_report["items_restored"]["rules"] = len(rules)
            
            # 3. 恢复错误日志
            errors = previous.get("errors", [])
            resume_report["items_restored"]["errors"] = len(errors)
            
            # 4. 恢复进度事件
            progress = previous.get("progress", [])
            resume_report["items_restored"]["progress"] = len(progress)
            
            # 5. 恢复内存快照
            memory_snapshot = previous.get("memory_snapshot", {})
            if memory_snapshot:
                resume_report["items_restored"]["memory_entries"] = memory_snapshot.get("count", 0)
            
            # 6. 加载最近的完整快照作为补充
            snapshots = sorted(ARCHIVE_DIR.glob("snapshot_*.json"))
            snapshot_data = []
            for snap_path in snapshots[-3:]:  # 最近3个快照
                try:
                    with open(snap_path, encoding="utf-8") as f:
                        snap = json.load(f)
                    snapshot_data.append({
                        "name": snap_path.name,
                        "saved_at": snap.get("saved_at", 0),
                        "decisions": len(snap.get("decisions", [])),
                        "rules": len(snap.get("rules", [])),
                        "errors": len(snap.get("errors", [])),
                    })
                except Exception as e:
                    resume_report["errors"].append(f"snapshot {snap_path.name}: {e}")
            
            self._snapshots_loaded = len(snapshot_data)
            resume_report["snapshot_details"] = snapshot_data
            
            self._resumed = True
            self._previous_session = previous
            self._resume_time = time.time() - start
            
            resume_report["resumed"] = True
            resume_report["resume_time_ms"] = round(self._resume_time * 1000, 1)
            resume_report["context_continuity"] = self._compute_continuity(previous)
            
            logger.info(
                f"SessionResume: 恢复完成 — "
                f"decisions={len(decisions)} rules={len(rules)} "
                f"errors={len(errors)} progress={len(progress)} "
                f"({self._resume_time*1000:.1f}ms)"
            )
            
        except Exception as e:
            resume_report["errors"].append(str(e))
            logger.error(f"SessionResume: 恢复异常: {e}")
        
        return resume_report
    
    def _compute_continuity(self, previous: Dict[str, Any]) -> float:
        """计算上下文连续性评分 0-100"""
        score = 0.0
        
        # 时间连续性: 越近越高
        age_hours = (time.time() - previous.get("saved_at", 0)) / 3600
        if age_hours < 1:
            score += 30
        elif age_hours < 6:
            score += 20
        elif age_hours < 24:
            score += 10
        elif age_hours < 72:
            score += 5
        
        # 内容丰富度
        total_items = (
            len(previous.get("decisions", [])) +
            len(previous.get("rules", [])) +
            len(previous.get("errors", [])) +
            len(previous.get("progress", []))
        )
        if total_items > 100:
            score += 30
        elif total_items > 50:
            score += 20
        elif total_items > 10:
            score += 10
        
        # 版本连续性
        from src.core import __version__ as current_version
        prev_version = previous.get("version", "")
        if prev_version == current_version:
            score += 20
        elif prev_version and prev_version.split(".")[:2] == current_version.split(".")[:2]:
            score += 10
        
        # 快照完整性
        snapshot_count = len(list(ARCHIVE_DIR.glob("snapshot_*.json")))
        if snapshot_count > 5:
            score += 20
        elif snapshot_count > 2:
            score += 10
        
        return min(100.0, score)
    
    def apply_to_kernel(self, kernel) -> List[str]:
        """将恢复的上下文应用到内核
        
        Args:
            kernel: Kernel实例
            
        Returns: 应用报告列表
        """
        reports = []
        if not self._resumed or not self._previous_session:
            reports.append("无恢复数据，跳过内核注入")
            return reports
        
        prev = self._previous_session
        
        # 注入历史决策到内核记忆
        decisions = prev.get("decisions", [])
        if decisions and hasattr(kernel, 'memory'):
            for d in decisions[-20:]:  # 最近20条决策
                try:
                    kernel.memory.add(
                        f"[恢复] 历史决策: {d.get('detail', '')}",
                        level="session",
                        metadata={"source": "session_resume", "type": "decision"}
                    )
                except Exception:
                    pass
            reports.append(f"注入了 {min(20, len(decisions))} 条历史决策到内核记忆")
        
        # 注入规则到内核
        rules = prev.get("rules", [])
        if rules and hasattr(kernel, 'rules'):
            for r in rules[-30:]:
                try:
                    kernel.rules.append(r.get("detail", ""))
                except Exception:
                    pass
            reports.append(f"注入了 {min(30, len(rules))} 条规则")
        
        # 记录恢复事件
        if hasattr(kernel, 'publish'):
            try:
                kernel.publish("session_resumed", {
                    "previous_session_id": prev.get("session_id"),
                    "items_restored": sum(len(prev.get(k, [])) for k in ["decisions", "rules", "errors", "progress"])
                })
                reports.append("发布了 session_resumed 事件")
            except Exception:
                pass
        
        return reports
    
    @property
    def is_resumed(self) -> bool:
        return self._resumed
    
    @property
    def previous_session_id(self) -> Optional[str]:
        if self._previous_session:
            return self._previous_session.get("session_id")
        return None
    
    def get_resume_report(self) -> Dict[str, Any]:
        """获取完整的恢复报告"""
        return {
            "resumed": self._resumed,
            "previous_session_id": self.previous_session_id,
            "resume_time_ms": round(self._resume_time * 1000, 1),
            "snapshots_loaded": self._snapshots_loaded,
            "archive_count": len(list(ARCHIVE_DIR.glob("*.json"))),
            "snapshot_count": len(list(ARCHIVE_DIR.glob("snapshot_*.json"))),
            "archive_dir": str(ARCHIVE_DIR),
        }
    
    def get_timeline(self) -> List[Dict[str, Any]]:
        """获取会话时间线（跨会话）"""
        timeline = []
        snapshots = sorted(ARCHIVE_DIR.glob("snapshot_*.json"))
        for snap_path in snapshots:
            try:
                with open(snap_path, encoding="utf-8") as f:
                    snap = json.load(f)
                timeline.append({
                    "session_id": snap.get("session_id", "unknown"),
                    "version": snap.get("version", ""),
                    "started_at": snap.get("started_at", 0),
                    "saved_at": snap.get("saved_at", 0),
                    "duration_minutes": round((snap.get("saved_at", 0) - snap.get("started_at", 0)) / 60, 1),
                    "decisions": len(snap.get("decisions", [])),
                    "errors": len(snap.get("errors", [])),
                })
            except Exception:
                pass
        
        if self._resumed and self._previous_session:
            timeline.append({
                "session_id": self._previous_session.get("session_id", "unknown"),
                "version": self._previous_session.get("version", ""),
                "started_at": self._previous_session.get("started_at", 0),
                "saved_at": self._previous_session.get("saved_at", 0),
                "status": "resumed",
            })
        
        return sorted(timeline, key=lambda t: t.get("saved_at", 0))
    
    def clear_archives(self, older_than_days: int = 30) -> int:
        """清理旧存档"""
        cutoff = time.time() - older_than_days * 86400
        deleted = 0
        for p in ARCHIVE_DIR.glob("snapshot_*.json"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                deleted += 1
        return deleted


# ═══════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════

_resume_engine: Optional[SessionResumeEngine] = None


def get_resume_engine() -> SessionResumeEngine:
    global _resume_engine
    if _resume_engine is None:
        _resume_engine = SessionResumeEngine()
    return _resume_engine
