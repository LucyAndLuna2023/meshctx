"""
meshctx v1.0 统一主服务

整合:
- v1.0 微内核 (事件总线+插件系统)
- v0.2 FastAPI REST API
- Web UI (Jinja2 模板)
- 向量存储 + 知识图谱

启动: meshctx start  或  python -m src.main
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════
# V1.0 内核
# ═══════════════════════════════════════════════════════════
from .core import (
    Kernel, MemoryPlugin, MetaCognitionPlugin, OrchestratorPlugin,
    PredictorPlugin, AgentLoopPlugin, PerformancePlugin,
    HealerPlugin, WebSocketPlugin, create_ws_routes,
    Event, EventPriority, MemoryItem, MemoryLevel,
    TaskEvaluation, TaskStatus, PatternEngine,
)
from .gateway import GatewayPlugin
from .core.hotreload import ConfigWatcher, APIKeyFailover, MemoryBackup

# ═══════════════════════════════════════════════════════════
# V0.2 兼容层
# ═══════════════════════════════════════════════════════════
from .memory_engine import MemoryEngine
from .models import Project, Conversation, Message, Memory, Agent, AgentSession
from .config import load_config

logger = logging.getLogger("meshctx.server")

# ─── 全局状态 ────────────────────────────────────────────
_kernel: Optional[Kernel] = None
_memory_engine: Optional[MemoryEngine] = None
_key_failover = APIKeyFailover()
_memory_backup = MemoryBackup()


def get_kernel() -> Kernel:
    """获取全局内核实例"""
    global _kernel
    if _kernel is None:
        _kernel = Kernel()
    return _kernel


def get_memory_engine() -> MemoryEngine:
    """获取全局记忆引擎"""
    global _memory_engine
    if _memory_engine is None:
        _memory_engine = MemoryEngine(use_llm=False, use_vector_store=False)
    return _memory_engine


# ═══════════════════════════════════════════════════════════
# v1.5.2 指标采集器 — 内存时间序列
# ═══════════════════════════════════════════════════════════

from collections import deque

class MetricsCollector:
    """轻量级指标采集，保留最近60个采样点(10分钟@10s)"""
    def __init__(self, maxlen=60):
        self.timestamps = deque(maxlen=maxlen)
        self.request_counts = deque(maxlen=maxlen)
        self.latency_ms = deque(maxlen=maxlen)
        self._counter = 0
        self._latency_acc = 0.0
        self._count_in_window = 0
    
    def record(self, latency_ms: float = 0):
        self._counter += 1
        self._latency_acc += latency_ms
        self._count_in_window += 1
    
    def snapshot(self):
        """返回当前快照"""
        import time as _time
        now = _time.time()
        avg_lat = round(self._latency_acc / max(1, self._count_in_window), 1)
        self.timestamps.append(now)
        self.request_counts.append(self._count_in_window)
        self.latency_ms.append(avg_lat)
        # 重置窗口
        self._count_in_window = 0
        self._latency_acc = 0.0
        return {
            "timestamps": list(self.timestamps),
            "requests": list(self.request_counts),
            "latency": list(self.latency_ms),
            "total_requests": self._counter,
        }

_metrics = MetricsCollector()

# ═══════════════════════════════════════════════════════════
# FastAPI 应用
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="meshctx API",
    description="世界第一自进化Agent系统",
    version="1.5.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """v1.5.2: 记录每个请求的延迟"""
    t0 = time.time()
    response = await call_next(request)
    elapsed = (time.time() - t0) * 1000
    _metrics.record(elapsed)
    return response


# ─── 静态文件 ────────────────────────────────────────────
# PyInstaller 打包后资源在 sys._MEIPASS 下；开发时相对于项目根目录
if getattr(sys, 'frozen', False):
    _static_dir = Path(sys._MEIPASS) / "static"
else:
    _static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ─── Web UI 路由 (延迟导入避免循环) ────────────────────
from .web_ui import router as web_ui_router
app.include_router(web_ui_router)

# 挂载引擎到 app.state
app.state.kernel = None
app.state.memory_engine = None


# ═══════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════

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

class IntentRequest(BaseModel):
    intent: str
    project_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "message": "MeshCtx API v1.3 运行中",
        "version": "1.4.0",
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
            "kernel_stats": "/kernel/stats",
            "orchestrator": "/orchestrator/execute",
            "metacognition": "/metacognition/report",
            "docs": "/docs",
        },
    }


# ── 项目管理 (委托给 MemoryEngine) ──────────────────────

@app.post("/projects", response_model=Project)
async def create_project(request: CreateProjectRequest):
    engine = get_memory_engine()
    return engine.create_project(request.name, request.description, request.tags)

@app.get("/projects", response_model=List[Project])
async def list_projects():
    return get_memory_engine().list_projects()

@app.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    project = get_memory_engine().get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, request: UpdateProjectRequest):
    project = get_memory_engine().update_project(
        project_id, **request.model_dump(exclude_unset=True)
    )
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if not get_memory_engine().delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"status": "deleted"}


# ── 会话管理 ────────────────────────────────────────────

@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    try:
        return get_memory_engine().start_conversation(request.project_id, request.title)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/projects/{project_id}/conversations", response_model=List[Conversation])
async def list_conversations(project_id: str):
    return get_memory_engine().list_conversations(project_id)


# ── 消息管理 ────────────────────────────────────────────

@app.post("/messages", response_model=Message)
async def add_message(request: AddMessageRequest):
    try:
        return get_memory_engine().add_message(
            request.conversation_id, request.role,
            request.content, request.metadata,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_conversation_messages(conversation_id: str, limit: int = 50, offset: int = 0):
    return get_memory_engine().get_messages(conversation_id, limit, offset)


# ── 向量搜索 ────────────────────────────────────────────

@app.post("/search")
async def search_messages(request: SearchRequest):
    return get_memory_engine().search_messages(request.query, request.project_id, request.top_k)


# ── 记忆管理 ────────────────────────────────────────────

@app.get("/projects/{project_id}/memories", response_model=List[Memory])
async def get_project_memories(project_id: str):
    return get_memory_engine().get_memories(project_id)

@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    if not get_memory_engine().delete_memory(memory_id):
        raise HTTPException(404, "Memory not found")
    return {"status": "deleted"}


# ── 助手管理 ────────────────────────────────────────────

@app.post("/agents", response_model=Agent)
async def register_agent(request: RegisterAgentRequest):
    return get_memory_engine().register_agent(
        request.name, request.description, request.capabilities, request.context_window
    )

@app.get("/agents", response_model=List[Agent])
async def list_agents():
    engine = get_memory_engine()
    return list(engine.agents.values())

@app.get("/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    agent = get_memory_engine().get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


# ── 助手会话管理 ────────────────────────────────────────

@app.post("/agent-sessions", response_model=AgentSession)
async def start_agent_session(request: StartAgentSessionRequest):
    try:
        return get_memory_engine().start_agent_session(
            request.agent_id, request.project_id, request.conversation_id
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.post("/agent-sessions/{session_id}/end")
async def end_agent_session(session_id: str, request: EndAgentSessionRequest = None):
    final = request.final_state if request else None
    session = get_memory_engine().end_agent_session(session_id, final)
    if not session:
        raise HTTPException(404, "Session not found")
    return {"status": "ended", "session": session}

@app.get("/agent-sessions")
async def list_agent_sessions(agent_id: Optional[str] = None, project_id: Optional[str] = None):
    return get_memory_engine().get_agent_sessions(agent_id, project_id)


# ── 连续性检测 ──────────────────────────────────────────

@app.get("/projects/{project_id}/continuity")
async def get_continuity(project_id: str):
    engine = get_memory_engine()
    if project_id not in engine.projects:
        raise HTTPException(404, "Project not found")
    return engine.detect_continuity(project_id)


# ── 上下文组装 ──────────────────────────────────────────

@app.post("/context/build")
async def build_context(request: BuildContextRequest):
    try:
        return get_memory_engine().build_context_for_agent(
            request.agent_id, request.project_id,
            request.conversation_id, request.max_messages,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


# ═══════════════════════════════════════════════════════════
# V1.0 新增端点 — 内核编排元认知
# ═══════════════════════════════════════════════════════════

@app.get("/kernel/stats")
async def kernel_stats():
    """v1.0 内核状态"""
    k = get_kernel()
    if not k._started:
        return {"status": "not_started"}
    return {
        "status": "running",
        "version": "1.5.15",
        "plugins": k.plugins.list_active(),
        "event_bus": k.bus.get_stats(),
    }

@app.post("/orchestrator/execute")
async def execute_intent(request: IntentRequest):
    """通过编排器执行意图"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")

    event = Event(
        type="orchestrator.execute",
        source="api",
        data={"intent": request.intent, "project_id": request.project_id},
    )
    event_id = await k.bus.publish(event)
    return {"event_id": event_id, "status": "accepted", "intent": request.intent}

