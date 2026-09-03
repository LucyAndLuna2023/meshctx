"""
meshctx MCP (Model Context Protocol) 服务器
完整实现 MCP 协议，可被任何 MCP 客户端发现和调用

支持:
    stdio transport — Claude Desktop, Cursor 等
    HTTP/SSE transport — 远程工具调用
"""
import asyncio
import json
import logging
import sys
from typing import Any, Callable, Dict, List, Optional

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.mcp")

# ═══════════════════════════════════════════════════
# MCP 协议类型
# ═══════════════════════════════════════════════════

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"

class MCPError(Exception):
    pass

# ═══════════════════════════════════════════════════
# MCP 工具注册
# ═══════════════════════════════════════════════════

class MCPTool:
    """MCP 工具定义"""
    def __init__(self, name: str, description: str, 
                 parameters: Dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema
        self.handler = handler
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters,
        }


class MCPServer:
    """
    MCP 服务器
    
    注册的工具自动暴露给 MCP 客户端 (Claude Desktop, Cursor, etc.)
    """
    
    def __init__(self, name: str = "meshctx", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: Dict[str, MCPTool] = {}
        self._resources: Dict[str, Dict] = {}
        self._next_id = 0
        
        # 注册内置工具
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        """注册内置 MCP 工具"""
        
        self.register_tool(
            name="memory_search",
            description="搜索 meshctx 层次记忆 (L0-L4)，支持向量+关键词混合检索",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "top_k": {"type": "integer", "default": 10},
                    "project_id": {"type": "string"},
                },
                "required": ["query"],
            },
            handler=self._handle_memory_search,
        )
        
        self.register_tool(
            name="model_chat",
            description="调用 LLM 模型对话 (30+模型可选)",
            parameters={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "模型ID, 如 bailian:qwen-flash"},
                    "prompt": {"type": "string", "description": "提示词"},
                    "system": {"type": "string"},
                },
                "required": ["prompt"],
            },
            handler=self._handle_model_chat,
        )
        
        self.register_tool(
            name="skill_execute",
            description="执行一个已注册的 Skill",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "input": {"type": "object"},
                },
                "required": ["skill_name"],
            },
            handler=self._handle_skill_execute,
        )
        
        self.register_tool(
            name="session_search",
            description="全文搜索历史会话",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            handler=self._handle_session_search,
        )
        
        self.register_tool(
            name="browser_navigate",
            description="浏览器导航到指定URL",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页URL"},
                },
                "required": ["url"],
            },
            handler=self._handle_browser_navigate,
        )
        
        self.register_tool(
            name="tts_speak",
            description="文字转语音合成",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "voice": {"type": "string"},
                },
                "required": ["text"],
            },
            handler=self._handle_tts,
        )

        # WP5 (MCTX-PLAN-2026-0903 P1-2): 记忆 API/任务卡/值守/配额/遥测工具扩展
        _register_wp5_tools(self)

    # ── 工具注册 ──────────────────────────────────────────
    
    def register_tool(self, name: str, description: str,
                      parameters: Dict, handler: Callable):
        tool = MCPTool(name, description, parameters, handler)
        self._tools[name] = tool
        logger.debug(f"MCP 工具注册: {name}")
    
    # ── 工具处理 ──────────────────────────────────────────
    
    async def _handle_memory_search(self, args: Dict) -> str:
        query = args.get("query", "")
        top_k = int(args.get("top_k") or 10)
        project_id = args.get("project_id")
        if not query:
            return json.dumps({"error": "缺少 query 参数"}, ensure_ascii=False)
        try:
            from .memory_engine import MemoryEngine
            engine = MemoryEngine(use_llm=False, use_vector_store=False)
            engine._load_existing_data()
            # 关键词检索：memories(key/value) + conversations(title) 双源命中
            hits = []
            for m in engine.memories.values():
                if project_id and m.project_id != project_id:
                    continue
                score = 0
                if query.lower() in m.key.lower():
                    score = max(score, 2.0 + m.importance)
                if query.lower() in m.value.lower():
                    score = max(score, 1.0 + m.importance)
                if score:
                    hits.append((score, {"id": m.id, "type": "memory", "project_id": m.project_id,
                                         "key": m.key, "value": m.value[:500], "importance": m.importance}))
            for c in engine.conversations.values():
                if project_id and c.project_id != project_id:
                    continue
                title = getattr(c, "title", "") or ""
                if query.lower() in title.lower():
                    hits.append((1.5, {"id": c.id, "type": "conversation", "project_id": c.project_id,
                                       "title": title}))
            hits.sort(key=lambda x: x[0], reverse=True)
            results = [h[1] for h in hits[:top_k]]
            return json.dumps({"query": query, "count": len(results), "results": results},
                              ensure_ascii=False)
        except Exception as e:
            logger.error(f"memory_search 失败: {e}")
            return json.dumps({"error": f"memory_search 失败: {e}"}, ensure_ascii=False)
    
    async def _handle_model_chat(self, args: Dict) -> str:
        from .model_registry import get_registry
        reg = get_registry()
        client = reg.get(args.get("model"))
        if not client:
            return json.dumps({"error": "模型不可用"})
        resp = client.chat([{"role":"user","content":args.get("prompt","")}])
        return resp["content"]
    
    async def _handle_skill_execute(self, args: Dict) -> str:
        name = args.get("skill_name", "")
        skill_input = args.get("input") or {}
        if not name:
            return json.dumps({"error": "缺少 skill_name 参数"}, ensure_ascii=False)
        try:
            from .skill_manager import SkillManager
            sm = SkillManager()
            skill = sm.get(name)
            if not skill:
                return json.dumps({"skill": name, "error": f"Skill 未注册: {name}"},
                                  ensure_ascii=False)
            # 真实执行：有 steps 时顺序执行（命令/工具步骤），否则返回元数据
            outputs = []
            for step in skill.steps or []:
                if isinstance(step, str) and step.startswith("!"):
                    import subprocess
                    try:
                        r = subprocess.run(step[1:], shell=True, capture_output=True,
                                           text=True, timeout=30)
                        outputs.append({"step": step, "stdout": r.stdout[:2000],
                                        "returncode": r.returncode})
                    except Exception as e:
                        outputs.append({"step": step, "error": str(e)})
                else:
                    outputs.append({"step": str(step), "status": "recorded"})
            skill.usage_count += 1
            sm._save(skill)
            return json.dumps({
                "skill": name,
                "description": skill.description,
                "steps_executed": len(outputs),
                "outputs": outputs,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"skill_execute 失败: {e}")
            return json.dumps({"error": f"skill_execute 失败: {e}"}, ensure_ascii=False)

    async def _handle_session_search(self, args: Dict) -> str:
        query = args.get("query", "")
        limit = int(args.get("limit") or 10)
        if not query:
            return json.dumps({"error": "缺少 query 参数"}, ensure_ascii=False)
        try:
            from .session_search import FTS5SessionSearch
            searcher = FTS5SessionSearch()
            results = searcher.search(query, limit=limit)
            return json.dumps({"query": query, "count": len(results), "results": results},
                              ensure_ascii=False)
        except Exception as e:
            logger.error(f"session_search 失败: {e}")
            return json.dumps({"error": f"session_search 失败: {e}"}, ensure_ascii=False)

    async def _handle_browser_navigate(self, args: Dict) -> str:
        url = args.get("url", "")
        if not url:
            return json.dumps({"error": "缺少 url 参数"}, ensure_ascii=False)
        try:
            from .browser_tool import BrowserTool
            tool = BrowserTool()
            result = await tool.navigate(url)
            return json.dumps({"url": url, **result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"browser_navigate 失败: {e}")
            return json.dumps({"url": url, "error": str(e)}, ensure_ascii=False)

    async def _handle_tts(self, args: Dict) -> str:
        text = args.get("text", "")
        voice = args.get("voice")
        if not text:
            return json.dumps({"error": "缺少 text 参数"}, ensure_ascii=False)
        try:
            from .tts import TTSEngine
            engine = TTSEngine()
            output = await engine.synthesize(text, voice=voice)
            return json.dumps({"text": text[:200], "status": "synthesized",
                               "output": output}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"tts_speak 失败: {e}")
            return json.dumps({"error": f"tts_speak 失败: {e}"}, ensure_ascii=False)
    
    # ── MCP 协议处理 ─────────────────────────────────────
    
    def _rpc_response(self, id: Any, result: Any) -> Dict:
        return {"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}
    
    def _rpc_error(self, id: Any, code: int, message: str) -> Dict:
        return {
            "jsonrpc": JSONRPC_VERSION, "id": id,
            "error": {"code": code, "message": message},
        }
    
    async def handle_request(self, request: Dict) -> Dict:
        """处理 MCP JSON-RPC 请求 (async — 兼容 stdio/HTTP 传输)"""
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")
        
        try:
            if method == "initialize":
                return self._rpc_response(req_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {}},
                })
            
            elif method == "tools/list":
                return self._rpc_response(req_id, {
                    "tools": [t.to_dict() for t in self._tools.values()],
                })
            
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool = self._tools.get(tool_name)
                if not tool:
                    return self._rpc_error(req_id, -32601, f"Tool not found: {tool_name}")
                
                tool_args = params.get("arguments", {})
                result = await tool.handler(tool_args)
                
                return self._rpc_response(req_id, {
                    "content": [{"type": "text", "text": str(result)}],
                })
            
            elif method == "resources/list":
                return self._rpc_response(req_id, {"resources": []})
            
            elif method == "notifications/initialized":
                return None  # 通知不需要回复
            
            else:
                return self._rpc_error(req_id, -32601, f"Method not found: {method}")
                
        except Exception as e:
            logger.error(f"MCP 请求处理失败: {e}")
            return self._rpc_error(req_id, -32603, str(e))
    
    # ── 传输层 ───────────────────────────────────────────
    
    async def run_stdio(self):
        """stdio 传输 — 用于 Claude Desktop / Cursor"""
        logger.info("MCP stdio 服务器启动")
        
        loop = asyncio.get_event_loop()
        
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                
                request = json.loads(line.strip())
                response = await self.handle_request(request)
                
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"MCP stdio error: {e}")


