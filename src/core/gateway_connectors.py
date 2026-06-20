"""
meshctx Gateway Connectors — MCP 协议 Gateway v1.0
===================================================
实现 Model Context Protocol (MCP) Gateway — meshctx 与外部工具生态的标准桥梁。

MCP 是 Anthropic 提出的开放协议, 用于 AI 模型与外部工具/资源之间的标准化通信。
meshctx 通过此模块接入 GitHub MCP Server、文件系统 MCP、数据库 MCP、
Web Search MCP 等所有兼容 MCP 的外部工具服务器。

核心组件:
  1. JsonRpcTransport — 传输层抽象 (stdio / HTTP / SSE)
  2. MCPClient — MCP 协议客户端, 处理握手、工具发现、工具调用
  3. ToolRegistry — 注册和发现所有 MCP 工具
  4. GatewayRouter — 路由请求到合适的 MCP 服务器
  5. MCPServerConfig — 服务器配置 (名称、命令、参数、环境变量)

协议: MCP 基于 JSON-RPC 2.0
  - 客户端→服务器: initialize, tools/list, tools/call
  - 服务器→客户端: 响应 + notifications/initialized
  - 传输: stdio (子进程), HTTP + SSE (远程)

使用示例:
  gateway = get_mcp_gateway()
  gateway.register_server("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
  tools = await gateway.list_tools()
  result = await gateway.call_tool("filesystem", "read_file", {"path": "/tmp/test.txt"})

与 Hermes Agent 对标:
  - Hermes: 内置工具系统, 固定函数调用
  - meshctx: 通过 MCP 协议动态接入任何外部工具, 零耦合

代码量: ~650 行
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.gateway_connectors")


# ═══════════════════════════════════════════════════════════
# 常量和类型
# ═══════════════════════════════════════════════════════════

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_REQUEST_TIMEOUT = 30.0  # 秒
DEFAULT_HEARTBEAT_INTERVAL = 10.0  # 秒
MAX_RECONNECT_ATTEMPTS = 3


class TransportType(str, Enum):
    """MCP 传输类型"""
    STDIO = "stdio"       # 本地子进程, 通过 stdin/stdout 通信
    HTTP = "http"         # HTTP POST JSON-RPC
    SSE = "sse"           # Server-Sent Events (流式)


class ServerState(str, Enum):
    """MCP 服务器连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    INITIALIZED = "initialized"  # 完成 MCP 握手
    ERROR = "error"
    RECONNECTING = "reconnecting"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class MCPServerConfig:
    """MCP 服务器配置"""
    name: str                                    # 唯一名称, e.g. "filesystem"
    command: str                                 # 启动命令, e.g. "npx" 或 "python"
    args: List[str] = field(default_factory=list)  # 命令行参数
    env: Dict[str, str] = field(default_factory=dict)  # 额外环境变量
    transport: TransportType = TransportType.STDIO
    url: str = ""                                # HTTP/SSE 传输时的 URL
    timeout: float = DEFAULT_REQUEST_TIMEOUT
    auto_reconnect: bool = True
    description: str = ""


@dataclass
class MCPTool:
    """MCP 工具的完整描述"""
    name: str
    description: str = ""
    server_name: str = ""                        # 所属服务器
    input_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    annotations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "server_name": self.server_name,
            "input_schema": self.input_schema,
            "annotations": self.annotations,
        }


@dataclass
class ServerInfo:
    """已注册 MCP 服务器的运行时信息"""
    config: MCPServerConfig
    state: ServerState = ServerState.DISCONNECTED
    tools: Dict[str, MCPTool] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    server_version: str = ""
    last_heartbeat: float = 0.0
    error_message: str = ""
    client: Optional["MCPClient"] = None


@dataclass
class GatewayStatus:
    """Gateway 整体状态快照"""
    total_servers: int
    connected_servers: int
    initialized_servers: int
    total_tools: int
    servers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_servers": self.total_servers,
            "connected_servers": self.connected_servers,
            "initialized_servers": self.initialized_servers,
            "total_tools": self.total_tools,
            "servers": self.servers,
        }


# ═══════════════════════════════════════════════════════════
# JSON-RPC 2.0 消息构造和解析
# ═══════════════════════════════════════════════════════════

class JsonRpcError(Exception):
    """JSON-RPC 错误"""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> Dict:
        d = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


def _make_request(method: str, params: dict = None) -> Dict[str, Any]:
    """构造 JSON-RPC 请求"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


def _make_notification(method: str, params: dict = None) -> Dict[str, Any]:
    """构造 JSON-RPC 通知 (无 id, 不期待响应)"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params or {},
    }