@app.get("/metacognition/report")
async def metacognition_report():
    """元认知报告"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")

    plugin = k.plugins.get("metacognition")
    if not plugin:
        return {"status": "disabled"}

    report = plugin.generate_report()
    return report

@app.get("/v1/plugins")
async def list_plugins():
    """列出所有插件"""
    k = get_kernel()
    return k.plugins.list_all() if k._started else []

# ── 预测引擎 ────────────────────────────────────────────

@app.get("/predictor/report")
async def predictor_report():
    """预测引擎报告"""
    k = get_kernel()
    plugin = k.plugins.get("predictor") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.generate_report()

@app.post("/predictor/learn")
async def predictor_learn(task_type: str = "general", project_id: str = None):
    """手动喂数据给预测引擎学习"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")
    
    await k.bus.publish(Event(
        type="user.activity",
        source="api",
        data={"task_type": task_type, "project_id": project_id},
    ))
    return {"status": "learned", "task_type": task_type}

# ── 自主Agent循环 ───────────────────────────────────────
@app.get("/agent/status")
async def agent_status():
    """Agent循环状态"""
    k = get_kernel()
    plugin = k.plugins.get("agent_loop") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.generate_report()


@app.post("/agent/start")
async def agent_start():
    """启动自主Agent循环"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")
    plugin = k.plugins.get("agent_loop")
    if not plugin:
        raise HTTPException(404, "agent_loop plugin not loaded")
    await plugin.start_loop()
    return {"status": "started", "message": "Agent loop started"}


@app.post("/agent/stop")
async def agent_stop():
    """停止自主Agent循环"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")
    plugin = k.plugins.get("agent_loop")
    if not plugin:
        raise HTTPException(404, "agent_loop plugin not loaded")
    await plugin.stop_loop()
    return {"status": "stopped", "message": "Agent loop stopped"}