class MCPPlugin(Plugin):
    """MCP 协议插件"""
    
    info = PluginInfo(
        name="mcp",
        version="1.0.0",
        description="MCP 协议完整实现 — stdio/HTTP 传输",
        author="meshctx",
    )
    
    def __init__(self):
        self.server = MCPServer()
    
    async def on_load(self):
        # 注册 MCP 相关事件
        self.kernel.bus.subscribe(
            "mcp.request", self._on_request, plugin_name="mcp"
        )
        logger.info("MCP 服务器已就绪 (6个内置工具)")
    
    async def on_unload(self):
        pass
    
    async def _on_request(self, event: Event):
        """处理内部 MCP 请求"""
        request = event.data.get("request", {})
        response = await self.server.handle_request(request)
        if response:
            await self.kernel.bus.publish(Event(
                type="mcp.response",
                source="mcp",
                correlation_id=event.id,
                data={"response": response},
            ))


# ═══════════════════════════════════════════════════════════════════════════
# WP5 (MCTX-PLAN-2026-0903 P1-2) 工具扩展 — Memory API / Task Cards / Routines
# / Quota / Telemetry (加法式; 宿主语义 owner=local 回环; 异常返回 JSON 错误串)
# ═══════════════════════════════════════════════════════════════════════════

def _reg(server: "MCPServer", name: str, description: str, properties: Dict,
         required: list, handler: Callable):
    server.register_tool(name=name, description=description,
                         parameters={"type": "object",
                                     "properties": properties,
                                     "required": required},
                         handler=handler)


