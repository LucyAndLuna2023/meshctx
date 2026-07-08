"""meshctx VersionGuard — 版本变更检测与历史记录"""
import json
import re
import time
from pathlib import Path


class VersionGuard:
    """检测版本变更，记录历史，持久化状态。"""

    STATE_FILE = ".meshctx_version_state.json"

    def __init__(self, project_root, auto_backup=True, **kw):
        self.project_root = Path(project_root)
        self.auto_backup = auto_backup
        self._last_version = None
        self._history = []
        self._load_state()

    # ── 状态持久化 ──────────────────────────────────────────────
    def _state_path(self, **kw):
        return self.project_root / self.STATE_FILE

    def _load_state(self, **kw):
        path = self._state_path()
        if path.exists():
            data = json.loads(path.read_text())
            self._last_version = data.get("last_version")
            self._history = data.get("history", [])

    def _save_state(self, **kw):
        path = self._state_path()
        data = {
            "last_version": self._last_version,
            "history": self._history,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # ── 版本检测 ─────────────────────────────────────────────────
    def detect_version(self, **kw):
        """从 src/core/__init__.py 读取 __version__"""
        init_file = self.project_root / "src" / "core" / "__init__.py"
        if not init_file.exists():
            return None
        content = init_file.read_text()
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        return m.group(1) if m else None

    # ── 版本判断 ─────────────────────────────────────────────────
    def is_new_version(self, **kw):
        """首次运行或版本号与上次不一致时返回 True"""
        current = self.detect_version()
        return current is not None and current != self._last_version

    # ── 变更检测 ─────────────────────────────────────────────────
    def detect_changes(self, **kw):
        current = self.detect_version()
        return {
            "current_version": current,
            "is_new_version": current is not None and current != self._last_version,
        }

    # ── 版本变更触发 ─────────────────────────────────────────────
    def on_version_change(self, **kw):
        current = self.detect_version()
        if current is None or current == self._last_version:
            return {"triggered": False}

        # 记录历史
        entry = {
            "version": current,
            "timestamp": time.time(),
        }
        self._history.append(entry)
        self._last_version = current
        self._save_state()

        return {
            "triggered": True,
            "to_version": current,
            "from_version": self._last_version,
            "actions": [
                f"版本历史已记录: {current}"
            ],
        }

    # ── 历史 ─────────────────────────────────────────────────────
    def get_history(self, **kw):
        return list(self._history)

    # ── 统计 ─────────────────────────────────────────────────────
    def get_stats(self, **kw):
        return {
            "current_version": self.detect_version(),
            "total_versions_recorded": len(self._history),
        }

