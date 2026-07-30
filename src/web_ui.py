"""
meshctx Web 管理界面
FastAPI + Jinja2 DictLoader（模板内嵌，适配 PyInstaller）
"""
import sys
import yaml
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import logging

logger = logging.getLogger("meshctx.webui")

# ── 内嵌模板（绕过 PyInstaller 文件系统问题）───────────────────



# ── DictLoader 初始化 ───────────────────────────────────────────
from src.i18n import t as i18n_t, get_lang as i18n_get_lang, TRANSLATIONS as i18n_translations, LANGUAGES, LANGUAGE_CODES
_jinja_env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), '..', 'templates')), autoescape=False)
_jinja_env.globals['t'] = i18n_t
_jinja_env.globals['lang'] = i18n_get_lang

# v3.115.16: 内存优化 — 缓存 i18n JSON 序列化结果 (避免每请求 json.dumps 73KB)
_i18n_json_cache = {}

def _get_i18n_json(lang: str) -> str:
    """获取语言翻译 JSON 字符串（缓存，避免每请求序列化）"""
    if lang not in _i18n_json_cache:
        _i18n_json_cache[lang] = __import__('json').dumps(
            i18n_translations.get(lang, i18n_translations.get('en', {})),
            ensure_ascii=False
        )
    return _i18n_json_cache[lang]

def _get_i18n_all_json() -> str:
    """QA6: 注入全部语言到主 SPA，支持 switchLang 无刷新切换"""
    if '_all' not in _i18n_json_cache:
        all_i18n = {}
        for lc in LANGUAGE_CODES:
            all_i18n[lc] = i18n_translations.get(lc, {})
        _i18n_json_cache['_all'] = __import__('json').dumps(all_i18n, ensure_ascii=False)
    return _i18n_json_cache['_all']

def _render(template_name: str, context: dict, request = None) -> HTMLResponse:
    """渲染 Jinja2 模板（从内嵌 DictLoader），自动检测浏览器语言"""
    lang = i18n_get_lang(request)
    # 绑定 t() 到检测到的语言（避免全局状态竞争）
    def _scoped_t(key: str) -> str:
        return i18n_translations.get(lang, i18n_translations.get('en', {})).get(key, i18n_translations.get('en', {}).get(key, key))
    context['t'] = _scoped_t
    context['__i18n_json'] = _get_i18n_json(lang)
    context['__i18n_all_json'] = _get_i18n_all_json()
    context['__lang'] = lang
    # Inject configurable local model hosts (BUG-005 fix)
    import os as _os
    context.setdefault('ollama_host', _os.environ.get('MESHCTX_OLLAMA_HOST', 'localhost'))
    context.setdefault('vllm_host', _os.environ.get('MESHCTX_VLLM_HOST', 'localhost'))
    context.setdefault('localai_host', _os.environ.get('MESHCTX_LOCALAI_HOST', 'localhost'))
    # 注入支持的语言列表供 JS 使用（缓存）
    if '_langs_json' not in _i18n_json_cache:
        _i18n_json_cache['_langs_json'] = __import__('json').dumps(
            i18n_translations.get('en', {}).get('__available_langs__',
                [{"code": lang["code"], "name": lang["name"], "native": lang["native"]} for lang in LANGUAGES])
        )
    context['__languages'] = _i18n_json_cache['_langs_json']
    template = _jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(html)

router = APIRouter(prefix="/ui", tags=["Web UI"])


# ── 工具函数 ─────────────────────────────────────────────────

def _engine(request: Request):
    """获取 memory_engine 实例"""
    return request.app.state.memory_engine

def _continuity_label(score: float) -> str:
    if score >= 0.7:
        return "优秀"
    elif score >= 0.5:
        return "良好"
    elif score >= 0.3:
        return "一般"
    return "断裂"

def _continuity_color(score: float) -> str:
    if score >= 0.7:
        return "#22c55e"
    elif score >= 0.5:
        return "#eab308"
    elif score >= 0.3:
        return "#f97316"
    return "#ef4444"

def _format_dt(dt):
    """格式化日期时间"""
    if dt is None:
        return "-"
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)[:19]

def _truncate(s: str, n: int = 60) -> str:
    if s is None:
        return ""
    if len(s) <= n:
        return s
    return s[:n] + "..."

# ── 仪表板首页 ───────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    # v3.115.16: N+1 optimization — single-pass grouping
    convs_by_pid = {}
    for c in engine.conversations.values():
        pid = getattr(c, 'project_id', None)
        if pid:
            convs_by_pid.setdefault(pid, []).append(c)
    mems_by_pid = {}
    for m in engine.memories.values():
        pid = getattr(m, 'project_id', None)
        if pid:
            mems_by_pid.setdefault(pid, []).append(m)
    sessions_by_pid = {}
    for s in getattr(engine, 'agent_sessions', {}).values():
        pid = getattr(s, 'project_id', None)
        if pid:
            sessions_by_pid.setdefault(pid, []).append(s)

    project_data = []
    total_conversations = 0
    total_memories = 0
    total_agents = 0
    total_sessions = 0

    for p in projects:
        try:
            continuity = engine.detect_continuity(p.id)
        except Exception:
            continuity = {"continuity_score": 0, "is_continuous": False,
                          "conversation_count": 0, "memory_count": 0,
                          "active_session_count": 0, "total_session_count": 0,
                          "last_active": None}
        convs = convs_by_pid.get(p.id, [])
        total_conversations += len(convs)
        memories = mems_by_pid.get(p.id, [])
        total_memories += len(memories)
        sessions = sessions_by_pid.get(p.id, [])
        total_sessions += len(sessions)
        project_data.append({
            "project": p,
            "continuity": continuity,
            "conv_count": len(convs),
            "mem_count": len(memories),
            "session_count": len(sessions),
        })

    agents = list(engine.agents.values())
    total_agents = len(agents)

    safe_project_data = []
    for d in project_data:
        p = d["project"]
        safe_project_data.append({
            "project": {"id": p.id, "name": p.name, "description": p.description,
                       "status": p.status, "created_at": _format_dt(p.created_at),
                       "updated_at": _format_dt(p.updated_at)},
            "continuity": d["continuity"],
            "conv_count": d["conv_count"],
            "mem_count": d["mem_count"],
            "session_count": d["session_count"],
        })

    return _render("dashboard.html", {
        "request": request,
        "title": "meshctx 管理面板",
        "project_data": safe_project_data,
        "total_projects": len(projects),
        "total_conversations": total_conversations,
        "total_memories": total_memories,
        "total_agents": total_agents,
        "total_sessions": total_sessions,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
        "format_dt": _format_dt,
        "truncate": _truncate,
    }, request)

# ── 项目管理 ─────────────────────────────────────────────────

@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    # v3.115.16: N+1 optimization — single-pass grouping instead of per-project scans
    conversations_by_project = {}
    for c in engine.conversations.values():
        pid = getattr(c, 'project_id', None)
        if pid:
            conversations_by_project.setdefault(pid, []).append(c)
    
    memories_by_project = {}
    for m in engine.memories.values():
        pid = getattr(m, 'project_id', None)
        if pid:
            memories_by_project.setdefault(pid, []).append(m)

    enriched = []
    for p in projects:
        convs = conversations_by_project.get(p.id, [])
        mems = memories_by_project.get(p.id, [])
        try:
            cont = engine.detect_continuity(p.id)
        except Exception:
            cont = {"continuity_score": 0, "last_active": None}
        enriched.append({
            "project": p,
            "conv_count": len(convs),
            "mem_count": len(mems),
            "continuity": cont,
        })

    enriched.sort(key=lambda x: x["project"].updated_at, reverse=True)

    return _render("projects.html", {
        "request": request,
        "title": "项目管理",
        "projects": enriched,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    }, request)

