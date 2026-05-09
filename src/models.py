"""
meshctx 核心数据模型定义
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel


class Project(BaseModel):
    """项目基础信息"""
    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    status: str  # active, completed, archived


class Conversation(BaseModel):
    """会话记录"""
    id: str
    project_id: str
    title: str
    summary: str
    created_at: datetime
    updated_at: datetime
    context_vectors: List[float]  # 上下文的向量表示


class Message(BaseModel):
    """消息记录"""
    id: str
    conversation_id: str
    role: str  # user, assistant, system
    content: str
    timestamp: datetime
    metadata: Dict[str, Any]  # 附加元数据


class Memory(BaseModel):
    """关键记忆"""
    id: str
    project_id: str
    key: str  # 记忆关键词
    value: str  # 记忆内容
    importance: float  # 重要性评分 0-1
    created_at: datetime
    updated_at: datetime


class Agent(BaseModel):
    """AI 助手定义"""
    id: str
    name: str
    description: str
    capabilities: List[str]  # 支持的功能
    context_window: int  # 上下文窗口大小


class AgentSession(BaseModel):
    """助手会话"""
    id: str
    agent_id: str
    project_id: str
    conversation_id: str
    started_at: datetime
    ended_at: Optional[datetime]
    session_state: Dict[str, Any]  # 会话状态


class ContextVector(BaseModel):
    """上下文向量表示"""
    id: str
    conversation_id: str
    vector: List[float]
    created_at: datetime
    content_hash: str  # 内容哈希值


class Plugin(BaseModel):
    """插件定义"""
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    config_schema: Dict[str, Any]  # 配置定义