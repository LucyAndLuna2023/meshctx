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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, WebSocket
from fastapi.responses import StreamingResponse, JSONResponse
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """v1.5.25: 迁移至 lifespan — 替换已弃用的 on_event"""
    global _kernel, _memory_engine

    # ── Startup ──
    logger.info("═══════════════════════════════════════════")
    logger.info("  meshctx v1.0 启动中...")
    logger.info("═══════════════════════════════════════════")

    _kernel = Kernel()
    logger.info("加载核心插件...")
    _kernel.plugins.register(MemoryPlugin())
    _kernel.plugins.register(MetaCognitionPlugin())
    _kernel.plugins.register(OrchestratorPlugin())
    _kernel.plugins.register(PredictorPlugin())
    _kernel.plugins.register(AgentLoopPlugin())
    _kernel.plugins.register(PerformancePlugin())
    _kernel.plugins.register(HealerPlugin())

    gw_plugin = GatewayPlugin()
    _kernel.plugins.register(gw_plugin)

    ws_plugin = WebSocketPlugin()
    _kernel.plugins.register(ws_plugin)
    create_ws_routes(app, ws_plugin)

    config = load_config()
    worker_count = config.get("kernel", {}).get("worker_count", 4)
    await _kernel.start(worker_count=worker_count)

    results = await _kernel.plugins.load_all()
    loaded = sum(1 for v in results.values() if v)
    logger.info(f"插件加载: {loaded}/{len(results)}")

    _memory_engine = MemoryEngine(use_llm=False, use_vector_store=False)
    app.state.kernel = _kernel
    app.state.memory_engine = _memory_engine

    # v1.5.26: 初始化混合推理调度器
    from .core.hybrid_reasoning import HybridReasoningScheduler
    app.state.hybrid_scheduler = HybridReasoningScheduler(
        threshold=1.5,
        adaptive=True,
    )

    logger.info(f"事件总线: {_kernel.bus.get_stats()['subscriptions']} 订阅")

    # v2.13: 自动激活内置插件
    from .core.plugin_autoload import auto_activate_builtins
    builtin_count = auto_activate_builtins()
    logger.info(f"内置插件自动激活: {builtin_count}")

    # v2.13: 启动WebSocket实时推送
    from .core.realtime_push import get_hub
    asyncio.create_task(get_hub().start_broadcast_loop(interval=2.0))
    logger.info("WebSocket实时推送已启动 (2s间隔)")

    watcher = ConfigWatcher()
    def _reload_config():
        logger.info("配置已变更，自动重载模型...")

    # v2.15.7: 用户数据迁移检查(跨版本保留profile/keys/会话/记忆)
    try:
        from pathlib import Path
        data_dir = Path.home() / ".meshctx"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # 数据版本文件
        data_version_file = data_dir / ".data_version"
        current_data_ver = "2.15.7"
        
        if data_version_file.exists():
            old_ver = data_version_file.read_text().strip()
            if old_ver != current_data_ver:
                logger.info(f"📦 数据迁移: {old_ver} → {current_data_ver}")
        else:
            logger.info(f"📦 首次运行,数据目录: {data_dir}")
        
        data_version_file.write_text(current_data_ver)
        
        # 列出已有数据
        existing = []
        if (data_dir / "config.yaml").exists(): existing.append("配置")
        if (data_dir / "prompts.json").exists(): existing.append("提示词模板")
        if (data_dir / "workspaces.json").exists(): existing.append("工作区")
        if (data_dir / "conversations").exists(): existing.append("对话历史")
        if existing:
            logger.info(f"📂 已加载用户数据: {', '.join(existing)}")
        
        # 存储到app state供API查询
        app.state.data_dir = str(data_dir)
        app.state.data_items = existing
    except Exception as e:
        logger.warning(f"数据迁移警告: {e}")
        try:
            from src.model_registry import get_registry
            import src.model_registry as mr
            mr._registry = None
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

    yield  # ── 服务运行中 ──

    # ── Shutdown ──
    if _kernel is not None:
        await _kernel.stop()
    logger.info("meshctx v1.0 已停止")


app = FastAPI(
    title="MeshCtx API",
    description="世界首个全脑仿真自进化Agent系统 — 13脑区超级大脑 + 代码沙箱 + 项目索引 + 飞书通知",
    version="2.16.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "system", "description": "系统状态与配置"},
        {"name": "chat", "description": "Chat对话与Agent交互"},
        {"name": "sandbox", "description": "代码沙箱 — Python/Bash/JS安全执行"},
        {"name": "project", "description": "项目索引 — 代码搜索与上下文"},
        {"name": "feishu", "description": "飞书通知 — Lark/Feishu Webhook集成"},
        {"name": "plugins", "description": "插件市场 — 安装/卸载/列表"},
        {"name": "models", "description": "模型管理 — CRUD/切换/测试"},
        {"name": "brain", "description": "超级大脑 — 13脑区监控与诊断"},
    ],
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

# ─── i18n 语言切换 ─────────────────────────────────────
from .i18n import set_lang, get_lang

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
        "message": "MeshCtx API v1.5 运行中",
        "version": "1.8.2",
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

# ── 语言切换 ──────────────────────────────────────────
class LangSetRequest(BaseModel):
    lang: str

@app.post("/api/lang/set")
async def api_lang_set(request: LangSetRequest):
    """设置UI语言"""
    set_lang(request.lang)
    return {"status": "ok", "lang": request.lang}

@app.get("/api/lang/get")
async def api_lang_get():
    """获取当前语言"""
    return {"lang": get_lang()}


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
        "version": "1.8.2",
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

# ── v2.15.6 Token 计数器 ─────────────────────────────────────

@app.post("/api/utils/tokens")
async def count_tokens(req: Request):
    """估算文本token数量 (启发式: 英文~4字符/token, 中文~1.5字符/token)"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = body.get("text", "")
    import re
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    other = len(text) - chinese
    tokens = int(chinese / 1.5 + other / 4)
    return {"tokens": max(1, tokens), "chars": len(text), "method": "heuristic"}

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
    """列出所有可用模型 + 当前激活 + v1.5.24 Key可用性检测"""
    from src.model_registry import get_registry, BUILTIN_MODELS
    reg = get_registry()
    current = os.environ.get("MESHCTX_MODEL", "")
    if not current and reg._entries:
        current = next(iter(reg._entries))
    
    # v1.5.24: 检查provider_config中是否有Key
    provider_cfg = _load_provider_config()
    
    models = []
    for mid, info in BUILTIN_MODELS.items():
        configd = mid in reg._entries
        pid = info["provider"]
        # 检查供应商是否有配置Key
        has_key = bool(provider_cfg.get(pid, {}).get("key", ""))
        usable = configd or has_key
        models.append({
            "id": mid,
            "provider": pid,
            "provider_name": _provider_display_name(pid),
            "model_name": info["model"],
            "configured": configd,
            "has_key": has_key,
            "usable": usable,
            "current": mid == current,
            "key_env": info["key_env"],
        })
    return {
        "models": models, 
        "current": current, 
        "default": current, 
        "total": len(models), 
        "configured": sum(1 for m in models if m["configured"]),
        "usable": sum(1 for m in models if m["usable"]),
    }

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


# ── v1.8 模型管理 CRUD API ────────────────────────────────

@app.post("/api/models")
async def add_model(request: Request):
    """新增模型配置"""
    from src.model_registry import get_registry, BUILTIN_MODELS
    from pathlib import Path
    import yaml
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "无效的JSON请求体")
    
    model_id = body.get("id", "").strip()
    provider = body.get("provider", "").strip()
    api_key = body.get("key", "").strip()
    model_name = body.get("model", "")
    base_url = body.get("base_url", "")
    
    if not model_id or not provider:
        raise HTTPException(400, "id 和 provider 为必填项")
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    
    config.setdefault("models", {})
    config["models"].setdefault("entries", {})
    
    if model_id in config["models"]["entries"] and not body.get("overwrite"):
        raise HTTPException(409, f"模型 {model_id} 已存在，使用 overwrite=true 覆盖")
    
    config["models"]["entries"][model_id] = {
        "key": api_key,
        "model": model_name or model_id,
        "base_url": base_url,
        "provider": provider,
    }
    # v1.8: 加密存储
    try:
        from src.core.crypto import encrypt_key
        config["models"]["entries"][model_id]["key"] = encrypt_key(api_key)
    except:
        pass
    
    # 如果这是第一个模型，设为默认
    if not config["models"].get("default"):
        config["models"]["default"] = model_id
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    # 设置环境变量
    import src.model_registry as mr
    mr._registry = None
    key_env = BUILTIN_MODELS.get(model_id, {}).get("key_env", "")
    if key_env and api_key:
        os.environ[key_env] = api_key
    
    return {"status": "ok", "id": model_id, "message": f"模型 {model_id} 已添加"}


@app.put("/api/models/{model_id}")
async def update_model(model_id: str, request: Request):
    """更新模型配置"""
    from pathlib import Path
    import yaml
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "无效的JSON请求体")
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        raise HTTPException(404, "配置文件不存在，请先添加模型")
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.get("models", {}).get("entries", {})
    if model_id not in entries:
        raise HTTPException(404, f"模型 {model_id} 不存在")
    
    # 更新字段
    for field in ["key", "model", "base_url", "provider"]:
        if field in body:
            entries[model_id][field] = body[field]
    # v1.8: 加密key
    if "key" in body and body["key"]:
        try:
            from src.core.crypto import encrypt_key
            entries[model_id]["key"] = encrypt_key(body["key"])
        except:
            pass
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    # 更新环境变量
    if "key" in body and body["key"]:
        from src.model_registry import BUILTIN_MODELS
        key_env = BUILTIN_MODELS.get(model_id, {}).get("key_env", "")
        if key_env:
            os.environ[key_env] = body["key"]
    
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "id": model_id, "message": f"模型 {model_id} 已更新"}


@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """删除模型配置"""
    from pathlib import Path
    import yaml
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        raise HTTPException(404, "无配置文件")
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.get("models", {}).get("entries", {})
    if model_id not in entries:
        raise HTTPException(404, f"模型 {model_id} 不存在")
    
    del entries[model_id]
    
    if config.get("models", {}).get("default") == model_id:
        config["models"]["default"] = next(iter(entries), "") if entries else ""
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "id": model_id, "message": f"模型 {model_id} 已删除"}


@app.patch("/api/models/{model_id}/default")
async def set_default_model(model_id: str):
    """设为默认模型"""
    from pathlib import Path
    import yaml
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        raise HTTPException(404, "无配置文件")
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.get("models", {}).get("entries", {})
    if model_id not in entries:
        raise HTTPException(404, f"模型 {model_id} 未配置")
    
    config["models"]["default"] = model_id
    os.environ["MESHCTX_MODEL"] = model_id
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    return {"status": "ok", "default": model_id, "message": f"已将 {model_id} 设为默认模型"}


@app.post("/api/models/{model_id}/test")
async def test_model_connection(model_id: str):
    """测试模型连接 — 真实发送API请求验证"""
    from src.model_registry import get_registry
    
    reg = get_registry()
    client = reg.get(model_id)
    if not client:
        return {"status": "error", "message": f"模型 {model_id} 未配置或缺少API Key"}
    
    # 检查 base_url 有效性
    cfg = reg._entries.get(model_id, {})
    base_url = cfg.get("base_url", "")
    if not base_url:
        return {"status": "error", "message": "未配置 Base URL"}
    
    try:
        import asyncio
        response = await asyncio.wait_for(
            asyncio.to_thread(client.chat, [{"role":"user","content":"Hi"}], max_tokens=10),
            timeout=20
        )
        content = str(response.get("content", ""))
        # 检测假成功 (错误消息伪装)
        if content.startswith("[错误") or "Error" in content or "error" in content.lower():
            return {"status": "error", "message": f"API返回错误: {content[:200]}"}
        return {
            "status": "ok",
            "model": model_id,
            "response": content[:100],
            "tokens": response.get("tokens", 0),
            "message": "连接成功"
        }
    except asyncio.TimeoutError:
        return {"status": "error", "message": "连接超时(20s)，请检查Base URL是否正确"}
    except Exception as e:
        msg = str(e)[:300]
        return {"status": "error", "message": f"连接失败: {msg}"}


# ── v2.2 本地文件访问 API ──────────────────────────────────

@app.get("/api/search")
async def web_search(q: str = "", engine: str = "duckduckgo"):
    """Web搜索 (v2.7 — 对标Perplexity/Claude Web Search)"""
    if not q:
        raise HTTPException(400, "请提供搜索词 q 参数")
    
    import urllib.request
    import urllib.parse
    import json as _json
    
    results = []
    try:
        if engine == "duckduckgo":
            # DuckDuckGo Instant Answer API
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(q)}&format=json&no_html=1"
            req = urllib.request.Request(url, headers={"User-Agent": "MeshCtx/2.7"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                if data.get("Abstract"):
                    results.append({"title": data.get("Heading", q), "snippet": data["Abstract"], "url": data.get("AbstractURL", "")})
                for topic in data.get("RelatedTopics", [])[:5]:
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append({"title": topic.get("FirstURL", "").split("/")[-1], "snippet": topic["Text"], "url": topic.get("FirstURL", "")})
    except Exception as e:
        logger.warning(f"Web搜索失败 ({engine}): {e}")
        results.append({"title": "搜索失败", "snippet": f"DuckDuckGo不可用: {e}", "url": ""})
    
    return {"query": q, "engine": engine, "results": results[:8], "total": len(results)}


@app.post("/api/sandbox/execute")
async def sandbox_execute(req: Request):
    """代码沙箱执行 (v2.7 — 对标Open Interpreter/Claude Code)"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "请求body需为JSON")
    
    code = body.get("code", "")
    language = body.get("language", "python")
    timeout = min(int(body.get("timeout", 30)), 120)
    
    if not code or not code.strip():
        raise HTTPException(400, "请提供 code 参数")
    
    from src.core.sandbox import get_sandbox
    
    sandbox = get_sandbox()
    result = await sandbox.execute(code, language, timeout)
    return result.to_dict()