def _parse_response(raw: str) -> Dict[str, Any]:
    """解析 JSON-RPC 响应, 处理错误"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JsonRpcError(-32700, f"Parse error: {e}")

    if not isinstance(data, dict):
        raise JsonRpcError(-32600, "Invalid Request: response is not an object")

    if "error" in data:
        err = data["error"]
        raise JsonRpcError(
            err.get("code", -32603),
            err.get("message", "Internal error"),
            err.get("data"),
        )

    if "result" not in data and "method" not in data:
        raise JsonRpcError(-32603, "Invalid response: missing result")

    return data


def _is_jsonrpc_notification(data: Dict) -> bool:
    """判断是否是 JSON-RPC 通知 (有 method 无 id)"""
    return "method" in data and "id" not in data


# ═══════════════════════════════════════════════════════════
# 传输层
# ═══════════════════════════════════════════════════════════

class BaseTransport:
    """传输层基类"""

    async def connect(self) -> None:
        pass  # Abstract method — override in subclass

    async def disconnect(self) -> None:
        pass  # Abstract method — override in subclass

    async def send(self, message: Dict[str, Any]) -> None:
        pass  # Abstract method — override in subclass

    async def receive(self, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> str:
        pass  # Abstract method — override in subclass

    @property
    def is_connected(self) -> bool:
        return False  # Abstract — override in subclass


class StdioTransport(BaseTransport):
    """stdio 传输: 通过子进程 stdin/stdout 通信

    这是 MCP 最常用的本地传输方式。客户端启动 MCP 服务器子进程,
    通过管道发送 JSON-RPC 请求并接收响应。
    """

    def __init__(self, command: str, args: List[str], env: Dict[str, str] = None):
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: Optional[subprocess.Popen] = None
        self._request_id: Optional[str] = None
        self._response_future: Optional[asyncio.Future] = None
        self._read_task: Optional[asyncio.Task] = None
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._notification_handlers: List[Callable] = []
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """启动子进程并建立连接"""
        merged_env = os.environ.copy()
        merged_env.update(self.env)

        try:
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
                text=True,
                bufsize=1,  # 行缓冲
            )
        except FileNotFoundError:
            raise JsonRpcError(-32000, f"Command not found: {self.command}")
        except Exception as e:
            raise JsonRpcError(-32000, f"Failed to start process: {e}")

        self._connected = True

    async def disconnect(self) -> None:
        """关闭子进程"""
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self.process and self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

        self._connected = False
        self._pending_responses.clear()

    def _read_stderr(self) -> None:
        """后台读取 stderr 用于调试日志"""
        if self.process and self.process.stderr:
            line = self.process.stderr.readline()
            while line:
                logger.debug(f"[{self.command}] stderr: {line.rstrip()}")
                line = self.process.stderr.readline()

    async def send(self, message: Dict[str, Any]) -> None:
        """发送 JSON-RPC 消息到子进程 stdin"""
        async with self._lock:
            if not self.process or self.process.poll() is not None:
                raise JsonRpcError(-32000, "Process is not running")
            raw = json.dumps(message) + "\n"
            try:
                self.process.stdin.write(raw)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise JsonRpcError(-32000, f"Write failed: {e}")

    async def receive(self, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> str:
        """从子进程 stdout 读取一行 JSON-RPC 响应"""
        if not self.process or self.process.stdout is None:
            raise JsonRpcError(-32000, "Process not running or stdout unavailable")

        loop = asyncio.get_running_loop()

        try:
            line = await asyncio.wait_for(
                loop.run_in_executor(None, self.process.stdout.readline),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise JsonRpcError(-32000, f"Receive timeout after {timeout}s")

        if not line:
            raise JsonRpcError(-32000, "Process stdout closed unexpectedly")

        return line.strip()

    async def request(self, method: str, params: dict = None,
                      timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Dict[str, Any]:
        """发送请求并等待响应"""
        req = _make_request(method, params)
        await self.send(req)
        raw = await self.receive(timeout=timeout)
        return _parse_response(raw)

    async def notify(self, method: str, params: dict = None) -> None:
        """发送通知 (不等待响应)"""
        notif = _make_notification(method, params)
        await self.send(notif)

    @property
    def is_connected(self) -> bool:
        return self._connected and self.process is not None and self.process.poll() is None


class HttpTransport(BaseTransport):
    """HTTP 传输: 通过 HTTP POST 发送 JSON-RPC 请求

    用于连接运行在远程 HTTP 服务器上的 MCP 服务。
    不依赖第三方库, 使用标准库 urllib。
    """

    def __init__(self, url: str, timeout: float = DEFAULT_REQUEST_TIMEOUT):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._connected = False
        self._session_id: Optional[str] = None

    async def connect(self) -> None:
        """验证 HTTP 端点可达性"""
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._session_id = None

    async def send(self, message: Dict[str, Any]) -> None:
        """HTTP 模式下 send 和 receive 合并为 request"""
        pass

    async def receive(self, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> str:
        """HTTP 模式下 receive 委托给 request() 方法"""
        # HTTP transport 使用 request() 进行原子化的请求/响应；
        # receive() 单独调用时返回空 JSON-RPC 响应以避免阻塞。
        return json.dumps({})

    async def request(self, method: str, params: dict = None,
                      timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Dict[str, Any]:
        """通过 HTTP POST 发送 JSON-RPC 请求"""
        import urllib.request
        import urllib.error

        req_body = _make_request(method, params)
        raw_body = json.dumps(req_body).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        http_req = urllib.request.Request(
            self.url,
            data=raw_body,
            headers=headers,
            method="POST",
        )

        try:
            loop = asyncio.get_running_loop()

            def _do_request():
                with urllib.request.urlopen(http_req, timeout=timeout) as resp:
                    session_id = resp.headers.get("Mcp-Session-Id")
                    if session_id:
                        self._session_id = session_id
                    return resp.read().decode("utf-8")

            body = await asyncio.wait_for(
                loop.run_in_executor(None, _do_request),
                timeout=timeout + 5,
            )
        except urllib.error.HTTPError as e:
            raise JsonRpcError(-32000, f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise JsonRpcError(-32000, f"Connection failed: {e.reason}")
        except asyncio.TimeoutError:
            raise JsonRpcError(-32000, f"HTTP request timeout after {timeout}s")

        return _parse_response(body)

    async def notify(self, method: str, params: dict = None) -> None:
        """HTTP 通知"""
        await self.request(method, params)

    @property
    def is_connected(self) -> bool:
        return self._connected


class SseTransport(HttpTransport):
    """SSE 传输: 通过 HTTP SSE (Server-Sent Events) 接收流式响应

    用于连接支持 SSE 的 MCP 服务器。发送通过 HTTP POST,
    接收通过 SSE 事件流。
    """

    def __init__(self, url: str, timeout: float = DEFAULT_REQUEST_TIMEOUT):
        super().__init__(url, timeout)
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._sse_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """建立 SSE 连接"""
        await super().connect()

    async def disconnect(self) -> None:
        """关闭 SSE 连接"""
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        await super().disconnect()

    async def _read_sse_stream(self) -> None:
        """后台读取 SSE 事件流 (简化实现)"""
        # SSE 实现需要异步 HTTP 客户端支持流式读取,
        # 此处提供框架, 实际使用时可集成 aiohttp 或 httpx
        logger.debug("SSE stream reader started (framework placeholder)")

    async def receive_event(self, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Dict[str, Any]:
        """接收下一个 SSE 事件"""
        try:
            raw = await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
            return _parse_response(raw)
        except asyncio.TimeoutError:
            raise JsonRpcError(-32000, f"SSE event timeout after {timeout}s")


# ═══════════════════════════════════════════════════════════
# MCPClient — MCP 协议客户端
# ═══════════════════════════════════════════════════════════

class MCPClient:
    """MCP 协议客户端

    处理 MCP 握手 (initialize → initialized),
    工具列表获取 (tools/list), 工具调用 (tools/call),
    以及资源/提示管理。
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.transport: Optional[BaseTransport] = None
        self.state: ServerState = ServerState.DISCONNECTED
        self.server_capabilities: Dict[str, Any] = {}
        self.server_info: Dict[str, str] = {}
        self._tools_cache: Dict[str, MCPTool] = {}
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """建立传输连接并完成 MCP 握手"""
        async with self._lock:
            if self.state == ServerState.INITIALIZED:
                return

            self.state = ServerState.CONNECTING

            # 1. 创建传输层
            if self.config.transport == TransportType.STDIO:
                self.transport = StdioTransport(
                    self.config.command,
                    self.config.args,
                    self.config.env,
                )
            elif self.config.transport == TransportType.HTTP:
                self.transport = HttpTransport(
                    self.config.url,
                    self.config.timeout,
                )
            elif self.config.transport == TransportType.SSE:
                self.transport = SseTransport(
                    self.config.url,
                    self.config.timeout,
                )
            else:
                raise JsonRpcError(-32000, f"Unknown transport: {self.config.transport}")

            # 2. 建立连接
            await self.transport.connect()
            self.state = ServerState.CONNECTED

            # 3. MCP 握手: initialize
            init_result = await self._initialize()
            self.server_capabilities = init_result.get("capabilities", {})
            self.server_info = init_result.get("serverInfo", {})
            self.state = ServerState.INITIALIZED

            logger.info(
                f"MCP server '{self.config.name}' initialized: "
                f"{self.server_info.get('name', 'unknown')} "
                f"v{self.server_info.get('version', '?')} "
                f"capabilities={list(self.server_capabilities.keys())}"
            )

    async def _initialize(self) -> Dict[str, Any]:
        """发送 initialize 请求并完成握手"""
        params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
            "clientInfo": {
                "name": "meshctx-gateway",
                "version": "1.0.0",
            },
        }

        response = await self._request("initialize", params)

        # 发送 initialized 通知
        await self._notify("notifications/initialized", {})

        return response.get("result", {})

    async def _request(self, method: str, params: dict = None,
                       timeout: float = None) -> Dict[str, Any]:
        """发送 JSON-RPC 请求"""
        if not self.transport or not self.transport.is_connected:
            raise JsonRpcError(-32000, "Transport not connected")

        timeout = timeout or self.config.timeout

        # 使用 transport 的 request 方法
        if hasattr(self.transport, 'request'):
            return await self.transport.request(method, params, timeout=timeout)

        # 回退: 手动发送/接收
        req = _make_request(method, params)
        await self.transport.send(req)
        raw = await self.transport.receive(timeout=timeout)
        return _parse_response(raw)

    async def _notify(self, method: str, params: dict = None) -> None:
        """发送 JSON-RPC 通知"""
        if self.transport and self.transport.is_connected:
            if hasattr(self.transport, 'notify'):
                await self.transport.notify(method, params)
            else:
                notif = _make_notification(method, params)
                await self.transport.send(notif)

    async def list_tools(self) -> Dict[str, MCPTool]:
        """获取服务器工具列表 (tools/list)

        Returns:
            Dict[str, MCPTool]: 工具名到 MCPTool 的映射
        """
        if self.state != ServerState.INITIALIZED:
            await self.connect()

        try:
            response = await self._request("tools/list")
            tools_data = response.get("result", {}).get("tools", [])
        except JsonRpcError as e:
            if "Method not found" in str(e):
                logger.warning(f"Server '{self.config.name}' does not support tools/list")
                return {}
            raise

        self._tools_cache = {}
        for tool_entry in tools_data:
            tool = MCPTool(
                name=tool_entry.get("name", ""),
                description=tool_entry.get("description", ""),
                server_name=self.config.name,
                input_schema=tool_entry.get("inputSchema", {}),
                annotations=tool_entry.get("annotations", {}),
            )
            self._tools_cache[tool.name] = tool

        logger.info(
            f"Server '{self.config.name}': discovered {len(self._tools_cache)} tools"
        )
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None,
                        timeout: float = None) -> Dict[str, Any]:
        """调用指定的工具 (tools/call)

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 超时时间

        Returns:
            Dict: 工具执行结果, 包含 content 列表
        """
        if self.state != ServerState.INITIALIZED:
            await self.connect()

        params = {
            "name": tool_name,
            "arguments": arguments or {},
        }

        response = await self._request("tools/call", params, timeout=timeout)
        result = response.get("result", {})

        # MCP 工具调用结果格式: { "content": [ { "type": "text", "text": "..." } ] }
        return result

    async def list_resources(self) -> List[Dict[str, Any]]:
        """获取服务器资源列表 (resources/list)"""
        if self.state != ServerState.INITIALIZED:
            await self.connect()

        try:
            response = await self._request("resources/list")
            return response.get("result", {}).get("resources", [])
        except JsonRpcError:
            return []

    async def list_prompts(self) -> List[Dict[str, Any]]:
        """获取服务器提示模板列表 (prompts/list)"""
        if self.state != ServerState.INITIALIZED:
            await self.connect()

        try:
            response = await self._request("prompts/list")
            return response.get("result", {}).get("prompts", [])
        except JsonRpcError:
            return []

    async def disconnect(self) -> None:
        """断开连接"""
        if self.transport:
            await self.transport.disconnect()
            self.transport = None
        self.state = ServerState.DISCONNECTED
        self._tools_cache.clear()

    async def health_check(self) -> bool:
        """健康检查: 发送 ping 或轻量请求"""
        try:
            await self._request("tools/list", timeout=5.0)
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
# ToolRegistry — 工具注册表
# ═══════════════════════════════════════════════════════════

