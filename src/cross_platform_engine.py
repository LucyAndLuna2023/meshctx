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

    # ── 数据查询 ─────────────────────────────────────────────

    def get_messages(self, conversation_id: str, limit: int = 10) -> list:
        """获取会话消息（从磁盘加载）"""
        messages_dir = self.base_path / "messages"
        if not messages_dir.exists():
            return []

        from .models import Message

        messages = []
        for file_path in messages_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("conversation_id") == conversation_id:
                        messages.append(Message(**data))
            except Exception:
                continue

        messages.sort(key=lambda x: x.timestamp)
        return messages[-limit:]

    def get_project_memories(self, project_id: str) -> list:
        """获取项目的所有记忆（从磁盘加载）"""
        from .models import Memory

        memories_dir = self.base_path / "memories"
        if not memories_dir.exists():
            return []

        memories = []
        for file_path in memories_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("project_id") == project_id:
                        memories.append(Memory(**data))
            except Exception:
                continue

        return memories

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