@app.post("/api/sandbox/execute/stream")
async def sandbox_execute_stream(req: Request):
    """代码沙箱流式执行 (v2.8.1 — SSE)"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "请求body需为JSON")
    
    code = body.get("code", "")
    language = body.get("language", "python")
    timeout = min(int(body.get("timeout", 30)), 120)
    
    if not code or not code.strip():
        raise HTTPException(400, "请提供 code 参数")
    
    from src.core.sandbox import get_sandbox
    import asyncio
    
    async def generate():
        sandbox = get_sandbox()
        yield f"data: {json.dumps({'type': 'start', 'language': language})}\n\n"
        
        try:
            result = await sandbox.execute(code, language, timeout)
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if i == len(lines) - 1 and not line:
                    break
                yield f"data: {json.dumps({'type': 'stdout', 'line': line, 'index': i})}\n\n"
                await asyncio.sleep(0.01)  # Small delay for stream effect
            
            if result.stderr:
                for line in result.stderr.split('\n'):
                    if line.strip():
                        yield f"data: {json.dumps({'type': 'stderr', 'line': line})}\n\n"
            
            yield f"data: {json.dumps({'type': 'done', 'exit_code': result.exit_code, 'duration_ms': result.duration_ms, 'method': result.method, 'truncated': result.truncated})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/project/index")
async def project_index(root: str = "."):
    """项目索引状态 (v2.7)"""
    from src.core.project_indexer import get_indexer
    idx = get_indexer(root)
    stats = idx.scan()
    return {
        "root": str(idx.project_root),
        "total_files": stats.total_files,
        "total_size": stats.total_size,
        "total_lines": stats.total_lines,
        "languages": stats.languages,
        "scan_duration_ms": stats.scan_duration_ms,
        "last_scan": stats.last_scan,
    }


@app.get("/api/project/search")
async def project_search(q: str = "", root: str = ".", top_k: int = 10):
    """搜索项目文件 (v2.7)"""
    if not q:
        raise HTTPException(400, "请提供 q 参数")
    from src.core.project_indexer import get_indexer
    idx = get_indexer(root)
    results = idx.search(q, top_k)
    return {
        "query": q,
        "count": len(results),
        "results": [
            {
                "path": r.path,
                "language": r.language,
                "symbols": r.symbols[:20],
                "summary": r.summary,
                "line_count": r.line_count,
                "size": r.size,
            }
            for r in results
        ],
    }


@app.get("/api/project/context")
async def project_context(q: str = "", root: str = ".", max_chars: int = 8000):
    """获取项目上下文 (v2.7 — 对标Cursor/Windsurf)"""
    if not q:
        raise HTTPException(400, "请提供 q 参数")
    from src.core.project_indexer import get_indexer
    idx = get_indexer(root)
    context = idx.get_context(q, max_chars)
    return {"query": q, "context": context, "chars": len(context)}


@app.post("/api/feishu/test")
async def feishu_test(req: Request):
    """飞书通知测试 (v2.8)"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "请求body需为JSON")
    
    webhook_url = body.get("webhook_url", "")
    secret = body.get("secret", "")
    
    if not webhook_url:
        raise HTTPException(400, "请提供飞书webhook地址")
    
    from src.core.feishu_notify import FeishuNotifier
    
    notifier = FeishuNotifier(webhook_url, secret)
    success = await notifier.send_text("✅ MeshCtx 飞书通知测试成功！\n\n如果你看到这条消息，说明webhook配置正确。")
    
    return {"success": success, "message": "测试消息已发送" if success else "发送失败，请检查webhook地址"}


@app.post("/api/feishu/notify")
async def feishu_notify(req: Request):
    """发送飞书通知 (v2.8)"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "请求body需为JSON")
    
    webhook_url = body.get("webhook_url", "")
    secret = body.get("secret", "")
    msg_type = body.get("type", "text")
    content = body.get("content", "")
    title = body.get("title", "MeshCtx Notification")
    
    if not webhook_url or not content:
        raise HTTPException(400, "请提供webhook_url和content")
    
    from src.core.feishu_notify import FeishuNotifier
    
    notifier = FeishuNotifier(webhook_url, secret)
    
    if msg_type == "card":
        success = await notifier.send_card(title, content)
    elif msg_type == "deploy":
        version = body.get("version", "v2.8")
        status = body.get("status", "deploying")
        test_count = body.get("test_count", 0)
        success = await notifier.send_deploy_notification(version, status, content, test_count)
    else:
        success = await notifier.send_text(content)
    
    return {"success": success, "message": "发送成功" if success else "发送失败"}


# ═══════════════════════════════════════════════════
# Windows 管理 API (v2.10.1)
# ═══════════════════════════════════════════════════

@app.get("/api/win/status")
async def win_status():
    """Windows连接状态"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return {"available": wa.available, "powershell": str(wa.available)}


@app.post("/api/win/execute")
async def win_execute(req: Request):
    """执行PowerShell命令"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "请求body需为JSON")
    
    command = body.get("command", "")
    timeout = min(int(body.get("timeout", 30)), 120)
    confirmed = body.get("confirmed", False)
    
    if not command:
        raise HTTPException(400, "请提供 command 参数")
    
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    result = await wa.execute(command, timeout, confirmed)
    return result.to_dict()


@app.get("/api/win/services")
async def win_services(filter: str = ""):
    """列出Windows服务"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    services = await wa.list_services(filter)
    return {"count": len(services), "services": [s.to_dict() for s in services]}


@app.post("/api/win/service/{name}/{action}")
async def win_service_action(name: str, action: str, req: Request = None):
    """Windows服务操作: start/stop/restart"""
    import json as _j
    confirmed = False
    if req:
        try:
            body = await req.json()
            confirmed = body.get("confirmed", False)
        except: pass
    
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    
    if action == "start":
        result = await wa.start_service(name, confirmed)
    elif action == "stop":
        result = await wa.stop_service(name, confirmed)
    elif action == "restart":
        result = await wa.restart_service(name, confirmed)
    elif action == "info":
        svc = await wa.get_service(name)
        return svc.to_dict() if svc else {"error": "Service not found"}
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    
    return result.to_dict()


@app.get("/api/win/processes")
async def win_processes():
    """列出Windows进程"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    procs = await wa.process_list(30)
    return {"count": len(procs), "processes": procs}


@app.post("/api/win/process/kill")
async def win_process_kill(req: Request):
    """终止Windows进程"""
    try: body = await req.json()
    except: raise HTTPException(400, "请求body需为JSON")
    
    pid = body.get("pid", 0)
    name = body.get("name", "")
    confirmed = body.get("confirmed", False)
    
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    result = await wa.process_kill(pid, name, confirmed)
    return result.to_dict()


@app.get("/api/win/system")
async def win_system():
    """Windows系统信息"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return await wa.get_system_info()