def _rpc_err(tag: str, e: Exception) -> str:
    return json.dumps({"error": f"{tag}: {type(e).__name__}: {e}"},
                      ensure_ascii=False)


def _register_wp5_tools(server: "MCPServer") -> None:
    """注册 WP5 扩展工具 (个人版全开; 配额/edition 语义与 HTTP API 一致)。"""
    # ── Memory API (WP3 服务, owner=local) ──
    _reg(server, "memory_api_store",
         "对外 Memory API: 存一条命名空间记忆 (WP3)",
         {"text": {"type": "string"}, "namespace": {"type": "string",
          "default": "default"}, "meta": {"type": "object"}},
         ["text"], _handle_mem_store)
    _reg(server, "memory_api_search",
         "对外 Memory API: 命名空间内检索 (TF-IDF/词重叠召回, WP3)",
         {"query": {"type": "string"}, "namespace": {"type": "string",
          "default": "default"}, "top_k": {"type": "integer", "default": 5}},
         ["query"], _handle_mem_search)
    _reg(server, "memory_api_list",
         "对外 Memory API: 列出命名空间全部记忆",
         {"namespace": {"type": "string", "default": "default"}},
         [], _handle_mem_list)
    _reg(server, "memory_api_delete_entry",
         "对外 Memory API: 按 id 删除单条记忆",
         {"namespace": {"type": "string", "default": "default"},
          "entry_id": {"type": "string"}},
         ["entry_id"], _handle_mem_delete_entry)
    _reg(server, "memory_api_delete_namespace",
         "对外 Memory API: 删除整命名空间 (GDPR 删除请求)",
         {"namespace": {"type": "string", "default": "default"}},
         [], _handle_mem_delete_ns)
    # ── Task Cards (Agent Hub) ──
    _reg(server, "task_spawn",
         "一句话派活: 创建后台任务卡并执行 (Agent Hub)",
         {"prompt": {"type": "string"}, "title": {"type": "string"},
          "max_rounds": {"type": "integer"}},
         ["prompt"], _handle_task_spawn)
    _reg(server, "task_status",
         "查询任务卡状态/进度/结果",
         {"card_id": {"type": "string"}},
         ["card_id"], _handle_task_status)
    _reg(server, "task_list",
         "列出任务卡 (最近 N 张)",
         {"limit": {"type": "integer", "default": 10}},
         [], _handle_task_list)
    _reg(server, "task_cancel",
         "取消任务卡 (运行中/等待审批即时收尾)",
         {"card_id": {"type": "string"}},
         ["card_id"], _handle_task_cancel)
    _reg(server, "task_approve",
         "审批任务卡挂起动作 (agree/reject/custom+text)",
         {"card_id": {"type": "string"},
          "action": {"type": "string", "enum": ["agree", "reject", "custom"]},
          "text": {"type": "string"}},
         ["card_id", "action"], _handle_task_approve)
    # ── Routines 值守 (WP6) ──
    _reg(server, "routine_create",
         "创建例行值守 (interval 秒 或 cron 5 字段; {now}/{date} 模板)",
         {"prompt": {"type": "string"}, "kind": {"type": "string",
          "enum": ["interval", "cron"]},
          "schedule": {"type": "string", "default": "3600"}},
         ["prompt"], _handle_routine_create)
    _reg(server, "routine_list",
         "列出全部值守任务",
         {}, [], _handle_routine_list)
    _reg(server, "routine_toggle",
         "启用/停用值守",
         {"routine_id": {"type": "string"}, "enabled": {"type": "boolean"}},
         ["routine_id", "enabled"], _handle_routine_toggle)
    _reg(server, "routine_run_now",
         "立即触发一次值守 (走配额/enqueue 同语义)",
         {"routine_id": {"type": "string"}},
         ["routine_id"], _handle_routine_run)
    # ── Quota / Telemetry ──
    _reg(server, "quota_status",
         "查询当前用户配额用量与剩余",
         {"owner": {"type": "string", "default": ""}},
         [], _handle_quota_status)
    _reg(server, "telemetry_stats",
         "遥测统计 (窗口内事件/token/span 状态)",
         {"window_hours": {"type": "integer", "default": 24}},
         [], _handle_telemetry_stats)
    _reg(server, "telemetry_trace",
         "按 trace_id 取全链路事件 (span/工具/审批/错误)",
         {"trace_id": {"type": "string"}},
         ["trace_id"], _handle_telemetry_trace)


