"""
meshctx FastAPI 主服务
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from pathlib import Path
import uvicorn

from .memory_engine import MemoryEngine
from .models import Project, Conversation, Message, Memory, Agent, AgentSession

app = FastAPI(
    title="meshctx API",
    description="智能助手连续上下文记忆平台",
    version="0.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化引擎
memory_engine = MemoryEngine(use_llm=True, use_vector_store=True)

# 挂载引擎到 app.state，供 Web UI 使用
app.state.memory_engine = memory_engine

# 静态文件 + Web UI 路由
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

from .web_ui import router as web_ui_router
app.include_router(web_ui_router)


# ── Request Models ───────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str
    description: str
    tags: Optional[List[str]] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class CreateConversationRequest(BaseModel):
    project_id: str
    title: str


class AddMessageRequest(BaseModel):
    conversation_id: str
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class RegisterAgentRequest(BaseModel):
    name: str
    description: str
    capabilities: List[str]
    context_window: int = 4000


class StartAgentSessionRequest(BaseModel):
    agent_id: str
    project_id: str
    conversation_id: str


class EndAgentSessionRequest(BaseModel):
    final_state: Optional[Dict[str, Any]] = None


class SearchRequest(BaseModel):
    query: str
    project_id: Optional[str] = None
    top_k: int = 10


class BuildContextRequest(BaseModel):
    agent_id: str
    project_id: str
    conversation_id: str
    max_messages: int = 20


# ── API Routes ───────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "meshctx API 正常运行",
        "version": "0.2.0",
        "endpoints": {
            "projects": "/projects",
            "conversations": "/conversations",
            "messages": "/messages",
            "memories": "/projects/{id}/memories",
            "agents": "/agents",
            "agent_sessions": "/agent-sessions",
            "continuity": "/projects/{id}/continuity",
            "context": "/context/build",
            "search": "/search",
            "health": "/health",
        },
    }


# ── 项目管理 ─────────────────────────────────────────────────

@app.post("/projects", response_model=Project)
async def create_project(request: CreateProjectRequest):
    return memory_engine.create_project(request.name, request.description, request.tags)


@app.get("/projects", response_model=List[Project])
async def list_projects():
    return memory_engine.list_projects()


@app.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    project = memory_engine.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, request: UpdateProjectRequest):
    project = memory_engine.update_project(
        project_id,
        **request.model_dump(exclude_unset=True),
    )
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if not memory_engine.delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"status": "deleted"}


# ── 会话管理 ─────────────────────────────────────────────────

@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    try:
        return memory_engine.start_conversation(request.project_id, request.title)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/projects/{project_id}/conversations", response_model=List[Conversation])
async def list_conversations(project_id: str):
    return memory_engine.list_conversations(project_id)


# ── 消息管理 ─────────────────────────────────────────────────

@app.post("/messages", response_model=Message)
async def add_message(request: AddMessageRequest):
    try:
        return memory_engine.add_message(
            request.conversation_id,
            request.role,
            request.content,
            request.metadata,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_conversation_messages(conversation_id: str, limit: int = 50, offset: int = 0):
    return memory_engine.get_messages(conversation_id, limit, offset)


# ── 向量搜索 ─────────────────────────────────────────────────

@app.post("/search")
async def search_messages(request: SearchRequest):
    results = memory_engine.search_messages(request.query, request.project_id, request.top_k)
    return results


# ── 记忆管理 ─────────────────────────────────────────────────

@app.get("/projects/{project_id}/memories", response_model=List[Memory])
async def get_project_memories(project_id: str):
    return memory_engine.get_memories(project_id)


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    if not memory_engine.delete_memory(memory_id):
        raise HTTPException(404, "Memory not found")
    return {"status": "deleted"}


# ── 助手管理 ─────────────────────────────────────────────────

@app.post("/agents", response_model=Agent)
async def register_agent(request: RegisterAgentRequest):
    return memory_engine.register_agent(
        request.name,
        request.description,
        request.capabilities,
        request.context_window,
    )


@app.get("/agents", response_model=List[Agent])
async def list_agents():
    return list(memory_engine.agents.values())


@app.get("/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    agent = memory_engine.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


# ── 助手会话管理 ─────────────────────────────────────────────

@app.post("/agent-sessions", response_model=AgentSession)
async def start_agent_session(request: StartAgentSessionRequest):
    try:
        return memory_engine.start_agent_session(
            request.agent_id, request.project_id, request.conversation_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/agent-sessions/{session_id}/end")
async def end_agent_session(session_id: str, request: EndAgentSessionRequest = None):
    final = request.final_state if request else None
    session = memory_engine.end_agent_session(session_id, final)
    if not session:
        raise HTTPException(404, "Session not found")
    return {"status": "ended", "session": session}


@app.get("/agent-sessions")
async def list_agent_sessions(agent_id: Optional[str] = None,
                              project_id: Optional[str] = None):
    return memory_engine.get_agent_sessions(agent_id, project_id)


# ── 连续性检测 ───────────────────────────────────────────────

@app.get("/projects/{project_id}/continuity")
async def get_continuity(project_id: str):
    if project_id not in memory_engine.projects:
        raise HTTPException(404, "Project not found")
    return memory_engine.detect_continuity(project_id)


# ── 上下文组装 ───────────────────────────────────────────────

@app.post("/context/build")
async def build_context(request: BuildContextRequest):
    try:
        return memory_engine.build_context_for_agent(
            request.agent_id, request.project_id,
            request.conversation_id, request.max_messages,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── 健康检查 ─────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "0.2.0",
        "projects_count": len(memory_engine.projects),
        "conversations_count": len(memory_engine.conversations),
        "memories_count": len(memory_engine.memories),
        "agents_count": len(memory_engine.agents),
        "sessions_count": len(memory_engine.agent_sessions),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