@app.post("/agent/message")
async def agent_message(content: str = ""):
    """发送消息给自主Agent (触发OODA循环)"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")
    
    if not content:
        raise HTTPException(400, "content required")
    
    await k.bus.publish(Event(
        type="user.message",
        source="api",
        data={"content": content},
    ))
    return {"status": "accepted", "message": content}

# ── 性能监控 ────────────────────────────────────────────

@app.get("/performance/report")
async def performance_report():
    """性能报告"""
    k = get_kernel()
    plugin = k.plugins.get("performance") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.generate_report()

# ── 配置热加载 / Key故障转移 / 记忆备份 ────────────────

@app.get("/v1/failover")
async def failover_status():
    """API Key 故障转移状态"""
    return _key_failover.status()

@app.get("/v1/backups")
async def list_backups():
    """记忆备份列表"""
    return {"backups": _memory_backup.list_backups()}

@app.post("/v1/backup")
async def create_backup(label: str = ""):
    """创建记忆备份"""
    engine = get_memory_engine()
    data = {
        "projects": {pid: p.model_dump() if hasattr(p,'model_dump') else str(p) for pid, p in engine.projects.items()},
        "conversations": {cid: c.model_dump() if hasattr(c,'model_dump') else str(c) for cid, c in engine.conversations.items()},
        "memories": {mid: m.model_dump() if hasattr(m,'model_dump') else str(m) for mid, m in engine.memories.items()},
    }
    path = _memory_backup.backup(data, label)
    return {"status": "ok", "path": path}

@app.post("/v1/restore")
async def restore_backup(name: str = ""):
    """恢复记忆备份"""
    data = _memory_backup.restore(name or None)
    if data is None:
        return {"status": "error", "message": "无可用备份"}
    return {"status": "ok", "keys": list(data.keys())}

@app.get("/v1/config/reload")
async def reload_config():
    """手动触发配置重载"""
    from src.config import load_config
    config = load_config()
    return {"status": "reloaded", "plugins": config.get("plugins", {}).get("builtin", [])}

# ── 自愈引擎 ────────────────────────────────────────────

@app.get("/healer/report")
async def healer_report():
    """自愈引擎报告"""
    k = get_kernel()
    plugin = k.plugins.get("healer") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.generate_report()

@app.post("/healer/heal/{plugin_name}")
async def healer_heal(plugin_name: str):
    """手动触发插件修复"""
    k = get_kernel()
    if not k._started:
        raise HTTPException(503, "Kernel not started")
    
    await k.bus.publish(Event(
        type="healer.heal",
        source="api",
        data={"plugin": plugin_name},
    ))
    return {"status": "healing", "plugin": plugin_name}

# ── WebSocket状态 ──────────────────────────────────────

@app.get("/ws/stats")
async def ws_stats():
    """WebSocket连接状态"""
    k = get_kernel()
    plugin = k.plugins.get("websocket") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.manager.stats()

# ── v1.5.6 系统资源 ──────────────────────────────────────

@app.get("/api/system/resources")
async def system_resources():
    """CPU/内存使用率"""
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "disk_percent": psutil.disk_usage("/").percent,
    }

# ── v1.5.6 基准测试 ──────────────────────────────────────

@app.post("/api/benchmark/run")
async def run_benchmark():
    """跑一次快速基准: 延迟、推理速度、token输出"""
    from src.model_registry import get_registry
    import time as _time
    reg = get_registry()
    current = os.environ.get("MESHCTX_MODEL", "")
    if not current and reg._entries:
        current = next(iter(reg._entries))
    if not current:
        return {"error": "没有配置的模型"}
    
    client = reg.get(current)
    if not client:
        return {"error": f"模型 {current} 未初始化"}
    
    results = {}
    test_messages = [{"role": "user", "content": "用一句话介绍meshctx"}]
    
    # 延迟测试
    t0 = _time.time()
    try:
        resp = client.chat.completions.create(model=client.model_name, messages=test_messages, max_tokens=50, temperature=0)
        elapsed = _time.time() - t0
        results["latency_ms"] = round(elapsed * 1000, 1)
        results["ttfb_ms"] = results["latency_ms"]  # 非流式近似
        results["output_tokens"] = resp.usage.completion_tokens if resp.usage else 0
        results["input_tokens"] = resp.usage.prompt_tokens if resp.usage else 0
        results["tokens_per_sec"] = round(results["output_tokens"] / elapsed, 1) if elapsed > 0 else 0
        results["model"] = current
        results["status"] = "ok"
        results["response_preview"] = resp.choices[0].message.content[:100] if resp.choices else ""
    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
        results["latency_ms"] = round((_time.time() - t0) * 1000, 1)
    
    return results

# ── v1.5.5 模型切换 API ─────────────────────────────────

@app.get("/api/models")
async def list_models():
    """列出所有可用模型 + 当前激活"""
    from src.model_registry import get_registry, BUILTIN_MODELS
    reg = get_registry()
    current = os.environ.get("MESHCTX_MODEL", "")
    if not current and reg._entries:
        current = next(iter(reg._entries))
    
    models = []
    for mid, info in BUILTIN_MODELS.items():
        configd = mid in reg._entries
        models.append({
            "id": mid,
            "provider": info["provider"],
            "model_name": info["model"],
            "configured": configd,
            "current": mid == current,
            "key_env": info["key_env"],
        })
    return {"models": models, "current": current, "default": current, "total": len(models), "configured": sum(1 for m in models if m["configured"])}

@app.post("/api/model/switch")
async def switch_model(request: Request):
    """切换当前模型"""
    from src.model_registry import get_registry
    body = await request.json()
    model_id = body.get("model_id", "")
    reg = get_registry()
    if model_id not in reg._entries:
        raise HTTPException(400, f"模型 {model_id} 未配置，请先 meshctx model add {model_id}")
    os.environ["MESHCTX_MODEL"] = model_id
    logger.info(f"模型已切换为: {model_id}")
    return {"status": "ok", "current": model_id}

# ── v1.5.0 系统总览摘要 (Desktop专属) ────────────────────

@app.get("/api/system/summary")
async def system_summary():
    """统一摘要端点: 内核+自愈+性能+Agent+预测 合并为一个富响应"""
    k = get_kernel()
    now = time.time()
    summary = {
        "version": "1.5.15",
        "uptime": int(now - (app.state.start_time if hasattr(app.state, 'start_time') else now)),
        "kernel": {"status": "running" if k._started else "stopped", "plugins": k.plugins.list_active() if k._started else []},
        "agents": {"total": 0, "active": 0, "sessions": 0, "list": [], "ooda": {}},
        "health": {"overall": "unknown", "plugins": {}, "recent_events": []},
        "performance": {"total_requests": 0, "avg_latency_ms": 0, "last_active": None},
        "predictor": {"patterns_learned": 0, "top_predictions": []},
        "metrics_history": _metrics.snapshot(),  # v1.5.2: 时间序列
    }
    
    # v1.5.6: 系统资源
    try:
        import psutil
        summary["resources"] = {
            "cpu": psutil.cpu_percent(interval=0.05),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        }
    except:
        summary["resources"] = {}
    
    if not k._started:
        return summary

    # Agent数据
    try:
        al = k.plugins.get("agent_loop")
        if al:
            rpt = al.generate_report()
            summary["agents"]["active"] = len(rpt.get("active_tasks", []))
            summary["agents"]["total"] = rpt.get("total_completed", 0)
            summary["agents"]["success_rate"] = rpt.get("success_rate", 0)
            summary["agents"]["recent_tasks"] = rpt.get("recent_tasks", [])[:10]
            summary["agents"]["ooda"] = {
                "status": rpt.get("status", "stopped"),
                "phase": rpt.get("current_phase", "idle"),
                "cycle_count": rpt.get("cycle_count", 0),
            }
    except:
        pass

    # 自愈数据
    try:
        healer = k.plugins.get("healer")
        if healer:
            hrpt = healer.generate_report()
            h = hrpt.get("health", {})
            summary["health"]["overall"] = h.get("overall", "unknown")
            summary["health"]["plugins"] = h.get("plugins", {})
            summary["health"]["recent_events"] = h.get("recent_events", [])[:15]
    except:
        pass

    # 性能数据
    try:
        perf = k.plugins.get("performance")
        if perf:
            prpt = perf.generate_report()
            summary["performance"]["total_requests"] = prpt.get("total_requests", 0)
            summary["performance"]["avg_latency_ms"] = prpt.get("avg_latency_ms", 0)
            summary["performance"]["last_active"] = prpt.get("last_active", None)
    except:
        pass

    # 预测数据
    try:
        pred = k.plugins.get("predictor")
        if pred:
            pr = pred.generate_report()
            summary["predictor"]["patterns_learned"] = pr.get("patterns_learned", 0)
            summary["predictor"]["accuracy"] = pr.get("accuracy", "N/A")
            summary["predictor"]["top_predictions"] = pr.get("current_predictions", [])[:5]
            summary["predictor"]["last_trained"] = pr.get("last_trained", None)
    except:
        pass

    # 模型统计
    try:
        from src.model_registry import get_registry
        reg = get_registry()
        models = reg.list_all()
        summary["models"] = {
            "total": len(models),
            "ready": sum(1 for m in models if m.get("ready")),
            "list": [{"id": m["id"], "ready": m.get("ready", False), "provider": m.get("provider", "?")} for m in models],
        }
    except:
        summary["models"] = {"total": 0, "ready": 0, "list": []}

    # v1.5.8: 系统健康评分 (0-100)
    hscore = 100
    h = summary.get("health", {})
    plugins = h.get("plugins", {})
    if plugins:
        weights = {"healthy": 1.0, "degraded": 0.5, "unstable": 0.2, "critical": 0.0, "unknown": 0.5}
        total_w = len(plugins)
        score = sum(weights.get(p.get("status", "unknown"), 0.5) for p in plugins.values()) / max(total_w, 1)
        hscore = round(score * 100)
    # 性能扣分
    res = summary.get("resources", {})
    if res.get("memory_percent", 0) > 80:
        hscore = max(0, hscore - 15)
    elif res.get("memory_percent", 0) > 60:
        hscore = max(0, hscore - 5)
    summary["health_score"] = hscore
    
    return summary


@app.get("/api/events/recent")
async def events_recent(limit: int = 30):
    """最近事件时间线"""
    k = get_kernel()
    if not k._started:
        return {"events": []}
    try:
        stats = k.bus.get_stats()
        return {"events": stats.get("recent_events", [])[-limit:], "total_events": stats.get("total_events", 0)}
    except:
        return {"events": []}


# ── Web Chat API ──────────────────────────────────────

@app.get("/api/models")
async def api_models():
    """返回可用模型列表"""
    from src.model_registry import get_registry
    from src.config import load_config
    try:
        reg = get_registry()
        cfg = load_config()
        default = cfg.get("models", {}).get("default", "deepseek:chat")
        return {
            "models": reg.list_all(),
            "default": default,
        }
    except:
        return {"models": [], "default": "deepseek:chat"}


@app.post("/api/chat")
async def api_chat(request: Request):
    """Web聊天API: 接收消息,调用AI,返回回复+工具执行"""
    from src.model_registry import get_registry
    from src.chat_tools import execute_tool, has_tool_call
    
    try:
        body = await request.json()
    except:
        return {"content": "无效请求", "tokens": 0}
    
    msgs = body.get("messages", [])
    if not msgs:
        # fallback: accept single 'message' field from web UI
        msg = body.get("message", "")
        if msg:
            msgs = [{"role": "user", "content": msg}]
    model_id = body.get("model")
    if not model_id:
        # 从配置读取默认模型，fallback到内置
        try:
            from src.config import load_config
            config = load_config()
            model_id = config.get("models", {}).get("default", "deepseek:chat")
        except:
            model_id = "deepseek:chat"
    
    if not msgs:
        return {"content": "请输入消息", "tokens": 0}
    
    try:
        reg = get_registry()
        client = reg.get(model_id) or reg.get(None)
        if not client:
            return {"content": "❌ 模型未配置。请访问 Setup 页面配置 API Key 后重试。", "tokens": 0}
        resp = client.chat(msgs)
    except Exception as e:
        return {"content": f"❌ 模型调用失败，请检查: 1) API Key是否正确 2) 网络连接 3) 模型名称。详情: " + str(e)[:100], "tokens": 0}
    content = resp.get("content", "")
    tokens = resp.get("tokens", 0)
    
    tool_result = None
    if has_tool_call(content):
        tool_result = execute_tool(content)
    
    return {
        "content": content,
        "tokens": tokens,
        "model": model_id,
        "tool_result": tool_result,
    }


@app.post("/api/chat/stream")
async def api_chat_stream(request: Request):
    """流式Chat API — SSE逐token推送"""
    from src.model_registry import get_registry
    from src.config import load_config
    import json as _json

    try:
        body = await request.json()
    except:
        return StreamingResponse(
            iter(["data: [错误] 无效请求\n\n"]),
            media_type="text/event-stream"
        )

    msgs = body.get("messages", [])
    if not msgs:
        msg = body.get("message", "")
        if msg:
            msgs = [{"role": "user", "content": msg}]

    if not msgs:
        return StreamingResponse(
            iter(["data: [请输入消息]\n\n"]),
            media_type="text/event-stream"
        )

    model_id = body.get("model")
    if not model_id:
        try:
            config = load_config()
            model_id = config.get("models", {}).get("default", "deepseek:chat")
        except:
            model_id = "deepseek:chat"

    async def generate():
        try:
            reg = get_registry()
            client = reg.get(model_id) or reg.get(None)
            if not client:
                yield f"data: {_json.dumps({'error': '模型未配置，请在Setup页面设置API Key'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            for token in client.chat_stream(msgs):
                yield f"data: {_json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# ── 内嵌终端 ──────────────────────────────────────

@app.post("/api/terminal")
async def api_terminal(request: Request):
    """执行终端命令"""
    import subprocess, asyncio
    try:
        body = await request.json()
        cmd = body.get("cmd","").strip()
        timeout = body.get("timeout", 30)
    except:
        return {"error": "无效请求", "output": ""}
    if not cmd:
        return {"error": "请输入命令", "output": ""}
    if any(d in cmd for d in ["rm -rf /","mkfs","dd if=","> /dev/sda"]):
        return {"error": "⚠️ 危险命令已拦截", "output": ""}
    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        out = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
        return {"output": out.strip() or "(无输出)", "exit_code": proc.returncode}
    except asyncio.TimeoutError:
        return {"error": f"超时({timeout}s)", "output": ""}
    except Exception as e:
        return {"error": str(e), "output": ""}

# ── 文件上传 API ──────────────────────────────────────

ALLOWED_EXTENSIONS = {
    ".txt", ".py", ".js", ".json", ".yaml", ".yml", ".md",
    ".csv", ".log", ".html", ".css", ".xml", ".toml",
    ".cfg", ".ini", ".sh", ".bat"
}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

@app.post("/api/chat/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件，读取文本内容返回"""
    import mimetypes

    # 检查扩展名
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"不支持的文件类型: {ext}。支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 读取内容并限制大小
    content_bytes = await file.read()
    if len(content_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            413,
            f"文件过大: {len(content_bytes)} bytes，最大 {MAX_UPLOAD_SIZE} bytes (5MB)"
        )

    # 尝试 UTF-8 解码，失败则用 latin-1
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1")

    mime_type, _ = mimetypes.guess_type(file.filename or "")
    file_type = mime_type or "text/plain"

    return {
        "filename": file.filename,
        "content": content,
        "size": len(content_bytes),
        "type": file_type,
    }