async def _handle_mem_store(args: Dict) -> str:
    try:
        from .core.memory_api import get_memory_service
        ns = str(args.get("namespace") or "default")
        e = get_memory_service().store(f"local:{ns}", str(args["text"]),
                                       args.get("meta"))
        return json.dumps({"ok": True, "id": e["id"]}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("memory_api_store", e)


async def _handle_mem_search(args: Dict) -> str:
    try:
        from .core.memory_api import get_memory_service
        ns = str(args.get("namespace") or "default")
        res = get_memory_service().search(f"local:{ns}", str(args.get("query", "")),
                                          int(args.get("top_k") or 5))
        return json.dumps({"results": res}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("memory_api_search", e)


async def _handle_mem_list(args: Dict) -> str:
    try:
        from .core.memory_api import get_memory_service
        ns = str(args.get("namespace") or "default")
        return json.dumps({"entries": get_memory_service().list_entries(f"local:{ns}")},
                          ensure_ascii=False)
    except Exception as e:
        return _rpc_err("memory_api_list", e)


async def _handle_mem_delete_entry(args: Dict) -> str:
    try:
        from .core.memory_api import get_memory_service
        ns = str(args.get("namespace") or "default")
        ok = get_memory_service().delete_entry(f"local:{ns}", str(args["entry_id"]))
        return json.dumps({"ok": ok}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("memory_api_delete_entry", e)


async def _handle_mem_delete_ns(args: Dict) -> str:
    try:
        from .core.memory_api import get_memory_service
        ns = str(args.get("namespace") or "default")
        removed = get_memory_service().delete_namespace(f"local:{ns}")
        return json.dumps({"ok": True, "removed": removed}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("memory_api_delete_namespace", e)


async def _handle_task_spawn(args: Dict) -> str:
    try:
        from .core.task_cards import TaskCard, get_card_worker, get_hub_quota
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return json.dumps({"error": "prompt 为空"}, ensure_ascii=False)
        worker = get_card_worker()
        hq = get_hub_quota()
        q = hq.try_consume_spawn("local", plan="free",
                                 concurrent_now=worker.running_count())
        if not q["ok"]:
            return json.dumps({"error": q.get("reason")}, ensure_ascii=False)
        card = TaskCard(owner="local", plan="free",
                        title=str(args.get("title") or prompt[:60]), prompt=prompt)
        if args.get("max_rounds"):
            card.extra["max_rounds"] = int(args["max_rounds"])
        if not worker.enqueue(card):
            hq.refund_spawn("local")
            return json.dumps({"error": "worker 未就绪"}, ensure_ascii=False)
        return json.dumps({"card_id": card.id, "status": "queued"},
                          ensure_ascii=False)
    except Exception as e:
        return _rpc_err("task_spawn", e)


async def _handle_task_status(args: Dict) -> str:
    try:
        from .core.task_cards import get_card_worker
        w = get_card_worker()
        c = w._store.load(str(args["card_id"]))
        if c is None:
            return json.dumps({"error": "card 不存在"}, ensure_ascii=False)
        return json.dumps({"id": c.id, "status": c.status.value,
                           "result": (c.result or "")[:2000],
                           "error": (c.error or "")[:1000],
                           "prompt_len": len(c.prompt or "")},
                          ensure_ascii=False)
    except Exception as e:
        return _rpc_err("task_status", e)


async def _handle_task_list(args: Dict) -> str:
    try:
        from .core.task_cards import get_card_worker
        cards = get_card_worker()._store.list_cards(owner="local")
        limit = int(args.get("limit") or 10)
        out = [{"id": c.id, "status": c.status.value,
                "title": (getattr(c, "title", "") or "")[:80]}
               for c in cards[-limit:]]
        return json.dumps({"cards": out}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("task_list", e)


async def _handle_task_cancel(args: Dict) -> str:
    try:
        from .core.task_cards import get_card_worker
        ok = get_card_worker().cancel(str(args["card_id"]))
        return json.dumps({"ok": ok}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("task_cancel", e)


async def _handle_task_approve(args: Dict) -> str:
    try:
        from .core.task_cards import get_card_worker
        w = get_card_worker()
        c = w._store.load(str(args["card_id"]))
        if c is None or not getattr(c, "approval_pending", None):
            return json.dumps({"error": "无挂起审批"}, ensure_ascii=False)
        rid = c.approval_pending.get("request_id", "")
        action = str(args.get("action") or "agree")
        text = str(args.get("text") or "")
        ok = w.decide_approval(rid, action, text)
        return json.dumps({"ok": ok}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("task_approve", e)


async def _handle_routine_create(args: Dict) -> str:
    try:
        from .core.routines import Routine
        from .core.routines_api import _validate
        body = {"prompt": args.get("prompt"), "kind": args.get("kind", "interval"),
                "schedule": args.get("schedule", "3600")}
        _validate(body)
        r = Routine(owner="local", prompt=str(body["prompt"]).strip(),
                    kind=str(body["kind"]),
                    schedule=str(body["schedule"]))
        from .core.routines_api import _store
        _store().save(r)
        return json.dumps({"routine_id": r.id}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("routine_create", e)


async def _handle_routine_list(args: Dict) -> str:
    try:
        from .core.routines_api import _store
        out = [{"id": r.id, "name": r.name, "kind": r.kind, "schedule": r.schedule,
                "enabled": r.enabled, "last_status": r.last_status}
               for r in _store().list() if r.owner == "local"]
        return json.dumps({"routines": out}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("routine_list", e)


async def _handle_routine_toggle(args: Dict) -> str:
    try:
        from .core.routines_api import _store
        st = _store()
        r = st.get(str(args["routine_id"]))
        if r is None:
            return json.dumps({"error": "routine 不存在"}, ensure_ascii=False)
        r.enabled = bool(args.get("enabled", not r.enabled))
        st.save(r)
        return json.dumps({"ok": True, "enabled": r.enabled}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("routine_toggle", e)


async def _handle_routine_run(args: Dict) -> str:
    try:
        from .core.routines_api import _store, make_spawn_fn
        import time
        st = _store()
        r = st.get(str(args["routine_id"]))
        if r is None:
            return json.dumps({"error": "routine 不存在"}, ensure_ascii=False)
        now = time.time()
        ok = make_spawn_fn()(r, now)
        if ok:
            st.mark_fired(r.id, True, ts=now)
        return json.dumps({"ok": ok}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("routine_run_now", e)


async def _handle_quota_status(args: Dict) -> str:
    try:
        from .core.task_cards import get_hub_quota
        owner = str(args.get("owner") or "local")
        hq = get_hub_quota()
        try:
            info = hq.check_usage(owner) if hasattr(hq, "check_usage") else {}
        except Exception:
            info = {}
        return json.dumps({"owner": owner, "usage": info}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("quota_status", e)


async def _handle_telemetry_stats(args: Dict) -> str:
    try:
        from .core import telemetry as tel
        return json.dumps(tel.get_telemetry().stats(
            window_hours=int(args.get("window_hours") or 24)), ensure_ascii=False)
    except Exception as e:
        return _rpc_err("telemetry_stats", e)


async def _handle_telemetry_trace(args: Dict) -> str:
    try:
        from .core import telemetry as tel
        return json.dumps({"events": tel.get_telemetry().events_by_trace(
            str(args["trace_id"]))}, ensure_ascii=False)
    except Exception as e:
        return _rpc_err("telemetry_trace", e)
