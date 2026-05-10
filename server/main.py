"""MeshCtx FastAPI Server — REST API for continuous context memory + Hermes orchestration."""

import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from src.memory_engine import get_engine, MemoryEngine
from src.capabilities import get_catalog, CapabilityCatalog
from src.orchestrator import get_orchestrator, SkillOrchestrator
from src.adapter import get_portal, ContextPortal

# ──────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MeshCtx API",
    description="AI Continuous Context Memory Platform with Hermes Skill Orchestration",
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
catalog: CapabilityCatalog = get_catalog()
orchestrator: SkillOrchestrator = get_orchestrator()
portal: ContextPortal = get_portal()


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


class OrchestrateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    project_id: str = Field(default="default")


class SkillContextRequest(BaseModel):
    skill_name: str = Field(..., min_length=1)
    project_id: str = Field(default="default")


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
# Hermes Integration — Capabilities & Orchestration
# ──────────────────────────────────────────────────────────────────────

# ── Catalog ────────────────────────────────────────────────────────

@app.get("/api/hermes/catalog")
def get_catalog_stats():
    """获取 Hermes 能力目录统计"""
    return catalog.stats()


@app.get("/api/hermes/skills")
def list_skills(
    category: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
):
    """列出/搜索 Hermes 技能"""
    if tag:
        skills = catalog.get_by_tag(tag)
        return {"count": len(skills), "skills": [{"name": s.name, "category": s.category, "description": s.description, "tags": s.tags} for s in skills]}
    if category:
        skills = catalog.get_by_category(category)
        return {"count": len(skills), "category": category, "skills": [{"name": s.name, "description": s.description, "tags": s.tags} for s in skills]}
    return catalog.export_skill_index()


@app.get("/api/hermes/skills/search")
def search_skills(q: str = Query(..., min_length=1), top_k: int = Query(default=10, ge=1, le=50)):
    """按关键词搜索技能"""
    results = catalog.find_skills(q, top_k=top_k)
    return {
        "query": q,
        "results": [{"name": s.name, "category": s.category, "description": s.description, "tags": s.tags, "score": round(score, 2)} for s, score in results],
    }


@app.get("/api/hermes/skills/{skill_name}")
def get_skill(skill_name: str):
    """获取单个技能详情"""
    skill = catalog.skill_info(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return {"name": skill.name, "category": skill.category, "description": skill.description, "tags": skill.tags, "related": skill.related}


@app.get("/api/hermes/categories")
def list_categories():
    """列出所有技能类别"""
    return catalog.list_categories()


# ── Tools ───────────────────────────────────────────────────────────

@app.get("/api/hermes/tools")
def list_tools(q: Optional[str] = Query(default=None)):
    """列出/搜索 Hermes 工具"""
    if q:
        results = catalog.find_tools(q)
        return {"query": q, "tools": [{"name": t.name, "toolset": t.toolset, "description": t.description, "score": round(s, 2)} for t, s in results]}
    return {"count": len(catalog.tools), "tools": [{"name": t.name, "toolset": t.toolset, "description": t.description} for t in sorted(catalog.tools.values(), key=lambda x: x.name)]}


# ── Providers ───────────────────────────────────────────────────────

@app.get("/api/hermes/providers")
def list_providers():
    """列出所有支持的 LLM 供应商"""
    return {name: {"type": p.type, "env_var": p.env_var} for name, p in catalog.providers.items()}


# ── Orchestration ───────────────────────────────────────────────────

@app.post("/api/hermes/orchestrate")
def orchestrate(req: OrchestrateRequest):
    """意图分析 + 技能匹配 + 执行计划"""
    match = orchestrator.match(req.query)
    plan = orchestrator.plan(req.query)
    return {
        "query": req.query,
        "match": {
            "intent": match.intent,
            "primary_skill": match.primary_skill,
            "confidence": round(match.confidence, 2),
            "top_skills": [{"name": s.name, "score": round(sc, 2)} for s, sc in match.skills[:5]],
        },
        "plan": {
            "skill_chain": plan.chain,
            "steps": plan.steps,
        },
    }


@app.get("/api/hermes/chains")
def list_skill_chains():
    """列出所有预定义技能链"""
    from src.orchestrator import SKILL_CHAINS
    return SKILL_CHAINS


# ── Context Bridge ──────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/hermes-context")
def get_hermes_context(project_id: str, max_tokens: int = Query(default=2000, ge=100, le=8000)):
    """获取格式化为 Hermes 可注入的上下文文本"""
    text = portal.extract_context_for_hermes(project_id, max_tokens=max_tokens)
    return {"project_id": project_id, "context_text": text, "length": len(text)}


@app.post("/api/projects/{project_id}/skill-context")
def get_skill_context(project_id: str, req: SkillContextRequest):
    """获取加载技能所需的完整上下文"""
    from src.adapter import SkillContextProvider
    provider = SkillContextProvider(portal=portal)
    ctx = provider.prepare_skill_context(req.skill_name, project_id)
    return ctx


@app.get("/api/projects/{project_id}/orchestrate-context")
def orchestrate_with_context(
    project_id: str,
    q: str = Query(..., min_length=1),
):
    """结合项目上下文进行编排"""
    plan = orchestrator.plan(q)
    skills = orchestrator.get_recommended_skills(q)
    hermes_ctx = portal.extract_context_for_hermes(project_id)
    return {
        "query": q,
        "project_id": project_id,
        "plan": {"intent": plan.intent, "chain": plan.chain, "steps": plan.steps},
        "recommended_skills": skills,
        "hermes_context": hermes_ctx[:1000],
    }
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8412, reload=True)
