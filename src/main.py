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

from fastapi import FastAPI, HTTPException, Request
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
# FastAPI 应用
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="meshctx API",
    description="世界第一自进化Agent系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 静态文件 ────────────────────────────────────────────
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
        "message": "meshctx API v1.0 运行中",
        "version": "1.0.0",
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
        "version": "1.0.0",
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

# ── Web Chat API ──────────────────────────────────────

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
    model_id = body.get("model", "deepseek:v4-flash")
    
    if not msgs:
        return {"content": "请输入消息", "tokens": 0}
    
    reg = get_registry()
    client = reg.get(model_id) or reg.get(None)
    if not client:
        return {"content": "模型未配置。请先设置 API Key", "tokens": 0}
    
    resp = client.chat(msgs)
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
from Crypto.Cipher import AES

def _wechat_verify_signature(token: str, timestamp: str, nonce: str, 
                              encrypt_str: str = "") -> str:
    """企业微信签名验证"""
    params = sorted([token, timestamp, nonce, encrypt_str])
    return hashlib.sha1("".join(params).encode()).hexdigest()

def _wechat_decrypt(encrypted: str, encoding_aes_key: str) -> tuple:
    """解密企业微信消息, 返回 (明文, corp_id)"""
    key = base64.b64decode(encoding_aes_key + "=")
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
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
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
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
        "version": "1.0.0",
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
    logger.info("═══════════════════════════════════════════")
    logger.info("  meshctx v1.0 已就绪!")
    logger.info(f"  API: http://0.0.0.0:8000")
    logger.info(f"  Docs: http://0.0.0.0:8000/docs")
    logger.info(f"  Web UI: http://0.0.0.0:8000/ui")
    logger.info("═══════════════════════════════════════════")


@app.on_event("shutdown")
async def on_shutdown():
    """优雅关闭"""
    global _kernel
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
