"""
Unified Diff Preview Engine — v2.44
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Claude Code 核心差异功能: 文件修改前展示 unified diff
特性:
- 使用 Python difflib 生成 unified diff
- 支持 SSE 流式逐行输出 diff
- 安全沙箱: 冻结模式(仅预览) vs 批准模式(预览+应用)
- 回滚: 应用前自动保存备份, 支持一键回滚
- 多语言语法高亮标记
- 类似 git diff 的输出格式
"""
import difflib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 备份目录
BACKUP_DIR = Path.home() / ".meshctx" / "diff_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


class DiffPreviewEngine:
    """统一 diff 预览引擎"""

    def __init__(self, freeze_mode: bool = False):
        """
        Args:
            freeze_mode: True=仅预览不修改, False=预览后可应用
        """
        self.freeze_mode = freeze_mode
        self._pending_changes: Dict[str, Dict] = {}  # change_id -> {original, diff, ...}
        self._applied_changes: List[Dict] = []  # applied changes history

    # ── Core: Generate Diff ────────────────────────────────

    def generate_diff(
        self,
        file_path: str,
        new_content: str,
        original_content: Optional[str] = None,
        context_lines: int = 3,
    ) -> Dict[str, Any]:
        """生成文件的 unified diff 预览

        Args:
            file_path: 文件路径
            new_content: 新内容
            original_content: 原始内容(None=从磁盘读取)
            context_lines: diff 上下文行数

        Returns:
            {change_id, file_path, diff_lines, stats, original_hash, new_hash, ...}
        """
        path = Path(file_path)
        if original_content is None:
            if path.exists():
                original_content = path.read_text(encoding="utf-8")
            else:
                original_content = ""  # 新文件

        import hashlib
        original_hash = hashlib.md5(original_content.encode()).hexdigest()
        new_hash = hashlib.md5(new_content.encode()).hexdigest()

        if original_hash == new_hash:
            return {
                "change_id": "",
                "file_path": str(path),
                "diff_lines": [],
                "stats": {"added": 0, "removed": 0, "unchanged": 0, "is_noop": True},
                "original_hash": original_hash,
                "new_hash": new_hash,
                "is_new_file": not path.exists(),
                "message": "No changes detected.",
            }

        # 生成 unified diff
        original_lines = original_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # 确保最后一行有换行符以便 difflib 正确工作
        if original_lines and not original_lines[-1].endswith('\n'):
            original_lines[-1] += '\n'
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'

        diff = list(difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=str(path),
            tofile=f"{path} (modified)",
            lineterm='',
            n=context_lines,
        ))

        # 统计
        added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
        removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))

        change_id = f"diff_{int(time.time())}_{original_hash[:8]}"

        # 保存待处理变更
        self._pending_changes[change_id] = {
            "file_path": str(path),
            "original_content": original_content,
            "new_content": new_content,
            "original_hash": original_hash,
            "new_hash": new_hash,
            "diff_lines": diff,
            "stats": {
                "added": added,
                "removed": removed,
                "modified": added + removed,
                "is_noop": False,
            },
            "is_new_file": not path.exists(),
            "created_at": time.time(),
        }

        return {
            "change_id": change_id,
            "file_path": str(path),
            "diff_lines": diff,
            "diff_text": "\n".join(diff),
            "stats": {
                "added": added,
                "removed": removed,
                "modified": added + removed,
                "is_noop": False,
            },
            "original_hash": original_hash,
            "new_hash": new_hash,
            "is_new_file": not path.exists(),
        }

    # ── Apply / Rollback ────────────────────────────────

    def apply_change(self, change_id: str, create_backup: bool = True) -> Dict[str, Any]:
        """应用已预览的变更

        Args:
            change_id: 从 generate_diff 返回的 change_id
            create_backup: 是否创建回滚备份

        Returns:
            {success, file_path, backup_path, stats}
        """
        if self.freeze_mode:
            return {"success": False, "error": "系统处于冻结模式, 不允许修改文件"}

        pending = self._pending_changes.pop(change_id, None)
        if pending is None:
            return {"success": False, "error": f"未找到待处理变更: {change_id}"}

        file_path = Path(pending["file_path"])

        # 创建回滚备份
        backup_path = None
        if create_backup and file_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = BACKUP_DIR / f"{file_path.name}.{ts}.bak"
            backup_path.write_text(pending["original_content"], encoding="utf-8")

        # 应用变更
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(pending["new_content"], encoding="utf-8")

        # 记录
        record = {
            "change_id": change_id,
            "file_path": str(file_path),
            "backup_path": str(backup_path) if backup_path else None,
            "stats": pending["stats"],
            "applied_at": time.time(),
        }
        self._applied_changes.append(record)

        logger.info(f"✅ 已应用变更: {file_path} (+{pending['stats']['added']} -{pending['stats']['removed']})")

        return {
            "success": True,
            "file_path": str(file_path),
            "backup_path": str(backup_path) if backup_path else None,
            "stats": pending["stats"],
            "change_id": change_id,
        }

    def rollback_change(self, change_id: str) -> Dict[str, Any]:
        """回滚已应用的变更"""
        if self.freeze_mode:
            return {"success": False, "error": "系统处于冻结模式, 不允许修改文件"}

        # 找到已应用的变更记录
        record = None
        for i, r in enumerate(self._applied_changes):
            if r["change_id"] == change_id:
                record = r
                break

        if record is None:
            return {"success": False, "error": f"未找到已应用变更: {change_id}"}

        backup_path = record.get("backup_path")
        if not backup_path or not Path(backup_path).exists():
            return {"success": False, "error": "回滚备份不存在, 无法回滚"}

        file_path = Path(record["file_path"])
        original = Path(backup_path).read_text(encoding="utf-8")
        file_path.write_text(original, encoding="utf-8")

        logger.info(f"⏪ 已回滚变更: {file_path}")

        return {
            "success": True,
            "file_path": str(file_path),
            "restored_from": backup_path,
            "change_id": change_id,
        }

    # ── Batch Operations ────────────────────────────────

    def generate_batch_diff(
        self,
        changes: List[Dict[str, str]],  # [{path, content}, ...]
        context_lines: int = 3,
    ) -> Dict[str, Any]:
        """批量生成多个文件的 diff 预览"""
        results = []
        total_added = 0
        total_removed = 0
        for change in changes:
            result = self.generate_diff(
                file_path=change["path"],
                new_content=change["content"],
                context_lines=context_lines,
            )
            results.append(result)
            total_added += result["stats"]["added"]
            total_removed += result["stats"]["removed"]

        return {
            "changes": results,
            "total_files": len(changes),
            "total_added": total_added,
            "total_removed": total_removed,
            "change_ids": [r["change_id"] for r in results if r["change_id"]],
        }

    def apply_batch(self, change_ids: List[str]) -> Dict[str, Any]:
        """批量应用多个变更"""
        results = []
        for cid in change_ids:
            results.append(self.apply_change(cid))
        success = all(r["success"] for r in results)
        return {"success": success, "results": results, "total": len(results)}

    # ── Streaming Diff ────────────────────────────────

    def stream_diff_lines(self, change_id: str):
        """生成器: 逐行产出 diff (用于 SSE)"""
        pending = self._pending_changes.get(change_id)
        if not pending:
            yield json.dumps({"error": f"未找到变更: {change_id}"})
            return

        yield json.dumps({"type": "header", "file": pending["file_path"],
                          "stats": pending["stats"]})

        for line in pending["diff_lines"]:
            yield json.dumps({"type": "diff_line", "line": line})
            time.sleep(0.01)  # 模拟流式输出

        yield json.dumps({"type": "done", "change_id": change_id})

    # ── History & Stats ────────────────────────────────

    def get_history(self, limit: int = 20) -> List[Dict]:
        """获取变更历史"""
        return self._applied_changes[-limit:]

    def get_pending(self) -> List[Dict]:
        """获取待处理的变更"""
        return [
            {"change_id": cid, "file_path": p["file_path"], "stats": p["stats"]}
            for cid, p in self._pending_changes.items()
        ]

    def clear_pending(self) -> int:
        """清除所有待处理变更"""
        count = len(self._pending_changes)
        self._pending_changes.clear()
        return count

    def list_backups(self) -> List[Dict]:
        """列出所有回滚备份"""
        backups = []
        for p in sorted(BACKUP_DIR.glob("*.bak"), reverse=True):
            stat = p.stat()
            backups.append({
                "filename": p.name,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return backups[:50]

    def diff_between_files(self, file_a: str, file_b: str, context_lines: int = 3) -> Dict[str, Any]:
        """比较两个文件的差异"""
        content_a = Path(file_a).read_text(encoding="utf-8")
        content_b = Path(file_b).read_text(encoding="utf-8")
        return self.generate_diff(
            file_path=file_b,
            new_content=content_b,
            original_content=content_a,
            context_lines=context_lines,
        )


# 单例
_diff_engine: Optional[DiffPreviewEngine] = None


def get_diff_engine(freeze_mode: bool = False) -> DiffPreviewEngine:
    global _diff_engine
    if _diff_engine is None:
        _diff_engine = DiffPreviewEngine(freeze_mode=freeze_mode)
    return _diff_engine