# ── 一键配置 API ────────────────────────────────────

@app.post("/api/setup")
async def api_setup(request: Request):
    """Web设置向导: 输入API Key,自动配置模型"""
    from src.model_registry import get_registry
    
    try:
        body = await request.json()
    except:
        return {"success": False, "error": "无效请求"}
    
    provider = body.get("provider", "deepseek")
    key = body.get("key", "").strip()
    
    if not key:
        return {"success": False, "error": "请输入API Key"}
    
    # 保存到环境
    env_map = {"deepseek":"DEEPSEEK_API_KEY","openai":"OPENAI_API_KEY","bailian":"BAILIAN_API_KEY"}
    env_var = env_map.get(provider, "DEEPSEEK_API_KEY")
    os.environ[env_var] = key
    
    # 写入bashrc
    bashrc = os.path.expanduser("~/.bashrc")
    with open(bashrc, "r") as f:
        lines = f.read()
    if env_var not in lines:
        with open(bashrc, "a") as f:
            f.write(f"\nexport {env_var}={key}\n")
    
    # 配置模型
    reg = get_registry()
    entries = reg.auto_configure()
    
    return {
        "success": True,
        "models": len([e for e in entries if e["ready"]]),
        "provider": provider,
    }

# ── Gateway Webhook (企业微信消息接收+回复) ──