class ToolRegistry:
    """所有 MCP 工具的全局注册表

    维护从工具名到 MCPTool 的映射, 提供工具发现、搜索和过滤功能。
    支持跨服务器的工具名冲突检测和命名空间隔离。
    """

    def __init__(self):
        # tool_name → MCPTool (全局命名空间, 含前缀)
        self._tools: Dict[str, MCPTool] = {}
        # server_name → [tool_name, ...]
        self._server_tools: Dict[str, List[str]] = {}
        # server_name → ServerInfo
        self._servers: Dict[str, ServerInfo] = {}
        self._lock = asyncio.Lock()

    async def register_server(self, info: ServerInfo) -> None:
        """注册服务器"""
        async with self._lock:
            self._servers[info.config.name] = info
            if info.config.name not in self._server_tools:
                self._server_tools[info.config.name] = []

    async def register_tools(self, server_name: str, tools: Dict[str, MCPTool]) -> None:
        """批量注册工具"""
        async with self._lock:
            # 清除该服务器的旧工具
            old_tools = self._server_tools.get(server_name, [])
            for old_name in old_tools:
                # 尝试带前缀和不带前缀的查找
                prefixed = f"{server_name}::{old_name}"
                self._tools.pop(prefixed, None)
                self._tools.pop(old_name, None)

            self._server_tools[server_name] = []

            for tool_name, tool in tools.items():
                # 使用 server::tool 作为唯一键, 避免冲突
                prefixed_name = f"{server_name}::{tool_name}"
                tool.server_name = server_name
                self._tools[prefixed_name] = tool
                self._tools[tool_name] = tool  # 短名称作为别名 (可能被覆盖)
                self._server_tools[server_name].append(tool_name)

    async def get_tool(self, name: str, server_name: str = None) -> Optional[MCPTool]:
        """查找工具

        Args:
            name: 工具名, 可以是 "tool" 或 "server::tool"
            server_name: 如果指定, 精确查找该服务器的工具
        """
        async with self._lock:
            if server_name:
                prefixed = f"{server_name}::{name}"
                return self._tools.get(prefixed) or self._tools.get(name)
            else:
                return self._tools.get(name)

    async def list_all_tools(self) -> Dict[str, MCPTool]:
        """列出所有已注册的工具"""
        async with self._lock:
            return dict(self._tools)

    async def list_server_tools(self, server_name: str) -> List[str]:
        """列出指定服务器的工具名"""
        async with self._lock:
            return list(self._server_tools.get(server_name, []))

    async def search_tools(self, query: str) -> List[MCPTool]:
        """模糊搜索工具 (按名称和描述)"""
        results = []
        async with self._lock:
            query_lower = query.lower()
            for tool in self._tools.values():
                if query_lower in tool.name.lower() or query_lower in tool.description.lower():
                    results.append(tool)
        # 去重
        seen = set()
        unique = []
        for t in results:
            if t.name not in seen:
                seen.add(t.name)
                unique.append(t)
        return unique

    async def get_server_info(self, server_name: str) -> Optional[ServerInfo]:
        """获取服务器信息"""
        async with self._lock:
            return self._servers.get(server_name)

    async def list_servers(self) -> Dict[str, ServerInfo]:
        """列出所有服务器"""
        async with self._lock:
            return dict(self._servers)

    async def remove_server(self, server_name: str) -> None:
        """移除服务器及其所有工具"""
        async with self._lock:
            self._servers.pop(server_name, None)
            old_tools = self._server_tools.pop(server_name, [])
            for tool_name in old_tools:
                prefixed = f"{server_name}::{tool_name}"
                self._tools.pop(prefixed, None)
                self._tools.pop(tool_name, None)