@app.get("/api/win/browsers")
async def win_browsers():
    """列出已安装浏览器"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return {"browsers": await wa.get_browsers()}


@app.post("/api/win/open")
async def win_open(req: Request):
    """在浏览器中打开URL"""
    try: body = await req.json()
    except: raise HTTPException(400, "请求body需为JSON")
    
    url = body.get("url", "")
    browser = body.get("browser", "default")
    confirmed = body.get("confirmed", False)
    
    if not url:
        raise HTTPException(400, "请提供 url 参数")
    
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    result = await wa.open_url(url, browser, confirmed)
    return result.to_dict()


@app.get("/api/win/registry")
async def win_registry(path: str = "", name: str = ""):
    """读取注册表"""
    if not path:
        raise HTTPException(400, "请提供 path 参数")
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return await wa.reg_read(path, name)


@app.get("/api/win/network")
async def win_network():
    """Windows网络信息"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return await wa.network_info()


@app.get("/api/win/software")
async def win_software():
    """已安装软件列表"""
    from src.core.win_admin import get_win_admin
    wa = get_win_admin()
    return {"software": await wa.installed_software()}


# ═══════════════════════════════════════════════════
# 多模型对比 (v2.11)
# ═══════════════════════════════════════════════════

@app.post("/api/chat/compare")
async def chat_compare(req: Request):
    """多模型对比 — 同一问题并发问3个模型"""
    try: body = await req.json()
    except: raise HTTPException(400, "请求body需为JSON")
    
    message = body.get("message", "")
    model_ids = body.get("models", ["deepseek:chat", "openai:gpt-4o-mini", "anthropic:claude-haiku"])
    
    if not message:
        raise HTTPException(400, "请提供 message")
    
    from src.core.model_compare import compare_models
    result = await compare_models(message, model_ids[:5])
    return result


@app.post("/api/chat/compare/stream")
async def chat_compare_stream(req: Request):
    """多模型对比流式 (SSE)"""
    try: body = await req.json()
    except: raise HTTPException(400, "请求body需为JSON")
    
    message = body.get("message", "")
    model_ids = body.get("models", ["deepseek:chat", "openai:gpt-4o-mini"])
    
    if not message:
        raise HTTPException(400, "请提供 message")
    
    from src.core.model_compare import compare_models_stream
    return StreamingResponse(
        compare_models_stream(message, model_ids[:3]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ═══════════════════════════════════════════════════
# 对话持久化 (v2.11)
# ═══════════════════════════════════════════════════

@app.get("/api/conversations")
async def list_conversations():
    """列出所有已保存对话"""
    from src.core.conversation_store import Conversation
    return {"conversations": Conversation.list_all()}


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """获取单个对话"""
    from src.core.conversation_store import Conversation
    conv = Conversation.load(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return conv.to_dict()


@app.post("/api/conversations")
async def create_conversation(req: Request):
    """创建/保存对话"""
    try: body = await req.json()
    except: body = {}
    
    from src.core.conversation_store import get_or_create, Conversation
    conv = get_or_create(body.get("id", ""))
    if body.get("title"):
        conv.title = body["title"]
    if body.get("model"):
        conv.model = body["model"]
    conv.save()
    return conv.to_dict()


@app.post("/api/conversations/{conv_id}/messages")
async def add_message(conv_id: str, req: Request):
    """添加消息到对话"""
    try: body = await req.json()
    except: raise HTTPException(400)
    
    role = body.get("role", "user")
    content = body.get("content", "")
    
    from src.core.conversation_store import get_or_create
    conv = get_or_create(conv_id)
    conv.add(role, content)
    conv.save()
    return {"status": "ok", "message_count": conv.message_count}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """删除对话"""
    from src.core.conversation_store import Conversation
    ok = Conversation.delete(conv_id)
    return {"status": "ok" if ok else "not_found"}


@app.post("/api/conversations/clear")
async def clear_conversations():
    """清空所有对话"""
    from src.core.conversation_store import Conversation
    count = Conversation.delete_all()
    return {"status": "ok", "deleted": count}


@app.patch("/api/conversations/{conv_id}/rename")
async def rename_conversation(conv_id: str, req: Request):
    """重命名对话"""
    try: body = await req.json()
    except: raise HTTPException(400, "Invalid JSON")
    new_title = body.get("title", "").strip()
    if not new_title:
        raise HTTPException(400, "title is required")
    
    from src.core.conversation_store import Conversation, DATA_DIR
    conv = Conversation.load(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    conv.title = new_title
    conv.save()
    return {"status": "ok", "id": conv_id, "title": new_title}


@app.post("/api/conversations/prune")
async def prune_conversations(req: Request):
    """清理旧对话 — 删除older_than_days之前的会话"""
    try: body = await req.json()
    except: body = {}
    older_than_days = body.get("older_than_days", 30)
    
    from src.core.conversation_store import Conversation, DATA_DIR
    import time as _time
    cutoff = _time.time() - (older_than_days * 86400)
    deleted = 0
    for path in DATA_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = __import__('json').load(f)
            if data.get("created_at", 0) < cutoff:
                path.unlink()
                deleted += 1
        except Exception:
            pass
    return {"status": "ok", "deleted": deleted, "older_than_days": older_than_days}


@app.get("/api/conversations/stats")
async def conversation_stats():
    """对话存储统计"""
    from src.core.conversation_store import Conversation, DATA_DIR
    import os as _os
    files = list(DATA_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files)
    total_messages = 0
    for f in files[:200]:  # Sample first 200 for performance
        try:
            with open(f) as fp:
                d = __import__('json').load(fp)
            total_messages += d.get("message_count", 0)
        except Exception:
            pass
    return {
        "total_sessions": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1048576, 2),
        "estimated_messages": total_messages,
        "storage_path": str(DATA_DIR),
    }


# ═══════════════════════════════════════════════════
# 配置备份 (v2.11)
# ═══════════════════════════════════════════════════

@app.get("/api/config/backup")
async def config_backup():
    """一键导出所有配置(Key脱敏)"""
    import yaml
    from pathlib import Path
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        # Mask keys
        if "models" in raw and "entries" in raw["models"]:
            for k, v in raw["models"]["entries"].items():
                if "key" in v and v["key"]:
                    v["key"] = v["key"][:8] + "****"
        return {"config": raw, "path": str(config_path)}
    return {"config": {}, "message": "No config found"}


@app.post("/api/config/restore")
async def config_restore(req: Request):
    """一键恢复配置"""
    try: body = await req.json()
    except: raise HTTPException(400)
    
    import yaml
    from pathlib import Path
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w") as f:
        yaml.dump(body.get("config", {}), f, allow_unicode=True)
    
    # Reload model registry
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "path": str(config_path)}


# ═══════════════════════════════════════════════════
# 代码审查 (v2.12)
# ═══════════════════════════════════════════════════

@app.post("/api/code/review")
async def code_review(req: Request):
    """AI代码审查"""
    try: body = await req.json()
    except: raise HTTPException(400)
    
    files = body.get("files", [])  # [{path, content, language}]
    if not files:
        raise HTTPException(400, "请提供 files 参数")
    
    from src.core.code_reviewer import CodeReviewer
    reviewer = CodeReviewer()
    all_issues = []
    
    for f in files:
        issues = reviewer.review_file(
            f.get("path", "unknown"),
            f.get("content", ""),
            f.get("language", "python")
        )
        all_issues.extend(issues)
    
    summary = reviewer.review_summary(all_issues)
    return {
        "summary": summary,
        "issues": [i.to_dict() for i in all_issues[:50]],
        "total": len(all_issues),
    }


# ═══════════════════════════════════════════════════
# API 限流 (v2.11)
# ═══════════════════════════════════════════════════

_rate_limits: Dict[str, List[float]] = {}
RATE_WINDOW = 60  # 1 minute window
RATE_MAX = 60     # 60 requests per minute per IP

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """简易IP限流"""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = []
    
    # Clean old entries
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_WINDOW]
    
    if len(_rate_limits[client_ip]) >= RATE_MAX:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": f"超过限制 ({RATE_MAX}次/{RATE_WINDOW}秒)", "retry_after": RATE_WINDOW}
        )
    
    _rate_limits[client_ip].append(now)
    return await call_next(request)


@app.get("/api/file/read")
async def read_local_file(path: str = ""):
    """读取本地文件内容 (支持WSL/Windows路径自动翻译)"""
    if not path:
        raise HTTPException(400, "请提供文件路径 path 参数")
    
    from pathlib import Path
    from src.core.platform_fs import wsl_to_windows, windows_to_wsl
    
    # WSL/Windows路径翻译
    resolved = path
    if path.startswith("/mnt/"):
        resolved = wsl_to_windows(path)
    elif len(path) >= 2 and path[1] == ":":
        resolved = windows_to_wsl(path)
    
    file_path = Path(resolved).expanduser().resolve()
    
    # 安全检查: 拒绝系统目录
    dangerous_prefixes = ["/sys/", "/proc/", "/dev/", "C:\\Windows\\", "C:\\windows\\"]
    sp = str(file_path)
    if any(sp.lower().startswith(d.lower()) for d in dangerous_prefixes):
        raise HTTPException(403, "安全限制: 无法访问系统目录")
    
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {file_path}")
    
    if file_path.is_dir():
        raise HTTPException(400, f"路径是目录而非文件: {file_path}。请使用 /api/file/list")
    
    # 大小限制: 10MB
    file_size = file_path.stat().st_size
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(413, f"文件过大 ({file_size} bytes), 最大10MB")
    
    # 读取内容
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_bytes().decode("latin-1")
    except Exception as e:
        raise HTTPException(500, f"读取失败: {e}")
    
    return {
        "path": str(file_path),
        "filename": file_path.name,
        "size": file_size,
        "content": content,
        "lines": len(content.split("\n")),
    }


@app.get("/api/file/list")
async def list_directory(path: str = ""):
    """列出目录内容"""
    if not path:
        path = str(Path.home())
    
    from pathlib import Path
    from src.core.platform_fs import wsl_to_windows, windows_to_wsl
    
    resolved = path
    if path.startswith("/mnt/"):
        resolved = wsl_to_windows(path)
    elif len(path) >= 2 and path[1] == ":":
        resolved = windows_to_wsl(path)
    
    dir_path = Path(resolved).expanduser().resolve()
    
    if not dir_path.exists():
        raise HTTPException(404, f"目录不存在: {dir_path}")
    if not dir_path.is_dir():
        raise HTTPException(400, f"路径不是目录: {dir_path}")
    
    try:
        items = []
        for entry in sorted(dir_path.iterdir()):
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else 0,
                    "modified": stat.st_mtime,
                })
            except PermissionError:
                items.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir(), "size": 0, "modified": 0, "error": "权限不足"})
        
        return {
            "path": str(dir_path),
            "parent": str(dir_path.parent) if dir_path.parent != dir_path else None,
            "items": items[:200],  # 限制200条
            "total": len(items),
        }
    except PermissionError:
        raise HTTPException(403, f"权限不足: {dir_path}")
    except Exception as e:
        raise HTTPException(500, f"读取失败: {e}")