import hashlib
import base64
import struct
import string
import random

# Lazy import — PyInstaller friendly
def _get_aes():
    try:
        from Crypto.Cipher import AES
        return AES
    except ImportError:
        return None

def _wechat_verify_signature(token: str, timestamp: str, nonce: str, 
                              encrypt_str: str = "") -> str:
    """企业微信签名验证"""
    params = sorted([token, timestamp, nonce, encrypt_str])
    return hashlib.sha1("".join(params).encode()).hexdigest()

def _wechat_decrypt(encrypted: str, encoding_aes_key: str) -> tuple:
    """解密企业微信消息, 返回 (明文, corp_id)"""
    key = base64.b64decode(encoding_aes_key + "=")
    cipher = _get_aes().new(key, _get_aes().MODE_CBC, key[:16])
    plain = cipher.decrypt(base64.b64decode(encrypted))
    # 去除 PKCS7 padding
    pad = plain[-1]
    content = plain[16:-pad]
    # 解析: 16字节随机 + 4字节msg_len + 消息 + corp_id
    msg_len = struct.unpack(">I", content[:4])[0]
    msg = content[4:4+msg_len].decode("utf-8")
    corp_id = content[4+msg_len:].decode("utf-8")
    return msg, corp_id

def _wechat_encrypt(text: str, encoding_aes_key: str, corp_id: str) -> str:
    """加密回复消息"""
    key = base64.b64decode(encoding_aes_key + "=")
    # 16字节随机 + 4字节msg_len + 消息 + corp_id
    rand_bytes = bytes(random.getrandbits(8) for _ in range(16))
    msg_bytes = text.encode("utf-8")
    msg_len = struct.pack(">I", len(msg_bytes))
    raw = rand_bytes + msg_len + msg_bytes + corp_id.encode("utf-8")
    # PKCS7 padding
    pad = 32 - len(raw) % 32
    raw += bytes([pad] * pad)
    cipher = _get_aes().new(key, _get_aes().MODE_CBC, key[:16])
    return base64.b64encode(cipher.encrypt(raw)).decode()

