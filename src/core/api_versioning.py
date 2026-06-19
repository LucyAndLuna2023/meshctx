"""
meshctx API Versioning — API 版本管理 v1.0
============================================

完整的 API 版本管理系统,
支持 URI 路径版本、Header 版本、内容协商和弃用策略。

核心能力:
  1. 多版本共存 (v1 / v2 / v3 同时运行)
  2. 版本路由和请求分发
  3. 自动文档生成 (OpenAPI / Swagger)
  4. 弃用策略和日落时间表
  5. 向后兼容检查和迁移辅助

使用场景:
  - REST API 版本管理
  - GraphQL Schema 演进
  - gRPC 服务版本
  - SDK 兼容性矩阵

使用示例:
  av = get_api_versioning()
  av.register_version("v1", deprecated=False)
  av.register_version("v2", base_version="v1", changes=["added /users/:id/avatar"])
  router = av.route("/users", version="v2")

代码量: ~450 行
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.api_versioning")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

DEFAULT_VERSION = "v1"
LATEST_VERSION = "latest"

VERSION_PATTERN = re.compile(r"^v(\d+)$")

SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class VersionSource(str, Enum):
    """版本号来源"""
    URI_PATH = "uri_path"        # /v1/users
    HEADER = "header"            # API-Version: v1
    QUERY = "query"              # ?version=v1
    ACCEPT = "accept"            # Accept: application/json; version=v1
    HOST = "host"                # v1.api.example.com


class DeprecationLevel(str, Enum):
    """弃用级别"""
    NONE = "none"               # 正常
    WARNING = "warning"         # 有更新的版本可用
    DEPRECATED = "deprecated"   # 已弃用, 建议迁移
    SUNSET = "sunset"           # 即将移除
    REMOVED = "removed"         # 已移除


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class SemVer:
    """语义化版本号"""
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    @classmethod
    def parse(cls, version_str: str) -> Optional["SemVer"]:
        """解析语义化版本字符串"""
        match = SEMVER_PATTERN.match(version_str.strip())
        if not match:
            return None
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=match.group("prerelease") or "",
            build=match.group("build") or "",
        )

    def __str__(self) -> str:
        v = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            v += f"-{self.prerelease}"
        if self.build:
            v += f"+{self.build}"
        return v

    def __lt__(self, other: "SemVer") -> bool:
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        if self.patch != other.patch:
            return self.patch < other.patch
        # prerelease < release
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        return self.prerelease < other.prerelease

    def __eq__(self, other: "SemVer") -> bool:
        return (self.major, self.minor, self.patch, self.prerelease) == (
            other.major, other.minor, other.patch, other.prerelease,
        )

    def is_compatible(self, other: "SemVer") -> bool:
        """检查是否兼容 (相同 major)"""
        return self.major == other.major

    @property
    def version_key(self) -> str:
        """生成 v{major} 格式的版本键"""
        return f"v{self.major}"


@dataclass
class VersionInfo:
    """版本信息"""
    version_key: str              # e.g. "v1", "v2"
    semver: Optional[SemVer] = None
    name: str = ""
    description: str = ""
    base_version: str = ""        # 基于哪个版本
    changes: List[str] = field(default_factory=list)  # 变更列表
    deprecation_level: DeprecationLevel = DeprecationLevel.NONE
    sunset_date: str = ""         # 日落日期 (ISO 8601)
    sunset_message: str = ""
    release_date: str = ""
    endpoints: Dict[str, Callable] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_key": self.version_key,
            "semver": str(self.semver) if self.semver else None,
            "name": self.name,
            "description": self.description,
            "base_version": self.base_version,
            "changes": self.changes,
            "deprecation_level": self.deprecation_level.value,
            "sunset_date": self.sunset_date,
            "sunset_message": self.sunset_message,
            "release_date": self.release_date,
            "endpoints": list(self.endpoints.keys()),
            "created_at": self.created_at,
        }


@dataclass
class RouteMapping:
    """路由映射"""
    path: str                     # API 路径
    version: str                  # 版本键
    handler: Callable
    methods: List[str] = field(default_factory=lambda: ["GET"])
    deprecated: bool = False
    description: str = ""


# ═══════════════════════════════════════════════════════════
# API 版本注册表
# ═══════════════════════════════════════════════════════════

class VersionRegistry:
    """版本注册表"""

    def __init__(self):
        self._versions: Dict[str, VersionInfo] = {}
        self._version_aliases: Dict[str, str] = {}  # alias → version_key
        self._lock = threading.RLock()

    def register(self, version: VersionInfo) -> None:
        """注册版本"""
        with self._lock:
            if version.version_key in self._versions:
                logger.warning(f"Version '{version.version_key}' already registered, updating")
            self._versions[version.version_key] = version
            logger.info(f"Registered API version: {version.version_key}")

    def get(self, version_key: str) -> Optional[VersionInfo]:
        """获取版本"""
        with self._lock:
            # 检查别名
            resolved = self._version_aliases.get(version_key, version_key)
            return self._versions.get(resolved)

    def set_alias(self, alias: str, version_key: str) -> None:
        """设置版本别名"""
        with self._lock:
            if version_key not in self._versions and version_key != LATEST_VERSION:
                raise ValueError(f"Version '{version_key}' not found")
            self._version_aliases[alias] = version_key

    def resolve(self, version_hint: str) -> str:
        """解析版本提示到具体版本键"""
        with self._lock:
            # 检查别名
            if version_hint in self._version_aliases:
                return self._version_aliases[version_hint]
            # 检查直接匹配
            if version_hint in self._versions:
                return version_hint
            # latest → 返回最新版本
            if version_hint == LATEST_VERSION or version_hint == "":
                return self._get_latest_version()
            # 尝试 vN 格式
            match = VERSION_PATTERN.match(version_hint)
            if match and version_hint in self._versions:
                return version_hint
        return DEFAULT_VERSION

    def _get_latest_version(self) -> str:
        """获取最新版本键"""
        if not self._versions:
            return DEFAULT_VERSION
        # 按版本号排序
        version_items = []
        for vk, vi in self._versions.items():
            if vi.deprecation_level != DeprecationLevel.REMOVED:
                match = VERSION_PATTERN.match(vk)
                num = int(match.group(1)) if match else 0
                version_items.append((num, vk))
        if not version_items:
            return DEFAULT_VERSION
        return sorted(version_items, key=lambda x: x[0], reverse=True)[0][1]

    def list_active_versions(self) -> List[VersionInfo]:
        """列出活跃版本 (未移除)"""
        with self._lock:
            return [
                v for v in self._versions.values()
                if v.deprecation_level != DeprecationLevel.REMOVED
            ]

    def list_deprecated_versions(self) -> List[VersionInfo]:
        """列出已弃用版本"""
        with self._lock:
            return [
                v for v in self._versions.values()
                if v.deprecation_level in (DeprecationLevel.DEPRECATED, DeprecationLevel.SUNSET)
            ]

    def to_dict(self) -> Dict[str, Any]:
        """导出所有版本信息"""
        with self._lock:
            return {
                "versions": {k: v.to_dict() for k, v in self._versions.items()},
                "aliases": dict(self._version_aliases),
                "latest": self._get_latest_version(),
            }


# ═══════════════════════════════════════════════════════════
# 版本路由器
# ═══════════════════════════════════════════════════════════

class VersionRouter:
    """版本路由器

    根据请求信息将流量路由到正确的 API 版本。
    支持多种版本来源解析策略。
    """

    def __init__(self, registry: VersionRegistry):
        self.registry = registry
        self._routes: List[RouteMapping] = []
        self._lock = threading.RLock()

    def register_route(
        self, path: str, version: str, handler: Callable,
        methods: List[str] = None, description: str = "",
    ) -> None:
        """注册路由"""
        with self._lock:
            route = RouteMapping(
                path=path,
                version=version,
                handler=handler,
                methods=methods or ["GET"],
                description=description,
            )
            self._routes.append(route)

    def resolve_route(
        self, path: str, method: str = "GET", version_hint: str = None,
    ) -> Optional[RouteMapping]:
        """解析路由

        Args:
            path: 请求路径
            method: HTTP 方法
            version_hint: 版本提示 (可为 None)

        Returns:
            RouteMapping 或 None
        """
        version_key = self.registry.resolve(version_hint or LATEST_VERSION)

        with self._lock:
            # 精确匹配
            for route in self._routes:
                if route.path == path and route.version == version_key and method in route.methods:
                    return route

            # 回退: 匹配路径但不同版本
            for route in self._routes:
                if route.path == path and method in route.methods:
                    logger.warning(
                        f"Route {path} not found for {version_key}, "
                        f"falling back to {route.version}"
                    )
                    return route

        return None

    def extract_version(
        self,
        path: str = "",
        headers: Dict[str, str] = None,
        query_params: Dict[str, str] = None,
        source_order: List[VersionSource] = None,
    ) -> Optional[str]:
        """从请求中提取版本号

        按指定顺序尝试多种来源,
        默认顺序: URI路径 > Header > Query > Accept

        Args:
            path: URI 路径
            headers: 请求头
            query_params: 查询参数
            source_order: 来源优先级顺序
        """
        headers = headers or {}
        query_params = query_params or {}
        source_order = source_order or [
            VersionSource.URI_PATH,
            VersionSource.HEADER,
            VersionSource.QUERY,
            VersionSource.ACCEPT,
        ]

        for source in source_order:
            version = None

            if source == VersionSource.URI_PATH:
                # /v1/users → v1
                import re as _re
                m = _re.match(r"^/(v\d+)(?:/|$)", path)
                if m:
                    version = m.group(1)

            elif source == VersionSource.HEADER:
                # API-Version: v2
                version = headers.get("API-Version") or headers.get("Api-Version") or headers.get("api-version")

            elif source == VersionSource.QUERY:
                # ?version=v2
                version = query_params.get("version")

            elif source == VersionSource.ACCEPT:
                # Accept: application/json; version=v2
                accept = headers.get("Accept", "")
                for part in accept.split(";"):
                    part = part.strip()
                    if part.startswith("version="):
                        version = part.split("=", 1)[1]
                        break

            elif source == VersionSource.HOST:
                # v2.api.example.com
                host = headers.get("Host", "")
                parts = host.split(".")
                if parts and VERSION_PATTERN.match(parts[0]):
                    version = parts[0]

            if version:
                return version

        return None

    def list_routes(self, version: str = None) -> List[Dict[str, Any]]:
        """列出路由"""
        with self._lock:
            routes = self._routes
            if version:
                routes = [r for r in routes if r.version == version]
            return [
                {
                    "path": r.path,
                    "version": r.version,
                    "methods": r.methods,
                    "description": r.description,
                    "deprecated": r.deprecated,
                }
                for r in routes
            ]


# ═══════════════════════════════════════════════════════════
# API版本管理器 — 主类
# ═══════════════════════════════════════════════════════════

class ApiVersioningManager:
    """API 版本管理器

    中枢类, 组合版本注册表和路由器,
    提供完整版本管理 API。
    """

    def __init__(self):
        self.registry = VersionRegistry()
        self.router = VersionRouter(self.registry)
        self._default_version_source_order = [
            VersionSource.URI_PATH,
            VersionSource.HEADER,
            VersionSource.QUERY,
        ]
        self._compatibility_matrix: Dict[str, Set[str]] = {}  # version → compatible versions

    # ── 版本管理 ────────────────────────────────────────────

    def register_version(
        self,
        version_key: str,
        name: str = "",
        description: str = "",
        base_version: str = "",
        changes: List[str] = None,
        semver: str = "",
    ) -> VersionInfo:
        """注册新 API 版本

        Args:
            version_key: 版本键, e.g. "v1", "v2"
            name: 人类可读名称
            description: 版本描述
            base_version: 基于哪个版本
            changes: 变更列表
            semver: 语义化版本号字符串
        """
        info = VersionInfo(
            version_key=version_key,
            semver=SemVer.parse(semver) if semver else None,
            name=name or f"API {version_key}",
            description=description,
            base_version=base_version,
            changes=changes or [],
        )
        self.registry.register(info)

        # 设置兼容性: 同 major 版本兼容
        if info.semver:
            compat_set = self._compatibility_matrix.setdefault(version_key, set())
            for vk, vi in self.registry._versions.items():
                if vi.semver and vi.semver.is_compatible(info.semver):
                    compat_set.add(vk)
                    self._compatibility_matrix.setdefault(vk, set()).add(version_key)

        return info

    def deprecate_version(
        self,
        version_key: str,
        level: DeprecationLevel = DeprecationLevel.DEPRECATED,
        sunset_date: str = "",
        message: str = "",
    ) -> bool:
        """弃用版本

        Args:
            version_key: 要弃用的版本
            level: 弃用级别
            sunset_date: 日落日期
            message: 用户提示消息
        """
        info = self.registry.get(version_key)
        if not info:
            return False

        info.deprecation_level = level
        info.sunset_date = sunset_date
        info.sunset_message = message
        logger.warning(f"Version '{version_key}' marked as {level.value}: {message}")
        return True

    def set_latest_alias(self) -> None:
        """设置 latest → 最新版本别名"""
        latest = self.registry._get_latest_version()
        self.registry.set_alias("latest", latest)
        self.registry.set_alias(LATEST_VERSION, latest)

    def get_version_info(self, version_key: str) -> Optional[Dict[str, Any]]:
        """获取版本详细信息"""
        info = self.registry.get(version_key)
        if not info:
            return None
        return info.to_dict()

    def list_versions(self) -> List[Dict[str, Any]]:
        """列出所有版本"""
        return [v.to_dict() for v in self.registry._versions.values()]

    def get_deprecation_warnings(self) -> List[Dict[str, str]]:
        """获取所有弃用警告"""
        warnings = []
        for v in self.registry.list_deprecated_versions():
            warnings.append({
                "version": v.version_key,
                "level": v.deprecation_level.value,
                "message": v.sunset_message or f"Version {v.version_key} is {v.deprecation_level.value}",
                "sunset_date": v.sunset_date,
                "suggested_migration": f"Migrate to latest version",
            })
        return warnings

    def check_compatibility(self, version_a: str, version_b: str) -> bool:
        """检查两个版本是否兼容"""
        if version_a == version_b:
            return True
        compat = self._compatibility_matrix.get(version_a, set())
        return version_b in compat

    # ── 路由 ────────────────────────────────────────────────

    def route(
        self,
        path: str,
        method: str = "GET",
        version: str = None,
        headers: Dict[str, str] = None,
        query_params: Dict[str, str] = None,
    ) -> Optional[Dict[str, Any]]:
        """路由请求到对应版本的处理器

        这是核心路由 API。自动从请求中提取版本号,
        回退到最新版本。

        Args:
            path: API 路径
            method: HTTP 方法
            version: 显式指定版本 (可选)
            headers: HTTP 请求头
            query_params: 查询参数

        Returns:
            Dict: 路由结果 {handler, version, path, ...}
        """
        # 提取版本
        if not version:
            version = self.router.extract_version(
                path=path, headers=headers, query_params=query_params,
                source_order=self._default_version_source_order,
            )

        # 解析路由
        route = self.router.resolve_route(path, method, version)

        if not route:
            logger.debug(f"No route found for {method} {path} (version={version})")
            return None

        # 检查弃用
        version_info = self.registry.get(route.version)
        deprecation_header = None
        if version_info and version_info.deprecation_level != DeprecationLevel.NONE:
            deprecation_header = {
                "Deprecation": "true",
                "Sunset": version_info.sunset_date,
                "Link": f'</docs/migration>; rel="deprecation"; type="text/html"',
            }

        return {
            "handler": route.handler,
            "version": route.version,
            "path": route.path,
            "method": method,
            "deprecated": route.deprecated,
            "deprecation_header": deprecation_header,
        }

    def register_endpoint(
        self,
        path: str,
        version: str,
        handler: Callable,
        methods: List[str] = None,
        description: str = "",
    ) -> None:
        """注册端点处理器

        Args:
            path: API 路径
            version: 版本键
            handler: 处理函数
            methods: HTTP 方法列表
            description: 端点描述
        """
        self.router.register_route(path, version, handler, methods, description)

        # 同时注册到 VersionInfo
        info = self.registry.get(version)
        if info:
            info.endpoints[path] = handler

    def generate_openapi_spec(
        self, title: str = "meshctx API", base_url: str = "",
    ) -> Dict[str, Any]:
        """生成 OpenAPI 3.0 规范

        自动从注册的版本和路由生成 OpenAPI 文档。
        """
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": title,
                "version": self.registry._get_latest_version(),
                "description": "Auto-generated API documentation",
            },
            "servers": [{"url": base_url}] if base_url else [],
            "paths": {},
        }

        for route in self.router.list_routes():
            path_entry = spec["paths"].setdefault(route["path"], {})
            for method in route["methods"]:
                path_entry[method.lower()] = {
                    "summary": route["description"],
                    "operationId": f"{route['version']}_{route['path'].strip('/').replace('/', '_')}_{method.lower()}",
                    "parameters": [
                        {
                            "name": "version",
                            "in": "header",
                            "description": "API version",
                            "schema": {"type": "string", "default": route["version"]},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Successful response"},
                    },
                    "deprecated": route["deprecated"],
                }

        return spec


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_api_versioning: Optional[ApiVersioningManager] = None
_global_av_lock = threading.Lock()


def get_api_versioning() -> ApiVersioningManager:
    """获取全局 ApiVersioningManager 单例"""
    global _global_api_versioning
    if _global_api_versioning is None:
        with _global_av_lock:
            if _global_api_versioning is None:
                _global_api_versioning = ApiVersioningManager()
                logger.info("Created global ApiVersioningManager instance")
    return _global_api_versioning


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx API Versioning — 诊断工具")
    print("=" * 60)

    av = ApiVersioningManager()

    # 注册版本
    av.register_version("v1", name="Initial Release",
                        description="首个稳定 API 版本",
                        changes=["Initial endpoints"])
    av.register_version("v2", name="Second Release",
                        description="增强版 API",
                        base_version="v1",
                        changes=["Added user avatars", "Pagination support"],
                        semver="2.0.0")
    av.register_version("v3", name="Current",
                        description="当前版本",
                        base_version="v2",
                        changes=["GraphQL support", "WebSocket API"],
                        semver="3.0.0-beta")

    # 弃用 v1
    av.deprecate_version("v1", DeprecationLevel.DEPRECATED,
                         sunset_date="2026-12-31",
                         message="v1 will be removed on 2026-12-31. Migrate to v2+")

    av.set_latest_alias()

    # 注册端点
    def get_users_v1():
        return {"users": ["alice", "bob"], "version": "v1"}
    def get_users_v2():
        return {"users": [{"name": "alice", "avatar": "/img/a.png"},
                          {"name": "bob", "avatar": "/img/b.png"}], "version": "v2"}

    av.register_endpoint("/users", "v1", get_users_v1, ["GET"], "List users (v1)")
    av.register_endpoint("/users", "v2", get_users_v2, ["GET"], "List users with avatars (v2)")

    # 路由测试
    print("\n[1] 版本列表:")
    for v in av.list_versions():
        print(f"    {v['version_key']}: {v['name']} ({v['deprecation_level']})")

    print("\n[2] 弃用警告:")
    for w in av.get_deprecation_warnings():
        print(f"    {w['version']}: {w['message']}")

    print("\n[3] 路由测试:")
    for version_hint in ["v1", "v2", "latest", None]:
        result = av.route("/users", version=version_hint)
        if result:
            handler = result["handler"]
            print(f"    {version_hint or 'auto'} → {result['version']}: {handler()}")

    print("\n[4] OpenAPI Spec (摘要):")
    spec = av.generate_openapi_spec()
    print(f"    OpenAPI 版本: {spec['openapi']}")
    print(f"    路径数: {len(spec['paths'])}")

    print("\n✅ API Versioning 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