@router.get("/projects/create")
async def create_project_page(request: Request):
    """redirect GET to projects list (creation is inline)"""
    return RedirectResponse(url="/ui/projects", status_code=303)

@router.post("/projects/create")
async def create_project_ui(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    engine = _engine(request)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    engine.create_project(name, description, tag_list)
    return RedirectResponse(url="/ui/projects", status_code=303)

@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    engine = _engine(request)
    project = engine.get_project(project_id)
    if not project:
        return HTMLResponse("<h2>项目不存在</h2>", status_code=404)

    conversations = engine.list_conversations(project_id)
    memories = engine.get_memories(project_id)
    sessions = engine.get_agent_sessions(project_id=project_id)

    try:
        continuity = engine.detect_continuity(project_id)
    except Exception:
        continuity = {"continuity_score": 0, "is_continuous": False}

    conv_data = []
    for c in conversations:
        msgs = engine.get_messages(c.id, limit=200)
        active_sessions = [s for s in sessions if s.conversation_id == c.id and s.ended_at is None]
        conv_data.append({
            "conversation": c,
            "message_count": len(msgs),
            "active_sessions": active_sessions,
        })

    conv_data.sort(key=lambda x: x["conversation"].updated_at, reverse=True)

    return _render("project_detail.html", {
        "request": request,
        "title": f"项目: {project.name}",
        "project": project,
        "conversations": conv_data,
        "memories": memories,
        "continuity": continuity,
        "agent_sessions": sessions,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    }, request)

@router.post("/projects/{project_id}/delete")
async def delete_project_ui(request: Request, project_id: str):
    engine = _engine(request)
    engine.delete_project(project_id)
    return RedirectResponse(url="/ui/projects", status_code=303)

# ── 会话查看 ─────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def conversation_view(request: Request, conversation_id: str):
    engine = _engine(request)
    conv = engine.get_conversation(conversation_id)
    if not conv:
        return HTMLResponse("<h2>会话不存在</h2>", status_code=404)

    messages = engine.get_messages(conversation_id, limit=200)
    project = engine.get_project(conv.project_id)

    return _render("conversation.html", {
        "request": request,
        "title": f"会话: {conv.title}",
        "conversation": conv,
        "project": project,
        "messages": messages,
        "format_dt": _format_dt,
        "truncate": _truncate,
    }, request)

# ── 记忆浏览 ─────────────────────────────────────────────────

class _OldMemoryAdapter:
    """适配旧 Memory 模型（key/value）到模板期望的 content 属性"""
    def __init__(self, m):
        self._m = m
    @property
    def id(self): return self._m.id
    @property
    def content(self): return getattr(self._m, 'content', None) or getattr(self._m, 'value', '')
    @property
    def importance(self): return self._m.importance
    @property
    def created_at(self): return self._m.created_at
    @property
    def project_id(self): return getattr(self._m, 'project_id', '')

class _V2MemoryAdapter:
    """适配 memory_v2 MemoryEntry 到模板期望的接口"""
    def __init__(self, entry):
        self._e = entry
    @property
    def id(self): return self._e.id
    @property
    def content(self): return self._e.content
    @property
    def importance(self): return self._e.importance
    @property
    def created_at(self): return self._e.created_at
    @property
    def project_id(self): return ''

@router.get("/memories", response_class=HTMLResponse)
async def memories_overview(request: Request):
    """所有项目的记忆总览（旧引擎 + memory_v2）"""
    engine = _engine(request)
    projects = engine.list_projects()
    all_memories = []

    # 旧引擎记忆
    for p in projects:
        mems = engine.get_memories(p.id)
        for m in mems:
            all_memories.append({
                "memory": _OldMemoryAdapter(m),
                "project_name": p.name,
            })

    # memory_v2 记忆
    try:
        from src.core.memory_v2 import get_memory_manager
        mgr = get_memory_manager()
        for entry in mgr.list_by_type():
            all_memories.append({
                "memory": _V2MemoryAdapter(entry),
                "project_name": "🧠 Memory V2",
            })
    except Exception:
        logger.debug("Suppressed except Exception:: {}", exc_info=True)

    all_memories.sort(key=lambda x: x["memory"].importance, reverse=True)

    return _render("memories.html", {
        "request": request,
        "title": "记忆浏览",
        "memories": all_memories,
        "projects": projects,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_color": _continuity_color,
    }, request)

@router.post("/memories/{memory_id}/delete")
async def delete_memory_ui(request: Request, memory_id: str):
    # 先尝试旧引擎删除
    engine = _engine(request)
    deleted = engine.delete_memory(memory_id)
    # 再尝试 memory_v2 删除
    if not deleted:
        try:
            from src.core.memory_v2 import get_memory_manager
            mgr = get_memory_manager()
            mgr.remove(memory_id)
        except Exception:
            logger.debug("Suppressed except Exception:: {}", exc_info=True)
    return RedirectResponse(url="/ui/memories", status_code=303)

# ── 记忆仪表板 (搜索+添加+图谱+统计) ──────────────────────

@router.get("/memory", response_class=HTMLResponse)
async def memory_dashboard(request: Request):
    """记忆仪表板: 搜索、添加、知识图谱可视化、统计"""
    return _render("memories.html", {
        "request": request,
        "title": "记忆仪表板",
    }, request)

# ── 连续性检测仪表板 ──────────────────────────────────────────

@router.get("/continuity", response_class=HTMLResponse)
async def continuity_dashboard(request: Request):
    """所有项目的连续性检测仪表板"""
    engine = _engine(request)
    projects = engine.list_projects()

    data = []
    for p in projects:
        try:
            cont = engine.detect_continuity(p.id)
        except Exception:
            cont = {"continuity_score": 0, "is_continuous": False,
                    "conversation_count": 0, "memory_count": 0,
                    "active_session_count": 0, "total_session_count": 0,
                    "last_active": None}
        data.append({
            "project": p,
            "continuity": cont,
        })

    data.sort(key=lambda x: x["continuity"]["continuity_score"], reverse=True)

    continuous_count = sum(1 for d in data if d["continuity"]["is_continuous"])

    return _render("continuity.html", {
        "request": request,
        "title": "连续性检测",
        "data": data,
        "continuous_count": continuous_count,
        "total_count": len(data),
        "format_dt": _format_dt,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    }, request)

# ── Chat 页面 ───────────────────────────────────────────

@router.get("/desktop", response_class=HTMLResponse)
async def desktop_page(request: Request):
    return _render("desktop.html", {"request": request, "title": "Desktop"}, request)

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    # 检测当前 profile
    import os as _os, yaml as _yaml
    profile = _os.environ.get("MESHCTX_PROFILE", "").strip()
    if not profile:
        try:
            cfg_path = _os.environ.get("MESHCTX_CONFIG",
                str(__import__('pathlib').Path.home() / ".meshctx" / "config.yaml"))
            with open(cfg_path) as f:
                cfg = _yaml.safe_load(f) or {}
            p = cfg.get("profile", {})
            if isinstance(p, dict):
                profile = p.get("active", "")
            elif p:
                profile = str(p)
        except Exception:
            profile = ""
    if profile == "default":
        profile = ""
    return _render("chat.html", {"request": request, "title": "Chat", "profile": profile}, request)

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    flash = ""
    if request.query_params.get("saved") == "1":
        flash = "success"
    elif request.query_params.get("error") == "1":
        flash = "error"
    
    # 合并内置模型 + 已配置模型
    configured = []
    seen_ids = set()
    try:
        from src.model_registry import get_registry, BUILTIN_MODELS
        reg = get_registry()
        
        # 读取config.yaml获取已配置模型详情
        from pathlib import Path
        cp = Path.home() / ".meshctx" / "config.yaml"
        config = {}
        if cp.exists():
            import yaml as _yaml2
            with open(cp) as f:
                config = _yaml2.safe_load(f) or {}
        entries = config.get("models", {}).get("entries", {})
        
        # 也检查 provider_config.json 补全遗漏的配置
        pcfg_path = Path(__file__).resolve().parent.parent / "provider_config.json"
        pcfg_keys = {}
        if pcfg_path.exists():
            try:
                import json as _json2
                pcfg_data = _json2.loads(pcfg_path.read_text())
                for pid, pinfo in pcfg_data.items():
                    if pinfo.get("key"):
                        pcfg_keys[pid] = pinfo["key"]
            except Exception as _e:
                logger.exception("web_ui error: %s", _e)
                logger.debug("Suppressed except:: {}", exc_info=True)
        # 对于 provider_config 中有 key 但 config.yaml 中无 entry 的 provider，
        # 自动补全该 provider 下所有内置模型的 entries
        for pid, pkey in pcfg_keys.items():
            for mid, info in BUILTIN_MODELS.items():
                if info.get("provider") == pid and mid not in entries:
                    entries[mid] = {
                        "key": pkey,
                        "provider": pid,
                        "model": info.get("model", ""),
                        "base_url": info.get("base_url", ""),
                    }
        
        default_id = config.get("models", {}).get("default", "")
        
        # 1. 内置模型 (BUILTIN_MODELS)
        # Build reverse lookup: (provider, model) -> config entry
        provider_model_to_entry = {}
        for mid, einfo in entries.items():
            pm_key = (einfo.get("provider", ""), einfo.get("model", ""))
            provider_model_to_entry[pm_key] = (mid, einfo)
        
        for mid, info in BUILTIN_MODELS.items():
            seen_ids.add(mid)
            # Exact ID match or fuzzy (provider+model) match
            is_configured = mid in entries
            config_entry = None
            
            if is_configured:
                config_entry = entries[mid]
            else:
                # Fuzzy match: same provider+model but different ID format
                pm_key = (info.get("provider", ""), info.get("model", ""))
                if pm_key in provider_model_to_entry:
                    config_mid, config_entry = provider_model_to_entry[pm_key]
                    is_configured = True
            
            entry = {
                "id": mid,
                "model": info.get("model", mid),
                "provider": info.get("provider", "?"),
                "base_url": info.get("base_url", ""),
                "ready": is_configured,
                "is_default": (default_id == mid),
                "builtin": True,
            }
            if is_configured and config_entry:
                raw_key = config_entry.get("key", "")
                if raw_key:
                    entry["key_full"] = raw_key
                    if raw_key.startswith("b64:"): entry["key_masked"] = "b64:****"
                    else: entry["key_masked"] = raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else "****"
            configured.append(entry)
        
        # 2. 用户自定义模型 (不在BUILTIN_MODELS中)
        for mid, einfo in entries.items():
            if mid in seen_ids:
                # Already shown as builtin, just update
                for item in configured:
                    if item["id"] == mid:
                        item["ready"] = True
                        raw_key = einfo.get("key", "")
                        if raw_key:
                            item["key_full"] = raw_key
                            item["key_masked"] = raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else "****"
                        item["base_url"] = einfo.get("base_url", item.get("base_url", ""))
                        break
            else:
                # Custom model not in builtins
                raw_key = einfo.get("key", "")
                configured.append({
                    "id": mid,
                    "model": einfo.get("model", mid),
                    "provider": einfo.get("provider", "?"),
                    "base_url": einfo.get("base_url", ""),
                    "ready": True,
                    "is_default": (default_id == mid),
                    "builtin": False,
                    "key_full": raw_key,
                    "key_masked": raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else ("****" if raw_key else ""),
                })
    except Exception as _e:
        logger.exception("web_ui error: %s", _e)
        logger.debug("Suppressed except:: {}", exc_info=True)
    
    # 排序: 默认最前 → 已配置 → 按provider
    configured.sort(key=lambda m: (
        not m.get("is_default", False),
        not m.get("ready", False),
        m.get("provider", ""),
    ))
    
    # 未配置模型默认折叠(仅显示前20)
    unconfigured_count = sum(1 for m in configured if not m.get("ready"))
    show_all = request.query_params.get("all") == "1"
    has_more = False
    if not show_all and unconfigured_count > 20:
        ready = [m for m in configured if m.get("ready")]
        unready = [m for m in configured if not m.get("ready")][:20]
        configured = ready + unready
        has_more = True
    
    return _render("setup.html", {
        "request": request, "title": "Setup",
        "flash": flash, "configured": configured,
        "has_more_unconfigured": has_more,
        "total_unconfigured": unconfigured_count,
    }, request)

@router.post("/setup/save")
async def save_api_key(
    request: Request,
    provider: str = Form(...),
    api_key: str = Form(...),
    base_url: str = Form(""),
    model_name: str = Form(""),
):
    """保存 API Key 并自动重载配置 — 无需重启"""
    from pathlib import Path

    config_path = Path.home() / ".meshctx" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    provider_defaults = {
        "deepseek": {"model_id": "deepseek:chat", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY"},
        "bailian": {"model_id": "bailian:qwen-flash", "model": "qwen-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "key_env": "BAILIAN_API_KEY"},
        "siliconflow": {"model_id": "siliconflow:qwen-flash", "model": "Qwen/Qwen2.5-7B-Instruct", "base_url": "https://api.siliconflow.cn/v1", "key_env": "SILICONFLOW_API_KEY"},
    }
    defaults = provider_defaults.get(provider, provider_defaults["deepseek"])
    actual_model = model_name or defaults["model"]
    actual_url = base_url or defaults["base_url"]
    model_id = defaults["model_id"]  # 使用内置目录中的标准ID

    config.setdefault("models", {})
    config["models"].setdefault("entries", {})
    config["models"]["default"] = model_id
    # v1.8: 加密存储 API Key
    encrypted_key = api_key
    try:
        from src.core.crypto import encrypt_key
        encrypted_key = encrypt_key(api_key)
    except Exception as _e:
        logger.exception("web_ui error: %s", _e)
        logger.debug("Suppressed except:: {}", exc_info=True)
    config["models"]["entries"][model_id] = {
        "key": encrypted_key,
        "model": actual_model,
        "base_url": actual_url,
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # 设置环境变量立即可用
    os.environ[defaults["key_env"]] = api_key
    
    # 重置模型registry缓存，使新key立即生效
    try:
        from src.model_registry import reset_registry
        reset_registry()
    except Exception as _e:
        logger.exception("web_ui error: %s", _e)
        logger.debug("Suppressed except:: {}", exc_info=True)

    return RedirectResponse(url="/ui/setup?saved=1", status_code=303)

@router.post("/setup/delete")
async def delete_api_key(
    request: Request,
    model_id: str = Form(...),
):
    """删除指定模型的API密钥"""
    from pathlib import Path
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        return RedirectResponse(url="/ui/setup?error=1", status_code=303)
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.get("models", {}).get("entries", {})
    if model_id in entries:
        del entries[model_id]
        # 如果删除的是默认模型，清除默认
        if config.get("models", {}).get("default") == model_id:
            config["models"]["default"] = next(iter(entries), "") if entries else ""
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    # 清除环境变量
    from src.model_registry import _registry
    import src.model_registry as mr
    mr._registry = None
    
    return RedirectResponse(url="/ui/setup?deleted=1", status_code=303)

# ── v2.17 系统仪表盘 ─────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>Dashboard - MeshCtx</title>
<style>
:root{--bg:#0b0e1a;--card-bg:rgba(255,255,255,0.04);--border:rgba(255,255,255,0.08);--text:#e0e4f0;--muted:#8090b0;--accent:#6c5ce7;--green:#22c55e;--red:#f85149;--yellow:#fbbf24;--input-bg:#16213e;--surface:#16213e;--hover:rgba(255,255,255,0.06)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);color:var(--text);min-height:100vh;padding:24px}
nav{display:flex;gap:12px;margin-bottom:24px}
nav a{color:var(--muted);text-decoration:none;padding:8px 16px;border-radius:8px;font-size:14px}
.container{max-width:1000px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center}
.card .v{font-size:36px;font-weight:700;margin:8px 0}
.card .l{font-size:12px;color:var(--muted)}
.green{color:var(--green)} .red{color:var(--red)} .yellow{color:var(--yellow)} .purple{color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted)}
/* ── Light Theme ── */
body.light{background:linear-gradient(135deg,#f8fafc,#eef2ff);color:#0f172a}
body.light .card{background:rgba(255,255,255,0.9);border-color:#e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.06)}
body.light nav a{color:#64748b}
body.light nav a:hover{background:#e2e8f0;color:#0f172a}
body.light th{color:#64748b}
body.light td{color:#0f172a}
body.light table tr:hover{background:rgba(108,92,231,0.06)}
body.light input,body.light select{background:#fff;border-color:#e2e8f0;color:#0f172a}
body.light .green{color:#16a34a}
body.light .red{color:#dc2626}
body.light .yellow{color:#d97706}
body.light .purple{color:#7c3aed}
</style></head><body>
<div class="container">
<nav><a href="/ui/chat" data-nav="chat">Chat</a><a href="/ui/setup" data-nav="setup">Setup</a><a href="/ui/plugins" data-nav="plugins">Plugins</a><a href="/ui/files" data-nav="files">📁 Files</a><a href="/ui/dashboard" data-nav="dashboard" style="color:var(--accent);background:rgba(108,92,231,0.15);">Dashboard</a><span style="flex:1"></span><button onclick="toggleThemeDash()" id="themeBtnDash" title="切换明暗主题" style="background:var(--card-bg);border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:14px;color:var(--text);">🌙</button></nav>
<script>
(function(){
  var L={chat:{en:'Chat',zh:'聊天',ja:'チャット',ko:'채팅',es:'Chat',fr:'Chat',de:'Chat'},
    setup:{en:'Setup',zh:'设置',ja:'設定',ko:'설정',es:'Configuración',fr:'Configuration',de:'Einrichtung'},
    plugins:{en:'Plugins',zh:'插件',ja:'プラグイン',ko:'플러그인',es:'Plugins',fr:'Plugins',de:'Plugins'},
    files:{en:'Files',zh:'文件',ja:'ファイル',ko:'파일',es:'Archivos',fr:'Fichiers',de:'Dateien'},
    dashboard:{en:'Dashboard',zh:'仪表板',ja:'ダッシュボード',ko:'대시보드',es:'Panel',fr:'Tableau de bord',de:'Dashboard'}};
  var lang=localStorage.getItem('meshctx_lang')||document.cookie.match(/meshctx_lang=([^;]+)/)?.[1]||'en';
  document.querySelectorAll('[data-nav]').forEach(function(el){
    var k=el.getAttribute('data-nav'),v=L[k];
    if(v&&v[lang])el.textContent=(k==='files'?'📁 ':'')+v[lang];
  });
})();
</script>
<h2 style="margin-bottom:16px;">📊 System Dashboard</h2>
<div class="grid" id="stats"></div>
<div class="card" style="margin-bottom:16px;text-align:left">
<h3 style="margin-bottom:8px">🛡️ Watchdog</h3>
<div id="wdStatus" style="font-size:12px;color:var(--muted)">Loading...</div>
</div>
<div class="card" style="margin-bottom:16px;text-align:left">
<h3 style="margin-bottom:8px">🏥 Auto-Healer</h3>
<div id="healerStatus" style="font-size:12px;color:var(--muted)">Loading...</div>
</div>
<h3 style="margin-top:8px;">API Endpoints</h3>
<table><thead><tr><th>Endpoint</th><th>Latency</th><th>Status</th></tr></thead><tbody id="epTable"></tbody></table>
<div id="pluginStatus" style="margin-top:16px;"></div>
</div>
<script>
(function(){var s=localStorage.getItem('meshctx_theme');if(!s){s=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}if(s==='light')document.body.classList.add('light');var b=document.getElementById('themeBtnDash');if(b)b.textContent=s==='light'?'☀️':'🌙';if(window.matchMedia)window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',function(e){var c=localStorage.getItem('meshctx_theme');if(!c||c==='auto'){if(e.matches)document.body.classList.remove('light');else document.body.classList.add('light')}})})();
function toggleThemeDash(){var b=document.body;var isLight=b.classList.toggle('light');localStorage.setItem('meshctx_theme',isLight?'light':'dark');var btn=document.getElementById('themeBtnDash');if(btn)btn.textContent=isLight?'☀️':'🌙'}
async function load(){
  var r=await fetch('/api/system/status');
  var d=await r.json();
  var s='';
  s+=card('Version',d.version,'purple');
  s+=card('Models',d.models.configured+'/'+d.models.builtin,'green');
  s+=card('Plugins',d.plugins.available,'yellow');
  s+=card('Sessions',d.sessions.total,'green');
  s+=card('Python',d.server.python,'purple');
  document.getElementById('stats').innerHTML=s;
  
  // Ping endpoints
  var eps=['/api/version','/api/health','/api/models','/api/plugins/market','/api/feishu/status'];
  var rows='';
  for(var i=0;i<eps.length;i++){
    var t0=performance.now();
    var ok=false;
    try{var r2=await fetch(eps[i]);ok=r2.ok}catch(e){}
    var ms=(performance.now()-t0).toFixed(0);
    rows+='<tr><td>'+eps[i]+'</td><td>'+ms+'ms</td><td style="color:'+(ok?'var(--green)':'var(--red)')+'">'+(ok?'OK':'FAIL')+'</td></tr>';
  }
  document.getElementById('epTable').innerHTML=rows;
  
  // Plugin status
  var r3=await fetch('/api/plugins/market');
  var pd=await r3.json();
  var ps='<h3>Plugins</h3><table><tr><th>Name</th><th>Status</th><th>Installs</th></tr>';
  pd.plugins.forEach(function(p){
    ps+='<tr><td>'+p.icon+' '+p.name+'</td><td style="color:'+(p.status=='active'?'var(--green)':'var(--yellow)')+'">'+p.status+'</td><td>'+p.installs+'</td></tr>';
  });
  ps+='</table>';
  document.getElementById('pluginStatus').innerHTML=ps;
  
  // Watchdog
  try{
    var wd=await fetch('/api/watchdog/status');
    var w=await wd.json();
    var ws='<div style="display:flex;gap:12px;flex-wrap:wrap">';
    ws+=badge('Running',w.running?'✅':'❌',w.running?'green':'red');
    ws+=badge('Uptime',w.uptime_human,'purple');
    ws+=badge('Checks',w.stats.checks_total,'yellow');
    ws+=badge('Fixed',w.stats.issues_fixed,'green');
    for(var k in w.subsystems){
      var s=w.subsystems[k];
      ws+=badge(k,s.status,s.status=='ok'?'green':'yellow');
    }
    ws+='</div>';
    if(w.recent_alerts&&w.recent_alerts.length){
      ws+='<div style="margin-top:8px;font-size:11px;color:var(--muted)">Recent alerts: '+w.recent_alerts.length+'</div>';
    }
    document.getElementById('wdStatus').innerHTML=ws;
  }catch(e){}

  // Auto-Healer
  try{
    var ah=await fetch('/api/healer/dashboard');
    var h=await ah.json();
    var hs='<div style="display:flex;gap:12px;flex-wrap:wrap">';
    var colorMap={green:'var(--green)',yellow:'var(--yellow)',orange:'#f97316',red:'var(--red)',gray:'var(--muted)'};
    var emojiMap={green:'🟢',yellow:'🟡',orange:'🟠',red:'🔴',gray:'⚪'};
    var emoji=emojiMap[h.color]||'⚪';
    hs+=badge('Status',emoji+' '+h.status,colorMap[h.color]||'var(--muted)');
    hs+=badge('Running',h.running?'✅':'❌',h.running?'green':'red');
    hs+=badge('Last Check',h.last_check_human,'purple');
    hs+=badge('Uptime',h.uptime_since_incident_human,'purple');
    hs+=badge('Heals',h.heals_successful+'/'+h.heals_performed,'yellow');
    hs+=badge('Checks',h.checks_total,'green');
    hs+='</div>';
    document.getElementById('healerStatus').innerHTML=hs;
  }catch(e){}
}
function badge(label,value,color){return '<span style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;text-align:center"><div style="font-size:10px;color:var(--muted)">'+label+'</div><div class="'+color+'" style="font-size:16px;font-weight:700">'+value+'</div></span>'}
function card(label,value,color){return '<div class="card"><div class="l">'+label+'</div><div class="v '+color+'">'+value+'</div></div>'}
load();
setInterval(load, 30000);

// WebSocket real-time watchdog (every 15s)
try {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(protocol + '//' + location.host + '/ws/dashboard');
    ws.onmessage = function(e) {
        var d = JSON.parse(e.data);
        if (d.type === 'watchdog') {
            var w = d.data;
            var wsHtml = '<div style="display:flex;gap:12px;flex-wrap:wrap">';
            wsHtml += badge('Running', w.running?'✅':'❌', w.running?'green':'red');
            wsHtml += badge('Uptime', w.uptime, 'purple');
            wsHtml += badge('Checks', w.checks, 'yellow');
            wsHtml += badge('Alerts', w.alerts, w.alerts>0?'red':'green');
            for (var k in w.subsystems) {
                var s = w.subsystems[k];
                wsHtml += badge(k, s.status, s.status=='ok'?'green':'yellow');
            }
            wsHtml += '</div>';
            document.getElementById('wdStatus').innerHTML = wsHtml;

            // Update healer if data available
            if (w.healer) {
                var h = w.healer;
                var hsHtml = '<div style="display:flex;gap:12px;flex-wrap:wrap">';
                var colorMap={green:'var(--green)',yellow:'var(--yellow)',orange:'#f97316',red:'var(--red)',gray:'var(--muted)'};
                var emojiMap={green:'🟢',yellow:'🟡',orange:'🟠',red:'🔴',gray:'⚪'};
                var emoji=emojiMap[h.color]||'⚪';
                hsHtml += badge('Status', emoji+' '+h.status, colorMap[h.color]||'var(--muted)');
                hsHtml += badge('Running', h.running?'✅':'❌', h.running?'green':'red');
                hsHtml += badge('Last Check', h.last_check_human, 'purple');
                hsHtml += badge('Uptime', h.uptime_since_incident_human, 'purple');
                hsHtml += badge('Heals', h.heals_successful+'/'+h.heals_performed, 'yellow');
                hsHtml += badge('Checks', h.checks_total, 'green');
                hsHtml += '</div>';
                document.getElementById('healerStatus').innerHTML = hsHtml;
            }
        }
    };
    ws.onerror = function() { /* WebSocket fallback to poll */ };
} catch(e) {} // Auto-refresh every 30s
</script></body></html>""")

# ── v2.18 插件市场 (增强卡片+URL安装+社区推荐) ──────────────────

@router.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request):
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>🔌 插件市场 - MeshCtx</title>
<style>
:root{--bg:#0b0e1a;--card-bg:rgba(255,255,255,0.04);--border:rgba(255,255,255,0.08);--text:#e0e4f0;--muted:#8090b0;--accent:#6c5ce7;--accent2:#00d48c;--danger:#f85149;--gold:#f0b90b;--green:#22c55e}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);color:var(--text);min-height:100vh;padding:24px}
nav{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}
nav a{color:var(--muted);text-decoration:none;padding:8px 16px;border-radius:8px;font-size:14px;transition:all 0.2s}
nav a:hover{background:rgba(108,92,231,0.15);color:var(--accent)}
nav a.active{color:var(--accent);background:rgba(108,92,231,0.15)}
.container{max-width:960px;margin:0 auto}
body.light{background:#f8fafc;color:#1e293b}
body.light .card{background:#fff;border-color:#e2e8f0}
body.light .section-title{color:#334155}
body.light nav a{color:#64748b}
body.light nav a:hover{background:#e2e8f0;color:#1e293b}
body.light nav a.active{color:#6c5ce7;background:rgba(108,92,231,0.1)}
body.light input,body.light select{background:#fff;border-color:#e2e8f0;color:#1e293b}
body.light .toolbar input,body.light .toolbar select{background:#fff;border-color:#d1d5db;color:#1e293b}
body.light .url-bar{background:#f1f5f9;border-color:#e2e8f0}
body.light .url-bar input{background:#fff;border-color:#d1d5db;color:#1e293b}
body.light .url-bar .hint code{background:#e2e8f0;color:#1e293b}
body.light .community-card{background:#fff;border-color:#e2e8f0}
body.light .community-card:hover{border-color:#6c5ce7;box-shadow:0 4px 20px rgba(108,92,231,0.1)}
body.light .stars .empty{color:#d1d5db}
body.light .divider{background:#e2e8f0}
body.light .plugin-icon{background:rgba(108,92,231,0.08)}
body.light .btn-outline{background:#fff;border-color:#d1d5db;color:#1e293b}
body.light .btn-outline:hover{border-color:#6c5ce7;color:#6c5ce7}
body.light .toast-success{background:#dcfce7;color:#166534;border-color:#86efac}
body.light .toast-error{background:#fef2f2;color:#991b1b;border-color:#fca5a5}
body.light h2{color:#0f172a}
body.light .cc-name{color:#0f172a}
h2{font-size:24px;font-weight:700;margin-bottom:4px}
h2 .ver{font-size:11px;color:var(--muted);font-weight:400;margin-left:8px}
.section-title{font-size:16px;font-weight:600;margin:28px 0 12px;display:flex;align-items:center;gap:8px;color:var(--text)}
.section-title .badge{font-size:10px;background:var(--accent);color:#fff;padding:2px 8px;border-radius:10px}
/* ── 搜索/筛选栏 ── */
.toolbar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.toolbar input,.toolbar select{padding:10px 14px;background:#1e293b;border:1px solid #334155;color:var(--text);border-radius:10px;font-size:13px;transition:border-color 0.2s}
.toolbar input:focus,.toolbar select:focus{outline:none;border-color:var(--accent)}
.toolbar input{flex:1;min-width:200px}

/* ── 卡片容器 ── */
.card{background:var(--card-bg);border:1px solid var(--border);border-radius:14px;padding:18px;transition:all 0.2s}
.card:hover{border-color:var(--accent);box-shadow:0 4px 24px rgba(108,92,231,0.12);transform:translateY(-1px)}

/* ── 插件卡片头部 ── */
.plugin-header{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.plugin-icon{font-size:32px;width:44px;height:44px;display:flex;align-items:center;justify-content:center;background:rgba(108,92,231,0.12);border-radius:12px;flex-shrink:0}
.plugin-meta{flex:1;min-width:0}
.plugin-name{font-size:15px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.plugin-version{font-size:11px;color:var(--muted);margin-left:4px}
.plugin-author{font-size:11px;color:var(--muted);margin-top:1px}

/* ── 星级评分 ── */
.stars{display:inline-flex;gap:2px;font-size:13px;color:var(--gold);margin:4px 0}
.stars .empty{color:#334155}
.stars .count{font-size:10px;color:var(--muted);margin-left:4px}

/* ── 描述 ── */
.plugin-desc{font-size:12px;color:var(--muted);line-height:1.6;margin:8px 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

/* ── 状态标签 ── */
.status-badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:10px;font-weight:600}
.status-installed{background:rgba(34,197,94,0.15);color:#22c55e}
.status-not-installed{background:rgba(100,116,139,0.15);color:#94a3b8}
.status-coming{background:rgba(240,185,11,0.15);color:#f0b90b}
.status-active{background:rgba(0,212,140,0.15);color:#00d48c}

/* ── 操作按钮 ── */
.plugin-actions{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.btn{padding:7px 16px;border-radius:8px;border:none;font-weight:600;cursor:pointer;font-size:12px;transition:all 0.2s;font-family:inherit;display:inline-flex;align-items:center;gap:4px}
.btn-primary{background:linear-gradient(135deg,#6c5ce7,#5a4bd1);color:#fff}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(108,92,231,0.3)}
.btn-success{background:rgba(34,197,94,0.2);color:#22c55e;border:1px solid rgba(34,197,94,0.3)}
.btn-success:hover{background:rgba(34,197,94,0.3)}
.btn-danger{background:rgba(248,81,73,0.15);color:#f85149;border:1px solid rgba(248,81,73,0.25)}
.btn-danger:hover{background:rgba(248,81,73,0.25)}
.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}
.btn:disabled{opacity:0.5;cursor:not-allowed;transform:none!important;box-shadow:none!important}

/* ── URL安装区域 ── */
.url-bar{background:rgba(108,92,231,0.06);border:1px solid rgba(108,92,231,0.15);border-radius:14px;padding:18px;margin:20px 0}
.url-bar h3{font-size:15px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.url-bar .url-input-row{display:flex;gap:8px}
.url-bar input{flex:1;padding:10px 14px;background:#1e293b;border:1px solid #334155;color:var(--text);border-radius:10px;font-size:13px;font-family:monospace}
.url-bar input:focus{outline:none;border-color:var(--accent)}
.url-bar .hint{font-size:10px;color:var(--muted);margin-top:8px}
.url-bar .parsed-info{font-size:11px;color:var(--accent2);margin-top:6px;display:none}

/* ── 社区推荐 ── */
.community-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.community-card{background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:14px;padding:16px;transition:all 0.2s}
.community-card:hover{border-color:var(--accent);box-shadow:0 4px 20px rgba(108,92,231,0.1)}
.community-card .cc-icon{font-size:28px;margin-bottom:8px}
.community-card .cc-name{font-size:14px;font-weight:700}
.community-card .cc-desc{font-size:11px;color:var(--muted);margin:6px 0;line-height:1.5}
.community-card .cc-meta{font-size:10px;color:var(--muted);display:flex;justify-content:space-between;align-items:center}
.submit-link{display:inline-flex;align-items:center;gap:6px;color:var(--accent);text-decoration:none;font-size:13px;margin-top:16px;padding:8px 0;transition:color 0.2s}
.submit-link:hover{color:#8b7cf6}

/* ── 分割线 ── */
.divider{height:1px;background:var(--border);margin:28px 0;opacity:0.5}

/* ── Toast ── */
.toast{position:fixed;top:20px;right:20px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;animation:slideIn 0.3s ease;max-width:400px}
.toast-success{background:#065f46;color:#22c55e;border:1px solid #22c55e}
.toast-error{background:#7f1d1d;color:#f85149;border:1px solid #f85149}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}

input,select{font-family:inherit}
</style></head><body>
<div class="container">
<nav>
<a href="/ui/chat" data-nav="chat">💬 Chat</a><a href="/ui/setup" data-nav="setup">⚙ Setup</a><a href="/ui/files" data-nav="files">📁 Files</a>
<a href="/ui/plugins" data-nav="plugins" class="active">🔌 插件市场</a>
<span style="flex:1"></span>
<button onclick="toggleThemePlugins()" id="themeBtnPlugins" title="切换明暗主题" style="background:var(--card-bg);border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:14px;color:var(--text);">🌙</button>
</nav>
<script>
(function(){
  var L={chat:{en:'💬 Chat',zh:'💬 聊天',ja:'💬 チャット',ko:'💬 채팅',es:'💬 Chat',fr:'💬 Chat',de:'💬 Chat'},
    setup:{en:'⚙ Setup',zh:'⚙ 设置',ja:'⚙ 設定',ko:'⚙ 설정',es:'⚙ Configuración',fr:'⚙ Configuration',de:'⚙ Einrichtung'},
    plugins:{en:'🔌 Plugins',zh:'🔌 插件',ja:'🔌 プラグイン',ko:'🔌 플러그인',es:'🔌 Plugins',fr:'🔌 Plugins',de:'🔌 Plugins'},
    files:{en:'📁 Files',zh:'📁 文件',ja:'📁 ファイル',ko:'📁 파일',es:'📁 Archivos',fr:'📁 Fichiers',de:'📁 Dateien'}};
  var lang=localStorage.getItem('meshctx_lang')||document.cookie.match(/meshctx_lang=([^;]+)/)?.[1]||'en';
  document.querySelectorAll('[data-nav]').forEach(function(el){
    var k=el.getAttribute('data-nav'),v=L[k];
    if(v&&v[lang])el.textContent=v[lang];
  });
})();
</script>

<h2>🔌 插件市场 <span class="ver">v2.4</span></h2>
<p style="color:var(--muted);margin-bottom:4px">发现和安装社区插件，扩展 MeshCtx 能力</p>

<!-- ═══ 搜索/筛选 ═══ -->
<div class="toolbar">
<input id="pluginSearch" placeholder="🔍 搜索插件..." aria-label="搜索插件" oninput="loadPlugins()">
<select id="pluginCat" onchange="loadPlugins()"><option value="">📂 全部分类</option></select>
<button class="btn btn-outline" onclick="loadPlugins()" title="刷新">🔄</button>
</div>

<!-- ═══ 插件列表 ═══ -->
<div id="pluginList" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">
<div style="text-align:center;color:var(--muted);padding:60px 20px;grid-column:1/-1">
<div style="font-size:40px;margin-bottom:12px">⏳</div>加载中...
</div>
</div>

<!-- ═══ URL安装 ═══ -->
<div class="divider"></div>
<div class="url-bar">
<h3>🔗 从 URL 安装插件</h3>
<p style="font-size:12px;color:var(--muted);margin-bottom:12px">支持 GitHub 仓库地址、直接 ZIP 链接或插件注册表 URL</p>
<div class="url-input-row">
<input id="urlInput" placeholder="https://github.com/user/plugin-repo" aria-label="Plugin URL" oninput="parseUrl()">
<button class="btn btn-primary" onclick="installFromUrl()">📥 安装</button>
</div>
<div class="hint">💡 示例: <code>https://github.com/example/meshctx-translator</code> 或 <code>https://meshctx.com/plugins/v1/hello.zip</code></div>
<div class="parsed-info" id="parsedInfo"></div>
</div>

<!-- ═══ 社区推荐 ═══ -->
<div class="divider"></div>
<div class="section-title">🌟 社区推荐 <span class="badge">热门</span></div>
<p style="font-size:12px;color:var(--muted);margin-bottom:12px">由社区贡献者维护的优质插件</p>
<div class="community-grid" id="communityGrid"></div>
<a href="https://github.com/nousresearch/meshctx/discussions" target="_blank" class="submit-link">✏️ 提交你的插件 →</a>

</div>

<!-- ═══ Toast容器 ═══ -->
<div id="toastContainer"></div>

<script>
(function(){var s=localStorage.getItem('meshctx_theme');if(!s){s=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}if(s==='light')document.body.classList.add('light');var b=document.getElementById('themeBtnPlugins');if(b)b.textContent=s==='light'?'☀️':'🌙';if(window.matchMedia)window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',function(e){var c=localStorage.getItem('meshctx_theme');if(!c||c==='auto'){if(e.matches)document.body.classList.remove('light');else document.body.classList.add('light')}})})();
function toggleThemePlugins(){var b=document.body;var isLight=b.classList.toggle('light');localStorage.setItem('meshctx_theme',isLight?'light':'dark');var btn=document.getElementById('themeBtnPlugins');if(btn)btn.textContent=isLight?'☀️':'🌙'}
var _installed = {};

// ── 星级渲染 ──
function renderStars(rating, count){
  var s='<span class="stars">';
  for(var i=1;i<=5;i++){
    if(i<=Math.floor(rating)) s+='★';
    else if(i-Math.floor(rating)<0.5) s+='★'; // 四舍五入
    else s+='<span class="empty">★</span>';
  }
  s+='<span class="count">('+(count||0)+')</span></span>';
  return s;
}

// ── Toast通知 ──
function showToast(msg, type){
  var t=document.getElementById('toastContainer');
  var el=document.createElement('div');
  el.className='toast toast-'+(type||'success');
  el.textContent=msg;
  t.appendChild(el);
  setTimeout(function(){el.style.opacity='0';el.style.transition='opacity 0.3s';setTimeout(function(){el.remove()},300)},3000);
}

// ── 加载已安装列表 ──
async function loadInstalled(){
  try{var r=await fetch('/api/plugins/installed');var d=await r.json();_installed=d.installed||{};}catch(e){}
}

// ── 加载插件市场 ──
async function loadPlugins(){
var q=document.getElementById('pluginSearch').value;
var cat=document.getElementById('pluginCat').value;
var list=document.getElementById('pluginList');
list.innerHTML='<div style="text-align:center;color:var(--muted);padding:60px 20px;grid-column:1/-1"><div style="font-size:40px;margin-bottom:12px">⏳</div>加载中...</div>';
try{
var r=await fetch('/api/plugins/market?search='+encodeURIComponent(q)+'&category='+encodeURIComponent(cat));
var d=await r.json();
if(!d.plugins.length){list.innerHTML='<div style="text-align:center;color:var(--muted);padding:60px 20px;grid-column:1/-1"><div style="font-size:40px;margin-bottom:12px">📭</div>暂无插件</div>';return}
list.innerHTML=d.plugins.map(function(p){
var isInstalled = _installed[p.name] !== undefined;
var isBuiltin = p.builtin;
var statusHtml, btnHtml;
if(isBuiltin && isInstalled){
  statusHtml='<span class="status-badge status-active">✅ 已激活</span>';
  btnHtml='';
}else if(isInstalled){
  statusHtml='<span class="status-badge status-installed">📦 已安装</span>';
  btnHtml='<button class="btn btn-danger" onclick="uninstallPlugin(&quot;'+p.name+'&quot;,this)">🗑 卸载</button>';
}else if(isBuiltin){
  statusHtml='<span class="status-badge status-not-installed">🔒 内置</span>';
  btnHtml='<button class="btn btn-primary" onclick="installPlugin(&quot;'+p.name+'&quot;,this)">⚡ 激活</button>';
}else{
  statusHtml='<span class="status-badge status-not-installed">📥 可安装</span>';
  btnHtml='<button class="btn btn-primary" onclick="installPlugin(&quot;'+p.name+'&quot;,this)">📥 安装</button>';
}
var rating = p.rating || (3+(Math.random()*2)).toFixed(1);
var downloads = p.downloads || Math.floor(Math.random()*5000+100);
var icon = p.icon || '🧩';
return '<div class="card">'
  +'<div class="plugin-header">'
  +'<div class="plugin-icon">'+icon+'</div>'
  +'<div class="plugin-meta">'
  +'<div class="plugin-name">'+(p.name||p.id||'unknown')+' <span class="plugin-version">v'+(p.version||'1.0.0')+'</span></div>'
  +'<div class="plugin-author">👤 '+(p.author||'社区')+'</div>'
  +'</div>'
  +'</div>'
  +renderStars(rating, downloads)
  +'<div class="plugin-desc">'+(p.description||'暂无描述')+'</div>'
  +'<div class="plugin-actions">'+statusHtml+(btnHtml?' '+btnHtml:'')+'</div>'
  +'</div>';
}).join('');
var sel=document.getElementById('pluginCat');
var cur=sel.value;
sel.innerHTML='<option value="">📂 全部分类</option>'+d.categories.map(function(c){return '<option value="'+c+'">'+c+'</option>'}).join('');
sel.value=cur;
}catch(e){list.innerHTML='<div style="color:#f85149;padding:40px 20px;text-align:center;grid-column:1/-1"><div style="font-size:40px;margin-bottom:12px">❌</div>加载失败: '+e.message+'</div>'}
}

// ── 安装插件 ──
async function installPlugin(name,btn){
btn.textContent='⏳ 安装中...';btn.disabled=true;
try{
var r=await fetch('/api/plugins/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
if(r.ok){_installed[name]={};showToast('✅ '+name+' 安装成功！','success');loadPlugins()}
else{var d=await r.json();showToast('❌ '+(d.detail||'安装失败'),'error');btn.textContent='📥 安装';btn.disabled=false}
}catch(e){showToast('❌ '+e.message,'error');btn.textContent='📥 安装';btn.disabled=false}
}

// ── 卸载插件 ──
async function uninstallPlugin(name,btn){
if(!confirm('确定要卸载 '+name+' 吗？此操作不可恢复。'))return;
btn.textContent='⏳ 卸载中...';btn.disabled=true;
try{
var r=await fetch('/api/plugins/uninstall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
if(r.ok){delete _installed[name];showToast('🗑 '+name+' 已卸载','success');loadPlugins();}
else{var d=await r.json();showToast('❌ '+(d.detail||'卸载失败'),'error');btn.textContent='✅ 已安装';btn.disabled=false}
}catch(e){showToast('❌ '+e.message,'error');btn.textContent='✅ 已安装';btn.disabled=false}
}

// ── URL解析(预览) ──
function parseUrl(){
var url=document.getElementById('urlInput').value.trim();
var info=document.getElementById('parsedInfo');
if(!url){info.style.display='none';return}
info.style.display='block';
if(url.includes('github.com')){
  var m=url.match(/github\\.com\\/([^\\/]+)\\/([^\\/]+)/);
  if(m){info.innerHTML='🔍 检测到 GitHub 仓库: <b>'+m[1]+'/'+m[2]+'</b> — 将自动克隆并安装';return}
}
if(url.endsWith('.zip')){info.innerHTML='📦 检测到 ZIP 文件 — 将下载并解压安装';return}
info.innerHTML='🔗 将从该 URL 下载安装插件';
}

// ── URL安装 ──
async function installFromUrl(){
var url=document.getElementById('urlInput').value.trim();
if(!url){showToast('⚠️ 请输入插件URL','error');return}
var btn=event.target;
btn.textContent='⏳ 解析中...';btn.disabled=true;
try{
var r=await fetch('/api/plugins/install-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
var d=await r.json();
if(r.ok){showToast('✅ 插件安装成功！','success');document.getElementById('urlInput').value='';document.getElementById('parsedInfo').style.display='none';loadInstalled();loadPlugins();}
else{showToast('❌ '+(d.detail||d.message||'安装失败'),'error')}
}catch(e){showToast('❌ '+e.message,'error')}
btn.textContent='📥 安装';btn.disabled=false;
}

// ── 社区推荐数据 ──
var communityPlugins = [
  {icon:'🌐',name:'Web Scraper Pro',desc:'智能网页抓取与内容提取插件，支持动态页面和反爬虫',author:'@scraper-dev',stars:4.8,downloads:3200,tag:'热门'},
  {icon:'📊',name:'Data Analyzer',desc:'数据分析与可视化，支持 CSV/JSON/Parquet 格式',author:'@data-team',stars:4.6,downloads:1800,tag:'推荐'},
  {icon:'🎨',name:'Image Generator',desc:'基于 Stable Diffusion 的图片生成插件',author:'@ai-artist',stars:4.5,downloads:2100,tag:'热门'},
  {icon:'🔊',name:'Voice Assistant',desc:'语音输入/输出插件，支持中英文实时转写',author:'@voice-lab',stars:4.3,downloads:950,tag:'新'},
  {icon:'📝',name:'Note Taker',desc:'会议记录自动摘要，支持导出 Markdown/PDF',author:'@productivity',stars:4.7,downloads:1600,tag:'推荐'},
  {icon:'🛡️',name:'Security Guard',desc:'代码安全扫描与漏洞检测，集成 OWASP 规则',author:'@sec-team',stars:4.9,downloads:2800,tag:'热门'},
  {icon:'🌍',name:'i18n Helper',desc:'多语言翻译辅助，支持 50+ 语言自动检测',author:'@locale-dev',stars:4.2,downloads:720,tag:''},
  {icon:'🔗',name:'API Bridge',desc:'快速对接第三方 API，自动生成调用代码',author:'@api-guild',stars:4.4,downloads:1400,tag:'推荐'}
];

function renderCommunity(){
var grid=document.getElementById('communityGrid');
grid.innerHTML=communityPlugins.map(function(p){
  return '<div class="community-card">'
    +'<div class="cc-icon">'+p.icon+'</div>'
    +'<div class="cc-name">'+p.name+(p.tag?' <span class="status-badge status-coming" style="margin-left:4px">'+p.tag+'</span>':'')+'</div>'
    +'<div class="cc-desc">'+p.desc+'</div>'
    +renderStars(p.stars,p.downloads)
    +'<div class="cc-meta"><span>👤 '+p.author+'</span><span class="status-badge status-coming">即将上线</span></div>'
    +'</div>';
}).join('');
}

// ── 初始化 ──
(async function(){
await loadInstalled();
loadPlugins();
renderCommunity();
})();

// ── URL输入框回车支持 ──
document.getElementById('urlInput').addEventListener('keydown',function(e){
if(e.key==='Enter') installFromUrl();
});
var paneHistory=document.createElement('div');paneHistory.id='pane-history';paneHistory.className='pane-history';paneHistory.style.display='none';document.body.appendChild(paneHistory);
function renderHistory(id){var e=document.getElementById('pane-history');if(e){e.style.display='block';e.innerHTML='<h3>Session: '+id+'</h3>';}}
</script></body></html>""")

# ── v1.5.13 下载页面 ─────────────────────────────────────

@router.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    html = r"""{% extends "base.html" %}
{% block content %}
<h2>{{ t("install_title") }}</h2>
<div class="card" style="margin-top:16px;">
  <h3>🍎 macOS</h3>
  <p style="color:var(--muted);">macOS 15+ · Apple Silicon / Intel</p>
  <details open style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式1: curl 一键安装</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install-mac.sh | bash</pre>
  </details>
  <details style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式2: Homebrew</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">brew tap LucyAndLuna2023/meshctx
brew install meshctx</pre>
  </details>
  <details style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式3: DMG 安装包</summary>
    <div style="text-align:center;padding:12px;">
      <a class="btn btn-primary" href="https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx.dmg" style="display:inline-block;text-decoration:none;padding:10px 28px;">⬇ 下载 DMG</a>
      <p style="font-size:11px;color:var(--muted);margin-top:6px;">下载后拖入 Applications 即可</p>
    </div>
  </details>
  <p style="font-size:11px;color:var(--muted);margin-top:8px;">需要 Python 3.10+ · 脚本自动处理依赖</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>🐧 Linux</h3>
  <p style="color:var(--muted);">{{ t("one_cmd_install_desc") }}</p>
  <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);">curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash</pre>
  <p style="font-size:11px;color:var(--muted);margin-top:8px;">{{ t("install_requirements") }}</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("windows_title") }}</h3>
  <div style="text-align:center;padding:16px;">
    <a class="btn btn-primary" href="https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx-setup.exe" style="display:inline-block;text-decoration:none;padding:12px 32px;font-size:15px;">{{ t("download_windows_btn") }}</a>
    <p style="font-size:11px;color:var(--muted);margin-top:8px;">v{{ version }} · {{ t("nsis_installer") }} · Win10/11 x64</p>
  </div>
  <details style="margin-top:8px;font-size:12px;">
    <summary style="cursor:pointer;color:var(--muted);">{{ t("cli_install_title") }}</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">curl -fsSL https://meshctx.com/install.sh | bash</pre>
  </details>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("docker_coming_soon") }}</h3>
  <p style="color:var(--muted);">docker pull meshctx/meshctx:latest</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("config_docs_title") }}</h3>
  <p>{{ t("supports_info") }} <a href="https://github.com/LucyAndLuna2023/meshctx#-model-configuration" target="_blank">{{ t("view_config_guide") }}</a></p>
  <p style="font-size:12px;color:var(--muted);">{{ t("more_models") }}</p>
</div>
{% endblock %}"""
    _TEMPLATES["download.html"] = html
    return _render("download.html", {"request": request, "title": "Download", "version": __import__("src").__version__}, request)

# ── Chat 页面模板 ────────────────────────────────────────────


# ── 模型列表页面 ────────────────────────────────────────────


@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    return _render("models.html", {"request": request, "title": "Models"}, request)

# ── 供应商列表页面 ───────────────────────────────────────────


@router.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    return _render("providers.html", {"request": request, "title": "Providers"}, request)

# ── 文件管理器 ─────────────────────────────────────────────


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    return _render("files.html", {"request": request, "title": "Files"}, request)

# ── PWA 支持 ───────────────────────────────────────────────

@router.get("/manifest.json", response_class=JSONResponse)
async def manifest():
    """PWA manifest.json"""
    return {
        "name": "MeshCtx",
        "short_name": "MeshCtx",
        "description": "MeshCtx - AI Context Manager",
        "start_url": "/ui/",
        "display": "standalone",
        "background_color": "#0a0a1a",
        "theme_color": "#0a0a1a",
        "orientation": "any",
        "icons": [
            {
                "src": "/ui/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/ui/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }

@router.get("/sw.js", response_class=Response)
async def service_worker():
    """Service Worker — 网络优先 + 缓存回退"""
    sw_js = r"""
const CACHE_NAME = 'meshctx-v1';
const PRECACHE_URLS = [
    '/ui/',
    '/ui/manifest.json',
    '/ui/icon-192.png',
    '/ui/icon-512.png'
];

// Install: 预缓存核心资源
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
    );
    self.skipWaiting();
});

// Activate: 清理旧缓存
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
        ))
    );
    self.clients.claim();
});

// Fetch: 网络优先，失败时回退缓存
self.addEventListener('fetch', event => {
    // 跳过非 GET 请求和 API 请求
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/api/')) return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // 缓存成功的响应
                if (response.ok && url.pathname.startsWith('/ui/')) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                // 网络失败时回退缓存
                return caches.match(event.request);
            })
    );
});
""".strip()
    return Response(content=sw_js, media_type="application/javascript")

# SVG 图标占位（192x192 和 512x512）
_ICON_SVG = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3a5f"/>
      <stop offset="100%" style="stop-color:#0a0a1a"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{radius}" fill="url(#bg)"/>
  <text x="50%" y="50%" dominant-baseline="central" text-anchor="middle"
        font-family="-apple-system,BlinkMacSystemFont,sans-serif"
        font-weight="700" font-size="{font_size}" fill="#38bdf8">🧠</text>
</svg>"""

@router.get("/icon-192.png", response_class=Response)
async def icon_192():
    return Response(
        content=_ICON_SVG.format(size=192, radius=32, font_size=80),
        media_type="image/svg+xml"
    )

@router.get("/icon-512.png", response_class=Response)
async def icon_512():
    return Response(
        content=_ICON_SVG.format(size=512, radius=80, font_size=200),
        media_type="image/svg+xml"
    )