def _get_wechat_config() -> dict:
    """获取企业微信配置"""
    from pathlib import Path
    import yaml
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("gateway", {}).get("wechat", {})
    return {}

@app.api_route("/gateway/wechat", methods=["GET", "POST"])
async def gateway_wechat(request: Request):
    """企业微信回调: 完整验签+解密+加密回复"""
    from urllib.parse import parse_qs
    import xml.etree.ElementTree as ET
    
    cfg = _get_wechat_config()
    token = cfg.get("token", "")
    aes_key = cfg.get("encoding_aes_key", "")
    corp_id = cfg.get("corp_id", "")
    
    params = parse_qs(str(request.url.query))
    msg_sig = params.get("msg_signature", [""])[0]
    timestamp = params.get("timestamp", [""])[0]
    nonce = params.get("nonce", [""])[0]
    
    if request.method == "GET":
        # URL验证: 验签→解密echostr→返回纯文本
        echostr = params.get("echostr", [""])[0]
        if token and aes_key and echostr:
            sig = _wechat_verify_signature(token, timestamp, nonce, echostr)
            if sig == msg_sig:
                plain, _ = _wechat_decrypt(echostr, aes_key)
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(plain)
        return echostr
    
    # POST: 接收消息
    try:
        body = await request.body()
        root = ET.fromstring(body)
        encrypt_el = root.find("Encrypt")
        
        if encrypt_el is None:
            return "success"
        
        encrypted = encrypt_el.text or ""
        
        # 验签
        if token:
            sig = _wechat_verify_signature(token, timestamp, nonce, encrypted)
            if sig != msg_sig:
                return "signature error"
        
        # 解密
        if aes_key:
            msg_xml, _ = _wechat_decrypt(encrypted, aes_key)
            msg_root = ET.fromstring(msg_xml)
        else:
            msg_root = root
        
        content_el = msg_root.find("Content")
        from_user = msg_root.find("FromUserName")
        to_user = msg_root.find("ToUserName")
        
        if content_el is None or from_user is None:
            return "success"
        
        msg_text = content_el.text or ""
        user_id = from_user.text or ""
        to_id = to_user.text if to_user is not None else ""
        
        # AI回复
        reply_text = await _get_ai_reply(msg_text)
        
        # 构建XML响应
        import time as _time
        reply_xml = f"""<xml>
<ToUserName><![CDATA[{user_id}]]></ToUserName>
<FromUserName><![CDATA[{to_id}]]></FromUserName>
<CreateTime>{int(_time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{reply_text}]]></Content>
</xml>"""
        
        # 加密回复
        if aes_key:
            enc_reply = _wechat_encrypt(reply_xml, aes_key, corp_id)
            ts = str(int(_time.time()))
            nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            sig = _wechat_verify_signature(token, ts, nonce_str, enc_reply)
            
            return f"""<xml>
<Encrypt><![CDATA[{enc_reply}]]></Encrypt>
<MsgSignature><![CDATA[{sig}]]></MsgSignature>
<TimeStamp>{ts}</TimeStamp>
<Nonce><![CDATA[{nonce_str}]]></Nonce>
</xml>"""
        
        return reply_xml
        
    except Exception as e:
        logger.error(f"企业微信处理失败: {e}")
        return "success"

