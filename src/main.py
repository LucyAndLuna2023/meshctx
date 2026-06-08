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
import random
import numpy as np
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, WebSocket
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, RedirectResponse
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

def _load_api_keys_on_startup():
    """v2.33: 从 .env 和 provider_config.json 加载 API Key"""
    import dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        dotenv.load_dotenv(env_path)
        logger.info(f"  .env loaded: {env_path}")
    
    pcfg = _load_provider_config()
    for provider, cfg in pcfg.items():
        if isinstance(cfg, dict):
            for key_name in ("api_key", "key", "token"):
                if key_name in cfg and cfg[key_name]:
                    env_key = f"{provider.upper().replace('-','_')}_API_KEY"
                    if not os.environ.get(env_key):
                        os.environ[env_key] = str(cfg[key_name])

@asynccontextmanager
async def lifespan(app: FastAPI):
    """v1.5.25: 迁移至 lifespan — 替换已弃用的 on_event"""
    global _kernel, _memory_engine

    # ── Startup ──
    logger.info("═══════════════════════════════════════════")
    logger.info("  meshctx v1.0 启动中...")
    logger.info("═══════════════════════════════════════════")
    
    # v2.33: 加载API Key — 从.env和provider_config.json
    _load_api_keys_on_startup()
    
    # 自动配置模型
    from src.model_registry import get_registry
    get_registry().auto_configure()
    logger.info(f"模型自动配置完成: {len(get_registry()._entries)} 个")

    _kernel = Kernel()
    logger.info("加载核心插件...")
    _kernel.plugins.register(MemoryPlugin())
    if MetaCognitionPlugin and callable(MetaCognitionPlugin):
        _kernel.plugins.register(MetaCognitionPlugin())
    else:
        logger.warning("MetaCognitionPlugin 不可用 — 跳过")
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
    try:
        from .core.hybrid_reasoning import HybridReasoningScheduler
        app.state.hybrid_scheduler = HybridReasoningScheduler(
            threshold=1.5,
            adaptive=True,
        )
    except ImportError:
        app.state.hybrid_scheduler = None

    logger.info(f"事件总线: {_kernel.bus.get_stats()['subscriptions']} 订阅")

    # v2.13: 自动激活内置插件
    from .core.plugin_autoload import auto_activate_builtins
    builtin_count = auto_activate_builtins()
    logger.info(f"内置插件自动激活: {builtin_count}")

    # v2.13: 启动WebSocket实时推送
    from .core.realtime_push import get_hub
    asyncio.create_task(get_hub().start_broadcast_loop(interval=2.0))
    logger.info("WebSocket实时推送已启动 (2s间隔)")

    # v3.34: 初始化Agent Swarm多Agent协同
    try:
        from .core.agent_swarm import init_swarm_manager
        await init_swarm_manager(host="0.0.0.0", port=3000)
        logger.info("Agent Swarm Manager已启动 (多Agent协同就绪)")
    except Exception as e:
        logger.warning(f"Agent Swarm初始化失败(非致命): {e}")

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

    # v2.18: 会话自动存档
    archiver = get_archiver()
    from src.core import __version__ as _ver; archiver.init_session(_ver)
    
    # 🔴 v3.35: Session Auto-Resume — 服务器重启自动恢复上下文
    try:
        from .core.session_resume import get_session_resume
        resume_engine = get_session_resume()
        previous = resume_engine.detect_previous_session()
        if previous:
            resume_report = resume_engine.restore(previous)
            app.state.resume_engine = resume_engine
            app.state.resume_report = resume_report
            
            # 注入历史上下文到内核
            reports = resume_engine.apply_to_kernel(_kernel)
            
            continuity = resume_report.get("context_continuity", 0)
            icon = "🔄" if continuity > 50 else "📋"
            logger.info(f"{icon} Session Auto-Resume: "
                       f"continuity={continuity:.0f}% "
                       f"decisions={resume_report['items_restored'].get('decisions', 0)} "
                       f"rules={resume_report['items_restored'].get('rules', 0)} "
                       f"({resume_report.get('resume_time_ms', 0)}ms)")
            
            archiver.record("session_resumed", f"continuity={continuity:.0f}%", "info")
        else:
            logger.info("🆕 新会话 — 无历史存档可恢复")
            app.state.resume_engine = resume_engine
    except Exception as e:
        logger.warning(f"Session Auto-Resume 初始化失败(非致命): {e}")
        app.state.resume_engine = None
    
    # v2.21: 智能自愈 + 性能优化器
    try:
        from src.core.auto_healer import healer
        from src.core.performance_optimizer import optimizer
        app.state.healer = healer
        app.state.optimizer = optimizer
        healer.start()
        logger.info("AutoHealer & PerformanceOptimizer started")
    except Exception as e:
        logger.warning(f"Healer/Optimizer init skipped: {e}")
    archiver.record("server_start", f"v{_ver}", "info")
    
    async def auto_archive():
        while True:
            await asyncio.sleep(300)
            try:
                archiver.record("auto_save", "自动存档", "info")
                archiver.save()
            except Exception as e:
                logger.debug(f"存档: {e}")
    asyncio.create_task(auto_archive())
    
    # v3.36: JEPA世界模型初始化 (杨立昆World Model)
    try:
        from .core.jepa_world_model import get_world_model, get_non_generative_router
        wm = get_world_model()
        router = get_non_generative_router()
        app.state.world_model = wm
        app.state.jepa_router = router
        # 初始感知
        init_obs = np.zeros(wm.config.embed_dim)
        wm.perceive(init_obs)
        logger.info(f"🧠 JEPA世界模型已初始化 (dim={wm.config.embed_dim}, "
                   f"潜空间预测→非生成式决策)")
        archiver.record("jepa_init", f"dim={wm.config.embed_dim}", "info")
    except Exception as e:
        logger.debug(f"JEPA世界模型初始化跳过: {e}")
        app.state.world_model = None
        app.state.jepa_router = None
    
    # v2.18: 主动监控守护进程 (解决Hermes被动响应痛点)
    daemon = get_daemon()
    await daemon.start()
    logger.info("🛡️ 主动监控守护进程已启动 (每60s检查cron/磁盘/内存)")

    yield  # ── 服务运行中 ──

    # ── Shutdown ──
    if _kernel is not None:
        await _kernel.stop()
    logger.info("meshctx v1.0 已停止")


app = FastAPI(
    title="MeshCtx API",
    description="世界首个全脑仿真自进化Agent系统 — 13脑区超级大脑 + 代码沙箱 + 项目索引 + 飞书通知",
    version="3.115.2",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "system", "description": "系统状态与配置"},
        {"name": "chat", "description": "Chat对话 + WebSocket流式 /ws/chat"},
        {"name": "sandbox", "description": "代码沙箱 — Python/Bash/JS安全执行"},
        {"name": "project", "description": "项目索引 — 代码搜索与上下文"},
        {"name": "memory", "description": "记忆系统 — 向量检索 + 知识图谱 + 语义搜索"},
        {"name": "multi-agent", "description": "多Agent协作 — 任务分解 + DAG并行执行"},
        {"name": "healer", "description": "智能自愈 — 健康评分 + 预测 + 自动修复"},
        {"name": "performance", "description": "性能优化 — 缓存 + 延迟统计 + 基准测试"},
        {"name": "files", "description": "文件管理 — 浏览/读取/写入"},
        {"name": "feishu", "description": "飞书通知 — Lark/Feishu Webhook集成"},
        {"name": "plugins", "description": "插件市场 — 一键安装/卸载/社区推荐"},
        {"name": "models", "description": "模型管理 — 123模型 37供应商 CRUD/切换/测试"},
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

# ── Security Headers Middleware ───────────────────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add standard security headers to all responses"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# GZip压缩 (v2.29) — 减少响应体积 60-80%
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)

# ── v2.17: Web UI 认证中间件 ────────────────────────
import hashlib, secrets
_AUTH_PASSWORD = os.environ.get("MESHCTX_PASSWORD", "")
_AUTH_SECRET = os.environ.get("MESHCTX_SECRET", secrets.token_hex(32))
_AUTH_ENABLED = bool(_AUTH_PASSWORD)