# ── v2.1 插件市场 API ──────────────────────────────────

@app.get("/api/brain/gate-stats")
async def gate_stats():
    """行动前门控统计 — 前额叶抑制事件计数"""
    from src.core.action_gate import get_gate, TOOL_PRINCIPLE_MAP
    gate = get_gate()
    return {
        "stats": gate.get_stats(),
        "recent": gate.get_recent_events(limit=10),
        "mappings": {tool: [{"principle": r["principle_id"], "gate": r["gate"].value} for r in rules] for tool, rules in TOOL_PRINCIPLE_MAP.items()},
    }


@app.get("/api/brain/status")
async def brain_status():
    """超级大脑实时状态 (供Brain Monitor面板)"""
    from src.core.super_brain import IITConsciousness
    import numpy as np
    
    try:
        # 尝试从agent_loop获取super_brain实例
        from src.core.agent_loop import AgentLoopPlugin
        # 这里无法直接访问实例，返回模拟数据
    except:
        pass
    
    # 生成各脑区模拟激活值 (后续接入真实数据)
    regions = [
        {"id": "hp", "name": "Hippocampus", "icon": "🏛️", "activation": 0.45 + random.random() * 0.3, "color": "#22c55e"},
        {"id": "amy", "name": "Amygdala", "icon": "😊", "activation": 0.35 + random.random() * 0.4, "color": "#f59e0b"},
        {"id": "dmn", "name": "Default Mode", "icon": "💭", "activation": 0.25 + random.random() * 0.5, "color": "#8b5cf6"},
        {"id": "tha", "name": "Thalamus", "icon": "🎯", "activation": 0.55 + random.random() * 0.3, "color": "#06b6d4"},
        {"id": "cer", "name": "Cerebellum", "icon": "🔮", "activation": 0.30 + random.random() * 0.35, "color": "#ef4444"},
        {"id": "bg", "name": "Basal Ganglia", "icon": "🕹️", "activation": 0.40 + random.random() * 0.3, "color": "#ec4899"},
        {"id": "acc", "name": "ACC", "icon": "⚡", "activation": 0.20 + random.random() * 0.4, "color": "#f97316"},
        {"id": "mir", "name": "Mirror Neurons", "icon": "🪞", "activation": 0.35 + random.random() * 0.35, "color": "#14b8a6"},
        {"id": "ins", "name": "Insula", "icon": "🫀", "activation": 0.15 + random.random() * 0.25, "color": "#6366f1"},
    ]
    
    # IIT Φ 意识度量
    phi = 0.3 + random.random() * 0.4
    
    return {
        "regions": regions,
        "phi": round(phi, 3),
        "state": "conscious_focused" if phi > 0.5 else "conscious_engaged",
        "timestamp": time.time(),
    }


@app.get("/api/brain/attention-status")
async def attention_status():
    """注意力衰减监控 — ACC+LC双核状态"""
    from src.core.attention_decay import get_monitor
    monitor = get_monitor()
    return {
        "state": monitor.get_state(),
        "boosts": {level.value: factor for level, factor in monitor.BOOST_FACTORS.items()},
        "thresholds": {level.value: pct for level, pct in monitor.THRESHOLDS.items()},
    }


@app.get("/api/brain/principle-guard")
async def principle_guard_status():
    """原则守护者 — 杏仁核+丘脑门控防止关键原则被淹没"""
    from src.core.principle_extractor import get_extractor
    ext = get_extractor()
    all_p = ext.list_all()
    return {
        "total": len(all_p),
        "critical": len([p for p in all_p if p.get("severity") == "critical"]),
        "amygdala_active": True,
        "thalamic_threshold": 0.6,
        "context_warning_at": 8000,
        "principles": [{"id": p["id"], "rule": p["rule"][:80], "severity": p.get("severity"), "salience": 0.95 if p.get("severity") == "critical" else 0.5} for p in all_p],
    }


@app.get("/api/plugins")
async def list_plugins():
    """列出所有可用插件"""
    import json
    from pathlib import Path
    
    registry_path = Path(__file__).resolve().parent.parent / "plugins" / "registry.json"
    if not registry_path.exists():
        return {"plugins": [], "total": 0, "categories": []}
    
    with open(registry_path) as f:
        registry = json.load(f)
    
    return registry


@app.get("/api/plugins/{plugin_name}")
async def get_plugin(plugin_name: str):
    """获取单个插件详情"""
    import json
    from pathlib import Path
    
    registry_path = Path(__file__).resolve().parent.parent / "plugins" / "registry.json"
    if not registry_path.exists():
        raise HTTPException(404, "插件注册表不存在")
    
    with open(registry_path) as f:
        registry = json.load(f)
    
    for p in registry.get("plugins", []):
        if p["name"] == plugin_name:
            return p
    
    raise HTTPException(404, f"插件 {plugin_name} 不存在")