async def _get_ai_reply(text: str) -> str:
    """调用AI获取回复"""
    try:
        from .model_registry import get_registry
        reg = get_registry()
        client = reg.get("deepseek:v4-flash") or reg.get(None)
        if client:
            resp = client.chat([
                {"role": "system", "content": "你是meshctx助手。简洁回复，中文优先，200字以内。"},
                {"role": "user", "content": text},
            ])
            return resp.get("content", "收到")[:500]
    except Exception as e:
        logger.error(f"AI回复失败: {e}")
    return "收到你的消息，正在处理中..."


# ═══════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    engine = get_memory_engine()
    k = get_kernel()

    result = {
        "status": "healthy",
        "version": "1.4.0",
        "kernel": "running" if (k._started if hasattr(k, '_started') else False) else "standalone",
        "projects_count": len(engine.projects),
        "conversations_count": len(engine.conversations),
        "memories_count": len(engine.memories),
        "agents_count": len(engine.agents),
        "sessions_count": len(engine.agent_sessions),
        "v1_plugins": k.plugins.list_active() if hasattr(k, 'plugins') else [],
    }

    # 添加 v1.0 记忆系统状态
    if hasattr(k, 'plugins'):
        mem_plugin = k.plugins.get("memory")
        if mem_plugin and hasattr(mem_plugin, 'store'):
            store = mem_plugin.store
            result["v1_memory"] = {
                "total_items": sum(len(s) for s in store._stores.values()),
                "vector_count": store.vector_index.count(),
                "kg_entities": store.knowledge_graph.get_stats()["entities"],
                "kg_relations": store.knowledge_graph.get_stats()["relations"],
            }

    return result