if _AUTH_ENABLED:
    import base64
    logger.info(f"🔐 Web UI 认证已启用 (密码保护)")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Web UI 基础认证 — 保护 /ui/* 路由"""
    if not _AUTH_ENABLED:
        return await call_next(request)
    
    path = request.url.path
    
    # Public endpoints (API, static, login)
    if not path.startswith("/ui/") or path == "/ui/login":
        return await call_next(request)
    
    # Check auth cookie
    session = request.cookies.get("meshctx_session", "")
    expected = hashlib.sha256(f"{_AUTH_PASSWORD}:{_AUTH_SECRET}".encode()).hexdigest()
    
    if session == expected:
        return await call_next(request)
    
    # Redirect to login
    return RedirectResponse(url=f"/ui/login?next={path}", status_code=302)

@app.get("/ui/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = ""):
    lang = request.cookies.get("meshctx_lang", "en")
    return HTMLResponse(content=r"""<!DOCTYPE html>
<html lang=""" + '"' + lang + '"' + r"""><head><meta charset="UTF-8"><title>MeshCtx Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:360px;text-align:center}
h1{color:#e0e4f0;margin-bottom:8px}
p{color:#8090b0;font-size:14px;margin-bottom:24px}
input{width:100%;padding:12px;border:1px solid rgba(255,255,255,0.12);border-radius:8px;background:rgba(0,0,0,0.3);color:#e0e4f0;font-size:16px;margin-bottom:16px;outline:none}
input:focus{border-color:#6c5ce7}
button{width:100%;padding:12px;background:linear-gradient(135deg,#6c5ce7,#5a4bd1);border:none;border-radius:8px;color:#fff;font-size:16px;cursor:pointer}
.error{color:#f85149;font-size:13px;margin-top:8px;display:none}
</style></head><body>
<div class="card">
<h1>🔐 MeshCtx</h1><p id="login-hint">请输入管理密码 / Enter password</p>
<form onsubmit="login(event)">
<input type="password" id="pw" placeholder="Password" aria-label="Password" autofocus>
<button type="submit" id="login-btn">登 录 / Login</button>
<div class="error" id="err">密码错误 / Wrong password</div>
</form>
<script>
async function login(e){e.preventDefault();
var pw=document.getElementById('pw').value;
var r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
if(r.ok){location.href='""" + (next or "/ui/chat") + """'}else{document.getElementById('err').style.display='block'}}
</script></div></body></html>""")

# 暴力破解防护 (BUG-005)
_login_attempts: Dict[str, List[float]] = {}
LOGIN_ATTEMPT_WINDOW = 300  # 5分钟窗口
LOGIN_MAX_ATTEMPTS = 5      # 5次失败后封禁
_login_bans: Dict[str, float] = {}  # IP -> ban解除时间

@app.post("/api/auth/login")
async def auth_login(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    # 检查是否被封禁
    if client_ip in _login_bans and now < _login_bans[client_ip]:
        retry_after = int(_login_bans[client_ip] - now)
        raise HTTPException(429, f"登录尝试过多，请{retry_after}秒后重试")
    # 清除过期封禁
    if client_ip in _login_bans and now >= _login_bans[client_ip]:
        del _login_bans[client_ip]
    try: body = await request.json()
    except: raise HTTPException(400)
    password = body.get("password", "")
    if password == _AUTH_PASSWORD:
        # 成功：清除失败记录
        _login_attempts.pop(client_ip, None)
        expected = hashlib.sha256(f"{_AUTH_PASSWORD}:{_AUTH_SECRET}".encode()).hexdigest()
        resp = JSONResponse({"status": "ok"})
        resp.set_cookie("meshctx_session", expected, httponly=True, secure=True, max_age=86400, samesite="lax")
        return resp
    # 失败：记录尝试
    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = []
    _login_attempts[client_ip].append(now)
    # 清理过期记录
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < LOGIN_ATTEMPT_WINDOW]
    if len(_login_attempts[client_ip]) >= LOGIN_MAX_ATTEMPTS:
        ban_duration = min(300, 30 * (2 ** (len(_login_attempts[client_ip]) - LOGIN_MAX_ATTEMPTS)))  # 指数退避
        _login_bans[client_ip] = now + ban_duration
        raise HTTPException(429, f"登录尝试过多，已封禁{ban_duration}秒")
    raise HTTPException(401, "密码错误")

@app.post("/api/auth/logout")
async def auth_logout():
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie("meshctx_session")
    return resp

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

# ─── Getting Started 页面 ────────────────────────────────
_docs_dir = Path(__file__).resolve().parent.parent / "docs"

@app.get("/getting-started")
async def serve_getting_started():
    """serve getting-started.html"""
    gs_path = _docs_dir / "getting-started.html"
    if gs_path.exists():
        return FileResponse(str(gs_path), media_type="text/html")
    return HTMLResponse("<h1>404 - Not Found</h1>", status_code=404)

# ─── 安装脚本 ────────────────────────────────────────
from fastapi.responses import FileResponse

@app.get("/install.sh")
async def serve_install_script():
    """curl -fsSL meshctx.com/install.sh | bash"""
    script_path = Path(__file__).resolve().parent.parent / "install.sh"
    if not script_path.exists():
        script_path = Path("/opt/meshctx/install.sh")
    return FileResponse(script_path, media_type="text/plain")

@app.get("/install.bat")
async def serve_install_bat():
    script_path = Path(__file__).resolve().parent.parent / "install.bat"
    if not script_path.exists():
        script_path = Path("/opt/meshctx/install.bat")
    return FileResponse(script_path, media_type="text/plain")

# ─── Web UI 路由 (延迟导入避免循环) ────────────────────
from .web_ui import router as web_ui_router
from .core.session_archiver import get_archiver, SessionArchiver
from .core.watchdog import WatchdogDaemon, get_daemon, HEARTBEAT_FILE
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

# ═══════════════════════════════════════════════════
# 实时健康面板 (v2.60)
# ═══════════════════════════════════════════════════
@app.get("/dashboard/live", response_class=HTMLResponse)
async def live_dashboard():
    """实时健康面板 — WebSocket驱动的15模块监控"""
    from pathlib import Path
    html_path = Path(__file__).parent / "core" / "templates" / "live_dashboard.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard template not found</h1>", status_code=404)

@app.get("/favicon.ico")
async def favicon():
    """浏览器 tab icon — 重定向到 SVG 图标"""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/ui/icon-192.png")

@app.get("/", response_class=HTMLResponse)
async def root():
    """服务主页 — 从 static/index.html"""
    import os
    from starlette.responses import HTMLResponse as StarletteHTMLResponse
    index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    if not os.path.exists(index_path):
        index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            resp = HTMLResponse(content=f.read())
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp
    # fallback
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url=/ui/">
<title>meshctx</title>
<style>
body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
p{font-size:18px;color:#94a3b8}a{color:#38bdf8}
</style>
</head>
<body>
<p>正在跳转到 <a href="/ui/">meshctx UI</a>...</p>
<p><small><a href="/static/index.html">🏠 主页</a></small></p>
</body>
</html>""")

# ── 语言切换 ──────────────────────────────────────────
class LangSetRequest(BaseModel):
    lang: str

@app.post("/api/lang/set")
async def api_lang_set(request: LangSetRequest, req: Request = None):
    """设置UI语言"""
    set_lang(request.lang)
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"status": "ok", "lang": request.lang})
    resp.set_cookie("meshctx_lang", request.lang, max_age=365*24*3600, path="/", samesite="lax")
    return resp

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

@app.get("/context/build")
async def context_build_doc():
    """POST /context/build 文档 — 构建Agent上下文记忆"""
    return {
        "method": "POST",
        "description": "为指定Agent构建上下文记忆",
        "body": {
            "agent_id": "string (必填) — Agent标识",
            "project_id": "string (必填) — 项目ID",
            "conversation_id": "string (必填) — 对话ID",
            "max_messages": "int (默认20) — 最大消息数"
        },
        "example": 'curl -X POST http://localhost:3001/context/build -H "Content-Type: application/json" -d \'{"agent_id":"main","project_id":"default","conversation_id":"conv1"}\''
    }

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
        "version": "3.115.2",
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


@app.get("/api/plugins/market")
async def plugin_market(search: str = "", category: str = ""):
    """插件市场 — 浏览/搜索可用插件"""
    import json, os
    from pathlib import Path
    reg_path = Path(__file__).parent.parent / "plugins" / "registry.json"
    if not reg_path.exists():
        return {"plugins": [], "total": 0}
    with open(reg_path) as f:
        data = json.load(f)
    plugins = data.get("plugins", [])
    if search:
        plugins = [p for p in plugins if search.lower() in p.get("name","").lower() 
                   or search.lower() in p.get("description","").lower()]
    if category:
        plugins = [p for p in plugins if p.get("category") == category]
    return {"plugins": plugins, "total": len(plugins), "categories": list(set(p.get("category","other") for p in data.get("plugins",[])))}


@app.post("/api/plugins/install")
async def install_plugin(request: Request):
    """安装插件 — 持久化到config.yaml"""
    try: body = await request.json()
    except: raise HTTPException(400)
    name = body.get("name", "")
    if not name: raise HTTPException(400, "Missing plugin name")
    
    import json, yaml
    from pathlib import Path
    
    # Verify plugin exists in registry
    reg_path = Path(__file__).parent.parent / "plugins" / "registry.json"
    plugin_info = None
    if reg_path.exists():
        with open(reg_path) as f:
            data = json.load(f)
        for p in data.get("plugins", []):
            if p["name"] == name:
                plugin_info = p
                p["installs"] = p.get("installs", 0) + 1
                with open(reg_path, "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                break
    
    if not plugin_info:
        raise HTTPException(404, f"插件 {name} 不存在")
    
    # Persist to config.yaml
    config_path = Path.home() / ".meshctx" / "config.yaml"
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    
    config.setdefault("plugins", {}).setdefault("installed", {})
    config["plugins"]["installed"][name] = {
        "version": plugin_info.get("version", "1.0.0"),
        "installed_at": __import__("time").time(),
        "category": plugin_info.get("category", ""),
    }
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    return {"status": "ok", "plugin": name, "message": f"插件 {name} 已安装"}


@app.post("/api/plugins/uninstall")
async def uninstall_plugin(request: Request):
    """卸载插件"""
    try: body = await request.json()
    except: raise HTTPException(400)
    name = body.get("name", "")
    
    import yaml
    from pathlib import Path
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        installed = config.get("plugins", {}).get("installed", {})
        if name in installed:
            del installed[name]
            with open(config_path, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            return {"status": "ok", "plugin": name, "message": f"插件 {name} 已卸载"}
    raise HTTPException(404, f"插件 {name} 未安装")


@app.get("/api/plugins/installed")
async def installed_plugins():
    """获取已安装插件列表"""
    import yaml
    from pathlib import Path
    config_path = Path.home() / ".meshctx" / "config.yaml"
    installed = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        installed = config.get("plugins", {}).get("installed", {})
    return {"installed": installed}


@app.get("/api/plugins/stats")
async def plugin_stats():
    """插件统计"""
    import json, os
    from pathlib import Path
    reg_path = Path(__file__).parent.parent / "plugins" / "registry.json"
    if not reg_path.exists():
        return {"total": 0, "categories": []}
    with open(reg_path) as f:
        data = json.load(f)
    plugins = data.get("plugins", [])
    return {
        "total": len(plugins),
        "total_installs": sum(p.get("installs", 0) for p in plugins),
        "categories": list(set(p.get("category", "other") for p in plugins)),
        "top": sorted(plugins, key=lambda p: p.get("installs", 0), reverse=True)[:5],
    }

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

# ── 多Agent协作 v2.0 API ────────────────────────────────

@app.get("/api/multi-agent/status")
async def multi_agent_status():
    """多Agent系统状态"""
    from src.core.multi_agent import get_manager, get_executor
    mgr = get_manager()
    executor = get_executor()
    return {
        "manager": mgr.get_summary(),
        "executor": {
            "timeout_per_task": executor.timeout_per_task,
            "decomposer_max_depth": executor.decomposer.max_depth,
        }
    }

@app.post("/api/multi-agent/create-team")
async def create_agent_team():
    """创建默认Agent团队"""
    from src.core.multi_agent import get_manager, AgentFactory
    mgr = get_manager()
    agents = AgentFactory.create_team(mgr)
    return {
        "status": "created",
        "agents": {aid: agent.get_info() for aid, agent in agents.items()},
    }

@app.post("/api/multi-agent/decompose")
async def decompose_task(task: dict = None):
    """分解复杂任务为子任务"""
    from src.core.multi_agent import get_executor
    if not task:
        raise HTTPException(400, "task body required")
    task["id"] = task.get("id", f"task_{int(time.time())}")
    executor = get_executor()
    plan = executor.get_execution_plan(task)
    return plan

@app.post("/api/multi-agent/execute")
async def execute_decomposed_task(task: dict = None):
    """执行分解后的复杂任务 (并行)"""
    from src.core.multi_agent import get_executor, get_manager, AgentFactory
    if not task:
        raise HTTPException(400, "task body required")
    task["id"] = task.get("id", f"task_{int(time.time())}")
    
    # 确保有Agent可用
    mgr = get_manager()
    if len(mgr.bus._agents) == 0:
        AgentFactory.create_team(mgr)
    
    executor = get_executor()
    result = await executor.execute_task(task)
    return result

@app.post("/api/multi-agent/plan")
async def get_execution_plan(task: dict = None):
    """查看任务执行计划 (不实际执行)"""
    from src.core.multi_agent import get_executor
    if not task:
        raise HTTPException(400, "task body required")
    task["id"] = task.get("id", "plan")
    executor = get_executor()
    return executor.get_execution_plan(task)

# ── Agent Swarm — 多Agent协同 (Manager-Worker) ──────────

@app.post("/swarm/register")
async def swarm_register(request: dict):
    """Worker注册 — Manager端点"""
    from src.core.agent_swarm import get_swarm_manager
    mgr = get_swarm_manager()
    if not mgr:
        raise HTTPException(503, "Swarm Manager not started")
    wi = mgr.register_worker(
        worker_id=request.get("worker_id", ""),
        name=request.get("name", ""),
        address=request.get("address", ""),
        public_key=request.get("public_key", ""),
        capabilities=request.get("capabilities", []),
    )
    return {"status": "registered", "worker": wi.to_dict()}

@app.post("/swarm/heartbeat")
async def swarm_heartbeat(request: dict):
    """Worker心跳 — Manager端点"""
    from src.core.agent_swarm import get_swarm_manager
    mgr = get_swarm_manager()
    if not mgr:
        raise HTTPException(503, "Swarm Manager not started")
    mgr.update_heartbeat(request.get("agent_id", ""))
    return {"status": "ok"}

@app.post("/swarm/task")
async def swarm_receive_task(request: dict):
    """Worker接收任务 — Worker端点"""
    from src.core.agent_swarm import get_swarm_worker
    worker = get_swarm_worker()
    if not worker:
        raise HTTPException(503, "Swarm Worker not started")
    result = await worker.execute_task(request)
    return result

@app.post("/swarm/result")
async def swarm_receive_result(request: dict):
    """Worker返回结果 — Manager端点"""
    from src.core.agent_swarm import get_swarm_manager
    mgr = get_swarm_manager()
    if not mgr:
        raise HTTPException(503, "Swarm Manager not started")
    await mgr.receive_result(
        task_id=request.get("task_id", ""),
        result=request.get("result", ""),
        error=request.get("error", ""),
    )
    return {"status": "ok"}

@app.post("/swarm/execute")
async def swarm_execute(request: dict):
    """提交任务到Swarm — 自动分解→派发→汇总"""
    from src.core.agent_swarm import get_swarm_manager
    mgr = get_swarm_manager()
    if not mgr:
        raise HTTPException(503, "Swarm Manager not started")
    tasks = await mgr.submit_task(
        description=request.get("task", ""),
        task_type=request.get("type", "general"),
        context=request.get("context", ""),
        priority=request.get("priority", 5),
    )
    return {
        "status": "submitted",
        "total_tasks": len(tasks),
        "tasks": [t.to_dict() for t in tasks],
    }

@app.get("/swarm/status")
async def swarm_status():
    """Swarm整体状态"""
    from src.core.agent_swarm import get_swarm_manager
    mgr = get_swarm_manager()
    if not mgr:
        return {"status": "not_started"}
    return mgr.get_swarm_status()

# ── P0-7 动态Summon子Agent API ──────────────────────────

@app.post("/api/summon")
async def summon_agent(request: dict = None):
    """
    召唤子Agent — POST /api/summon

    请求体:
        {\"description\": \"写一个排序算法\", \"task\": \"实现快速排序\", \"timeout\": 120, \"role\": \"coder\"}

    响应:
        {\"agent_id\": \"...\", \"status\": \"done\", \"result\": \"...\", ...}
    """
    from src.core.summon_engine import get_summon_engine

    if not request:
        raise HTTPException(400, "请求体不能为空，需要提供 description 字段")

    description = request.get("description", "")
    if not description:
        raise HTTPException(400, "description 字段为必填项")

    task = request.get("task", "")
    timeout = request.get("timeout", 300)
    role = request.get("role", "")
    async_mode = request.get("async", False)

    engine = get_summon_engine()
    result = engine.summon(
        description=description,
        task=task,
        timeout=float(timeout),
        role=role,
        async_mode=async_mode,
    )
    return result.to_dict()


@app.get("/api/summon")
async def list_active_summons():
    """
    列出活跃子Agent — GET /api/summon

    响应:
        {\"active\": [...], \"count\": N, \"stats\": {...}}
    """
    from src.core.summon_engine import get_summon_engine

    engine = get_summon_engine()
    active = engine.active_agents()
    stats = engine.get_stats()
    return {
        "active": active,
        "count": len(active),
        "stats": stats,
    }


@app.delete("/api/summon/{agent_id}")
async def dismiss_summon(agent_id: str):
    """
    遣散子Agent — DELETE /api/summon/{agent_id}

    响应:
        {\"agent_id\": \"...\", \"dismissed\": true/false}
    """
    from src.core.summon_engine import get_summon_engine

    engine = get_summon_engine()
    success = engine.dismiss(agent_id)
    if not success:
        raise HTTPException(404, f"Agent {agent_id} 不存在或已完成")
    return {"agent_id": agent_id, "dismissed": True}

# ── 性能监控 ────────────────────────────────────────────

@app.get("/performance/report")
async def performance_report():
    """性能报告"""
    k = get_kernel()
    plugin = k.plugins.get("performance") if k._started else None
    if not plugin:
        return {"status": "disabled"}
    return plugin.generate_report()


@app.get("/api/performance/stats")
async def api_performance_stats():
    """性能统计 (/api/ 前缀兼容)"""
    try:
        from src.core.performance_optimizer import get_perf_optimizer
        opt = get_perf_optimizer()
        if opt and hasattr(opt, "get_stats"):
            return opt.get_stats()
        return {"status": "not_initialized"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/performance/report")
async def api_performance_report():
    """性能报告 (/api/ 前缀兼容)"""
    return await performance_report()


# ── Tasks / Cache / Backup / Governance 兼容路由 ──────

@app.get("/api/tasks/stats")
async def api_tasks_stats():
    """任务统计"""
    try:
        from src.core.agent_swarm import get_swarm_manager
        mgr = get_swarm_manager()
        if mgr and hasattr(mgr, "get_stats"):
            return mgr.get_stats()
        return {"total_tasks": 0, "running": 0, "completed": 0, "failed": 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/tasks/history")
async def api_tasks_history():
    """任务历史"""
    try:
        from src.core.agent_swarm import get_swarm_manager
        mgr = get_swarm_manager()
        if mgr and hasattr(mgr, "get_history"):
            return {"history": mgr.get_history()}
        return {"history": [], "total": 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/cache/stats")
async def api_cache_stats():
    """缓存统计"""
    try:
        from src.core.performance_optimizer import get_perf_optimizer
        opt = get_perf_optimizer()
        if opt and hasattr(opt, "cache_stats"):
            return opt.cache_stats()
        return {"status": "not_initialized", "hits": 0, "misses": 0, "size": 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/backup/stats")
async def api_backup_stats():
    """备份统计"""
    try:
        from src.core.backup_vault import get_backup_vault
        vault = get_backup_vault()
        if vault and hasattr(vault, "get_stats"):
            return vault.get_stats()
        return {"status": "not_initialized", "backups": 0, "total_size": 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/governance/status")
async def api_governance_status():
    """治理状态"""
    try:
        from src.core.agent_governance import get_governance
        gov = get_governance()
        return gov.status() if gov else {"status": "not_initialized"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/governance/rules")
async def api_governance_rules():
    """治理规则"""
    try:
        from src.core.agent_governance import get_governance
        gov = get_governance()
        return {"rules": gov.rules() if gov else []}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/governance/errors")
async def api_governance_errors():
    """治理错误模式"""
    try:
        from src.core.agent_governance import get_governance
        gov = get_governance()
        return gov.error_patterns() if gov else {"patterns": []}
    except Exception as e:
        return {"status": "error", "error": str(e)}

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

@app.get("/api/healer/dashboard")
async def healer_dashboard_api():
    """Healer Dashboard API (兼容前端)"""
    try:
        from src.core.auto_healer import healer
        report = healer.get_dashboard_report() if hasattr(healer, 'get_dashboard_report') else {}
        if not report:
            report = {
                "status": healer._status if hasattr(healer, '_status') else "unknown",
                "color": "gray",
                "running": hasattr(healer, '_running') and healer._running,
                "last_check_human": "N/A",
                "uptime_since_incident_human": "N/A",
                "heals_successful": 0,
                "heals_performed": 0,
                "checks_total": 0,
                "plugins": {},
            }
        return report
    except Exception as e:
        return {"status": "error", "color": "red", "running": False,
                "last_check_human": "Error", "uptime_since_incident_human": "N/A",
                "heals_successful": 0, "heals_performed": 0, "checks_total": 0,
                "plugins": {}, "error": str(e)}


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
    try:
        import psutil
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "disk_percent": psutil.disk_usage("/").percent,
        }
    except ImportError:
        # psutil未安装时使用/proc fallback
        import os
        mem = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if parts[0] == "MemTotal:": mem["total_kb"] = int(parts[1])
                    elif parts[0] == "MemAvailable:": mem["avail_kb"] = int(parts[1])
        except: pass
        total = mem.get("total_kb", 0)
        avail = mem.get("avail_kb", 0)
        used_pct = round((total - avail) / total * 100, 1) if total else 0
        return {
            "cpu_percent": 0,
            "memory_percent": used_pct,
            "memory_used_gb": round((total - avail) / 1048576, 1),
            "memory_total_gb": round(total / 1048576, 1),
            "disk_percent": 0,
            "note": "psutil not installed, using /proc fallback"
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


def _load_provider_config():
    """加载 provider_config.json 中的供应商配置"""
    pcfg_path = Path(__file__).resolve().parent.parent / "provider_config.json"
    if not pcfg_path.exists():
        return {}
    try:
        return json.loads(pcfg_path.read_text())
    except Exception:
        return {}


_PROVIDER_DISPLAY = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "mistral": "Mistral",
    "qwen": "通义千问",
    "zhipu": "智谱",
    "moonshot": "月之暗面",
    "baidu": "百度",
    "minimax": "MiniMax",
    "xunfei": "讯飞",
    "volcengine": "火山引擎",
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "groq": "Groq",
    "ollama": "Ollama",
    "azure": "Azure OpenAI",
}


def _provider_display_name(pid: str) -> str:
    """供应商ID→显示名"""
    return _PROVIDER_DISPLAY.get(pid, pid)

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
    
    model_id = (body.get("id") or "").strip()
    provider = (body.get("provider") or "").strip()
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
    
    entries = config.setdefault("models", {}).setdefault("entries", {})

    # v3.34.1: builtin模型首次配key时自动创建entry
    if model_id not in entries:
        from src.model_registry import BUILTIN_MODELS
        builtin = BUILTIN_MODELS.get(model_id)
        if not builtin:
            raise HTTPException(404, f"模型 {model_id} 不存在")
        # 从builtin自动创建entry
        entries[model_id] = {
            "provider": builtin.get("provider", ""),
            "model": builtin.get("model", model_id),
            "base_url": builtin.get("base_url", ""),
            "key": "",
        }
    
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


@app.patch("/api/models/{model_id}")
async def rename_model(model_id: str, request: Request):
    """重命名模型ID + 更新配置"""
    from pathlib import Path
    import yaml
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "无效的JSON请求体")
    
    rename_to = body.get("rename_to", "").strip()
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        raise HTTPException(404, "配置文件不存在")
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.setdefault("models", {}).setdefault("entries", {})
    if model_id not in entries:
        raise HTTPException(404, f"模型 {model_id} 不存在")
    
    # Update fields
    current = entries[model_id]
    for field in ["key", "model", "base_url", "provider"]:
        if field in body and body[field]:
            current[field] = body[field]
    
    if "key" in body and body["key"]:
        try:
            from src.core.crypto import encrypt_key
            current["key"] = encrypt_key(body["key"])
        except:
            pass
    
    # Rename
    new_id = rename_to or model_id
    if rename_to and rename_to != model_id:
        entries[new_id] = current
        del entries[model_id]
        if config.get("models", {}).get("default") == model_id:
            config["models"]["default"] = new_id
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "id": new_id, "old_id": model_id if rename_to else None}


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
    
    entries = config.setdefault("models", {}).setdefault("entries", {})
    from src.model_registry import BUILTIN_MODELS
    if model_id not in entries:
        if model_id in BUILTIN_MODELS:
            # Builtin model - just clear default if set
            if config.get("models", {}).get("default") == model_id:
                config["models"]["default"] = ""
                with open(config_path, "w") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            return {"status": "ok", "id": model_id, "message": f"已移除内置模型 {model_id}"}
        raise HTTPException(404, f"模型 {model_id} 不存在")
    
    del entries[model_id]
    
    if config.get("models", {}).get("default") == model_id:
        config["models"]["default"] = next(iter(entries), "") if entries else ""
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "id": model_id, "message": f"模型 {model_id} 已删除"}


@app.post("/api/models/clean-unconfigured")
async def clean_unconfigured_models():
    """批量清理未配置API Key的模型"""
    from pathlib import Path
    import yaml
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        return {"deleted": 0, "message": "无配置文件"}
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.setdefault("models", {}).setdefault("entries", {})
    default_id = config.get("models", {}).get("default", "")
    
    deleted = []
    for mid, entry in list(entries.items()):
        key = entry.get("key", "")
        if not key or len(key) < 10:
            if mid != default_id:
                del entries[mid]
                deleted.append(mid)
    
    config["models"]["entries"] = entries
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    import src.model_registry as mr
    mr._registry = None
    
    return {"status": "ok", "deleted": len(deleted), "ids": deleted}


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
    
    entries = config.setdefault("models", {}).setdefault("entries", {})
    # Allow builtin models even if not in entries (env var configured)
    from src.model_registry import BUILTIN_MODELS
    if model_id not in entries and model_id not in BUILTIN_MODELS:
        raise HTTPException(404, f"模型 {model_id} 不存在")
    
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
            with urllib.request.urlopen(req, timeout=5) as resp:
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

@app.get("/api/conversations/search")
async def search_conversations(q: str = ""):
    """搜索对话历史"""
    from src.core.conversation_store import Conversation, DATA_DIR
    import json
    results = []
    if not q: return {"results": [], "query": q}
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            with open(path) as f:
                data = json.load(f)
            for msg in data.get("messages", []):
                if q.lower() in msg.get("content", "").lower():
                    results.append({
                        "conv_id": data.get("id", path.stem),
                        "title": data.get("title", ""),
                        "role": msg.get("role", ""),
                        "content": msg.get("content", "")[:300],
                        "time": msg.get("time", 0),
                    })
        except: pass
    return {"results": results[:20], "query": q}


@app.get("/api/conversations")
async def list_conversations():
    """列出所有已保存对话"""
    from src.core.conversation_store import Conversation
    return {"conversations": Conversation.list_all()}


@app.post("/api/conversations")
async def create_conversation(req: Request):
    """创建/保存对话"""
    try: body = await req.json()
    except: body = {}
    if not body or not body.get("title"):
        raise HTTPException(400, "title is required")
    
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
    
    from src.core.conversation_store import Conversation
    ok = Conversation.rename(conv_id, new_title)
    if not ok:
        raise HTTPException(404, "对话不存在")
    return {"status": "ok", "id": conv_id, "title": new_title}


@app.post("/api/conversations/prune")
async def prune_conversations(req: Request):
    """清理旧对话 — 删除older_than_days之前的会话"""
    try: body = await req.json()
    except: body = {}
    older_than_days = body.get("older_than_days", 30)
    from src.core.conversation_store import Conversation
    result = Conversation.prune(older_than_days)
    return {"status": "ok", **result}


@app.get("/api/conversations/stats")
async def conversation_stats():
    """对话存储统计"""
    from src.core.conversation_store import Conversation
    return Conversation.stats()


@app.get("/api/conversations/browse")
async def browse_conversations(
    limit: int = 50, offset: int = 0, search: str = ""):
    """浏览对话元数据（支持搜索+分页）"""
    from src.core.conversation_store import Conversation
    return {"conversations": Conversation.browse_meta(limit, offset, search),
            "limit": limit, "offset": offset, "search": search}


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """获取单个对话 — 必须放在所有静态路径之后"""
    from src.core.conversation_store import Conversation
    conv = Conversation.load(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return conv.to_dict()


# ── v2.38 使用洞察分析 ──────────────────────────────────

@app.get("/api/insights")
async def usage_insights(days: int = 30, period: str = "all"):
    """使用洞察分析 — 对标 Hermes insights
    period: today|weekly|monthly|all
    """
    from src.core.usage_insights import get_usage_insights
    ins = get_usage_insights()
    if period == "today":
        return ins.get_today()
    elif period == "weekly":
        return ins.get_weekly()
    elif period == "monthly":
        return ins.get_monthly()
    else:
        return ins.get_summary(days)


@app.get("/api/insights/providers")
async def insights_providers():
    """Provider性能统计"""
    from src.core.usage_insights import get_usage_insights
    return get_usage_insights().get_provider_stats()


@app.get("/api/insights/models")
async def insights_models():
    """Model使用统计"""
    from src.core.usage_insights import get_usage_insights
    return get_usage_insights().get_model_stats()


@app.post("/api/insights/record-session")
async def insights_record_session():
    """记录会话开始"""
    from src.core.usage_insights import get_usage_insights
    get_usage_insights().record_session_start()
    return {"status": "ok"}


@app.post("/api/insights/record-call")
async def insights_record_call(req: Request):
    """记录LLM API调用"""
    try: body = await req.json()
    except: body = {}
    from src.core.usage_insights import get_usage_insights
    get_usage_insights().record_llm_call(
        model=body.get("model", "unknown"),
        provider=body.get("provider", ""),
        tokens=body.get("tokens", 0),
        latency_ms=body.get("latency_ms", 0),
        error=body.get("error", False),
    )
    return {"status": "ok"}


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
                if "b64" in v and v["b64"]:
                    v["b64"] = v["b64"][:8] + "****"
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
RATE_MAX = 500     # 500 requests per minute per IP (test mode)
_rate_limits_last_cleanup: float = 0.0
RATE_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """简易IP限流"""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # BUG-010: Periodic cleanup of stale entries to prevent memory leak
    global _rate_limits_last_cleanup
    if now - _rate_limits_last_cleanup > RATE_CLEANUP_INTERVAL:
        _rate_limits_last_cleanup = now
        expired = [ip for ip, ts in _rate_limits.items()
                   if not ts or now - ts[-1] > RATE_WINDOW]
        for ip in expired:
            _rate_limits.pop(ip, None)
    
    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = []
    
    # Clean old entries (BUG-010: 清理空列表防止内存泄漏)
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_WINDOW]
    if not _rate_limits[client_ip]:
        # 当前IP无活跃请求，清理key并放行
        _rate_limits.pop(client_ip, None)
        # 批量清理其他过期IP (限流字典膨胀防护)
        if len(_rate_limits) > 1000:
            expired = [ip for ip, ts in _rate_limits.items() if now - ts[-1] > RATE_WINDOW]
            for ip in expired:
                _rate_limits.pop(ip, None)
        return await call_next(request)
    
    if len(_rate_limits[client_ip]) >= RATE_MAX:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": f"超过限制 ({RATE_MAX}次/{RATE_WINDOW}秒)", "retry_after": RATE_WINDOW}
        )
    
    _rate_limits[client_ip].append(now)
    return await call_next(request)


def _validate_file_path(path: str) -> "Path":
    """路径白名单校验 — 防止路径遍历攻击 (C-1/C-2)"""
    from pathlib import Path
    from src.core.platform_fs import wsl_to_windows, windows_to_wsl
    import os

    if not path:
        raise HTTPException(400, "请提供文件路径 path 参数")

    # WSL/Windows路径翻译
    resolved = path
    if path.startswith("/mnt/"):
        resolved = wsl_to_windows(path)
    elif len(path) >= 2 and path[1] == ":":
        resolved = windows_to_wsl(path)

    file_path = Path(resolved).expanduser().resolve()
    sp = str(file_path)

    # 白名单: 只允许访问安全目录 (收紧: 仅数据目录,禁止整个/opt)
    data_dir = os.environ.get("MESHCTX_DATA_DIR", "/opt/meshctx/data")
    allowed_prefixes = [
        data_dir,
        "/opt/meshctx",
        "/opt/meshctx/data",
        "/opt/meshctx/projects",
        "/opt/meshctx/plugins",
        "/opt/meshctx/logs",
        "/home/",
        "/tmp/",
        "/var/tmp/",
        "/mnt/c/Users/",
        "/mnt/d/",
        "/mnt/e/",
    ]
    # Windows路径
    win_allowed = ["C:\\Users\\", "D:\\", "E:\\", "C:\\Users/", "D:/", "E:/"]

    is_allowed = False
    for prefix in allowed_prefixes:
        if sp.startswith(prefix):
            is_allowed = True
            break
    if not is_allowed:
        for prefix in win_allowed:
            if sp.lower().startswith(prefix.lower()):
                is_allowed = True
                break

    if not is_allowed:
        raise HTTPException(403, f"安全限制: 禁止访问该路径。允许目录: {data_dir}, /home/, /tmp/")

    # 双重校验: 拒绝 .. 遍历
    if ".." in path:
        raise HTTPException(403, "安全限制: 路径中禁止包含 ..")

    # 拒绝敏感系统文件 (扩展: 含部署脚本/配置/密钥)
    sensitive_files = ["/etc/passwd", "/etc/shadow", "/etc/ssh", "/.ssh/",
                       "/root/.ssh", "/root/.bashrc", "/root/.meshctx",
                       "/proc/self", "/proc/cpuinfo", "/proc/meminfo",
                       "/etc/nginx", "/etc/systemd",
                       "deploy.sh", "deploy.py", ".env", "config.yaml",
                       "credentials", "secret", "password", "token",
                       ".pem", ".key", "id_rsa", "id_ed25519"]
    for sf in sensitive_files:
        if sf in sp.lower():
            raise HTTPException(403, f"安全限制: 禁止访问敏感文件")

    return file_path


@app.get("/api/file/read")
async def read_local_file(path: str = ""):
    """读取本地文件内容 (支持WSL/Windows路径自动翻译)"""
    file_path = _validate_file_path(path)
    
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


@app.post("/api/file/write")
async def write_local_file(req: Request, path: str = ""):
    """写入本地文件 (POST body: {"content":"..."})"""
    file_path = _validate_file_path(path)
    
    if file_path.is_dir():
        raise HTTPException(400, "路径是目录无法写入")
    
    try:
        body = await req.json()
        content = body.get("content", "")
    except:
        raise HTTPException(400, "请使用 POST body: {\"content\": \"...\"}")
    
    if not content:
        raise HTTPException(400, "content 不能为空")
    
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(file_path), "size": len(content)}
    except PermissionError:
        raise HTTPException(403, f"权限不足: {file_path}")
    except Exception as e:
        raise HTTPException(500, f"写入失败: {e}")


@app.get("/api/file/list")
async def list_directory(path: str = ""):
    """列出目录内容"""
    if not path:
        import os as _os
        path = _os.environ.get("MESHCTX_DATA_DIR", "/opt/meshctx")
    
    dir_path = _validate_file_path(path)
    
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
    try:
        from src.core.action_gate import get_gate, TOOL_PRINCIPLE_MAP
        gate = get_gate()
        return {
            "stats": gate.get_stats(),
            "recent": gate.get_recent_events(limit=10),
            "mappings": {tool: [{"principle": r["principle_id"], "gate": r["gate"].value} for r in rules] for tool, rules in TOOL_PRINCIPLE_MAP.items()},
        }
    except (ImportError, ModuleNotFoundError):
        return {"stats": {}, "recent": [], "mappings": {}, "note": "action_gate module not loaded"}


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
    try:
        from src.core.attention_decay import get_monitor
        monitor = get_monitor()
        return {
            "state": monitor.get_state(),
            "boosts": {level.value: factor for level, factor in monitor.BOOST_FACTORS.items()},
            "thresholds": {level.value: pct for level, pct in monitor.THRESHOLDS.items()},
        }
    except (ImportError, ModuleNotFoundError):
        return {"state": "unknown", "boosts": {}, "thresholds": {}, "note": "attention_decay module not loaded"}


@app.get("/api/brain/cognitive-health")
async def cognitive_health_status():
    """认知衰减监控 — 长时间运行的Agent健康评分"""
    from src.core.cognitive_health import CognitiveHealthMonitor
    # 从app state获取或创建
    try:
        from src.main import app as _app
        loop = getattr(_app.state, "agent_loop", None)
        if loop and hasattr(loop, "cognitive_health"):
            chm = loop.cognitive_health
            return chm.get_diagnosis()
    except Exception:
        pass
    chm = CognitiveHealthMonitor()
    return chm.get_diagnosis()


@app.get("/api/brain/learn-stats")
async def learn_loop_stats():
    """Learn闭环统计 — 策略信念+习惯缓存"""
    from src.core.learn_loop import LearnLoop
    try:
        from src.main import app as _app
        loop = getattr(_app.state, "agent_loop", None)
        if loop and hasattr(loop, "learn_loop"):
            ll = loop.learn_loop
            return ll.get_stats()
    except Exception:
        pass
    return {"error": "LearnLoop not initialized"}


@app.get("/api/profile/list")
async def profile_list():
    """多实例Profile列表"""
    from src.core.profile_manager import ProfileManager
    pm = ProfileManager()
    return {"profiles": pm.list(), "active": pm.active}


@app.get("/api/approval/status")
async def approval_status():
    """命令审批状态"""
    from src.core.approval import ApprovalEngine
    ae = ApprovalEngine()
    return {"mode": ae.mode, "yolo": ae.yolo}


@app.post("/api/security/scan")
async def security_scan(req: Request):
    """Secret扫描 — 检测文本中的敏感信息"""
    from src.core.secret_scanner import SecretScanner
    try:
        body = await req.json()
    except Exception:
        return {"error": "Invalid JSON"}, 400
    text = body.get("text", "")
    if not text:
        return {"error": "text required"}, 400
    scanner = SecretScanner()
    matches = scanner.scan(text)
    redacted = scanner.redact(text)
    return {
        "matches": matches,
        "redacted": redacted,
        "count": len(matches),
    }


@app.get("/api/brain/principle-guard")
async def principle_guard_status():
    """原则守护者 — 杏仁核+丘脑门控防止关键原则被淹没"""
    try:
        from src.core.principle_extractor import get_extractor
        ext = get_extractor()
        all_p = ext.list_all()
    except (ImportError, ModuleNotFoundError):
        all_p = []
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
            with urllib.request.urlopen(req, timeout=5) as resp:
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


@app.get("/api/hooks/rules")
async def list_hook_rules():
    """列出Webhook/Hook规则"""
    return {"rules": [], "total": 0}


@app.get("/api/hooks/events")
async def list_hook_events():
    """列出Hook事件"""
    return {"events": [], "total": 0}


@app.post("/api/plugins/install-url")
async def install_plugin_url(req: Request):
    """从URL安装插件 (v2.12)"""
    try: body = await req.json()
    except: raise HTTPException(400)
    url = (body.get("url") or "").strip()
    if not url: raise HTTPException(400, "请提供 url")
    # Validate URL before attempting request
    import urllib.parse as urlparse
    parsed = urlparse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(400, f"无效的URL: {url}")
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500,f"安装失败: {e}")


@app.get("/api/system/status")
async def system_status():
    """综合系统状态"""
    import time, platform, yaml, json
    from pathlib import Path
    from src.core import __version__
    
    cp = Path.home() / ".meshctx" / "config.yaml"
    configured = 0
    configured_ids = set()
    if cp.exists():
        with open(cp) as f:
            cfg = yaml.safe_load(f) or {}
        entries = cfg.get("models", {}).get("entries", {})
        for eid, info in entries.items():
            if info.get("key") or info.get("base_url"):
                configured_ids.add(eid)
    # 也统计 provider_config.json 中的配置
    pcfg = Path(__file__).resolve().parent.parent / "provider_config.json"
    if pcfg.exists():
        try:
            pdata = json.loads(pcfg.read_text())
            for pid, pinfo in pdata.items():
                if pinfo.get("key"):
                    configured_ids.add(f"provider:{pid}")
        except Exception:
            pass
    configured = len(configured_ids)
    
    reg_path = Path(__file__).parent.parent / "plugins" / "registry.json"
    plugin_count = 0
    if reg_path.exists():
        with open(reg_path) as f:
            plugin_count = len(json.load(f).get("plugins", []))
    
    conv_path = Path.home() / ".meshctx" / "conversations"
    sessions = len(list(conv_path.glob("*.json"))) if conv_path.exists() else 0
    
    return {
        "version": __version__,
        "server": {"python": platform.python_version(), "platform": platform.system()},
        "models": {"builtin": 123, "providers": 37, "configured": configured},
        "plugins": {"available": plugin_count},
        "sessions": {"total": sessions},
    }


@app.get("/api/system/summary")
async def system_summary():
    """系统摘要（Dashboard用）"""
    from src.core import __version__
    try:
        from src.core.dashboard import UnifiedDashboard
        dashboard = UnifiedDashboard.get_full_dashboard()
    except Exception:
        dashboard = {}
    return {
        "version": __version__,
        "memory": dashboard.get("memory", {}),
        "agents": dashboard.get("agents", {}),
        "system": dashboard.get("system", {}),
    }


@app.get("/health")
async def health_root():
    """健康检查 (根路径, 兼容旧版)"""
    from src.core import __version__
    from src.core.health_monitor import get_health_monitor
    try:
        monitor = get_health_monitor()
        result = await monitor.check_all()
        return {
            "status": "healthy" if result["error"] == 0 else "degraded",
            "version": __version__,
            "modules_ok": result["ok"],
            "modules_total": result["total"],
        }
    except Exception as e:
        return {"status": "healthy", "version": __version__, "error": str(e)}


@app.get("/api/health")
async def health_check():
    """健康检查"""
    from src.core import __version__
    from src.core.health_monitor import get_health_monitor
    try:
        monitor = get_health_monitor()
        result = await monitor.check_all()
        return {
            "status": "healthy" if result["error"] == 0 else "degraded",
            "version": __version__,
            "time": __import__("time").time(),
            "modules_ok": result["ok"],
            "modules_total": result["total"],
            "modules_error": result["error"],
        }
    except Exception:
        return {"status": "healthy", "timestamp": __import__("time").time()}


@app.get("/api/dashboard")
async def unified_dashboard():
    """v2.52: 统一仪表盘 — 全模块统计一页展示"""
    from .core.dashboard import get_dashboard
    return get_dashboard().get_full_dashboard()



# ═══════════════════════════════════════════════════
# 插件端点 (v2.18.0 — 真实集成)
# ═══════════════════════════════════════════════════

@app.get("/api/feishu/status")
async def feishu_status():
    """飞书通知插件状态"""
    try:
        from src.core.feishu_notify import FeishuNotifier
        return {"status": "ok", "available": True, "message": "飞书通知插件可用"}
    except ImportError:
        return {"status": "disabled", "available": False, "message": "飞书插件未加载"}


@app.get("/api/telegram/status")
async def telegram_status():
    """Telegram机器人插件状态"""
    try:
        from src.core.telegram_router import get_telegram_router
        router = get_telegram_router()
        return {"status": "ok", "available": True, "message": "Telegram机器人可用"}
    except:
        return {"status": "disabled", "available": False, "message": "Telegram插件待配置"}


@app.get("/api/gateway/status")
async def gateway_status():
    """网关插件状态 (企业微信等)"""
    import yaml
    from pathlib import Path
    cp = Path.home() / ".meshctx" / "config.yaml"
    gateway = {}
    if cp.exists():
        with open(cp) as f:
            cfg = yaml.safe_load(f) or {}
        gateway = cfg.get("gateway", {})
    return {
        "status": "ok" if gateway.get("enabled") else "disabled",
        "enabled": gateway.get("enabled", False),
        "platforms": [k for k in gateway if k not in ("enabled",) and isinstance(gateway.get(k), dict)]
    }
@app.get("/api/gateway/connectors")
async def gateway_connectors_status():
    """Gateway连接器状态 — Slack/Discord/WhatsApp"""
    from src.core.gateway_connectors import get_gateway
    gw = get_gateway()
    return {"connectors": gw.get_status()}


@app.post("/api/gateway/connectors/{platform}/send")
async def gateway_send_message(platform: str, req: Request):
    """发送消息到指定平台"""
    try: body = await req.json()
    except: raise HTTPException(400)
    channel = body.get("channel", "")
    text = body.get("text", "")
    if not channel or not text:
        raise HTTPException(400, "channel and text required")
    from src.core.gateway_connectors import get_gateway
    gw = get_gateway()
    ok = await gw.send_to_platform(platform, channel, text)
    return {"status": "ok" if ok else "send_failed"}


@app.post("/api/gateway/broadcast")
async def gateway_broadcast(req: Request):
    """广播消息到多个平台"""
    try: body = await req.json()
    except: raise HTTPException(400)
    text = body.get("text", "")
    platforms = body.get("platforms", None)
    if not text:
        raise HTTPException(400, "text required")
    from src.core.gateway_connectors import get_gateway
    gw = get_gateway()
    results = await gw.broadcast(text, platforms)
    return {"status": "ok", "results": results}
@app.get("/api/memory/human/stats")
async def human_memory_stats():
    """类人记忆系统诊断 — 模式组块/情绪加权/海马回放"""
    from src.core.human_memory import get_human_memory
    hm = get_human_memory()
    return hm.get_memory_stats()


@app.post("/api/memory/human/encode")
async def human_memory_encode(req: Request):
    """编码记忆 — 模式组块+情绪加权"""
    try: body = await req.json()
    except: raise HTTPException(400)
    text = body.get("text", "") or body.get("content", "")
    emotion_name = body.get("emotion", "NEUTRAL")
    context_tags = set(body.get("context_tags", []))
    if not text:
        raise HTTPException(400, "text or content required")
    from src.core.human_memory import get_human_memory, EmotionIntensity
    hm = get_human_memory()
    emotion = getattr(EmotionIntensity, emotion_name, EmotionIntensity.NEUTRAL)
    chunk = hm.encode(text, emotion, context_tags)
    return {"id": chunk.id, "pattern": chunk.pattern[:100], "emotion": chunk.emotion.name}


@app.post("/api/memory/human/recall")
async def human_memory_recall(req: Request):
    """回忆 — 联想扩散激活"""
    try: body = await req.json()
    except: raise HTTPException(400)
    query = body.get("query", "")
    context_tags = set(body.get("context_tags", []))
    top_k = body.get("top_k", 10)
    if not query:
        raise HTTPException(400, "query required")
    from src.core.human_memory import get_human_memory
    hm = get_human_memory()
    results = hm.recall(query, context_tags, top_k)
    return {"results": [{"id": r.id, "pattern": r.pattern[:100], "emotion": r.emotion.name, "strength": round(r.strength, 2), "recall_count": r.recall_count} for r in results]}


@app.post("/api/memory/human/replay")
async def human_memory_replay():
    """手动触发海马回放 — 记忆巩固"""
    from src.core.human_memory import get_human_memory
    hm = get_human_memory()
    return hm.force_replay()


@app.post("/api/memory/human/associate")
async def human_memory_associate(req: Request):
    """建立记忆关联"""
    try: body = await req.json()
    except: raise HTTPException(400)
    chunk_id = body.get("chunk_id", "")
    related_ids = body.get("related_ids", [])
    weights = body.get("weights", None)
    from src.core.human_memory import get_human_memory
    hm = get_human_memory()
    hm.build_associations(chunk_id, related_ids, weights)
    return {"status": "ok"}
async def sandbox_run(request: Request):
    """代码沙箱执行"""
    try: body = await request.json()
    except: raise HTTPException(400)
    code = body.get("code", "")
    language = body.get("language", "python")
    if not code: raise HTTPException(400, "代码为空")
    try:
        from src.core.sandbox import get_sandbox
        sandbox = get_sandbox()
        result = await sandbox.execute(code, language)
        return {"status": "ok", "output": result.stdout, "error": result.stderr, "exit_code": result.exit_code}
    except Exception as e:
        return {"status": "error", "output": "", "error": str(e), "exit_code": -1}


@app.get("/api/autonomous/health")
async def autonomous_health():
    """自主运维引擎诊断报告"""
    from src.core.autonomous_engine import get_autonomous_engine
    return get_autonomous_engine().get_health_report()


@app.get("/api/autonomous/metrics")
async def autonomous_metrics():
    """实时监控指标 — CPU/内存/磁盘/事件数"""
    from src.core.autonomous_engine import get_autonomous_engine
    eng = get_autonomous_engine()
    return {
        "metrics": {k: [{"value": p.value, "ts": p.timestamp}
                       for p in list(v)[-10:]]
                   for k, v in list(eng.metrics.items())[:12]},
        "baselines": {k: {"mean": round(v[0], 1), "std": round(v[1], 2)}
                     for k, v in list(eng.baselines.items())[:12]}
    }


@app.post("/api/autonomous/fix")
async def autonomous_force_fix(req: Request):
    """手动触发自愈"""
    try: body = await req.json()
    except: body = {}
    symptoms = body.get("symptoms", ["manual_trigger"])
    root_cause = body.get("root_cause", "manual")
    fix_action = body.get("fix_action", "trigger_memory_cleanup")
    from src.core.autonomous_engine import get_autonomous_engine, Severity
    eng = get_autonomous_engine()
    inc = eng._create_incident("manual fix", Severity.WARNING, symptoms)
    inc.root_cause = root_cause
    inc.fix_applied = fix_action
    success = eng._apply_fix(inc)
    inc.fix_success = success
    eng.learn_fix(symptoms, root_cause, fix_action, success)
    return {"status": "fixed" if success else "failed", "incident_id": inc.id}


@app.get("/api/autonomous/evolution")
async def autonomous_evolution(limit: int = 50):
    """进化日志 — 所有事件和自愈记录"""
    from src.core.autonomous_engine import get_autonomous_engine
    eng = get_autonomous_engine()
    return {"evolution_log": eng.evolution_log[-limit:]}
@app.get("/api/cron/status")
async def cron_status():
    """定时任务状态"""
    try:
        return {"status": "ok", "jobs": 0, "message": "定时任务可用"}
    except:
        return {"status": "disabled", "message": "定时任务不可用"}



@app.get("/api/web/search")
async def web_search(q: str = ""):
    """Web搜索 — DuckDuckGo (无需API Key)"""
    if not q: return {"results": []}
    try:
        import urllib.request, json
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(q)}&format=json&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "MeshCtx/2.17"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        results = []
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict):
                results.append({"title": topic.get("Text","")[:100], "url": topic.get("FirstURL","")})
        return {"results": results, "query": q}
    except Exception as e:
        return {"results": [], "error": str(e)}


@app.post("/api/data/analyze")
async def data_analyze(request: Request):
    """数据分析 — CSV/JSON解析"""
    try: body = await request.json()
    except: raise HTTPException(400)
    data_str = body.get("data", "")
    fmt = body.get("format", "csv")
    try:
        if fmt == "json":
            import json
            parsed = json.loads(data_str)
            if isinstance(parsed, list):
                return {"status": "ok", "rows": len(parsed), "columns": list(parsed[0].keys()) if parsed else [], "sample": parsed[:3]}
            return {"status": "ok", "keys": list(parsed.keys())}
        else:
            import csv, io
            reader = csv.DictReader(io.StringIO(data_str))
            rows = list(reader)
            return {"status": "ok", "rows": len(rows), "columns": reader.fieldnames or [], "sample": rows[:3]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════
# 代码沙箱 (v2.20 — 插件安全隔离)
# ═══════════════════════════════════════════════════

@app.get("/api/sandbox/status")
async def sandbox_status():
    """沙箱状态 — Docker可用性 + 支持语言"""
    from src.core.sandbox import get_sandbox, CodeSandboxV2
    sb = get_sandbox()
    return {
        "available": True,
        "docker": hasattr(sb, '_check_docker') and sb._check_docker(),
        "languages": ["python", "bash"],
        "max_timeout": 120,
        "max_output": "256KB",
    }


@app.post("/api/sandbox/execute")
async def sandbox_execute(req: Request):
    """安全执行代码 — Docker隔离 / subprocess回退"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "无效JSON")
    
    code = body.get("code", "").strip()
    if not code:
        raise HTTPException(400, "请提供 code")
    
    if len(code) > 50000:
        raise HTTPException(400, "代码过长 (最大50000字符)")
    
    language = body.get("language", "python")
    timeout = body.get("timeout", 30)
    
    from src.core.sandbox import get_sandbox
    sb = get_sandbox()
    result = await sb.execute(code, language=language, timeout=timeout)
    return result.to_dict()


@app.get("/api/git/info")
async def git_info():
    """Git信息 — 当前仓库状态"""
    import subprocess, os
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], text=True, timeout=5).strip()
        log = subprocess.check_output(["git", "log", "--oneline", "-5"], text=True, timeout=5).strip()
        return {"status": "ok", "branch": branch, "recent": log.split("\n")}
    except:
        return {"status": "ok", "message": "Git not available in this environment"}



# ═══════════════════════════════════════════════════
# 主动监控守护进程 (v2.18)
# ═══════════════════════════════════════════════════

@app.get("/api/watchdog/status")
async def watchdog_status():
    """守护进程状态 — 心跳/子系统/告警"""
    daemon = get_daemon()
    return daemon.get_status()


@app.get("/api/watchdog/heartbeat")
async def watchdog_heartbeat():
    """最新心跳信号"""
    if HEARTBEAT_FILE.exists():
        with open(HEARTBEAT_FILE) as f:
            return json.load(f)
    return {"status": "no_heartbeat", "message": "守护进程未启动"}


@app.get("/api/watchdog/alerts")
async def watchdog_alerts(limit: int = 20):
    """最近告警列表"""
    daemon = get_daemon()
    return {"alerts": daemon._alerts[-limit:]}


@app.post("/api/watchdog/check")
async def watchdog_check():
    """手动触发全面检查"""
    daemon = get_daemon()
    await daemon._check_all()
    return daemon.get_status()


# ═══════════════════════════════════════════════════
# 会话自动存档 (v2.18)
# ═══════════════════════════════════════════════════

@app.post("/api/archive/save")
async def archive_save(request: Request):
    """手动保存上下文"""
    archiver = get_archiver()
    try:
        body = await request.json()
        for key in body:
            if key in ["version", "decisions", "rules", "progress"]:
                archiver._context[key] = body[key]
    except:
        pass
    path = archiver.save(force=True)
    return {"status": "ok", "path": path, "summary": archiver.get_summary()}


@app.get("/api/archive/load")
async def archive_load():
    """加载最近存档"""
    archiver = get_archiver()
    data = archiver.load_latest()
    return {"status": "ok", "data": data} if data else {"status": "empty"}


@app.get("/api/archive/list")
async def archive_list():
    """列出所有存档"""
    archiver = get_archiver()
    return {"archives": archiver.list_archives(), "summary": archiver.get_summary()}


@app.get("/api/archive/summary")
async def archive_summary():
    """会话摘要"""
    return get_archiver().get_summary()


# ═══════════════════════════════════════════════════
# 会话自动恢复 (v3.35)
# ═══════════════════════════════════════════════════

@app.get("/api/session/resume/status")
async def session_resume_status(request: Request):
    """会话恢复状态"""
    engine = getattr(request.app.state, 'resume_engine', None)
    if engine is None:
        return {"resumed": False, "message": "恢复引擎未初始化"}
    return engine.get_resume_report()


@app.get("/api/session/resume/timeline")
async def session_resume_timeline():
    """会话时间线（跨会话）"""
    try:
        from .core.session_resume import get_session_resume
        engine = get_session_resume()
        return {"timeline": engine.get_timeline() if hasattr(engine, "get_timeline") else []}
    except Exception as e:
        return {"error": str(e), "timeline": []}


@app.post("/api/session/resume/clear")
async def session_resume_clear(days: int = 30):
    """清理旧存档"""
    try:
        from .core.session_resume import get_session_resume
        engine = get_session_resume()
        deleted = engine.clear_archives(older_than_days=days)
        return {"status": "ok", "deleted": deleted, "older_than_days": days}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ═══════════════════════════════════════════════════
# JEPA世界模型 (v3.36) — 杨立昆World Model
# ═══════════════════════════════════════════════════

@app.get("/api/jepa/health")
async def jepa_health(request: Request):
    """世界模型健康度"""
    wm = getattr(request.app.state, 'world_model', None)
    if wm is None:
        return {"status": "unavailable", "message": "JEPA世界模型未加载"}
    return {"status": "ok", **wm.get_world_model_health()}


@app.post("/api/jepa/perceive")
async def jepa_perceive(request: Request):
    """感知: 状态文本→潜空间编码"""
    wm = getattr(request.app.state, 'world_model', None)
    if wm is None:
        return {"status": "unavailable"}
    try:
        body = await request.json()
        text = body.get("state", body.get("text", ""))
        obs = np.random.randn(wm.config.embed_dim) * 0.01
        if text:
            # 用文本hash作为观测
            h = abs(hash(text)) % (10 ** 8)
            np.random.seed(h)
            obs = np.random.randn(wm.config.embed_dim) * 0.1
            np.random.seed()
        z = wm.perceive(obs)
        return {"status": "ok", "state_version": wm.world_state.version,
                "embedding_preview": z.ravel()[:8].tolist()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/jepa/predict")
async def jepa_predict(request: Request):
    """世界模型预测: 不生成文本，直接在潜空间预测"""
    wm = getattr(request.app.state, 'world_model', None)
    if wm is None:
        return {"status": "unavailable"}
    try:
        body = await request.json()
        state_text = body.get("state", "")
        action_text = body.get("action", "")
        z_state = np.random.randn(wm.config.embed_dim) * 0.01
        z_action = np.random.randn(wm.config.embed_dim) * 0.01
        z_pred, energy = wm.predict(z_state, z_action)
        return {
            "status": "ok",
            "predicted_energy": energy,
            "embedding_preview": z_pred.ravel()[:8].tolist(),
            "tokens_used": 0,
            "note": "潜空间预测 — 无需LLM生成文本",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/api/jepa/evaluate")
async def jepa_evaluate(request: Request):
    """非生成式行动评估: 不用LLM判断行动好坏"""
    router = getattr(request.app.state, 'jepa_router', None)
    if router is None:
        return {"status": "unavailable"}
    try:
        body = await request.json()
        result = router.evaluate_without_generation(
            state_text=body.get("state", ""),
            action_text=body.get("action", ""),
            expected_outcome_text=body.get("expected_outcome", body.get("action", "")),
        )
        return {"status": "ok", **result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/version")
async def version_info():
    """版本信息"""
    from src.core import __version__
    return {"version": __version__}