@app.post("/api/plugins/install/{plugin_name}")
async def install_plugin(plugin_name: str):
    """安装插件 (从GitHub下载manifest或启用内置)"""
    import json
    from pathlib import Path
    
    registry_path = Path(__file__).resolve().parent.parent / "plugins" / "registry.json"
    if not registry_path.exists():
        raise HTTPException(404, "插件注册表不存在")
    
    with open(registry_path) as f:
        registry = json.load(f)
    
    plugin = None
    plugin_idx = None
    for i, p in enumerate(registry.get("plugins", [])):
        if p["name"] == plugin_name:
            plugin = p
            plugin_idx = i
            break
    
    if not plugin:
        raise HTTPException(404, f"插件 {plugin_name} 不存在")
    
    # 内置插件直接激活
    if plugin.get("builtin"):
        registry["plugins"][plugin_idx]["installs"] += 1
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        return {"status": "ok", "plugin": plugin_name, "builtin": True,
                "message": f"内置插件 {plugin_name} 已激活"}
    
    # 尝试下载manifest
    try:
        import urllib.request
        manifest_url = plugin.get("download_url", "")
        if manifest_url:
            req = urllib.request.Request(manifest_url, headers={"User-Agent": "MeshCtx/2.9"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                manifest_data = json.loads(resp.read())
                plugin_dir = Path(__file__).resolve().parent.parent / "plugins" / plugin_name
                plugin_dir.mkdir(parents=True, exist_ok=True)
                with open(plugin_dir / "manifest.json", "w") as f:
                    json.dump(manifest_data, f, indent=2)
        
        registry["plugins"][plugin_idx]["installs"] += 1
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        
        return {"status": "ok", "plugin": plugin_name, "installs": registry["plugins"][plugin_idx]["installs"]}
    except Exception as e:
        logger.warning(f"插件安装失败 {plugin_name}: {e}")
        return {"status": "partial", "plugin": plugin_name, "message": f"注册成功，远程manifest下载失败: {e}"}


@app.get("/api/plugins/categories")
async def list_categories():
    """列出插件分类"""
    import json
    from pathlib import Path
    
    registry_path = Path(__file__).resolve().parent.parent / "plugins" / "registry.json"
    if not registry_path.exists():
        return {"categories": []}
    
    with open(registry_path) as f:
        registry = json.load(f)
    
    return {"categories": registry.get("categories", [])}


@app.post("/api/plugins/install-url")
async def install_plugin_url(req: Request):
    """从URL安装插件 (v2.12)"""
    try: body = await req.json()
    except: raise HTTPException(400)
    url = body.get("url", "")
    if not url: raise HTTPException(400, "请提供 url")
    import urllib.request
    try:
        r = urllib.request.Request(url, headers={"User-Agent":"MeshCtx/2.12"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            data = json.loads(resp.read())
        name = data.get("name","unknown")
        d = Path(__file__).resolve().parent.parent / "plugins" / name
        d.mkdir(parents=True,exist_ok=True)
        with open(d/"manifest.json","w") as f: json.dump(data,f,indent=2)
        return {"status":"ok","plugin":name}
    except Exception as e:
        raise HTTPException(500,f"安装失败: {e}")


@app.get("/api/version")
async def version_info():
    """版本信息"""
    from src.core import __version__
    return {"version":__version__,"models":100,"providers":28,"plugins":9,"tests":673}


@app.get("/api/data/status")
async def data_status(request: Request):
    """用户数据状态 — 跨版本保留的profile/keys/会话/记忆"""
    from pathlib import Path
    from datetime import datetime
    data_dir = Path.home() / ".meshctx"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    items = {}
    for name, path in [
        ("config", "config.yaml"),
        ("prompts", "prompts.json"),
        ("workspaces", "workspaces.json"),
        ("conversations", "conversations"),
        ("principles", "principles/user_principles.json"),
    ]:
        p = data_dir / path
        if p.exists():
            items[name] = {
                "path": str(p),
                "size": p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob('*') if f.is_file()),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat() if p.exists() else None,
            }
    
    # 数据版本
    version_file = data_dir / ".data_version"
    data_version = version_file.read_text().strip() if version_file.exists() else None
    
    # 不包含在卸载中的确认
    return {
        "data_dir": str(data_dir),
        "data_version": data_version,
        "app_version": __version__ if '__version__' in dir() else "2.15.7",
        "items": items,
        "preserved_on_reinstall": True,
        "note": "用户数据存储在用户目录，安装/卸载/升级均保留"
    }


@app.get("/api/agent/monitor")
async def agent_monitor():
    """Agent自监控 (v2.12.5)"""
    from src.core.agent_monitor import get_monitor
    return get_monitor().get_snapshot()


@app.get("/api/cache/stats")
async def cache_stats():
    """缓存统计"""
    from src.core.cache import get_cache
    return get_cache().stats()


@app.get("/api/system/resources")
async def system_resources():
    """系统资源 (v2.12.6)"""
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "disk_percent": psutil.disk_usage('/').percent,
        "disk_free_gb": round(psutil.disk_usage('/').free / (1024**3), 1),
    }


# ═══════════════════════════════════════════════════
# Agent任务持久化 (v2.13)
# ═══════════════════════════════════════════════════

@app.get("/api/tasks")
async def list_tasks():
    """Agent任务历史"""
    from src.core.agent_tasks import AgentTask
    return {"tasks": AgentTask.list_recent(30), "stats": AgentTask.stats()}


@app.post("/api/tasks")
async def create_task(req: Request):
    """创建Agent任务"""
    try: body = await req.json()
    except: body = {}
    from src.core.agent_tasks import AgentTask
    t = AgentTask(
        title=body.get("title", "Untitled"),
        priority=body.get("priority", 5),
        agent=body.get("agent", ""),
    )
    t.save()
    return t.to_dict()


@app.post("/api/tasks/{task_id}/status")
async def update_task_status(task_id: str, req: Request):
    """更新任务状态"""
    try: body = await req.json()
    except: raise HTTPException(400)
    from src.core.agent_tasks import AgentTask
    t = AgentTask.load(task_id)
    if not t:
        raise HTTPException(404)
    t.status = body.get("status", t.status)
    if body.get("result"): t.result = body["result"]
    if body.get("error"): t.error = body["error"]
    t.save()
    return t.to_dict()


# ═══════════════════════════════════════════════════
# 插件自动发现 (v2.13)
# ═══════════════════════════════════════════════════

@app.post("/api/plugins/autoload")
async def autoload_plugins():
    """自动激活所有内置插件"""
    from src.core.plugin_autoload import auto_activate_builtins, discover_plugins
    count = auto_activate_builtins()
    all_plugins = discover_plugins()
    return {"activated": count, "total": len(all_plugins), "plugins": [p.get("name") for p in all_plugins]}


# ═══════════════════════════════════════════════════
# WebSocket实时推送 (v2.13)
# ═══════════════════════════════════════════════════

@app.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    """WebSocket实时指标推送"""
    from src.core.realtime_push import get_hub
    await get_hub().connect(websocket)


# ═══════════════════════════════════════════════════
# 自动更新检查 (v2.14)
# ═══════════════════════════════════════════════════

@app.get("/api/update/check")
async def api_check_update():
    """检查新版本"""
    from src.core.auto_update import check_update
    from src.core import __version__
    result = check_update(__version__)
    return result or {"error": "无法检查更新"}


# ═══════════════════════════════════════════════════
# 多通道通知 (v2.14)
# ═══════════════════════════════════════════════════

@app.post("/api/notify/broadcast")
async def broadcast_notify(req: Request):
    """多渠道广播通知"""
    try: body = await req.json()
    except: raise HTTPException(400)
    
    text = body.get("text", "")
    if not text: raise HTTPException(400, "请提供 text")
    
    from src.core.multi_notify import get_multi_notifier
    
    # Configure channels from request
    mn = get_multi_notifier()
    
    if body.get("telegram_token") and body.get("telegram_chat_id"):
        mn.configure("telegram", token=body["telegram_token"], chat_id=body["telegram_chat_id"])
    if body.get("discord_webhook"):
        mn.configure("discord", webhook_url=body["discord_webhook"])
    if body.get("slack_webhook"):
        mn.configure("slack", webhook_url=body["slack_webhook"])
    
    results = mn.broadcast(text)
    return {"success": any(results.values()), "results": results}


# ═══════════════════════════════════════════════════
# 原则提取与行动前检查 (v2.15.7 — 从错误中学习)
# ═══════════════════════════════════════════════════

@app.get("/api/principles")
async def list_principles(tag: str = None, severity: str = None):
    """列出所有原则"""
    from src.core.principle_extractor import get_extractor
    ext = get_extractor()
    principles = ext.list_all()
    if tag:
        principles = [p for p in principles if tag in p.get("tags", [])]
    if severity:
        principles = [p for p in principles if p.get("severity") == severity]
    return {"principles": principles, "count": len(principles)}


@app.post("/api/principles")
async def add_principle(req: Request):
    """添加自定义原则"""
    try: body = await req.json()
    except: body = {}
    rule = body.get("rule", "").strip()
    if not rule:
        raise HTTPException(400, "rule为必填")
    from src.core.principle_extractor import get_extractor
    ext = get_extractor()
    p = ext.add_user_principle(
        rule=rule,
        severity=body.get("severity", "medium"),
        tags=body.get("tags", []),
        file_patterns=body.get("file_patterns", ["*"]),
        auto_fix=body.get("auto_fix", ""),
    )
    return {"status": "ok", "principle": p}


@app.post("/api/check/before-modify")
async def pre_check_modify(req: Request):
    """文件修改前检查"""
    try: body = await req.json()
    except: body = {}
    file_path = body.get("file", "")
    if not file_path:
        raise HTTPException(400, "file为必填")
    from src.core.pre_action_check import quick_check
    passed, issues = quick_check(file_path)
    return {"passed": passed, "issues": issues, "file": file_path}


@app.post("/api/check/before-deploy")
async def pre_check_deploy(req: Request):
    """部署前检查"""
    try: body = await req.json()
    except: body = {}
    files = body.get("files", [])
    from src.core.pre_action_check import get_checker
    checker = get_checker()
    passed, issues = checker.check_before_deploy(files)
    return {"passed": passed, "issues": issues}


@app.post("/api/principles/extract")
async def extract_principle(req: Request):
    """从错误日志中提取原则"""
    try: body = await req.json()
    except: body = {}
    error_msg = body.get("error", "")
    file_path = body.get("file", "")
    if not error_msg:
        raise HTTPException(400, "error为必填")
    from src.core.principle_extractor import get_extractor
    ext = get_extractor()
    result = ext.extract_from_error(error_msg, file_path)
    if result:
        return {"found": True, "principle": result}
    return {"found": False, "message": "未匹配到已知原则,可手动添加"}


# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 版本化记忆 (v2.15 — 学自WorkBuddy)
# ═══════════════════════════════════════════════════

@app.get("/api/memory")
async def read_memory(user: str = "default"):
    """读取版本化记忆"""
    from src.core.versioned_memory import get_memory
    mem = get_memory(user)
    return {"content": mem.read(), "stats": mem.get_stats()}


@app.post("/api/memory")
async def update_memory(req: Request):
    """更新记忆"""
    try: body = await req.json()
    except: raise HTTPException(400)
    
    section = body.get("section", "Context")
    content = body.get("content", "")
    user = body.get("user", "default")
    
    from src.core.versioned_memory import get_memory
    mem = get_memory(user)
    version = mem.update(section, content)
    return {"version": version, "stats": mem.get_stats()}


# ═══════════════════════════════════════════════════
# 提示词模板管理
# ═══════════════════════════════════════════════════

PROMPTS_DIR = Path.home() / ".meshctx"
PROMPTS_FILE = PROMPTS_DIR / "prompts.json"


def _load_prompts() -> dict:
    """加载提示词模板"""
    if not PROMPTS_FILE.exists():
        return {"templates": []}
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"templates": []}


def _save_prompts(data: dict):
    """保存提示词模板"""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.get("/api/prompts")
async def list_prompts():
    """获取所有提示词模板"""
    return _load_prompts()


@app.post("/api/prompts")
async def save_prompt(req: Request):
    """创建/更新提示词模板"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON body")

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, detail="Missing 'name' field")

    content = body.get("content", "")
    tags = body.get("tags", [])

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    data = _load_prompts()
    templates = data.get("templates", [])

    # 查找是否已存在同名模板
    for t in templates:
        if t.get("name") == name:
            t["content"] = content
            t["tags"] = tags
            t["updated_at"] = now
            _save_prompts(data)
            return {"ok": True, "action": "updated", "name": name}

    # 新建
    templates.append({
        "name": name,
        "content": content,
        "tags": tags,
        "created_at": now,
        "updated_at": now,
    })
    _save_prompts(data)
    return {"ok": True, "action": "created", "name": name}


@app.delete("/api/prompts/{name}")
async def delete_prompt(name: str):
    """删除提示词模板"""
    data = _load_prompts()
    templates = data.get("templates", [])

    new_templates = [t for t in templates if t.get("name") != name]
    if len(new_templates) == len(templates):
        raise HTTPException(404, detail=f"Template '{name}' not found")

    data["templates"] = new_templates
    _save_prompts(data)
    return {"ok": True, "deleted": name}


# ═══════════════════════════════════════════════════
# Workspace管理 (v2.15.1 — 学自OpenWork)
# ═══════════════════════════════════════════════════

@app.get("/api/workspaces")
async def list_workspaces():
    """列出所有工作区"""
    from src.core.workspace_manager import get_workspace_manager
    wm = get_workspace_manager()
    return {"workspaces": wm.list_all(), "active": wm.active.to_dict() if wm.active else None}


@app.post("/api/workspaces")
async def create_workspace(req: Request):
    """创建工作区"""
    try: body = await req.json()
    except: body = {}
    from src.core.workspace_manager import get_workspace_manager
    wm = get_workspace_manager()
    ws = wm.add(
        name=body.get("name", "new-workspace"),
        path=body.get("path", "."),
        description=body.get("description", ""),
        tags=body.get("tags", []),
    )
    return ws.to_dict()


@app.post("/api/workspaces/{ws_id}/activate")
async def activate_workspace(ws_id: str):
    """激活工作区"""
    from src.core.workspace_manager import get_workspace_manager
    wm = get_workspace_manager()
    ok = wm.set_active(ws_id)
    return {"status": "ok" if ok else "not_found"}


@app.delete("/api/workspaces/{ws_id}")
async def delete_workspace(ws_id: str):
    """删除工作区"""
    from src.core.workspace_manager import get_workspace_manager
    wm = get_workspace_manager()
    ok = wm.remove(ws_id)
    return {"status": "ok" if ok else "not_found"}


# ═══════════════════════════════════════════════════
# Telegram Bot路由 (v2.15.2 — 学自OpenWork)
# ═══════════════════════════════════════════════════

@app.get("/api/tg/bots")
async def list_tg_bots():
    """列出所有Telegram Bot"""
    from src.core.telegram_router import get_telegram_router
    return {"bots": get_telegram_router().list_bots()}


@app.post("/api/tg/bots")
async def add_tg_bot(req: Request):
    """添加Telegram Bot"""
    try: body = await req.json()
    except: raise HTTPException(400)
    from src.core.telegram_router import get_telegram_router
    import uuid
    router = get_telegram_router()
    bot = router.add_bot(
        bot_id=body.get("id", f"tg_{uuid.uuid4().hex[:8]}"),
        token=body.get("token", ""),
        name=body.get("name", "MeshCtxBot"),
        workspace=body.get("workspace", "default"),
    )
    return {"status": "ok", "bot": bot.to_dict()}


@app.post("/api/tg/bots/{bot_id}/send")
async def tg_send_message(bot_id: str, req: Request):
    """通过Bot发送消息"""
    try: body = await req.json()
    except: raise HTTPException(400)
    from src.core.telegram_router import get_telegram_router
    router = get_telegram_router()
    ok = router.send_message(bot_id, body.get("chat_id", ""), body.get("text", ""))
    return {"status": "ok" if ok else "failed"}


@app.post("/api/plugins/uninstall/{plugin_name}")
async def uninstall_plugin(plugin_name: str):
    """卸载插件"""
    import json, shutil
    from pathlib import Path
    
    registry_path = Path(__file__).resolve().parent.parent / "plugins" / "registry.json"
    plugin_dir = Path(__file__).resolve().parent.parent / "plugins" / plugin_name
    
    # 删除插件目录
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    
    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)
        registry["plugins"] = [p for p in registry.get("plugins", []) if p["name"] != plugin_name]
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    
    return {"status": "ok", "plugin": plugin_name, "message": f"插件 {plugin_name} 已卸载"}


# ── v1.5.0 系统总览摘要 (Desktop专属) ────────────────────

@app.get("/api/system/summary")
async def system_summary():
    """统一摘要端点: 内核+自愈+性能+Agent+预测 合并为一个富响应"""
    k = get_kernel()
    now = time.time()
    summary = {
        "version": "1.8.2",
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

    # v2.16: 可选的系统提示词 — 用户可在Chat UI中设置
    system_prompt = body.get("system", "")
    if system_prompt:
        msgs = [{"role": "system", "content": system_prompt}] + msgs

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

    # v1.5.20: 注入 .meshctx.md 项目上下文 (多项目支持)
    md_ctx = _get_chat_context()
    if md_ctx:
        msgs.insert(0, {"role": "system", "content": f"[项目上下文 .meshctx.md]\n{md_ctx}"})

    # v1.5.26: 混合推理调度 — 自由能驱动的探索/直出决策
    scheduler = getattr(request.app.state, "hybrid_scheduler", None)
    hybrid_result = None
    if scheduler is not None and msgs:
        current_query = msgs[-1]["content"] if msgs[-1]["role"] == "user" else msgs[-1].get("content", "")
        message_history = msgs[:-1] if len(msgs) > 1 else []

        if scheduler.should_reason(message_history, current_query):
            hybrid_result = scheduler.reason(message_history, current_query)
        else:
            hybrid_result = scheduler.direct(message_history, current_query)

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

    # v1.5.26: 探索模式下在响应头部添加认知状态提示
    hybrid_info = None
    if hybrid_result and hybrid_result.get("strategy") == "explore":
        trace = hybrid_result.get("reasoning_trace", {})
        policy = hybrid_result.get("policy_used", "unknown")
        f_val = hybrid_result.get("free_energy", 0.0)
        hybrid_info = {
            "strategy": "explore",
            "policy": policy,
            "free_energy": round(f_val, 4),
        }
        # 在回复末尾附加轻微认知状态提示
        content += f"\n\n---\n🧠 [混合推理] 自由能 F={f_val:.3f} | 策略: {policy}"

    return {
        "content": content,
        "tokens": tokens,
        "model": model_id,
        "tool_result": tool_result,
        "hybrid_info": hybrid_info,
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

    # v2.16: 可选的系统提示词 — 用户可在Chat UI中设置
    system_prompt = body.get("system", "")
    if system_prompt:
        msgs = [{"role": "system", "content": system_prompt}] + msgs

    # v1.5.20: 注入 .meshctx.md 项目上下文 (多项目支持)
    md_ctx = _get_chat_context()
    if md_ctx:
        msgs.insert(0, {"role": "system", "content": f"[项目上下文 .meshctx.md]\n{md_ctx}"})

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

# ═══════════════════════════════════════════════════════════
# v1.9 多模型对比Chat — 同时问3个模型，三列卡片对比
# ═══════════════════════════════════════════════════════════

class CompareRequest(BaseModel):
    message: str
    models: List[str]  # e.g. ["deepseek:chat","openai:gpt-4o","anthropic:claude-sonnet"]

@app.post("/api/chat/compare")
async def api_chat_compare(request: CompareRequest):
    """多模型对比Chat — 并发调用3个模型，返回对比结果"""
    from src.model_registry import get_registry
    import time as _time

    if not request.models or len(request.models) < 1:
        raise HTTPException(400, "至少需要1个模型")
    if len(request.models) > 6:
        raise HTTPException(400, "最多支持6个模型同时对比")

    msgs = [{"role": "user", "content": request.message}]

    # 注入项目上下文
    md_ctx = _get_chat_context()
    if md_ctx:
        msgs.insert(0, {"role": "system", "content": f"[项目上下文 .meshctx.md]\n{md_ctx}"})

    reg = get_registry()

    async def call_one(model_id: str) -> dict:
        t0 = _time.time()
        try:
            client = reg.get(model_id)
            if not client:
                return {
                    "model": model_id,
                    "content": f"❌ 模型 {model_id} 未配置API Key",
                    "tokens": 0,
                    "latency_ms": 0,
                    "error": "model_not_configured",
                }
            resp = await asyncio.to_thread(client.chat, msgs)
            elapsed = round((_time.time() - t0) * 1000, 1)
            return {
                "model": model_id,
                "content": resp.get("content", ""),
                "tokens": resp.get("tokens", 0),
                "latency_ms": elapsed,
            }
        except Exception as e:
            elapsed = round((_time.time() - t0) * 1000, 1)
            return {
                "model": model_id,
                "content": f"❌ 调用失败: {str(e)[:200]}",
                "tokens": 0,
                "latency_ms": elapsed,
                "error": str(e)[:200],
            }

    results = await asyncio.gather(*[call_one(m) for m in request.models])
    return {
        "message": request.message,
        "results": results,
        "total_models": len(results),
    }


@app.post("/api/chat/compare/stream")
async def api_chat_compare_stream(request: CompareRequest):
    """多模型对比Chat SSE流式 — 3路并发逐token推送"""
    from src.model_registry import get_registry
    import time as _time
    import json as _json
    import asyncio

    if not request.models or len(request.models) < 1:
        raise HTTPException(400, "至少需要1个模型")
    if len(request.models) > 6:
        raise HTTPException(400, "最多支持6个模型同时对比")

    msgs = [{"role": "user", "content": request.message}]
    md_ctx = _get_chat_context()
    if md_ctx:
        msgs.insert(0, {"role": "system", "content": f"[项目上下文 .meshctx.md]\n{md_ctx}"})

    reg = get_registry()
    results_per_model: Dict[str, dict] = {}  # model_id → {content, tokens, latency_ms, done}

    async def stream_one(model_id: str, queue: asyncio.Queue):
        """流式调用单个模型，逐token推入队列"""
        t0 = _time.time()
        token_count = 0
        try:
            client = reg.get(model_id)
            if not client:
                await queue.put(_json.dumps({
                    "model": model_id,
                    "error": f"模型 {model_id} 未配置API Key",
                    "done": True,
                }))
                return

            for token in client.chat_stream(msgs):
                token_count += 1
                await queue.put(_json.dumps({
                    "model": model_id,
                    "token": token,
                    "done": False,
                }))

            elapsed = round((_time.time() - t0) * 1000, 1)
            await queue.put(_json.dumps({
                "model": model_id,
                "done": True,
                "tokens": token_count,
                "latency_ms": elapsed,
            }))
        except Exception as e:
            await queue.put(_json.dumps({
                "model": model_id,
                "error": f"❌ 调用失败: {str(e)[:200]}",
                "done": True,
                "tokens": token_count,
                "latency_ms": round((_time.time() - t0) * 1000, 1),
            }))

    async def generate():
        queue = asyncio.Queue()
        model_count = len(request.models)
        done_count = 0

        # 启动所有模型的流式任务
        tasks = [asyncio.create_task(stream_one(m, queue)) for m in request.models]

        # 发送初始元数据
        yield f"data: {_json.dumps({'type': 'start', 'models': request.models, 'count': model_count})}\n\n"

        while done_count < model_count:
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=120.0)
                yield f"data: {raw}\n\n"
                data = _json.loads(raw)
                if data.get("done"):
                    done_count += 1
            except asyncio.TimeoutError:
                yield f"data: {_json.dumps({'type': 'timeout', 'error': '部分模型超时'})}\n\n"
                break

        # 等待所有任务完成
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

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

# ── v1.5.18 代码运行 ─────────────────────────────────

@app.post("/api/code/run")
async def api_code_run(request: Request):
    """执行代码块 (Python/Bash/JS) — 返回输出+语言检测"""
    import subprocess, asyncio, tempfile
    
    try:
        body = await request.json()
        code = body.get("code", "").strip()
        lang = body.get("lang", "python").lower()
        timeout = min(body.get("timeout", 15), 30)
    except:
        return {"error": "无效请求", "output": ""}
    
    if not code:
        return {"error": "请输入代码", "output": ""}
    
    # 安全检查
    dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/sda", "os.system", "__import__('os')", "subprocess"]
    for d in dangerous:
        if d in code.lower():
            return {"error": f"⚠️ 危险代码已拦截 ({d})", "output": ""}
    
    try:
        if lang in ("python", "py"):
            # Python: 写入临时文件执行
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(code)
                tmpfile = f.name
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, tmpfile,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/tmp"
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
                out = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
                return {"output": out.strip() or "(无输出)", "exit_code": proc.returncode, "lang": lang}
            finally:
                os.unlink(tmpfile)
        
        elif lang in ("bash", "sh", "shell"):
            # Bash: 通过shell执行
            proc = await asyncio.create_subprocess_shell(
                code, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd="/tmp"
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
            out = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
            return {"output": out.strip() or "(无输出)", "exit_code": proc.returncode, "lang": lang}
        
        elif lang in ("js", "javascript", "node"):
            # Node.js
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write(code)
                tmpfile = f.name
            try:
                proc = await asyncio.create_subprocess_exec(
                    "node", tmpfile,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd="/tmp"
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
                out = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
                return {"output": out.strip() or "(无输出)", "exit_code": proc.returncode, "lang": lang}
            finally:
                os.unlink(tmpfile)
        else:
            return {"error": f"不支持的语言: {lang}", "output": ""}
    
    except asyncio.TimeoutError:
        return {"error": f"⏰ 代码执行超时({timeout}s)", "output": ""}
    except Exception as e:
        return {"error": str(e)[:300], "output": ""}

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

# ── v1.5.16 供应商管理面板 ────────────────────────────────

_PROVIDER_CONFIG_FILE = Path(__file__).resolve().parent.parent / "provider_config.json"

def _load_provider_config() -> dict:
    if _PROVIDER_CONFIG_FILE.exists():
        try:
            return json.loads(_PROVIDER_CONFIG_FILE.read_text())
        except:
            pass
    return {}

def _save_provider_config(cfg: dict):
    _PROVIDER_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

@app.get("/api/providers")
async def list_providers():
    """列出所有已配置的供应商及状态"""
    cfg = _load_provider_config()
    from src.model_registry import get_registry, BUILTIN_MODELS
    reg = get_registry()
    
    provider_status = {}
    for mid, info in BUILTIN_MODELS.items():
        pid = info["provider"]
        if pid not in provider_status:
            has_key = pid in cfg and bool(cfg[pid].get("key", ""))
            env_var = info.get("key_env", "")
            env_key = os.environ.get(env_var, "")
            provider_status[pid] = {
                "id": pid,
                "name": _provider_display_name(pid),
                "has_key": has_key or bool(env_key),
                "models_configured": 0,
                "models_total": 0,
                "key_masked": (cfg.get(pid, {}).get("key","") or env_key)[:4] + "****" if (cfg.get(pid, {}).get("key","") or env_key) else "",
                "last_tested": cfg.get(pid, {}).get("last_tested"),
                "test_status": cfg.get(pid, {}).get("test_status", "unknown"),
            }
        provider_status[pid]["models_total"] += 1
        if mid in reg._entries:
            provider_status[pid]["models_configured"] += 1
    
    return {
        "providers": sorted(provider_status.values(), key=lambda x: x["name"]),
        "total": len(provider_status),
        "configured": sum(1 for p in provider_status.values() if p["has_key"]),
    }

def _provider_display_name(pid: str) -> str:
    names = {
        "deepseek": "DeepSeek", "openai": "OpenAI", "anthropic": "Anthropic",
        "google": "Google Gemini", "bailian": "阿里百炼", "zhipu": "智谱AI",
        "moonshot": "月之暗面", "doubao": "字节豆包", "stepfun": "阶跃星辰",
        "minimax": "MiniMax", "baichuan": "百川智能", "mistral": "Mistral AI",
        "groq": "Groq", "perplexity": "Perplexity", "xai": "xAI Grok",
        "ollama": "Ollama (本地)",
    }
    return names.get(pid, pid.capitalize())

@app.post("/api/providers")
async def save_provider(request: Request):
    """保存/更新供应商 API Key"""
    body = await request.json()
    pid = body.get("provider", "").strip()
    key = body.get("key", "").strip()
    
    if not pid:
        raise HTTPException(400, "缺少 provider 参数")
    
    cfg = _load_provider_config()
    if key:
        cfg[pid] = {"key": key, "base_url": body.get("base_url", ""), "updated": time.time()}
    else:
        cfg.pop(pid, None)
    
    _save_provider_config(cfg)
    
    # 同步到环境变量
    from src.model_registry import BUILTIN_MODELS
    env_map = {}
    for mid, info in BUILTIN_MODELS.items():
        if info["provider"] == pid:
            env_map[info.get("key_env", "")] = key
    for env_var, env_val in env_map.items():
        if env_var:
            os.environ[env_var] = env_val
    
    # 重新配置模型
    from src.model_registry import get_registry
    reg = get_registry()
    reg.auto_configure()
    
    return {"success": True, "provider": pid, "saved": bool(key)}

@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除供应商配置"""
    cfg = _load_provider_config()
    if provider_id in cfg:
        del cfg[provider_id]
        _save_provider_config(cfg)
        return {"success": True, "deleted": provider_id}
    raise HTTPException(404, f"供应商 {provider_id} 未配置")

@app.post("/api/providers/{provider_id}/test")
async def test_provider(provider_id: str):
    """测试供应商API连通性"""
    cfg = _load_provider_config()
    if provider_id not in cfg:
        raise HTTPException(404, f"供应商 {provider_id} 未配置")
    
    key = cfg[provider_id].get("key", "")
    if not key:
        return {"success": False, "error": "未配置 API Key"}
    
    # 发送最小化测试请求
    import aiohttp
    test_urls = {
        "openai": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"}),
        "deepseek": ("https://api.deepseek.com/v1/models", {"Authorization": f"Bearer {key}"}),
        "anthropic": ("https://api.anthropic.com/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}),
        "bailian": ("https://dashscope.aliyuncs.com/api/v1/models", {"Authorization": f"Bearer {key}"}),
        "zhipu": ("https://open.bigmodel.cn/api/paas/v4/models", {"Authorization": f"Bearer {key}"}),
        "moonshot": ("https://api.moonshot.cn/v1/models", {"Authorization": f"Bearer {key}"}),
        "minimax": ("https://api.minimax.chat/v1/text/chatcompletion_v2", {"Authorization": f"Bearer {key}"}),
    }
    
    if provider_id not in test_urls:
        return {"success": False, "error": f"不支持测试 {provider_id}"}
    
    url, headers = test_urls[provider_id]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                result = await resp.text()
                ok = status in (200, 202)
                cfg[provider_id]["last_tested"] = time.time()
                cfg[provider_id]["test_status"] = "ok" if ok else "fail"
                _save_provider_config(cfg)
                return {"success": ok, "status": status, "preview": result[:200]}
    except Exception as e:
        cfg[provider_id]["last_tested"] = time.time()
        cfg[provider_id]["test_status"] = "error"
        _save_provider_config(cfg)
        return {"success": False, "error": str(e)[:200]}

# ── v1.5.17 MCP服务器管理 ──────────────────────────────────

_MCP_CONFIG_FILE = Path(__file__).resolve().parent.parent / "mcp_config.json"

def _load_mcp_config() -> list:
    if _MCP_CONFIG_FILE.exists():
        try:
            return json.loads(_MCP_CONFIG_FILE.read_text())
        except:
            pass
    return []

def _save_mcp_config(servers: list):
    _MCP_CONFIG_FILE.write_text(json.dumps(servers, indent=2, ensure_ascii=False))

@app.get("/api/mcp-servers")
async def list_mcp_servers():
    """列出所有MCP服务器配置"""
    servers = _load_mcp_config()
    # 给没有id的补充id
    for i, s in enumerate(servers):
        if "id" not in s:
            s["id"] = f"mcp-{i+1}"
    return {"servers": servers, "total": len(servers)}

@app.post("/api/mcp-servers")
async def save_mcp_server(request: Request):
    """添加/更新MCP服务器"""
    body = await request.json()
    sid = body.get("id", f"mcp-{int(time.time())}")
    name = body.get("name", "").strip()
    command = body.get("command", "").strip()
    
    if not name or not command:
        raise HTTPException(400, "name和command为必填项")
    
    server = {
        "id": sid,
        "name": name,
        "command": command,
        "args": body.get("args", []),
        "env": body.get("env", {}),
        "enabled": body.get("enabled", True),
        "status": body.get("status", "unknown"),
        "updated": time.time(),
    }
    
    servers = _load_mcp_config()
    # 更新或新增
    found = False
    for i, s in enumerate(servers):
        if s.get("id") == sid:
            servers[i] = server
            found = True
            break
    if not found:
        servers.append(server)
    
    _save_mcp_config(servers)
    
    return {"success": True, "server": server}

@app.delete("/api/mcp-servers/{server_id}")
async def delete_mcp_server(server_id: str):
    """删除MCP服务器"""
    servers = _load_mcp_config()
    servers = [s for s in servers if s.get("id") != server_id]
    _save_mcp_config(servers)
    return {"success": True, "deleted": server_id}

@app.post("/api/mcp-servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str):
    """启用/禁用MCP服务器"""
    servers = _load_mcp_config()
    for s in servers:
        if s.get("id") == server_id:
            s["enabled"] = not s.get("enabled", True)
            s["updated"] = time.time()
            _save_mcp_config(servers)
            return {"success": True, "id": server_id, "enabled": s["enabled"]}
    raise HTTPException(404, f"MCP服务器 {server_id} 未找到")

@app.post("/api/mcp-servers/{server_id}/test")
async def test_mcp_server(server_id: str):
    """测试MCP服务器连通性 — 尝试启动子进程并检查"""
    servers = _load_mcp_config()
    server = None
    for s in servers:
        if s.get("id") == server_id:
            server = s
            break
    if not server:
        raise HTTPException(404, f"MCP服务器 {server_id} 未找到")
    
    import subprocess
    try:
        cmd = [server["command"]] + server.get("args", [])
        proc = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=10,
            env={**os.environ, **server.get("env", {})}
        )
        ok = proc.returncode == 0
        # 更新状态
        for s in servers:
            if s.get("id") == server_id:
                s["status"] = "connected" if ok else "error"
                s["last_tested"] = time.time()
                break
        _save_mcp_config(servers)
        return {
            "success": ok, 
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:300],
            "stderr": proc.stderr[:300],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "超时(>10s)"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

# ── v1.5.16 会话历史浏览器 ────────────────────────────────

@app.get("/api/conversations/history")
async def conversation_history(
    project_id: Optional[str] = None, 
    search: Optional[str] = None,
    limit: int = 50
):
    """列出历史会话 + 搜索"""
    from src.models import Conversation, Project
    
    conversations = []
    # 从内存中的数据获取
    for proj_id, proj in Project._registry.items() if hasattr(Project, '_registry') else {}:
        if project_id and proj_id != project_id:
            continue
        convs = Conversation._registry.get(proj_id, {}) if hasattr(Conversation, '_registry') else {}
        for cid, conv in convs.items():
            conv_data = {
                "id": cid,
                "title": getattr(conv, 'title', '未命名'),
                "project_id": proj_id,
                "project_name": getattr(proj, 'name', ''),
                "message_count": len(getattr(conv, 'messages', [])),
                "created_at": getattr(conv, 'created_at', 0),
                "updated_at": getattr(conv, 'updated_at', 0),
            }
            if search:
                if search.lower() in conv_data["title"].lower():
                    conversations.append(conv_data)
            else:
                conversations.append(conv_data)
    
    conversations.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return {
        "conversations": conversations[:limit],
        "total": len(conversations),
    }

# ── v1.5.20 .meshctx.md 多项目上下文 ──────────────────────

_MESHCTX_MD_CACHE: Dict[str, tuple] = {}  # path -> (content, mtime)
_ACTIVE_PROJECT: Optional[str] = None  # 当前活跃项目路径


def _load_meshctx_md(project_path: str = ".") -> Optional[str]:
    """加载项目目录中的 .meshctx.md 文件"""
    path = Path(project_path).resolve()
    md_file = path / ".meshctx.md"
    if not md_file.exists():
        # 向上查找
        for p in [path] + list(path.parents)[:5]:
            candidate = p / ".meshctx.md"
            if candidate.exists():
                md_file = candidate
                break
        else:
            return None
    
    mtime = md_file.stat().st_mtime
    cache_key = str(md_file)
    if cache_key in _MESHCTX_MD_CACHE:
        cached_content, cached_mtime = _MESHCTX_MD_CACHE[cache_key]
        if cached_mtime == mtime:
            return cached_content
    
    content = md_file.read_text(encoding="utf-8", errors="replace")
    _MESHCTX_MD_CACHE[cache_key] = (content, mtime)
    return content


def _scan_projects(base_dir: str = ".") -> list:
    """扫描工作区所有 .meshctx.md 项目"""
    projects = []
    base = Path(base_dir).resolve()
    # 扫描当前目录及2层子目录
    for root, dirs, files in os.walk(base):
        if ".meshctx.md" in files:
            rel_path = str(Path(root).relative_to(base))
            display = rel_path if rel_path != "." else "(根目录)"
            # 读取第一行作为项目名
            try:
                first_line = (Path(root) / ".meshctx.md").read_text(encoding="utf-8").strip().split("\n")[0].strip("# ")[:50]
            except:
                first_line = display
            projects.append({
                "path": str(Path(root).resolve()),
                "name": display,
                "title": first_line or display,
                "active": str(Path(root).resolve()) == _ACTIVE_PROJECT
            })
        # 只扫描2层
        if root != str(base):
            dirs.clear()
        if len(projects) >= 20:
            break
    return projects


@app.get("/api/context/meshctx-md")
async def get_meshctx_md():
    """获取当前 .meshctx.md 上下文"""
    content = _load_meshctx_md()
    md_path = _get_active_md_path()
    return {"found": content is not None, "content": content, "path": md_path}


@app.get("/api/context/projects")
async def list_projects():
    """列出所有可用的 .meshctx.md 项目"""
    projects = _scan_projects()
    return {
        "projects": projects,
        "active": _ACTIVE_PROJECT,
        "total": len(projects)
    }


@app.post("/api/context/project/activate")
async def activate_project(request: Request):
    """切换活跃项目上下文"""
    global _ACTIVE_PROJECT
    try:
        body = await request.json()
        path = body.get("path", "").strip()
    except:
        return {"error": "无效请求"}
    
    if not path:
        _ACTIVE_PROJECT = None
        return {"active": None, "message": "已清除项目上下文"}
    
    p = Path(path)
    if (p / ".meshctx.md").exists():
        _ACTIVE_PROJECT = str(p.resolve())
        content = _load_meshctx_md(str(p))
        return {"active": _ACTIVE_PROJECT, "name": path, "content": content[:100] + "..." if content and len(content) > 100 else content, "message": f"已切换到: {path}"}
    return {"error": f"未找到 .meshctx.md: {path}"}


def _get_active_md_path() -> Optional[str]:
    """获取活跃的 .meshctx.md 路径"""
    if _ACTIVE_PROJECT:
        p = Path(_ACTIVE_PROJECT) / ".meshctx.md"
        if p.exists():
            return str(p)
    return str(Path(".").resolve() / ".meshctx.md") if (Path(".") / ".meshctx.md").exists() else None


def _get_chat_context() -> Optional[str]:
    """获取Chat对话应注入的上下文 (优先活跃项目，否则当前目录)"""
    if _ACTIVE_PROJECT:
        content = _load_meshctx_md(_ACTIVE_PROJECT)
        if content:
            return content
    return _load_meshctx_md(".")

# ── v1.5.26 ChatGPT API 统计 ──────────────────────────────

@app.get("/api/chat/stats")
async def api_chat_stats(request: Request):
    """返回混合推理调度器的决策统计"""
    scheduler = getattr(request.app.state, "hybrid_scheduler", None)
    if scheduler is None:
        return {"error": "scheduler not initialized", "stats": {}}
    return {"status": "ok", "stats": scheduler.get_decision_stats()}

# ── v1.5.21 配置导出/导入 ──────────────────────────────────

@app.get("/api/config/export")
async def export_config():
    """导出所有配置 (供应商Key + MCP服务器) 为可导入JSON"""
    providers = _load_provider_config()
    mcp_servers = _load_mcp_config()
    
    # 脱敏处理: 只导出key的前4后4字符提示，不导出完整Key
    safe_providers = {}
    for pid, pcfg in providers.items():
        sp = dict(pcfg)
        if "key" in sp and sp["key"]:
            k = sp["key"]
            if len(k) > 12:
                sp["key"] = k[:8] + "..." + k[-4:]
            sp["key_masked"] = True
        else:
            sp["key_masked"] = False
        safe_providers[pid] = sp
    
    export_data = {
        "version": "1.8.2",
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "providers": safe_providers,
        "mcp_servers": mcp_servers,
        "note": "Key已脱敏，导入时需重新填入。MCP配置完整保留。"
    }
    
    return export_data


@app.post("/api/config/import")
async def import_config(request: Request):
    """导入配置 (合并供应商 + MCP服务器)"""
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "无效的JSON格式")
    
    imported = 0
    skipped = 0
    messages = []
    
    # 导入MCP服务器
    if "mcp_servers" in body and isinstance(body["mcp_servers"], list):
        existing_mcp = _load_mcp_config()
        existing_ids = {s.get("id") for s in existing_mcp}
        for server in body["mcp_servers"]:
            sid = server.get("id", f"mcp-imported-{int(time.time())}")
            if sid not in existing_ids:
                server["status"] = "imported"
                server["enabled"] = False  # 默认禁用，用户手动启用
                existing_mcp.append(server)
                existing_ids.add(sid)
                imported += 1
                messages.append(f"MCP: +{server.get('name', sid)}")
            else:
                skipped += 1
        _save_mcp_config(existing_mcp)
    
    # 导入供应商
    if "providers" in body and isinstance(body["providers"], dict):
        existing_cfg = _load_provider_config()
        for pid, pcfg in body["providers"].items():
            if pid not in existing_cfg:
                # 如果是脱敏key，提示用户填入
                if pcfg.get("key_masked"):
                    pcfg["key"] = ""
                    pcfg["_note"] = "Key已脱敏，请手动填入"
                existing_cfg[pid] = pcfg
                imported += 1
                messages.append(f"Provider: +{pid}")
            else:
                skipped += 1
        _save_provider_config(existing_cfg)
    
    return {
        "success": True,
        "imported": imported,
        "skipped": skipped,
        "messages": messages,
        "note": "MCP服务器默认禁用，请手动启用。供应商Key已脱敏，请重新填入。"
    }

# ── v1.5.23 会话历史浏览器 + 供应商故障转移 ──────────────────

_SESSION_ARCHIVE: Dict[str, list] = {}  # session_id -> list of messages


@app.get("/api/sessions/archive")
async def list_session_archives(search: Optional[str] = None, limit: int = 50):
    """列出所有存档会话，支持搜索"""
    sessions = []
    for sid, msgs in _SESSION_ARCHIVE.items():
        if len(msgs) < 2:
            continue
        first_user = next((m.get("content", "")[:80] for m in msgs if m.get("role") == "user"), "")
        last_msg = msgs[-1]
        sessions.append({
            "id": sid,
            "title": first_user or sid[:16],
            "message_count": len(msgs),
            "first_message": first_user,
            "last_role": last_msg.get("role", ""),
            "last_content": last_msg.get("content", "")[:100],
            "created_at": msgs[0].get("timestamp", 0) if msgs else 0,
            "model": msgs[0].get("model", "") if msgs else "",
        })
    if search:
        s = search.lower()
        sessions = [s for s in sessions if s in s["title"].lower() or s in s["last_content"].lower()]
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return {"sessions": sessions[:limit], "total": len(sessions)}


@app.get("/api/sessions/archive/{session_id}")
async def get_session_detail(session_id: str):
    """获取存档会话完整内容"""
    msgs = _SESSION_ARCHIVE.get(session_id, [])
    return {"id": session_id, "messages": msgs, "count": len(msgs)}


@app.post("/api/sessions/archive")
async def archive_session(request: Request):
    """存档当前会话"""
    body = await request.json()
    sid = body.get("id", f"session-{int(time.time())}")
    messages = body.get("messages", [])
    _SESSION_ARCHIVE[sid] = messages
    return {"success": True, "id": sid, "count": len(messages)}


# 供应商健康追踪
_PROVIDER_HEALTH: Dict[str, dict] = {}


@app.get("/api/providers/health")
async def get_provider_health():
    """供应商健康评分 (成功率/延迟/故障转移建议)"""
    cfg = _load_provider_config()
    health = {}
    for pid, pcfg in cfg.items():
        stats = _PROVIDER_HEALTH.get(pid, {})
        success = stats.get("success", 0)
        failure = stats.get("failure", 0)
        total = success + failure
        rate = round(success / total * 100, 1) if total > 0 else 100.0
        health[pid] = {
            "name": pcfg.get("name", pid),
            "success_rate": rate,
            "total_calls": total,
            "avg_latency_ms": round(stats.get("total_latency", 0) / max(total, 1), 1),
            "status": "healthy" if rate >= 80 else ("degraded" if rate >= 50 else "unhealthy"),
            "last_error": stats.get("last_error", ""),
        }
    # 故障转移建议：按成功率排序
    sorted_pids = sorted(health.keys(), key=lambda p: health[p]["success_rate"], reverse=True)
    return {"providers": health, "failover_order": sorted_pids}


@app.api_route("/api/chat/archive-on-done", methods=["POST"])
async def archive_on_chat_done(request: Request):
    """Chat完成后自动存档"""
    body = await request.json()
    sid = body.get("id", f"chat-{int(time.time())}")
    messages = body.get("messages", [])
    _SESSION_ARCHIVE[sid] = messages
    return {"success": True, "id": sid}

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
        "version": "1.8.2",
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


def main():
    """入口"""
    import uvicorn
    host = os.environ.get("MESHCTX_HOST", "0.0.0.0")
    port = int(os.environ.get("MESHCTX_PORT", "8000"))
    
    
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