# ═══════════════════════════════════════════════════════════
# 生命周期事件 (在模块级别注册)
# ═══════════════════════════════════════════════════════════

@app.on_event("startup")
async def on_startup():
    """启动 v1.0 内核 + 挂载到 app.state"""
    global _kernel, _memory_engine

    logger.info("═══════════════════════════════════════════")
    logger.info("  meshctx v1.0 启动中...")
    logger.info("═══════════════════════════════════════════")

    _kernel = Kernel()

    # 加载核心插件
    logger.info("加载核心插件...")
    _kernel.plugins.register(MemoryPlugin())
    _kernel.plugins.register(MetaCognitionPlugin())
    _kernel.plugins.register(OrchestratorPlugin())
    _kernel.plugins.register(PredictorPlugin())
    _kernel.plugins.register(AgentLoopPlugin())
    _kernel.plugins.register(PerformancePlugin())
    _kernel.plugins.register(HealerPlugin())
    
    # Gateway插件
    gw_plugin = GatewayPlugin()
    _kernel.plugins.register(gw_plugin)
    
    # WebSocket插件单独注册(需要app引用)
    ws_plugin = WebSocketPlugin()
    _kernel.plugins.register(ws_plugin)
    create_ws_routes(app, ws_plugin)

    # 启动内核
    config = load_config()
    worker_count = config.get("kernel", {}).get("worker_count", 4)
    await _kernel.start(worker_count=worker_count)

    # 加载插件
    results = await _kernel.plugins.load_all()
    loaded = sum(1 for v in results.values() if v)
    logger.info(f"插件加载: {loaded}/{len(results)}")

    _memory_engine = MemoryEngine(use_llm=False, use_vector_store=False)

    # 挂载到 app.state
    app.state.kernel = _kernel
    app.state.memory_engine = _memory_engine

    logger.info(f"事件总线: {_kernel.bus.get_stats()['subscriptions']} 订阅")
    
    # 启动配置热加载 — 文件变更后自动重载模型注册表
    watcher = ConfigWatcher()
    def _reload_config():
        logger.info("配置已变更，自动重载模型...")
        try:
            from src.model_registry import get_registry
            import src.model_registry as mr
            mr._registry = None  # 清除缓存，下次请求重建
            reg = get_registry()
            available = reg.list_all()
            ready = [e["id"] for e in available if e["ready"]]
            logger.info(f"配置重载完成: {len(ready)}/{len(available)} 模型就绪")
        except Exception as e:
            logger.error(f"配置重载失败: {e}")
    watcher.on_change(_reload_config)
    watcher.start()
    
    logger.info("═══════════════════════════════════════════")
    logger.info("  meshctx v1.0 已就绪!")
    logger.info(f"  API: http://0.0.0.0:8000")
    logger.info(f"  Docs: http://0.0.0.0:8000/docs")
    logger.info(f"  Web UI: http://0.0.0.0:8000/ui")
    logger.info("═══════════════════════════════════════════")


@app.on_event("shutdown")
async def on_shutdown():
    """优雅关闭"""
    global _kernel  # noqa: F824
    if _kernel is not None:
        await _kernel.stop()
    logger.info("meshctx v1.0 已停止")


def main():
    """入口"""
    import uvicorn
    host = os.environ.get("MESHCTX_HOST", "0.0.0.0")
    port = int(os.environ.get("MESHCTX_PORT", "8000"))
    
    
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
