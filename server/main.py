"""MeshCtx FastAPI Server — REST API for continuous context memory."""

import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from src.memory_engine import get_engine, MemoryEngine

# ──────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MeshCtx API",
    description="AI Continuous Context Memory Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine: MemoryEngine = get_engine()


# ──────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────
class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)
    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    metadata: dict = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(default="")


class AddMessageResponse(BaseModel):
    message_id: int
    project_id: str
    vector_key: str
    facts_extracted: int
    facts: list[str]


class ContextResponse(BaseModel):
    project_id: str
    message_count: int
    recent_messages: list
    extracted_facts: list


class SearchResponse(BaseModel):
    query: str
    semantic_matches: list
    keyword_matches: list


# ──────────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/stats")
def stats():
    return engine.stats()


# ──────────────────────────────────────────────────────────────────────
# Projects
# ──────────────────────────────────────────────────────────────────────
@app.get("/api/projects")
def list_projects():
    return engine.list_projects()


@app.post("/api/projects", status_code=201)
def create_project(proj: ProjectCreate):
    engine.cross_platform_engine.ensure_project(proj.id, proj.name)
    return {"id": proj.id, "name": proj.name, "created": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    result = engine.delete_project(project_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


# ──────────────────────────────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────────────────────────────
@app.post("/api/projects/{project_id}/messages", response_model=AddMessageResponse, status_code=201)
def add_message(project_id: str, msg: MessageRequest):
    return engine.add_message(
        content=msg.content,
        project_id=project_id,
        role=msg.role,
        metadata=msg.metadata,
    )


@app.get("/api/projects/{project_id}/messages")
def get_messages(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    messages = engine.cross_platform_engine.get_messages(project_id, limit=limit, offset=offset)
    count = engine.cross_platform_engine.get_message_count(project_id)
    return {"project_id": project_id, "count": count, "messages": messages}


# ──────────────────────────────────────────────────────────────────────
# Context & Search
# ──────────────────────────────────────────────────────────────────────
@app.get("/api/projects/{project_id}/context", response_model=ContextResponse)
def get_context(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    include_facts: bool = Query(default=True),
):
    return engine.get_context(project_id, limit=limit, include_facts=include_facts)


@app.get("/api/projects/{project_id}/search", response_model=SearchResponse)
def search(
    project_id: str,
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=10, ge=1, le=50),
):
    return engine.search(project_id, q, top_k=top_k)


@app.get("/api/projects/{project_id}/facts")
def get_facts(project_id: str, limit: int = Query(default=50, ge=1, le=500)):
    facts = engine.cross_platform_engine.get_facts(project_id, limit=limit)
    return {"project_id": project_id, "facts": facts}


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8412, reload=True)
