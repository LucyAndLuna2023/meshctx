"""
跨会话身份连续性 — SessionIdentity

策略信念、习惯、偏好持久化到 ~/.meshctx/identity/
重启后自动加载，Agent不会"失忆"

接入点: AgentLoopPlugin on_load 加载, on_unload 保存
"""
import json
import time
import os
from pathlib import Path
from typing import Dict, Optional


class SessionIdentity:
    """Agent身份持久化 — 策略/习惯/偏好跨会话存活"""

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/.meshctx/identity")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.storage_dir / "agent_identity.json"

        # 策略信念: task_type → {strategy: weight}
        self._strategy_beliefs: Dict[str, Dict[str, float]] = {}

        # 习惯: task_type → {strategy, count, last_used}
        self._habits: Dict[str, Dict] = {}

        # 偏好
        self._preferences: Dict[str, str] = {}

        # 时间戳
        self.created_at = time.time()
        self.last_active = time.time()
        self.session_count = 0

        # 尝试加载已有身份
        self.load()

    # ── 策略信念 ────────────────────────────────

    def set_strategy_belief(self, task_type: str, beliefs: Dict[str, float]):
        self._strategy_beliefs[task_type] = dict(beliefs)

    def get_strategy_belief(self, task_type: str) -> Optional[Dict[str, float]]:
        return self._strategy_beliefs.get(task_type)

    # ── 习惯 ─────────────────────────────────────

    def set_habit(self, task_type: str, strategy: str, count: int = 0):
        self._habits[task_type] = {
            "strategy": strategy,
            "count": count,
            "last_used": time.time(),
        }

    def get_habit(self, task_type: str) -> Optional[Dict]:
        return self._habits.get(task_type)

    def is_habit_formed(self, task_type: str) -> bool:
        h = self._habits.get(task_type)
        return h is not None and h.get("count", 0) >= 10

    # ── 偏好 ─────────────────────────────────────

    def set_preference(self, key: str, value: str):
        self._preferences[key] = value

    def get_preference(self, key: str) -> Optional[str]:
        return self._preferences.get(key)

    # ── 生命周期 ─────────────────────────────────

    def touch(self):
        self.last_active = time.time()

    def save(self):
        """持久化到磁盘"""
        data = {
            "strategy_beliefs": self._strategy_beliefs,
            "habits": self._habits,
            "preferences": self._preferences,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "session_count": self.session_count + 1,
        }
        self.file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        self.session_count = data["session_count"]

    def load(self):
        """从磁盘加载"""
        if not self.file.exists():
            return
        try:
            data = json.loads(self.file.read_text())
            self._strategy_beliefs = data.get("strategy_beliefs", {})
            self._habits = data.get("habits", {})
            self._preferences = data.get("preferences", {})
            self.created_at = data.get("created_at", time.time())
            self.last_active = data.get("last_active", time.time())
            self.session_count = data.get("session_count", 0)
        except (json.JSONDecodeError, KeyError):
            pass

    # ── LearnLoop集成 ────────────────────────────

    def merge_from_learn_loop(self, new_beliefs: Dict, new_habits: Dict):
        """从LearnLoop合并新数据"""
        for task_type, beliefs in new_beliefs.items():
            self._strategy_beliefs[task_type] = dict(beliefs)

        for task_type, habit_data in new_habits.items():
            existing = self._habits.get(task_type, {})
            existing.update(habit_data)
            self._habits[task_type] = existing

    def export_for_learn_loop(self) -> tuple:
        """导出供LearnLoop初始化"""
        return dict(self._strategy_beliefs), dict(self._habits)
