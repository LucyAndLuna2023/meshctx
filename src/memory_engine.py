"""
meshctx 记忆管理引擎 — 统一版本
整合跨平台存储、LLM记忆提取、向量检索
"""
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

from .models import (
    Project, Conversation, Message, Memory,
    Agent, AgentSession, ContextVector, Plugin,
)
from .cross_platform_engine import CrossPlatformStorage
from .plugin_system import get_plugin_manager

logger = logging.getLogger("meshctx")


class MemoryEngine:
    """核心记忆管理引擎"""

    def __init__(self, storage_backend: Optional[CrossPlatformStorage] = None,
                 use_llm: bool = True, use_vector_store: bool = False):
        self.storage = storage_backend or CrossPlatformStorage()
        self.projects: Dict[str, Project] = {}
        self.conversations: Dict[str, Conversation] = {}
        self.memories: Dict[str, Memory] = {}
        self.agents: Dict[str, Agent] = {}
        self.agent_sessions: Dict[str, AgentSession] = {}
        self.plugins: Dict[str, Plugin] = {}

        # 可选组件
        self.use_llm = use_llm
        self.use_vector_store = use_vector_store
        self._llm_extractor = None
        self._vector_store = None
        self._embedding_engine = None

        if use_llm:
            try:
                from .llm_extractor import get_llm_extractor
                self._llm_extractor = get_llm_extractor()
                logger.info("LLM extractor initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM extractor: {e}")

        if use_vector_store:
            try:
                from .vector_store import get_vector_store, get_embedding_engine
                self._vector_store = get_vector_store()
                self._embedding_engine = get_embedding_engine()
                logger.info(f"Vector store backend: {self._vector_store.backend_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize vector store: {e}")

        # 加载现有数据到内存
        self._load_existing_data()

        # 插件系统
        self.plugin_manager = get_plugin_manager()
        logger.info(f"Plugin system loaded: {self.plugin_manager.active_count} active plugins")

    # ── 数据加载 ──────────────────────────────────────────────

    def _load_existing_data(self):
        """从磁盘加载现有数据到内存（Pydantic v2 兼容）"""
        for dir_name, store, cls in [
            ("projects", self.projects, Project),
            ("conversations", self.conversations, Conversation),
            ("memories", self.memories, Memory),
            ("agents", self.agents, Agent),
        ]:
            p = self.storage.base_path / dir_name
            if p.exists():
                count = 0
                for fp in p.glob("*.json"):
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        obj = cls.model_validate(data)
                        store[obj.id] = obj
                        count += 1
                    except Exception:
                        logger.debug(f"Skipped invalid entity file: {fp.name}")
                if count:
                    logger.info(f"Loaded {count} {dir_name} from disk")

        # 加载消息（不占用主内存，通过 storage.get_messages 按需读取）
        msgs_dir = self.storage.base_path / "messages"
        if msgs_dir.exists():
            msg_count = len(list(msgs_dir.glob("*.json")))
            logger.info(f"{msg_count} messages on disk (loaded on-demand)")

    # ── 项目管理 ──────────────────────────────────────────────

    def create_project(self, name: str, description: str,
                       tags: Optional[List[str]] = None) -> Project:
        """创建新项目"""
        project_id = str(uuid.uuid4())
        now = datetime.now()
        project = Project(
            id=project_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            status="active",
        )
        self.projects[project_id] = project
        self.storage.save_project(project)
        logger.info(f"Project created: {name} ({project_id[:8]}...)")

        # 插件钩子
        self.plugin_manager.dispatch_project_created(project.model_dump())

        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.projects.get(project_id)

    def update_project(self, project_id: str, **kwargs) -> Optional[Project]:
        project = self.projects.get(project_id)
        if not project:
            return None
        for k, v in kwargs.items():
            if hasattr(project, k) and k not in ("id", "created_at"):
                setattr(project, k, v)
        project.updated_at = datetime.now()
        self.storage.save_project(project)
        return project

    def delete_project(self, project_id: str) -> bool:
        if project_id not in self.projects:
            return False
        del self.projects[project_id]
        # 清理关联数据
        to_remove = [cid for cid, c in self.conversations.items()
                     if c.project_id == project_id]
        for cid in to_remove:
            del self.conversations[cid]
        to_remove_m = [mid for mid, m in self.memories.items()
                       if m.project_id == project_id]
        for mid in to_remove_m:
            del self.memories[mid]
        # 持久化清理
        self.storage.delete_entity("projects", project_id)
        return True

    def list_projects(self) -> List[Project]:
        return list(self.projects.values())

    # ── 会话管理 ──────────────────────────────────────────────

    def start_conversation(self, project_id: str, title: str) -> Conversation:
        """开始新会话"""
        if project_id not in self.projects:
            raise ValueError(f"Project {project_id} not found")
        conversation_id = str(uuid.uuid4())
        now = datetime.now()
        conversation = Conversation(
            id=conversation_id,
            project_id=project_id,
            title=title,
            summary="",
            created_at=now,
            updated_at=now,
            context_vectors=[],
        )
        self.conversations[conversation_id] = conversation
        self.storage.save_conversation(conversation)
        logger.info(f"Conversation started: {title} in project {project_id[:8]}...")
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return self.conversations.get(conversation_id)

    def list_conversations(self, project_id: str) -> List[Conversation]:
        return [c for c in self.conversations.values()
                if c.project_id == project_id]

    # ── 消息管理 ──────────────────────────────────────────────

    def add_message(self, conversation_id: str, role: str, content: str,
                    metadata: Optional[Dict[str, Any]] = None) -> Message:
        """添加消息到会话"""
        if conversation_id not in self.conversations:
            raise ValueError(f"Conversation {conversation_id} not found")

        message_id = str(uuid.uuid4())
        message = Message(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {},
        )

        # 更新会话摘要
        self._update_conversation_summary(conversation_id, message)

        # 提取关键记忆
        self._extract_memories(conversation_id, message)

        # 向量索引
        if self._vector_store and self._embedding_engine:
            try:
                emb = self._embedding_engine.encode(content)
                self._vector_store.add(
                    text=content,
                    embedding=emb,
                    metadata={
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "project_id": self.conversations[conversation_id].project_id,
                        "role": role,
                    },
                )
            except Exception:
                pass

        self.storage.save_message(message)

        # 插件钩子
        self.plugin_manager.dispatch_message_added({
            "project_id": self.conversations[conversation_id].project_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
        })

        return message

    def get_messages(self, conversation_id: str, limit: int = 50,
                     offset: int = 0) -> List[Message]:
        """获取会话消息（优先内存，回退磁盘）"""
        # 先从内存中查找
        in_memory = []
        for conv in self.conversations.values():
            if conv.id == conversation_id:
                break
        else:
            # 对话不在内存中，直接从磁盘读取
            return self.storage.get_messages(conversation_id, limit + offset)[offset:]

        # 如果内存中有该对话的消息缓存则返回
        # 否则从磁盘加载
        all_msgs = self.storage.get_messages(conversation_id, limit + offset)
        return all_msgs[offset:offset + limit]

    def search_messages(self, query: str, project_id: Optional[str] = None,
                        top_k: int = 10) -> List[Dict]:
        """向量搜索消息内容"""
        if not self._vector_store or not self._embedding_engine:
            return []
        emb = self._embedding_engine.encode(query)
        return self._vector_store.search(
            query_embedding=emb,
            top_k=top_k,
            filter_project=project_id,
        )

    # ── 记忆管理 ──────────────────────────────────────────────

    def _update_conversation_summary(self, conversation_id: str, message: Message):
        conversation = self.conversations[conversation_id]
        # 使用 LLM 生成摘要（可用时）
        if self._llm_extractor:
            try:
                msgs = self.get_messages(conversation_id, limit=20)
                summary_dicts = []
                for m in msgs:
                    d = {"role": m.role, "content": m.content}
                    summary_dicts.append(d)
                summary = self._llm_extractor.generate_summary(summary_dicts)
                if summary:
                    conversation.summary = summary
            except Exception:
                pass
        else:
            if len(conversation.summary) < 500:
                conversation.summary += f" {message.content[:80]}"
        conversation.updated_at = datetime.now()
        self.storage.save_conversation(conversation)

    def _extract_memories(self, conversation_id: str, message: Message):
        """从消息中提取关键记忆"""
        project_id = self.conversations[conversation_id].project_id

        if self._llm_extractor:
            try:
                ctx = self.get_messages(conversation_id, limit=10)
                ctx_dicts = [
                    {"role": m.role, "content": m.content}
                    for m in ctx
                ]
                extracted = self._llm_extractor.extract_memories(
                    content=message.content,
                    role=message.role,
                    conversation_context=ctx_dicts,
                )
                for item in extracted:
                    memory = Memory(
                        id=str(uuid.uuid4()),
                        project_id=project_id,
                        key=item.get("key", "unknown"),
                        value=item.get("value", ""),
                        importance=item.get("importance", 0.5),
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    self.memories[memory.id] = memory
                    self.storage.save_memory(memory)

                # 插件钩子
                for item in extracted:
                    self.plugin_manager.dispatch_memory_extracted({
                        "key": item.get("key", "unknown"),
                        "value": item.get("value", ""),
                        "importance": float(item.get("importance", 0.5)),
                        "category": item.get("category", "other"),
                        "entities": item.get("entities", []),
                    })
                return
            except Exception as e:
                logger.warning(f"LLM memory extraction failed: {e}")

        # 回退：关键词匹配
        important_keywords = [
            "重要", "关键", "记住", "预置", "目标", "记忆", "上下文",
            "连续", "决定", "结论", "注意", "必须", "禁止",
        ]
        for keyword in important_keywords:
            if keyword in message.content:
                memory = Memory(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    key=keyword,
                    value=message.content,
                    importance=0.6,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                self.memories[memory.id] = memory
                self.storage.save_memory(memory)
                break

    def get_memories(self, project_id: str) -> List[Memory]:
        """获取项目的所有记忆（内存优先）"""
        in_memory = [m for m in self.memories.values()
                     if m.project_id == project_id]
        if in_memory:
            return in_memory
        return self.storage.get_project_memories(project_id)

    def delete_memory(self, memory_id: str) -> bool:
        if memory_id not in self.memories:
            return False
        del self.memories[memory_id]
        return True

    # ── 助手管理 ──────────────────────────────────────────────

    def register_agent(self, name: str, description: str,
                       capabilities: List[str],
                       context_window: int = 4000) -> Agent:
        agent_id = str(uuid.uuid4())
        agent = Agent(
            id=agent_id,
            name=name,
            description=description,
            capabilities=capabilities,
            context_window=context_window,
        )
        self.agents[agent_id] = agent
        self.storage.save_agent(agent)
        logger.info(f"Agent registered: {name}")
        return agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    # ── 助手会话管理 ──────────────────────────────────────────

    def start_agent_session(self, agent_id: str, project_id: str,
                            conversation_id: str) -> AgentSession:
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        if project_id not in self.projects:
            raise ValueError(f"Project {project_id} not found")
        if conversation_id not in self.conversations:
            raise ValueError(f"Conversation {conversation_id} not found")

        session_id = str(uuid.uuid4())
        # 加载项目记忆作为初始上下文
        project_memories = self.get_memories(project_id)
        initial_context = {
            "memories": [
                {"key": m.key, "value": m.value, "importance": m.importance}
                for m in project_memories
            ],
            "project": self._model_to_dict(self.projects[project_id]),
        }

        session = AgentSession(
            id=session_id,
            agent_id=agent_id,
            project_id=project_id,
            conversation_id=conversation_id,
            started_at=datetime.now(),
            ended_at=None,
            session_state=initial_context,
        )
        self.agent_sessions[session_id] = session
        # 持久化
        self.storage._save_entity("agent_sessions", session_id, {
            "id": session_id,
            "agent_id": agent_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "started_at": session.started_at.isoformat(),
            "ended_at": None,
            "session_state": initial_context,
        })
        return session

    def end_agent_session(self, session_id: str,
                          final_state: Optional[Dict] = None) -> Optional[AgentSession]:
        session = self.agent_sessions.get(session_id)
        if not session:
            return None
        session.ended_at = datetime.now()
        if final_state:
            session.session_state.update(final_state)
        self.storage._save_entity("agent_sessions", session_id, {
            "id": session.id,
            "agent_id": session.agent_id,
            "project_id": session.project_id,
            "conversation_id": session.conversation_id,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat(),
            "session_state": session.session_state,
        })
        return session

    def get_agent_session(self, session_id: str) -> Optional[AgentSession]:
        return self.agent_sessions.get(session_id)

    def get_agent_sessions(self, agent_id: Optional[str] = None,
                           project_id: Optional[str] = None) -> List[AgentSession]:
        sessions = list(self.agent_sessions.values())
        if agent_id:
            sessions = [s for s in sessions if s.agent_id == agent_id]
        if project_id:
            sessions = [s for s in sessions if s.project_id == project_id]
        return sessions

    # ── 连续性检测 ────────────────────────────────────────────

    def detect_continuity(self, project_id: str) -> Dict[str, Any]:
        """检测项目的连续性：活跃会话、未完成任务、最近活动"""
        conversations = self.list_conversations(project_id)
        memories = self.get_memories(project_id)
        sessions = self.get_agent_sessions(project_id=project_id)

        active_sessions = [s for s in sessions if s.ended_at is None]

        # 计算最近活动时间
        all_timestamps = []
        for c in conversations:
            all_timestamps.append(c.updated_at)
        for s in sessions:
            all_timestamps.append(s.started_at)
            if s.ended_at:
                all_timestamps.append(s.ended_at)

        last_active = max(all_timestamps) if all_timestamps else None

        # 连续性评分 (0-1)
        score = 0.0
        if conversations:
            score += 0.3
        if memories:
            score += 0.3
        if active_sessions:
            score += 0.2
        if last_active:
            hours_since = (datetime.now() - last_active).total_seconds() / 3600
            if hours_since < 24:
                score += 0.2

        return {
            "project_id": project_id,
            "continuity_score": round(score, 2),
            "conversation_count": len(conversations),
            "memory_count": len(memories),
            "active_session_count": len(active_sessions),
            "total_session_count": len(sessions),
            "last_active": last_active.isoformat() if last_active else None,
            "is_continuous": score >= 0.5,
        }

    # ── 上下文组装（给 AI 助手用） ──────────────────────────────

    def build_context_for_agent(self, agent_id: str, project_id: str,
                                conversation_id: str,
                                max_messages: int = 20) -> Dict[str, Any]:
        """为 AI 助手组装完整的上下文"""
        agent = self.agents.get(agent_id)
        project = self.projects.get(project_id)
        conversation = self.conversations.get(conversation_id)

        if not all([agent, project, conversation]):
            raise ValueError("Invalid agent/project/conversation ID")

        messages = self.get_messages(conversation_id, limit=max_messages)
        memories = self.get_memories(project_id)
        sessions = self.get_agent_sessions(agent_id=agent_id, project_id=project_id)
        active_session = next((s for s in sessions if s.ended_at is None), None)

        raw_context = {
            "project": self._model_to_dict(project),
            "agent": self._model_to_dict(agent),
            "conversation": self._model_to_dict(conversation),
            "messages": [self._model_to_dict(m) for m in messages],
            "memories": [self._model_to_dict(m) for m in memories],
            "active_session": self._model_to_dict(active_session) if active_session else None,
            "continuity": self.detect_continuity(project_id),
            "generated_at": datetime.now().isoformat(),
        }

        # 插件管道处理
        context = self.plugin_manager.build_context_pipeline(raw_context)
        return context

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _model_to_dict(obj) -> Dict:
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        if hasattr(obj, 'dict'):
            return obj.dict()
        return {}
