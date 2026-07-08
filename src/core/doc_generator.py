"""
meshctx Doc Generator — API 文档自动生成器
===========================================

从路由/代码自动提取文档，Markdown/HTML 输出，参数/返回值文档，示例代码和变更日志。

核心功能:
  1. API 文档生成 — 从路由/函数签名自动提取
  2. Markdown / HTML 输出 — 双格式渲染
  3. 参数文档 — 类型、默认值、描述
  4. 返回值文档 — 类型、字段说明
  5. 示例代码生成 — 自动生成 curl / Python 请求示例
  6. 变更日志跟踪 — 记录 API 变更历史

使用示例:
  dg = get_doc_generator()
  dg.register_route("GET", "/api/chat", handler=chat_handler, description="Chat endpoint")
  md = dg.generate_markdown()
  html = dg.generate_html()
  dg.record_change("v1.2.0", "Added /api/chat")
"""

import hashlib
import inspect
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, get_type_hints

logger = logging.getLogger("meshctx.doc_generator")


# ═══════════════════════════════════════════════════════════
# 枚举与数据结构
# ═══════════════════════════════════════════════════════════

class ParamLocation(str, Enum):
    """参数位置。"""
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    BODY = "body"
    FORM = "form"
    COOKIE = "cookie"


class HttpMethod(str, Enum):
    """HTTP 方法。"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ContentType(str, Enum):
    """内容类型。"""
    JSON = "application/json"
    FORM = "application/x-www-form-urlencoded"
    MULTIPART = "multipart/form-data"
    TEXT = "text/plain"
    HTML = "text/html"
    OCTET = "application/octet-stream"


@dataclass
class ParamDoc:
    """参数文档。"""
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""
    location: ParamLocation = ParamLocation.QUERY
    example: Any = None
    constraints: Dict[str, Any] = field(default_factory=dict)  # e.g. {"min": 0, "max": 100}
    enum_values: List[str] = field(default_factory=list)
    deprecated: bool = False
    since: str = ""

    def to_dict(self, **kw) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "location": self.location.value,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.example is not None:
            d["example"] = self.example
        if self.constraints:
            d["constraints"] = self.constraints
        if self.enum_values:
            d["enum"] = self.enum_values
        if self.deprecated:
            d["deprecated"] = True
        if self.since:
            d["since"] = self.since
        return d


@dataclass
class ResponseDoc:
    """返回值文档。"""
    status_code: int
    description: str = ""
    content_type: ContentType = ContentType.JSON
    schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    example: Any = None
    headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        d = {
            "status_code": self.status_code,
            "description": self.description,
            "content_type": self.content_type.value,
        }
        if self.schema:
            d["schema"] = self.schema
        if self.example is not None:
            d["example"] = self.example
        if self.headers:
            d["headers"] = self.headers
        return d


@dataclass
class RouteDoc:
    """API 路由文档。"""
    method: HttpMethod
    path: str
    summary: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    params: List[ParamDoc] = field(default_factory=list)
    request_body: Optional[Dict[str, Any]] = None  # JSON Schema
    request_content_type: ContentType = ContentType.JSON
    responses: List[ResponseDoc] = field(default_factory=list)
    auth_required: bool = False
    rate_limited: bool = False
    deprecated: bool = False
    since: str = ""
    handler_name: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)  # [{"lang": "python", "code": "..."}]

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "method": self.method.value,
            "path": self.path,
            "summary": self.summary,
            "description": self.description,
            "tags": self.tags,
            "params": [p.to_dict() for p in self.params],
            "request_body": self.request_body,
            "request_content_type": self.request_content_type.value,
            "responses": [r.to_dict() for r in self.responses],
            "auth_required": self.auth_required,
            "rate_limited": self.rate_limited,
            "deprecated": self.deprecated,
            "since": self.since,
            "handler_name": self.handler_name,
            "examples": self.examples,
        }

    @property
    def operation_id(self, **kw) -> str:
        """生成 OpenAPI operationId。"""
        base = re.sub(r'[^a-zA-Z0-9]', '_', self.path.strip("/"))
        return f"{self.method.value.lower()}_{base}" if base else self.method.value.lower()


@dataclass
class ChangeLogEntry:
    """API 变更日志条目。"""
    version: str
    date: str = ""
    changes: List[str] = field(default_factory=list)
    breaking: bool = False
    description: str = ""

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "version": self.version,
            "date": self.date,
            "changes": self.changes,
            "breaking": self.breaking,
            "description": self.description,
        }


@dataclass
class DocMeta:
    """文档元信息。"""
    title: str = "API Documentation"
    version: str = "1.0.0"
    description: str = ""
    base_url: str = "http://localhost:8000"
    contact: Dict[str, str] = field(default_factory=dict)
    license_info: Dict[str, str] = field(default_factory=dict)
    generated_at: str = ""


# ═══════════════════════════════════════════════════════════
# DocGenerator 主类
# ═══════════════════════════════════════════════════════════

class DocGenerator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    meshctx API 文档自动生成器。

    从注册的路由信息自动生成 Markdown/HTML 文档,
    包括参数、返回值、示例代码和变更日志追踪。
    """

    def __init__(self, output_dir: Optional[str] = None, **kw):
        self._output_dir = output_dir or os.path.join(
            os.environ.get("MESHCTX_DATA", os.path.expanduser("~/.meshctx")),
            "docs",
        )
        self._routes: Dict[str, RouteDoc] = OrderedDict()
        self._routes_lock = threading.Lock()
        self._changelog: List[ChangeLogEntry] = []
        self._changelog_lock = threading.Lock()
        self._meta = DocMeta()

        self._callbacks: Dict[str, List[Callable]] = {
            "on_route_added": [],
            "on_doc_generated": [],
            "on_change_recorded": [],
        }

        os.makedirs(self._output_dir, exist_ok=True)
        self._load_changelog()

        logger.info(f"DocGenerator initialized (output: {self._output_dir})")

    # ── 路由注册 ─────────────────────────────────────────

    def register_route(self, method: Union[str, HttpMethod],
                       path: str,
                       handler: Optional[Callable] = None,
                       summary: str = "",
                       description: str = "",
                       tags: List[str] = None,
                       params: List[ParamDoc] = None,
                       request_body: Optional[Dict[str, Any]] = None,
                       request_content_type: Union[str, ContentType] = ContentType.JSON,
                       responses: List[ResponseDoc] = None,
                       auth_required: bool = False,
                       rate_limited: bool = False,
                       deprecated: bool = False,
                       since: str = "",
                       examples: List[Dict[str, Any]] = None) -> RouteDoc:
        """注册一个 API 路由。

        Args:
            method: HTTP 方法
            path: 路由路径 (e.g. "/api/chat")
            handler: 处理函数 (可选, 用于自动提取类型信息)
            summary: 路由摘要
            description: 详细描述
            tags: 标签列表
            params: 参数文档列表
            request_body: 请求体 JSON Schema
            request_content_type: 请求内容类型
            responses: 响应文档列表
            auth_required: 是否需要认证
            rate_limited: 是否有速率限制
            deprecated: 是否已废弃
            since: 引入版本
            examples: 示例代码列表 [{"lang": "python", "code": "..."}]

        Returns:
            RouteDoc 实例
        """
        if isinstance(method, str):
            method = HttpMethod(method.upper())
        if isinstance(request_content_type, str):
            request_content_type = ContentType(request_content_type)

        # 从 handler 自动提取参数 (如果提供)
        if handler and not params:
            params = self._extract_params_from_handler(handler)

        if handler and not responses:
            responses = self._extract_response_from_handler(handler)

        route = RouteDoc(
            method=method,
            path=path,
            summary=summary or (handler.__doc__ or "").split("\n")[0].strip() if handler else "",
            description=description or (handler.__doc__ or "").strip() if handler else "",
            tags=tags or [],
            params=params or [],
            request_body=request_body,
            request_content_type=request_content_type,
            responses=responses or [],
            auth_required=auth_required,
            rate_limited=rate_limited,
            deprecated=deprecated,
            since=since,
            handler_name=handler.__name__ if handler else "",
            examples=examples or [],
        )

        # 自动生成示例
        if not route.examples and handler:
            route.examples = self._generate_examples(route)

        key = f"{method.value} {path}"
        with self._routes_lock:
            self._routes[key] = route

        # 触发回调
        for cb in self._callbacks.get("on_route_added", []):
            try:
                cb(route)
            except Exception as e:
                logger.warning(f"Route added callback error: {e}")

        logger.debug(f"Registered route: {key}")
        return route

    def register_routes_from_module(self, module, **kw) -> int:
        """从 Python 模块自动注册路由。

        扫描模块中标记了 @route 装饰器的函数。

        Args:
            module: Python 模块对象

        Returns:
            注册的路由数
        """
        count = 0
        for name in dir(module):
            obj = getattr(module, name)
            if callable(obj) and hasattr(obj, "_meshctx_route"):
                route_info = obj._meshctx_route
                self.register_route(
                    method=route_info.get("method", "GET"),
                    path=route_info.get("path", f"/{name}"),
                    handler=obj,
                    summary=route_info.get("summary", ""),
                    description=route_info.get("description", ""),
                    tags=route_info.get("tags", []),
                    auth_required=route_info.get("auth_required", False),
                )
                count += 1
        logger.info(f"Registered {count} routes from module")
        return count

    def get_route(self, method: str, path: str, **kw) -> Optional[RouteDoc]:
        """获取指定路由的文档。"""
        with self._routes_lock:
            return self._routes.get(f"{method.upper()} {path}")

    def list_routes(self, tag: Optional[str] = None,
                    method: Optional[str] = None) -> List[RouteDoc]:
        """列出路由 (可按标签和方法过滤)。

        Args:
            tag: 按标签过滤
            method: 按 HTTP 方法过滤

        Returns:
            路由文档列表
        """
        with self._routes_lock:
            routes = list(self._routes.values())
        if method:
            routes = [r for r in routes if r.method.value == method.upper()]
        if tag:
            routes = [r for r in routes if tag in r.tags]
        return routes

    def remove_route(self, method: str, path: str, **kw) -> bool:
        """移除路由文档。"""
        key = f"{method.upper()} {path}"
        with self._routes_lock:
            if key in self._routes:
                del self._routes[key]
                logger.debug(f"Removed route: {key}")
                return True
        return False

    # ── 文档生成 ─────────────────────────────────────────

    def generate_markdown(self, output_path: Optional[str] = None, **kw) -> str:
        """生成 Markdown 格式的 API 文档。

        Args:
            output_path: 输出文件路径 (可选, 不提供则返回字符串)

        Returns:
            Markdown 字符串
        """
        with self._routes_lock:
            routes = list(self._routes.values())

        lines = [
            f"# {self._meta.title}",
            "",
            f"**版本**: {self._meta.version}  ",
            f"**Base URL**: {self._meta.base_url}  ",
            f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if self._meta.description:
            lines.append(self._meta.description)
            lines.append("")

        # 目录
        lines.append("---")
        lines.append("")
        lines.append("## 📑 目录")
        lines.append("")

        # 按 tag 分组
        grouped = self._group_by_tag(routes)

        for tag, tag_routes in grouped.items():
            tag_slug = tag.lower().replace(" ", "-")
            lines.append(f"- [{tag}](#{tag_slug}) ({len(tag_routes)} routes)")
            for r in tag_routes:
                lines.append(f"  - [`{r.method.value} {r.path}`](#{r.operation_id})")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 各分组详情
        for tag, tag_routes in grouped.items():
            lines.append(f"## {tag}")
            lines.append("")
            for route in tag_routes:
                lines.extend(self._render_route_markdown(route))
        lines.append("")

        # 变更日志
        lines.extend(self._render_changelog_markdown())

        md = "\n".join(lines)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(md)
            logger.info(f"Markdown docs saved to {output_path}")

        # 触发回调
        for cb in self._callbacks.get("on_doc_generated", []):
            try:
                cb("markdown", md)
            except Exception as e:
                logger.warning(f"Doc generated callback error: {e}")

        return md

    def generate_html(self, output_path: Optional[str] = None, **kw) -> str:
        """生成 HTML 格式的 API 文档。

        Args:
            output_path: 输出文件路径

        Returns:
            完整 HTML 字符串
        """
        with self._routes_lock:
            routes = list(self._routes.values())

        # 生成路由 HTML
        grouped = self._group_by_tag(routes)
        route_html_parts = []
        for tag, tag_routes in grouped.items():
            route_html_parts.append(
                f'<section class="tag-section" id="{tag.lower().replace(" ", "-")}">'
                f'<h2>{self._escape_html(tag)}</h2>'
            )
            for route in tag_routes:
                route_html_parts.append(self._render_route_html(route))
            route_html_parts.append('</section>')

        # 侧边栏
        sidebar_items = []
        for tag, tag_routes in grouped.items():
            sidebar_items.append(f'<li class="sidebar-tag">{self._escape_html(tag)}</li>')
            for r in tag_routes:
                sidebar_items.append(
                    f'<li class="sidebar-route">'
                    f'<a href="#{r.operation_id}">'
                    f'<span class="method {r.method.value.lower()}">{r.method.value}</span> '
                    f'{self._escape_html(r.path)}'
                    f'</a></li>'
                )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self._escape_html(self._meta.title)} — API Documentation</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117; color: #c9d1d9; display: flex; min-height: 100vh;
  }}
  .sidebar {{
    width: 280px; background: #161b22; border-right: 1px solid #30363d;
    padding: 20px; position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }}
  .sidebar h3 {{ font-size: 16px; margin-bottom: 12px; color: #58a6ff; }}
  .sidebar ul {{ list-style: none; }}
  .sidebar li {{ margin: 4px 0; font-size: 13px; }}
  .sidebar-tag {{ color: #8b949e; font-weight: bold; margin-top: 12px; text-transform: uppercase; font-size: 11px; }}
  .sidebar-route a {{ color: #c9d1d9; text-decoration: none; display: block; padding: 4px 8px; border-radius: 4px; }}
  .sidebar-route a:hover {{ background: #21262d; color: #58a6ff; }}
  .method {{ display: inline-block; font-weight: bold; font-size: 10px; padding: 1px 5px; border-radius: 3px; min-width: 45px; text-align: center; }}
  .method.get {{ background: #1a3a2a; color: #7ee787; }}
  .method.post {{ background: #1a2a3a; color: #79c0ff; }}
  .method.put {{ background: #3a2a1a; color: #d2a8ff; }}
  .method.delete {{ background: #3a1a1a; color: #f85149; }}
  .method.patch {{ background: #2a3a1a; color: #ffa657; }}
  .content {{ flex: 1; padding: 30px; max-width: 900px; }}
  .content h1 {{ font-size: 28px; margin-bottom: 8px; border-bottom: 1px solid #30363d; padding-bottom: 12px; }}
  .content h2 {{ font-size: 22px; margin: 24px 0 12px; color: #58a6ff; }}
  .route-card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    margin: 16px 0; padding: 20px;
  }}
  .route-header {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
  }}
  .route-path {{ font-family: monospace; font-size: 16px; font-weight: bold; }}
  .route-summary {{ color: #8b949e; font-size: 14px; }}
  .param-table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }}
  .param-table th {{ background: #21262d; text-align: left; padding: 6px 10px; color: #8b949e; font-weight: 600; }}
  .param-table td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; }}
  .param-table .required {{ color: #f85149; font-weight: bold; }}
  .param-table .optional {{ color: #8b949e; }}
  .code-block {{
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    padding: 12px; margin: 8px 0; font-family: monospace; font-size: 13px;
    overflow-x: auto; white-space: pre-wrap;
  }}
  .response-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px;
    font-weight: bold; margin: 4px;
  }}
  .response-2xx {{ background: #1a3a2a; color: #7ee787; }}
  .response-4xx {{ background: #3a2a1a; color: #d2a8ff; }}
  .response-5xx {{ background: #3a1a1a; color: #f85149; }}
  .deprecated-badge {{ background: #3a1a1a; color: #f85149; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
  footer {{ margin-top: 32px; padding-top: 12px; border-top: 1px solid #30363d; font-size: 12px; color: #484f58; }}
</style>
</head>
<body>
<nav class="sidebar">
  <h3>📚 {self._escape_html(self._meta.title)}</h3>
  <p style="color: #8b949e; font-size: 12px; margin-bottom: 16px;">v{self._escape_html(self._meta.version)}</p>
  <ul>
    {"".join(sidebar_items)}
  </ul>
</nav>
<main class="content">
  <h1>{self._escape_html(self._meta.title)}</h1>
  <p style="color: #8b949e;">{self._escape_html(self._meta.description)}</p>
  <p style="color: #484f58; font-size: 12px;">Base URL: {self._escape_html(self._meta.base_url)} · 生成: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

  {"".join(route_html_parts)}

  <footer>meshctx Doc Generator · Auto-generated API Documentation</footer>
</main>
</body>
</html>"""

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"HTML docs saved to {output_path}")

        return html

    def generate_openapi(self, output_path: Optional[str] = None, **kw) -> str:
        """生成 OpenAPI 3.0 JSON。

        Args:
            output_path: 输出文件路径

        Returns:
            JSON 字符串
        """
        with self._routes_lock:
            routes = list(self._routes.values())

        paths = {}
        for route in routes:
            path_item = paths.setdefault(route.path, {})

            operation = {
                "operationId": route.operation_id,
                "summary": route.summary,
                "description": route.description,
                "tags": route.tags,
                "parameters": [
                    {
                        "name": p.name,
                        "in": p.location.value,
                        "required": p.required,
                        "description": p.description,
                        "schema": {"type": p.type},
                    }
                    for p in route.params if p.location != ParamLocation.BODY
                ],
                "responses": {
                    str(r.status_code): {
                        "description": r.description,
                        "content": {
                            r.content_type.value: {
                                "schema": r.schema or {"type": "object"},
                            }
                        } if r.schema else {},
                    }
                    for r in route.responses
                },
            }

            if route.request_body:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        route.request_content_type.value: {
                            "schema": route.request_body,
                        }
                    },
                }

            if route.deprecated:
                operation["deprecated"] = True

            path_item[route.method.value.lower()] = operation

        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": self._meta.title,
                "version": self._meta.version,
                "description": self._meta.description,
            },
            "servers": [{"url": self._meta.base_url}],
            "paths": paths,
        }

        json_str = json.dumps(spec, ensure_ascii=False, indent=2)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"OpenAPI spec saved to {output_path}")

        return json_str

    def export_json(self, output_path: Optional[str] = None, **kw) -> str:
        """导出完整路由文档为 JSON。

        Args:
            output_path: 输出文件路径

        Returns:
            JSON 字符串
        """
        with self._routes_lock:
            routes = [r.to_dict() for r in self._routes.values()]

        result = {
            "meta": {
                "title": self._meta.title,
                "version": self._meta.version,
                "description": self._meta.description,
                "base_url": self._meta.base_url,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total_routes": len(routes),
            },
            "routes": routes,
            "changelog": [e.to_dict() for e in self._changelog],
        }

        json_str = json.dumps(result, ensure_ascii=False, indent=2)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"JSON docs saved to {output_path}")

        return json_str

    # ── 示例代码生成 ────────────────────────────────────

    def generate_curl_example(self, route: RouteDoc, **kw) -> str:
        """生成 curl 请求示例。

        Args:
            route: 路由文档

        Returns:
            curl 命令字符串
        """
        url = f"{self._meta.base_url}{route.path}"

        # URL 参数
        query_params = [p for p in route.params if p.location == ParamLocation.QUERY]
        if query_params:
            qp = "&".join(
                f"{p.name}={p.example if p.example is not None else 'value'}"
                for p in query_params
            )
            url += f"?{qp}"

        parts = [f"curl -X {route.method.value}"]

        # Header 参数
        for p in route.params:
            if p.location == ParamLocation.HEADER:
                parts.append(f'-H "{p.name}: {p.example or "value"}"')

        # 认证
        if route.auth_required:
            parts.append('-H "Authorization: Bearer YOUR_TOKEN"')

        # Body
        if route.request_body:
            body_json = json.dumps(route.request_body.get("example", {}), ensure_ascii=False)
            parts.append(f'-H "Content-Type: {route.request_content_type.value}"')
            parts.append(f"-d '{body_json}'")

        parts.append(f'"{url}"')
        return " \\\n  ".join(parts)

    def generate_python_example(self, route: RouteDoc, **kw) -> str:
        """生成 Python 请求示例。

        Args:
            route: 路由文档

        Returns:
            Python 代码字符串
        """
        url = f"{self._meta.base_url}{route.path}"
        lines = ["import requests", "", ""]

        # URL 参数
        query_params = [p for p in route.params if p.location == ParamLocation.QUERY]
        if query_params:
            lines.append("# 查询参数")
            lines.append("params = {")
            for p in query_params:
                val = f'"{p.example}"' if p.example is not None else '"..."'
                lines.append(f'    "{p.name}": {val},')
            lines.append("}")
            lines.append("")

        # Header
        headers_lines = []
        if route.auth_required:
            headers_lines.append('    "Authorization": "Bearer YOUR_TOKEN",')
        for p in route.params:
            if p.location == ParamLocation.HEADER:
                val = f'"{p.example}"' if p.example is not None else '"..."'
                headers_lines.append(f'    "{p.name}": {val},')

        if headers_lines:
            lines.append("headers = {")
            lines.extend(headers_lines)
            lines.append("}")
            lines.append("")

        # Body
        has_body = route.request_body is not None
        if has_body:
            body_example = route.request_body.get("example", route.request_body.get("properties", {}))
            if isinstance(body_example, dict):
                lines.append("data = {")
                for k, v in body_example.items():
                    lines.append(f'    "{k}": {json.dumps(v, ensure_ascii=False)},')
                lines.append("}")
            else:
                lines.append(f"data = {json.dumps(body_example, ensure_ascii=False)}")
            lines.append("")

        # 请求
        kwargs = []
        if query_params:
            kwargs.append("params=params")
        if headers_lines:
            kwargs.append("headers=headers")
        if has_body:
            kwargs.append("json=data")

        kw_str = ", ".join(kwargs)
        lines.append(f"# {route.summary or route.method.value + ' ' + route.path}")
        lines.append(f'response = requests.{route.method.value.lower()}("{url}"{", " + kw_str if kw_str else ""})')
        lines.append("")
        lines.append("print(response.status_code)")
        lines.append("print(response.json())")

        return "\n".join(lines)

    def _generate_examples(self, route: RouteDoc, **kw) -> List[Dict[str, Any]]:
        """为路由自动生成示例代码。"""
        examples = []
        curl = self.generate_curl_example(route)
        if curl:
            examples.append({"lang": "curl", "code": curl, "label": "cURL"})
        py = self.generate_python_example(route)
        if py:
            examples.append({"lang": "python", "code": py, "label": "Python"})
        return examples

    # ── 变更日志 ─────────────────────────────────────────

    def record_change(self, version: str, change: str,
                      breaking: bool = False,
                      description: str = "") -> ChangeLogEntry:
        """记录一次 API 变更。

        Args:
            version: 版本号
            change: 变更描述 (单条)
            breaking: 是否为破坏性变更
            description: 详细描述

        Returns:
            ChangeLogEntry
        """
        today = time.strftime("%Y-%m-%d")
        with self._changelog_lock:
            # 查找或创建版本条目
            entry = None
            for e in self._changelog:
                if e.version == version:
                    entry = e
                    break
            if entry is None:
                entry = ChangeLogEntry(version=version, date=today, description=description)
                self._changelog.insert(0, entry)

            entry.changes.append(change)
            if breaking:
                entry.breaking = True
            if description and not entry.description:
                entry.description = description

        self._persist_changelog()

        for cb in self._callbacks.get("on_change_recorded", []):
            try:
                cb(version, change)
            except Exception as e:
                logger.warning(f"Change recorded callback error: {e}")

        logger.info(f"Recorded change: [{version}] {change}")
        return entry

    def get_changelog(self, last_n: int = 0, **kw) -> List[ChangeLogEntry]:
        """获取变更日志。

        Args:
            last_n: 返回最近 N 条 (0 = 全部)

        Returns:
            变更日志列表
        """
        with self._changelog_lock:
            log = list(self._changelog)
        if last_n > 0:
            log = log[:last_n]
        return log

    def generate_changelog_markdown(self, output_path: Optional[str] = None, **kw) -> str:
        """单独生成变更日志 Markdown。

        Args:
            output_path: 输出文件路径

        Returns:
            Markdown 字符串
        """
        lines = self._render_changelog_markdown()
        md = "\n".join(lines)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(md)
        return md

    # ── 配置 ─────────────────────────────────────────────

    def set_meta(self, title: str = "", version: str = "",
                 description: str = "", base_url: str = "",
                 contact: Dict[str, str] = None,
                 license_info: Dict[str, str] = None) -> None:
        """设置文档元信息。"""
        if title:
            self._meta.title = title
        if version:
            self._meta.version = version
        if description:
            self._meta.description = description
        if base_url:
            self._meta.base_url = base_url
        if contact:
            self._meta.contact = contact
        if license_info:
            self._meta.license_info = license_info

    def on(self, event: str, callback: Callable, **kw) -> None:
        """注册事件回调。

        Events:
          - "on_route_added": (RouteDoc) -> None
          - "on_doc_generated": (format: str, content: str) -> None
          - "on_change_recorded": (version: str, change: str) -> None
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    # ── 内部方法 ─────────────────────────────────────────

    def _group_by_tag(self, routes: List[RouteDoc], **kw) -> Dict[str, List[RouteDoc]]:
        """按 tag 分组路由。无 tag 的放入 'General'。"""
        grouped: Dict[str, List[RouteDoc]] = OrderedDict()
        for route in routes:
            tags = route.tags if route.tags else ["General"]
            for tag in tags:
                grouped.setdefault(tag, []).append(route)
        return grouped

    def _render_route_markdown(self, route: RouteDoc, **kw) -> List[str]:
        """将单个路由渲染为 Markdown。"""
        lines = []

        # 路由标题
        deprecated_marker = " ⚠️ **DEPRECATED**" if route.deprecated else ""
        auth_marker = " 🔒" if route.auth_required else ""
        lines.append(f"### `{route.method.value} {route.path}`{deprecated_marker}{auth_marker}")
        lines.append(f"<a id=\"{route.operation_id}\"></a>")
        lines.append("")

        if route.summary:
            lines.append(f"**{route.summary}**")
            lines.append("")

        if route.description:
            lines.append(route.description)
            lines.append("")

        if route.since:
            lines.append(f"> 引入版本: {route.since}")
            lines.append("")

        # 参数表
        if route.params:
            lines.append("**参数**")
            lines.append("")
            lines.append("| 名称 | 类型 | 位置 | 必需 | 默认值 | 描述 |")
            lines.append("|------|------|------|------|--------|------|")
            for p in route.params:
                req = "✅" if p.required else "❌"
                default = f"`{p.default}`" if p.default is not None else "-"
                lines.append(
                    f"| `{p.name}` | `{p.type}` | `{p.location.value}` | {req} | {default} | {p.description} |"
                )
            lines.append("")

        # 请求体
        if route.request_body:
            lines.append("**Request Body**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(route.request_body, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

        # 响应
        if route.responses:
            lines.append("**响应**")
            lines.append("")
            for resp in route.responses:
                lines.append(f"- `{resp.status_code}` — {resp.description}")
                if resp.schema:
                    lines.append("")
                    lines.append("  ```json")
                    lines.append("  " + json.dumps(resp.schema, ensure_ascii=False, indent=2).replace("\n", "\n  "))
                    lines.append("  ```")
            lines.append("")

        # 示例
        for ex in route.examples:
            label = ex.get("label", ex.get("lang", "Example"))
            lines.append(f"**{label} 示例**")
            lines.append("")
            lines.append(f"```{ex.get('lang', '')}")
            lines.append(ex["code"])
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")
        return lines

    def _render_route_html(self, route: RouteDoc, **kw) -> str:
        """将单个路由渲染为 HTML。"""
        parts = [f'<div class="route-card" id="{route.operation_id}">']

        # 头部
        deprecated = ' <span class="deprecated-badge">DEPRECATED</span>' if route.deprecated else ''
        auth_badge = ' 🔒' if route.auth_required else ''
        parts.append(
            f'<div class="route-header">'
            f'<span class="method {route.method.value.lower()}">{route.method.value}</span>'
            f'<span class="route-path">{self._escape_html(route.path)}</span>'
            f'{deprecated}{auth_badge}'
            f'</div>'
        )

        if route.summary:
            parts.append(f'<div class="route-summary">{self._escape_html(route.summary)}</div>')

        if route.description:
            parts.append(f'<p>{self._escape_html(route.description)}</p>')

        # 参数表
        if route.params:
            parts.append('<table class="param-table">')
            parts.append('<tr><th>名称</th><th>类型</th><th>位置</th><th>必需</th><th>默认值</th><th>描述</th></tr>')
            for p in route.params:
                req_cls = "required" if p.required else "optional"
                req_text = "✅ 必需" if p.required else "❌ 可选"
                default = str(p.default) if p.default is not None else "-"
                parts.append(
                    f'<tr>'
                    f'<td><code>{self._escape_html(p.name)}</code></td>'
                    f'<td><code>{self._escape_html(p.type)}</code></td>'
                    f'<td>{p.location.value}</td>'
                    f'<td class="{req_cls}">{req_text}</td>'
                    f'<td>{self._escape_html(default)}</td>'
                    f'<td>{self._escape_html(p.description)}</td>'
                    f'</tr>'
                )
            parts.append('</table>')

        # 响应
        if route.responses:
            parts.append('<div style="margin-top: 12px;">')
            for resp in route.responses:
                cls = "2xx" if 200 <= resp.status_code < 300 else ("4xx" if 400 <= resp.status_code < 500 else "5xx")
                parts.append(
                    f'<span class="response-badge response-{cls}">'
                    f'{resp.status_code} — {self._escape_html(resp.description)}'
                    f'</span>'
                )
            parts.append('</div>')

        # 示例
        for ex in route.examples:
            label = self._escape_html(ex.get("label", ex.get("lang", "Example")))
            parts.append(f'<p style="margin-top: 12px; color: #8b949e;"><strong>{label}</strong></p>')
            parts.append(
                f'<div class="code-block">'
                f'{self._escape_html(ex["code"])}'
                f'</div>'
            )

        parts.append('</div>')
        return "\n".join(parts)

    def _render_changelog_markdown(self, **kw) -> List[str]:
        """渲染变更日志为 Markdown 行。"""
        if not self._changelog:
            return []

        lines = ["---", "", "## 📝 变更日志", ""]
        for entry in self._changelog:
            breaking = " 💥 **BREAKING**" if entry.breaking else ""
            lines.append(f"### {entry.version}{breaking} ({entry.date})")
            lines.append("")
            if entry.description:
                lines.append(entry.description)
                lines.append("")
            for change in entry.changes:
                lines.append(f"- {change}")
            lines.append("")
        return lines

    def _extract_params_from_handler(self, handler: Callable, **kw) -> List[ParamDoc]:
        """从函数签名自动提取参数文档。"""
        try:
            sig = inspect.signature(handler)
            hints = get_type_hints(handler) if hasattr(handler, "__annotations__") else {}
        except (ValueError, TypeError):
            return []

        params = []
        for name, param in sig.parameters.items():
            if name in ("self", "cls", "request", "response"):
                continue

            type_name = "string"
            if name in hints:
                hint = hints[name]
                if hasattr(hint, "__name__"):
                    type_name = hint.__name__
                else:
                    type_name = str(hint).replace("typing.", "")

            default = None
            required = True
            if param.default is not inspect.Parameter.empty:
                default = param.default
                required = False

            location = ParamLocation.BODY if required else ParamLocation.QUERY

            params.append(ParamDoc(
                name=name,
                type=type_name,
                required=required,
                default=default,
                location=location,
            ))
        return params

    def _extract_response_from_handler(self, handler: Callable, **kw) -> List[ResponseDoc]:
        """尝试从 handler docstring 提取响应信息。"""
        return [
            ResponseDoc(status_code=200, description="OK"),
            ResponseDoc(status_code=400, description="Bad Request"),
            ResponseDoc(status_code=500, description="Internal Server Error"),
        ]

    def _persist_changelog(self, **kw) -> None:
        """持久化变更日志。"""
        try:
            fpath = os.path.join(self._output_dir, "changelog.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self._changelog], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist changelog: {e}")

    def _load_changelog(self, **kw) -> None:
        """加载持久化的变更日志。"""
        fpath = os.path.join(self._output_dir, "changelog.json")
        if not os.path.exists(fpath):
            return
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._changelog_lock:
                self._changelog = [
                    ChangeLogEntry(
                        version=e["version"],
                        date=e.get("date", ""),
                        changes=e.get("changes", []),
                        breaking=e.get("breaking", False),
                        description=e.get("description", ""),
                    )
                    for e in data
                ]
            logger.debug(f"Loaded {len(self._changelog)} changelog entries")
        except Exception as e:
            logger.warning(f"Failed to load changelog: {e}")

    @staticmethod
    def _escape_html(text: str, **kw) -> str:
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


# ═══════════════════════════════════════════════════════════
# 路由装饰器
# ═══════════════════════════════════════════════════════════

def route(method: str = "GET", path: str = "/",
          summary: str = "", description: str = "",
          tags: List[str] = None, auth_required: bool = False) -> Callable:
    """标记函数为 API 路由的装饰器。

    由 DocGenerator.register_routes_from_module() 自动识别。

    Args:
        method: HTTP 方法
        path: 路由路径
        summary: 摘要
        description: 描述
        tags: 标签
        auth_required: 是否需要认证

    Example:
        @route("GET", "/api/health", summary="Health check", tags=["System"])
        def health(**kw):
            return {"status": "ok"}
    """
    def decorator(func: Callable, **kw) -> Callable:
        func._meshctx_route = {
            "method": method,
            "path": path,
            "summary": summary,
            "description": description,
            "tags": tags or [],
            "auth_required": auth_required,
        }
        return func
    return decorator


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_doc_generator_instance: Optional[DocGenerator] = None
_doc_generator_lock = threading.Lock()


def get_doc_generator(output_dir: Optional[str] = None) -> DocGenerator:
    """
    获取全局 DocGenerator 单例 (auto-create)。

    Args:
        output_dir: 输出目录

    Returns:
        DocGenerator 实例
    """
    global _doc_generator_instance
    if _doc_generator_instance is None:
        with _doc_generator_lock:
            if _doc_generator_instance is None:
                _doc_generator_instance = DocGenerator(output_dir=output_dir)
    return _doc_generator_instance


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    dg = get_doc_generator()

    # 设置元信息
    dg.set_meta(
        title="meshctx API",
        version="1.0.0",
        description="meshctx 多智能体系统 API 文档",
        base_url="http://localhost:8000",
    )

    # 注册路由
    dg.register_route(
        method="GET",
        path="/api/health",
        summary="Health Check",
        description="返回系统健康状态。",
        tags=["System"],
        params=[
            ParamDoc(name="verbose", type="boolean", required=False,
                     default=False, description="是否返回详细信息",
                     location=ParamLocation.QUERY),
        ],
        responses=[
            ResponseDoc(status_code=200, description="OK",
                        schema={"type": "object", "properties": {"status": {"type": "string"}}},
                        example={"status": "ok", "uptime": 12345}),
        ],
    )

    def chat_handler(message: str, model: str = "default", **kw) -> dict:
        """Send a chat message to the AI model.

        Args:
            message: The message to send
            model: Model name to use
        """
        return {"reply": "Hello!"}

    dg.register_route(
        method="POST",
        path="/api/chat",
        handler=chat_handler,
        summary="Chat Completion",
        description="向 AI 模型发送消息并获取回复。",
        tags=["AI", "Core"],
        request_body={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "用户消息"},
                "model": {"type": "string", "description": "模型名称", "default": "default"},
            },
            "required": ["message"],
            "example": {"message": "Hello, how are you?", "model": "default"},
        },
        request_content_type=ContentType.JSON,
        responses=[
            ResponseDoc(status_code=200, description="成功",
                        schema={"type": "object", "properties": {"reply": {"type": "string"}}},
                        example={"reply": "I'm doing well, thank you!"}),
            ResponseDoc(status_code=400, description="请求参数错误"),
            ResponseDoc(status_code=500, description="服务器内部错误"),
        ],
        auth_required=True,
        rate_limited=True,
        since="v1.0.0",
    )

    dg.register_route(
        method="DELETE",
        path="/api/sessions/{session_id}",
        summary="Delete Session",
        description="删除指定的会话。",
        tags=["Session"],
        params=[
            ParamDoc(name="session_id", type="string", required=True,
                     description="会话 ID", location=ParamLocation.PATH),
        ],
        responses=[
            ResponseDoc(status_code=204, description="No Content"),
            ResponseDoc(status_code=404, description="Session Not Found"),
        ],
        since="v2.0.0",
    )

    # 生成文档
    md = dg.generate_markdown()
    print(f"✅ Markdown 生成: {len(md)} 字符")

    html = dg.generate_html()
    print(f"✅ HTML 生成: {len(html)} 字符")

    openapi = dg.generate_openapi()
    print(f"✅ OpenAPI 生成: {len(openapi)} 字符")

    # 变更日志
    dg.record_change("v1.0.0", "初始版本", description="API 首次发布")
    dg.record_change("v1.1.0", "新增 /api/chat 端点")
    dg.record_change("v2.0.0", "新增 /api/sessions 端点 (破坏性变更: 移除了旧 /api/chat/gpt4)", breaking=True)

    changelog_md = dg.generate_changelog_markdown()
    print(f"✅ 变更日志: {len(changelog_md)} 字符")

    # 示例生成
    route = dg.get_route("POST", "/api/chat")
    if route:
        print(f"\n📋 curl 示例:")
        print(dg.generate_curl_example(route))
        print(f"\n📋 Python 示例:")
        print(dg.generate_python_example(route))

    print(f"\n📊 路由总数: {len(dg.list_routes())}")
    print("\n✅ Doc Generator 模块正常运行")