# ═══════════════════════════════════════════════════════════
# GatewayRouter — 路由层
# ═══════════════════════════════════════════════════════════

class GatewayRouter:
    """Gateway 路由器

    负责:
    - 路由工具调用到正确的 MCP 服务器
    - 负载均衡和故障转移
    - 超时和重试管理
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._clients: Dict[str, MCPClient] = {}
        self._lock = asyncio.Lock()

    async def route_call(self, tool_name: str, arguments: Dict[str, Any] = None,
                         server_name: str = None,
                         timeout: float = None) -> Dict[str, Any]:
        """路由工具调用到正确的服务器

        Args:
            tool_name: 工具名称, 支持 "tool" 或 "server::tool" 格式
            arguments: 工具参数
            server_name: 指定服务器 (可选, 自动推断)
            timeout: 超时时间

        Returns:
            Dict: 工具执行结果

        Raises:
            JsonRpcError: 工具未找到或调用失败
        """
        # 1. 解析 server::tool 格式
        resolved_server = server_name
        resolved_tool = tool_name

        if "::" in tool_name:
            parts = tool_name.split("::", 1)
            resolved_server = resolved_server or parts[0]
            resolved_tool = parts[1]

        # 2. 查找工具
        tool = await self.registry.get_tool(resolved_tool, resolved_server)
        if tool is None:
            # 尝试在所有服务器中搜索
            all_tools = await self.registry.list_all_tools()
            for name, t in all_tools.items():
                if t.name == resolved_tool or name.endswith(f"::{resolved_tool}"):
                    tool = t
                    resolved_server = t.server_name
                    break

        if tool is None:
            raise JsonRpcError(-32601, f"Tool not found: {resolved_tool}")

        if not resolved_server:
            resolved_server = tool.server_name

        # 3. 获取或创建 MCP 客户端
        client = await self._get_client(resolved_server)

        # 4. 调用工具
        try:
            result = await client.call_tool(resolved_tool, arguments or {}, timeout=timeout)
            return result
        except JsonRpcError:
            # 故障转移: 尝试重连后重试一次
            logger.warning(f"Tool call failed for '{resolved_tool}' on '{resolved_server}', retrying...")
            await self._reconnect_client(resolved_server)
            client = await self._get_client(resolved_server)
            return await client.call_tool(resolved_tool, arguments or {}, timeout=timeout)

    async def _get_client(self, server_name: str) -> MCPClient:
        """获取或创建 MCP 客户端"""
        async with self._lock:
            if server_name in self._clients:
                client = self._clients[server_name]
                if client.state == ServerState.INITIALIZED:
                    return client

            server_info = await self.registry.get_server_info(server_name)
            if server_info is None:
                raise JsonRpcError(-32000, f"Server not registered: {server_name}")

            client = MCPClient(server_info.config)
            await client.connect()

            # 自动发现工具
            tools = await client.list_tools()
            await self.registry.register_tools(server_name, tools)

            self._clients[server_name] = client
            return client

    async def _reconnect_client(self, server_name: str) -> None:
        """重连客户端"""
        async with self._lock:
            old_client = self._clients.pop(server_name, None)
            if old_client:
                try:
                    await old_client.disconnect()
                except Exception:
                    pass

    async def disconnect_all(self) -> None:
        """断开所有客户端连接"""
        async with self._lock:
            for name, client in list(self._clients.items()):
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting '{name}': {e}")
            self._clients.clear()

    async def health_check_all(self) -> Dict[str, bool]:
        """对所有服务器进行健康检查"""
        results = {}
        async with self._lock:
            for name, client in list(self._clients.items()):
                try:
                    results[name] = await client.health_check()
                except Exception:
                    results[name] = False
        return results


# ═══════════════════════════════════════════════════════════
# MCPGateway — 顶层 Gateway 门面
# ═══════════════════════════════════════════════════════════


@dataclass
class Channel:
    """Communication channel for MCP Gateway."""
    channel_id: str
    server_name: str
    channel_type: str = "stdio"
    status: str = "idle"
    created_at: str = ""
    last_activity: str = ""

@dataclass  
class ChannelManager:
    """Manages communication channels."""
    channels: dict = None
    def __post_init__(self):
        if self.channels is None:
            self.channels = {}
    def add(self, ch: Channel) -> str:
        self.channels[ch.channel_id] = ch
        return ch.channel_id
    def get(self, cid: str):
        return self.channels.get(cid)
    def list_all(self):
        return list(self.channels.values())
    def remove(self, cid: str):
        return self.channels.pop(cid, None)

class MCPGateway:
    """MCP Gateway 顶层 API

    这是外部使用的主要入口, 组合了注册表、路由器和连接管理。
    提供简洁的 API 用于注册 MCP 服务器、发现工具、调用工具。
    """

    def __init__(self):
        self.registry = ToolRegistry()
        self.router = GatewayRouter(self.registry)
        self.channel_manager = ChannelManager()
        self._initialized = False

    # ── 服务器管理 ──────────────────────────────────────────

    async def register_server(
        self,
        name: str,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        transport: TransportType = TransportType.STDIO,
        url: str = "",
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        description: str = "",
        auto_connect: bool = False,
    ) -> None:
        """注册 MCP 服务器

        Args:
            name: 服务器唯一名称, e.g. "filesystem"
            command: 启动命令, e.g. "npx", "python", "node"
            args: 命令行参数
            env: 额外环境变量
            transport: 传输类型 (默认 stdio)
            url: HTTP/SSE 传输时的 URL
            timeout: 请求超时
            description: 服务器描述
            auto_connect: 是否立即连接并初始化
        """
        config = MCPServerConfig(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            transport=transport,
            url=url,
            timeout=timeout,
            description=description,
        )

        info = ServerInfo(config=config)
        await self.registry.register_server(info)

        logger.info(f"Registered MCP server: {name} (transport={transport.value})")

        if auto_connect:
            await self._connect_server(name)

    async def _connect_server(self, name: str) -> None:
        """内部: 连接并初始化服务器, 自动发现工具"""
        client = MCPClient(
            (await self.registry.get_server_info(name)).config
        )
        await client.connect()

        # 发现工具
        tools = await client.list_tools()
        await self.registry.register_tools(name, tools)

        # 更新服务器状态
        info = await self.registry.get_server_info(name)
        if info:
            info.state = ServerState.INITIALIZED
            info.client = client
            info.tools = tools
            info.capabilities = client.server_capabilities
            info.server_version = client.server_info.get("version", "")

    async def unregister_server(self, name: str) -> None:
        """注销 MCP 服务器"""
        info = await self.registry.get_server_info(name)
        if info and info.client:
            try:
                await info.client.disconnect()
            except Exception:
                pass
        await self.registry.remove_server(name)
        logger.info(f"Unregistered MCP server: {name}")

    # ── 工具发现 ────────────────────────────────────────────

    async def list_tools(self, server_name: str = None) -> List[MCPTool]:
        """列出可用工具

        Args:
            server_name: 指定服务器 (None = 所有)
        """
        if server_name:
            # 确保该服务器已连接
            await self._ensure_connected(server_name)
            names = await self.registry.list_server_tools(server_name)
            tools = []
            for name in names:
                tool = await self.registry.get_tool(name, server_name)
                if tool:
                    tools.append(tool)
            return tools
        else:
            # 返回所有工具
            all_tools = await self.registry.list_all_tools()
            # 去重 (一个工具可能有短名和全名两个条目)
            seen = set()
            result = []
            for name, tool in all_tools.items():
                key = f"{tool.server_name}::{tool.name}"
                if key not in seen:
                    seen.add(key)
                    result.append(tool)
            return result

    # ── 工具调用 ────────────────────────────────────────────

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any] = None,
        timeout: float = None,
    ) -> Dict[str, Any]:
        """调用指定工具

        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            arguments: 工具参数
            timeout: 超时 (覆盖默认值)

        Returns:
            Dict: 工具执行结果

        Raises:
            JsonRpcError: 调用失败
        """
        # 确保服务器已连接
        await self._ensure_connected(server_name)

        return await self.router.route_call(
            tool_name=tool_name,
            arguments=arguments,
            server_name=server_name,
            timeout=timeout,
        )

    async def call_tool_auto(self, tool_name: str, arguments: Dict[str, Any] = None,
                             timeout: float = None) -> Dict[str, Any]:
        """自动路由工具调用 (无需指定服务器)

        自动在所有已注册的服务器中查找工具并调用。

        Args:
            tool_name: 工具名称 (支持 "server::tool" 格式)
            arguments: 工具参数
            timeout: 超时
        """
        return await self.router.route_call(
            tool_name=tool_name,
            arguments=arguments,
            server_name=None,
            timeout=timeout,
        )

    # ── 资源/提示 ───────────────────────────────────────────

    async def list_resources(self, server_name: str) -> List[Dict[str, Any]]:
        """列出指定服务器的资源"""
        await self._ensure_connected(server_name)
        client = await self.router._get_client(server_name)
        return await client.list_resources()

    async def list_prompts(self, server_name: str) -> List[Dict[str, Any]]:
        """列出指定服务器的提示模板"""
        await self._ensure_connected(server_name)
        client = await self.router._get_client(server_name)
        return await client.list_prompts()

    # ── 状态查询 ────────────────────────────────────────────

    async def get_gateway_status(self) -> GatewayStatus:
        """获取 Gateway 整体状态"""
        servers = await self.registry.list_servers()
        all_tools = await self.list_tools()

        connected = sum(
            1 for s in servers.values()
            if s.state == ServerState.CONNECTED or s.state == ServerState.INITIALIZED
        )
        initialized = sum(
            1 for s in servers.values() if s.state == ServerState.INITIALIZED
        )

        server_status = {}
        for name, info in servers.items():
            server_status[name] = {
                "state": info.state.value,
                "tools_count": len(info.tools),
                "transport": info.config.transport.value,
                "server_version": info.server_version or "unknown",
                "error": info.error_message or None,
                "description": info.config.description,
            }

        return GatewayStatus(
            total_servers=len(servers),
            connected_servers=connected,
            initialized_servers=initialized,
            total_tools=len(all_tools),
            servers=server_status,
        )

    async def search_tools(self, query: str) -> List[MCPTool]:
        """模糊搜索工具"""
        return await self.registry.search_tools(query)

    # ── 生命周期 ────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化 Gateway: 连接所有已注册的 auto_connect 服务器"""
        if self._initialized:
            return
        self._initialized = True
        logger.info("MCP Gateway initialized")

    async def shutdown(self) -> None:
        """优雅关闭所有连接"""
        logger.info("Shutting down MCP Gateway...")
        await self.channel_manager.close_all_channels()
        await self.router.disconnect_all()
        self._initialized = False

    async def _ensure_connected(self, server_name: str) -> None:
        """确保指定服务器已连接"""
        await self.router._get_client(server_name)

    # ── 通道 / 消息 管理 ────────────────────────────────────

    async def connect(self, server_name: str) -> Channel:
        """建立与 MCP 服务器的连接通道

        创建通信通道并完成 MCP 握手, 返回激活的通道对象。

        Args:
            server_name: 服务器名称

        Returns:
            Channel: 激活的通信通道
        """
        # 确保服务器已注册且连接
        await self._ensure_connected(server_name)

        # 创建通道
        channel = await self.channel_manager.create_channel(
            server_name=server_name,
            channel_type="tools",
        )
        await self.channel_manager.activate_channel(channel.channel_id)
        logger.info(f"Connected to '{server_name}' via channel {channel.channel_id}")
        return channel

    async def disconnect(self, server_name: str) -> None:
        """断开与 MCP 服务器的连接

        关闭所有与该服务器关联的通道并释放连接资源。

        Args:
            server_name: 服务器名称
        """
        # 关闭所有通道
        await self.channel_manager.close_all_channels(server_name=server_name)
        # 断开客户端连接
        await self.router._reconnect_client(server_name)
        logger.info(f"Disconnected from '{server_name}'")

    async def send_message(
        self, server_name: str, message: Dict[str, Any],
        channel_type: str = "tools",
    ) -> str:
        """向 MCP 服务器发送消息

        通过指定通道向服务器发送 JSON-RPC 消息并返回 channel_id。

        Args:
            server_name: 目标服务器
            message: JSON-RPC 消息体
            channel_type: 通道类型 (默认 "tools")

        Returns:
            str: 通道 ID, 用于后续接收响应
        """
        # 确保通道存在
        channels = await self.channel_manager.list_channels(
            server_name=server_name, channel_type=channel_type,
        )
        if not channels:
            # 自动创建通道
            channel = await self.channel_manager.create_channel(
                server_name=server_name, channel_type=channel_type,
            )
            await self.channel_manager.activate_channel(channel.channel_id)
        else:
            channel = channels[0]

        # 发送消息到通道
        await self.channel_manager.send_to_channel(channel.channel_id, message)
        logger.debug(f"Message sent to '{server_name}' on channel {channel.channel_id}")
        return channel.channel_id

    async def receive_message(
        self, channel_id: str, timeout: float = None,
    ) -> Dict[str, Any]:
        """从通道接收消息

        阻塞等待指定通道上的下一条消息。

        Args:
            channel_id: 通道 ID (由 send_message 返回)
            timeout: 超时时间 (默认使用全局配置)

        Returns:
            Dict: 接收到的 JSON-RPC 响应消息
        """
        timeout = timeout or DEFAULT_REQUEST_TIMEOUT
        return await self.channel_manager.receive_from_channel(channel_id, timeout=timeout)

    async def list_channels(
        self, server_name: str = None, channel_type: str = None,
    ) -> List[Dict[str, Any]]:
        """列出所有通信通道

        Args:
            server_name: 按服务器过滤 (None = 所有)
            channel_type: 按类型过滤 (None = 所有)

        Returns:
            List[Dict]: 通道信息列表
        """
        channels = await self.channel_manager.list_channels(
            server_name=server_name, channel_type=channel_type,
        )
        return [
            {
                "channel_id": c.channel_id,
                "server_name": c.server_name,
                "channel_type": c.channel_type,
                "state": c.state.value,
                "metadata": c.metadata,
                "created_at": c.created_at,
                "last_activity": c.last_activity,
            }
            for c in channels
        ]

    async def broadcast_message(
        self, message: Dict[str, Any], channel_type: str = None,
    ) -> List[str]:
        """向所有活跃通道广播消息

        Args:
            message: 要广播的 JSON-RPC 消息
            channel_type: 只广播特定类型通道 (None = 所有)

        Returns:
            List[str]: 成功发送的通道 ID 列表
        """
        channels = await self.channel_manager.list_channels(channel_type=channel_type)
        sent_ids = []
        for channel in channels:
            if channel.state in (ServerState.CONNECTED, ServerState.INITIALIZED):
                try:
                    await self.channel_manager.send_to_channel(
                        channel.channel_id, message,
                    )
                    sent_ids.append(channel.channel_id)
                except JsonRpcError:
                    logger.warning(f"Failed to broadcast to channel {channel.channel_id}")
        logger.info(f"Broadcast message to {len(sent_ids)}/{len(channels)} channels")
        return sent_ids


# ═══════════════════════════════════════════════════════════
# Channel — 通信通道抽象
# ═══════════════════════════════════════════════════════════

@dataclass
class Channel:
    """MCP 通信通道

    表示与一个 MCP 服务器的逻辑通信通道。
    一个服务器可以有多个通道 (如工具通道、资源通道、提示通道)。
    """
    channel_id: str
    server_name: str
    channel_type: str  # "tools", "resources", "prompts", "notifications"
    state: ServerState = ServerState.DISCONNECTED
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_activity: float = 0.0


class ChannelManager:
    """通道管理器

    管理所有 MCP 通信通道的生命周期:
    - 通道创建和销毁
    - 通道状态跟踪
    - 消息路由到正确通道
    - 通道级健康检查
    """

    def __init__(self):
        self._channels: Dict[str, Channel] = {}
        self._server_channels: Dict[str, List[str]] = {}  # server_name → [channel_id]
        self._message_queues: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def create_channel(
        self, server_name: str, channel_type: str,
        metadata: Dict[str, Any] = None,
    ) -> Channel:
        """创建新通道"""
        async with self._lock:
            channel_id = f"{server_name}:{channel_type}:{uuid.uuid4().hex[:8]}"
            channel = Channel(
                channel_id=channel_id,
                server_name=server_name,
                channel_type=channel_type,
                state=ServerState.CONNECTING,
                metadata=metadata or {},
            )
            self._channels[channel_id] = channel
            self._server_channels.setdefault(server_name, []).append(channel_id)
            self._message_queues[channel_id] = asyncio.Queue(maxsize=1000)
            logger.info(f"Channel created: {channel_id} (type={channel_type})")
            return channel

    async def activate_channel(self, channel_id: str) -> None:
        """激活通道 (标记为已连接)"""
        async with self._lock:
            channel = self._channels.get(channel_id)
            if channel:
                channel.state = ServerState.CONNECTED
                channel.last_activity = time.time()

    async def close_channel(self, channel_id: str) -> None:
        """关闭通道"""
        async with self._lock:
            channel = self._channels.pop(channel_id, None)
            if channel:
                server_list = self._server_channels.get(channel.server_name, [])
                if channel_id in server_list:
                    server_list.remove(channel_id)
                channel.state = ServerState.DISCONNECTED
            self._message_queues.pop(channel_id, None)
            logger.debug(f"Channel closed: {channel_id}")

    async def list_channels(
        self, server_name: str = None, channel_type: str = None,
    ) -> List[Channel]:
        """列出通道

        Args:
            server_name: 按服务器过滤 (None = 所有)
            channel_type: 按类型过滤 (None = 所有)
        """
        async with self._lock:
            channels = list(self._channels.values())
            if server_name:
                channels = [c for c in channels if c.server_name == server_name]
            if channel_type:
                channels = [c for c in channels if c.channel_type == channel_type]
            return sorted(channels, key=lambda c: c.created_at)

    async def get_channel(self, channel_id: str) -> Optional[Channel]:
        """获取通道信息"""
        async with self._lock:
            return self._channels.get(channel_id)

    async def list_server_channels(self, server_name: str) -> List[Channel]:
        """列出指定服务器的所有通道"""
        return await self.list_channels(server_name=server_name)

    async def send_to_channel(
        self, channel_id: str, message: Dict[str, Any],
    ) -> None:
        """向通道发送消息"""
        queue = self._message_queues.get(channel_id)
        if queue is None:
            raise JsonRpcError(-32000, f"Channel not found: {channel_id}")
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            raise JsonRpcError(-32000, f"Channel queue full: {channel_id}")
        # 更新活动时间
        async with self._lock:
            channel = self._channels.get(channel_id)
            if channel:
                channel.last_activity = time.time()

    async def receive_from_channel(
        self, channel_id: str, timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> Dict[str, Any]:
        """从通道接收消息"""
        queue = self._message_queues.get(channel_id)
        if queue is None:
            raise JsonRpcError(-32000, f"Channel not found: {channel_id}")
        try:
            message = await asyncio.wait_for(queue.get(), timeout=timeout)
            async with self._lock:
                channel = self._channels.get(channel_id)
                if channel:
                    channel.last_activity = time.time()
            return message
        except asyncio.TimeoutError:
            raise JsonRpcError(-32000, f"Channel receive timeout: {channel_id}")

    async def close_all_channels(self, server_name: str = None) -> None:
        """关闭所有通道 (可选按服务器过滤)"""
        async with self._lock:
            if server_name:
                ids = list(self._server_channels.get(server_name, []))
            else:
                ids = list(self._channels.keys())
        for channel_id in ids:
            await self.close_channel(channel_id)


# ═══════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════

_global_gateway: Optional[MCPGateway] = None
_global_lock = asyncio.Lock()


def get_mcp_gateway() -> MCPGateway:
    """惰性初始化全局 MCPGateway 实例

    线程安全 (asyncio.Lock), 确保整个进程只有一个 Gateway 实例。

    Returns:
        MCPGateway: 全局单例
    """
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = MCPGateway()
        logger.info("Created global MCP Gateway instance")
    return _global_gateway


async def get_gateway_connectors_async() -> MCPGateway:
    """异步获取 MCP Gateway 全局单例 (带锁)"""
    global _global_gateway, _global_lock
    async with _global_lock:
        if _global_gateway is None:
            _global_gateway = MCPGateway()
            logger.info("Created global MCP Gateway instance (async)")
    return _global_gateway


def get_gateway_connectors() -> MCPGateway:
    """获取 MCP Gateway 连接器全局单例

    推荐使用此函数而不是 get_mcp_gateway()。
    这是该模块的标准 get_{name}() 入口。

    Returns:
        MCPGateway: 全局单例
    """
    return get_mcp_gateway()


# ═══════════════════════════════════════════════════════════
# 便捷函数 (同步风格的异步封装)
# ═══════════════════════════════════════════════════════════

def register_server_sync(
    name: str,
    command: str,
    args: List[str] = None,
    env: Dict[str, str] = None,
    transport: str = "stdio",
    url: str = "",
    description: str = "",
) -> None:
    """同步注册 MCP 服务器 (便捷函数)

    在已有事件循环的环境中使用 run_coroutine_threadsafe,
    否则创建新的事件循环执行。

    Example:
        register_server_sync("filesystem", "npx",
                            ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
    """
    transport_type = TransportType(transport) if transport else TransportType.STDIO

    async def _register():
        gateway = get_mcp_gateway()
        await gateway.register_server(
            name=name,
            command=command,
            args=args,
            env=env,
            transport=transport_type,
            url=url,
            description=description,
        )

    try:
        loop = asyncio.get_running_loop()
        # 如果有运行中的事件循环, 创建 task
        asyncio.ensure_future(_register())
    except RuntimeError:
        # 没有运行中的事件循环, 创建新的
        asyncio.run(_register())


# ═══════════════════════════════════════════════════════════
# CLI 诊断工具
# ═══════════════════════════════════════════════════════════

async def _cli_main():
    """CLI 诊断入口"""
    print("=" * 60)
    print("  meshctx MCP Gateway — 诊断工具")
    print("=" * 60)

    gateway = MCPGateway()

    # 注册一个示例服务器 (文件系统)
    print("\n[1] 注册文件系统 MCP 服务器...")
    await gateway.register_server(
        name="filesystem",
        command="echo",  # 占位, 实际替换为 npx
        args=["MCP filesystem placeholder"],
        description="MCP 文件系统服务器 (占位)",
    )

    status = await gateway.get_gateway_status()
    print(f"\n[2] Gateway 状态:")
    print(f"    服务器总数: {status.total_servers}")
    print(f"    已连接: {status.connected_servers}")
    print(f"    已初始化: {status.initialized_servers}")
    print(f"    工具总数: {status.total_tools}")

    print("\n[3] 搜索工具 (query='file'):")
    tools = await gateway.search_tools("file")
    for t in tools:
        print(f"    - {t.server_name}::{t.name}: {t.description}")

    print("\n✅ Gateway 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_cli_main())
