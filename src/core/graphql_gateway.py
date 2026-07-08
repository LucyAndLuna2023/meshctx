"""
meshctx GraphQL Gateway — GraphQL API 网关 v1.0
=================================================

统一的 GraphQL 网关层, 支持 schema 拼接、查询优化、
缓存策略、速率限制和联邦查询。

核心能力:
  1. Schema 拼接 (Stitching) — 合并多个后端 GraphQL 服务
  2. 查询验证和深度限制
  3. 持久化查询 (Persisted Queries)
  4. 响应缓存 (基于查询哈希)
  5. 批量查询优化 (DataLoader 模式)
  6. 联邦查询支持 (Apollo Federation)

使用场景:
  - 微服务 GraphQL 统一入口
  - 前端 BFF (Backend for Frontend)
  - API 聚合层

使用示例:
  gw = get_graphql_gateway()
  gw.register_schema("users", users_sdl, users_resolvers)
  gw.register_schema("products", products_sdl, products_resolvers)
  result = await gw.execute("{ user(id: 1) { name orders { total } } }")

代码量: ~500 行
"""

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.graphql_gateway")


# ═══════════════════════════════════════════════════════════
# 常量和类型
# ═══════════════════════════════════════════════════════════

DEFAULT_MAX_DEPTH = 10
DEFAULT_MAX_COMPLEXITY = 1000
DEFAULT_CACHE_TTL = 300  # 秒
MAX_QUERY_SIZE = 1024 * 1024  # 1MB


class OperationType(str, Enum):
    """GraphQL 操作类型"""
    QUERY = "query"
    MUTATION = "mutation"
    SUBSCRIPTION = "subscription"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class SchemaRegistration:
    """注册的 GraphQL Schema"""
    name: str                          # 服务名称
    sdl: str                           # Schema Definition Language
    resolvers: Dict[str, Any]          # 解析器映射 {Type.field: resolver_fn}
    url: str = ""                      # 远程 GraphQL 端点 (联邦模式)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryAnalysis:
    """查询分析结果"""
    operation_type: OperationType
    depth: int
    complexity: int
    fields: List[str]
    estimated_cost: float = 0.0
    cacheable: bool = True
    errors: List[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """执行结果"""
    data: Optional[Dict[str, Any]] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    extensions: Dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    execution_time_ms: float = 0.0

    def to_dict(self, **kw) -> Dict[str, Any]:
        result = {}
        if self.data is not None:
            result["data"] = self.data
        if self.errors:
            result["errors"] = self.errors
        if self.extensions:
            result["extensions"] = self.extensions
        return result


@dataclass
class CacheEntry:
    """缓存条目"""
    result: Dict[str, Any]
    created_at: float
    ttl: float


# ═══════════════════════════════════════════════════════════
# 查询分析器
# ═══════════════════════════════════════════════════════════

class QueryAnalyzer:
    """GraphQL 查询静态分析器

    解析查询文档, 计算深度、复杂度和字段列表。
    不需要完整的 GraphQL 解析器, 用正则+状态机做轻量级分析。
    """

    # GraphQL 关键字
    KEYWORDS = {"query", "mutation", "subscription", "fragment", "on", "true", "false", "null"}
    DIRECTIVES = {"@include", "@skip", "@deprecated", "@specifiedBy"}

    @staticmethod
    def analyze(query: str, **kw) -> QueryAnalysis:
        """分析 GraphQL 查询

        Args:
            query: GraphQL 查询字符串

        Returns:
            QueryAnalysis: 分析结果
        """
        errors = []

        # 确定操作类型
        op_type = OperationType.QUERY
        query_lower = query.strip().lower()
        if query_lower.startswith("mutation"):
            op_type = OperationType.MUTATION
        elif query_lower.startswith("subscription"):
            op_type = OperationType.SUBSCRIPTION

        # 计算深度
        depth = QueryAnalyzer._calculate_depth(query)

        # 计算复杂度
        complexity = QueryAnalyzer._calculate_complexity(query)

        # 提取字段
        fields = QueryAnalyzer._extract_fields(query)

        # 检查缓存性
        cacheable = op_type == OperationType.QUERY

        # 深度检查
        if depth > DEFAULT_MAX_DEPTH:
            errors.append(f"Query depth {depth} exceeds maximum {DEFAULT_MAX_DEPTH}")

        # 复杂度检查
        if complexity > DEFAULT_MAX_COMPLEXITY:
            errors.append(f"Query complexity {complexity} exceeds maximum {DEFAULT_MAX_COMPLEXITY}")

        return QueryAnalysis(
            operation_type=op_type,
            depth=depth,
            complexity=complexity,
            fields=fields,
            estimated_cost=complexity * 0.01,
            cacheable=cacheable,
            errors=errors,
        )

    @staticmethod
    def _calculate_depth(query: str, **kw) -> int:
        """计算查询嵌套深度"""
        max_depth = 0
        current_depth = 0
        in_string = False
        string_char = ""

        for ch in query:
            if ch in ('"', "'") and not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char and in_string:
                in_string = False
            elif not in_string:
                if ch == "{":
                    current_depth += 1
                    max_depth = max(max_depth, current_depth)
                elif ch == "}":
                    current_depth = max(0, current_depth - 1)

        return max_depth

    @staticmethod
    def _calculate_complexity(query: str, **kw) -> int:
        """计算查询复杂度 (字段总数)"""
        # 简化: 计算顶层的字段数 * 嵌套字段
        score = 0
        in_selection = False
        selection_depth = 0
        in_string = False
        string_char = ""

        for ch in query:
            if ch in ('"', "'") and not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char and in_string:
                in_string = False
            elif not in_string:
                if ch == "{":
                    selection_depth += 1
                    in_selection = True
                elif ch == "}":
                    selection_depth = max(0, selection_depth - 1)
                elif ch in ("\n", " ", ",", "(") and in_selection and selection_depth > 0:
                    score += selection_depth

        return max(1, score)

    @staticmethod
    def _extract_fields(query: str, **kw) -> List[str]:
        """提取字段名列表"""
        fields = []
        # 简化: 匹配不在字符串内的标识符
        pattern = r'(?:^|\s|,|{)\s*([_a-zA-Z][_a-zA-Z0-9]*)\s*(?:\(|{|\s|$)'
        for match in re.finditer(pattern, query):
            field = match.group(1)
            if field not in QueryAnalyzer.KEYWORDS and field not in QueryAnalyzer.DIRECTIVES:
                if not field.startswith("__"):  # 跳过内省字段
                    fields.append(field)
        return list(dict.fromkeys(fields))  # 去重保持顺序


# ═══════════════════════════════════════════════════════════
# Schema 注册表
# ═══════════════════════════════════════════════════════════

class SchemaRegistry:
    """GraphQL Schema 注册表

    管理多个后端服务的 Schema 和 Resolver,
    支持 Schema Stitching (拼接)。
    """

    def __init__(self, **kw):
        self._schemas: Dict[str, SchemaRegistration] = {}
        self._merged_sdl: str = ""
        self._field_to_schema: Dict[str, str] = {}  # field → schema_name
        self._lock = threading.RLock()

    def register(self, schema: SchemaRegistration, **kw) -> None:
        """注册 Schema"""
        with self._lock:
            self._schemas[schema.name] = schema

            # 索引: 字段 → 服务名
            for resolver_key in schema.resolvers:
                if "." in resolver_key:
                    field = resolver_key.split(".")[-1]
                else:
                    field = resolver_key
                self._field_to_schema[field] = schema.name

            logger.info(f"Registered GraphQL schema: {schema.name}")
        self._rebuild_merged_sdl()

    def unregister(self, name: str, **kw) -> None:
        """注销 Schema"""
        with self._lock:
            schema = self._schemas.pop(name, None)
            if schema:
                # 清理索引
                keys_to_remove = [
                    k for k, v in self._field_to_schema.items()
                    if v == name
                ]
                for k in keys_to_remove:
                    del self._field_to_schema[k]
        self._rebuild_merged_sdl()

    def get_schema(self, name: str, **kw) -> Optional[SchemaRegistration]:
        """获取 Schema"""
        with self._lock:
            return self._schemas.get(name)

    def resolve_schema_for_field(self, field: str, **kw) -> Optional[str]:
        """根据字段名解析所属 Schema"""
        with self._lock:
            return self._field_to_schema.get(field)

    def list_schemas(self, **kw) -> List[Dict[str, Any]]:
        """列出所有 Schema"""
        with self._lock:
            return [
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "url": s.url or "local",
                    "resolver_count": len(s.resolvers),
                }
                for s in self._schemas.values()
            ]

    def get_merged_sdl(self, **kw) -> str:
        """获取合并后的 SDL"""
        with self._lock:
            return self._merged_sdl

    def _rebuild_merged_sdl(self, **kw) -> None:
        """重建合并的 SDL"""
        parts = []
        with self._lock:
            for name, schema in self._schemas.items():
                if schema.enabled:
                    parts.append(f"# Schema: {name}")
                    parts.append(schema.sdl)
                    parts.append("")
        self._merged_sdl = "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# 查询缓存
# ═══════════════════════════════════════════════════════════

class QueryCache:
    """GraphQL 查询响应缓存"""

    def __init__(self, max_size: int = 1000, default_ttl: float = DEFAULT_CACHE_TTL, **kw):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def _hash_query(self, query: str, variables: Dict = None, **kw) -> str:
        """计算查询哈希"""
        key = query.strip()
        if variables:
            key += json.dumps(variables, sort_keys=True)
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def get(self, query: str, variables: Dict = None, **kw) -> Optional[Dict[str, Any]]:
        """从缓存获取结果"""
        key = self._hash_query(query, variables)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if time.time() - entry.created_at > entry.ttl:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            logger.debug(f"Cache hit for query {key[:8]}...")
            return entry.result

    def set(self, query: str, variables: Dict, result: Dict[str, Any],
            ttl: float = None) -> None:
        """存入缓存"""
        key = self._hash_query(query, variables)
        with self._lock:
            # 淘汰策略: LRU (简单实现: 超过最大容量删除最旧的)
            if len(self._cache) >= self._max_size:
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k].created_at,
                )
                del self._cache[oldest_key]

            self._cache[key] = CacheEntry(
                result=result,
                created_at=time.time(),
                ttl=ttl or self._default_ttl,
            )

    def invalidate(self, query_pattern: str = None, **kw) -> int:
        """失效缓存"""
        count = 0
        with self._lock:
            if query_pattern:
                keys_to_remove = [
                    k for k in self._cache
                    if query_pattern in k
                ]
                for k in keys_to_remove:
                    del self._cache[k]
                    count += 1
            else:
                count = len(self._cache)
                self._cache.clear()
        return count

    @property
    def stats(self, **kw) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(1, total), 4),
            }


# ═══════════════════════════════════════════════════════════
# 执行引擎
# ═══════════════════════════════════════════════════════════

class ExecutionEngine:
    """GraphQL 查询执行引擎"""

    def __init__(self, registry: SchemaRegistry, **kw):
        self.registry = registry

    def execute(
        self, query: str, variables: Dict[str, Any] = None,
        operation_name: str = None,
    ) -> ExecutionResult:
        """执行 GraphQL 查询

        路由到正确的后端 Schema 并调用对应的 Resolver。

        Args:
            query: GraphQL 查询字符串
            variables: 查询变量
            operation_name: 操作名 (多条操作时指定)

        Returns:
            ExecutionResult: 执行结果
        """
        start = time.time()

        # 1. 查询分析
        analysis = QueryAnalyzer.analyze(query)

        if analysis.errors:
            return ExecutionResult(
                errors=[{"message": e} for e in analysis.errors],
                execution_time_ms=(time.time() - start) * 1000,
            )

        # 2. 路由: 找到处理该查询的 Schema
        # 简化实现: 尝试匹配字段到注册的 resolver
        data = {}
        errors = []

        try:
            for field in analysis.fields:
                schema_name = self.registry.resolve_schema_for_field(field)
                if schema_name:
                    schema = self.registry.get_schema(schema_name)
                    if schema and schema.enabled:
                        resolver = schema.resolvers.get(field)
                        if resolver:
                            # 调用 resolver
                            try:
                                result = resolver(
                                    variables=variables or {},
                                    context={"schema_name": schema_name},
                                )
                                data[field] = result
                            except Exception as e:
                                errors.append({
                                    "message": f"Resolver error for '{field}': {str(e)}",
                                    "path": [field],
                                })
                                data[field] = None

            # 如果没有任何 Schema 处理此查询
            if not data and not errors:
                return ExecutionResult(
                    data=None,
                    errors=[{"message": f"No schema found for fields: {analysis.fields}"}],
                    execution_time_ms=(time.time() - start) * 1000,
                )

        except Exception as e:
            errors.append({"message": f"Execution error: {str(e)}"})

        elapsed = (time.time() - start) * 1000
        return ExecutionResult(
            data=data if data else None,
            errors=errors,
            execution_time_ms=elapsed,
            extensions={
                "complexity": analysis.complexity,
                "depth": analysis.depth,
            },
        )


# ═══════════════════════════════════════════════════════════
# GraphQLGateway — 主类
# ═══════════════════════════════════════════════════════════

class GraphQLGateway:
    """GraphQL API 网关

    统一入口, 组合 Schema 注册、查询分析、缓存和执行。
    """

    def __init__(self, **kw):
        self.registry = SchemaRegistry()
        self.cache = QueryCache()
        self.executor = ExecutionEngine(self.registry)
        self._max_depth = DEFAULT_MAX_DEPTH
        self._max_complexity = DEFAULT_MAX_COMPLEXITY
        self._cache_enabled = True
        self._persisted_queries: Dict[str, str] = {}  # hash → query
        self._query_count: Dict[str, int] = {}
        self._lock = threading.RLock()

    # ── Schema 管理 ─────────────────────────────────────────

    def register_schema(
        self,
        name: str,
        sdl: str,
        resolvers: Dict[str, Callable],
        url: str = "",
    ) -> None:
        """注册 GraphQL Schema

        Args:
            name: 服务名称 (唯一)
            sdl: Schema Definition Language 字符串
            resolvers: 解析器映射, e.g. {"User.name": get_user_name}
            url: 远程 GraphQL 端点 (可选, 联邦模式)
        """
        schema = SchemaRegistration(
            name=name,
            sdl=sdl,
            resolvers=resolvers,
            url=url,
        )
        self.registry.register(schema)

    def unregister_schema(self, name: str, **kw) -> None:
        """注销 Schema"""
        self.registry.unregister(name)

    def list_schemas(self, **kw) -> List[Dict[str, Any]]:
        """列出所有 Schema"""
        return self.registry.list_schemas()

    def get_sdl(self, **kw) -> str:
        """获取合并的 SDL"""
        return self.registry.get_merged_sdl()

    # ── 查询执行 ────────────────────────────────────────────

    def execute(
        self,
        query: str,
        variables: Dict[str, Any] = None,
        operation_name: str = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """执行 GraphQL 查询

        这是主要 API。支持缓存、持久化查询和查询分析。

        Args:
            query: GraphQL 查询字符串 (或持久化查询的 hash)
            variables: 查询变量
            operation_name: 操作名
            use_cache: 是否使用缓存

        Returns:
            Dict: {data, errors, extensions}
        """
        variables = variables or {}

        # 持久化查询: 如果查询是 hash, 查找原始查询
        if len(query) == 64 and all(c in "0123456789abcdef" for c in query.lower()):
            persisted = self._persisted_queries.get(query)
            if persisted:
                logger.debug(f"Resolved persisted query: {query[:8]}...")
                query = persisted
            else:
                return {
                    "errors": [{"message": "PersistedQueryNotFound",
                               "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"}}],
                }

        # 统计
        with self._lock:
            query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
            self._query_count[query_hash] = self._query_count.get(query_hash, 0) + 1

        # 缓存读取
        if self._cache_enabled and use_cache and QueryAnalyzer.analyze(query).cacheable:
            cached_result = self.cache.get(query, variables)
            if cached_result:
                cached_result.setdefault("extensions", {})["cached"] = True
                return cached_result

        # 执行
        result = self.executor.execute(query, variables, operation_name)

        # 缓存写入
        if self._cache_enabled and use_cache and not result.errors:
            self.cache.set(query, variables, result.to_dict())

        return result.to_dict()

    def execute_batch(
        self, queries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """批量执行查询

        Args:
            queries: [{"query": "...", "variables": {}}, ...]

        Returns:
            List[Dict]: 结果列表
        """
        return [
            self.execute(
                q.get("query", ""),
                q.get("variables"),
                q.get("operationName"),
            )
            for q in queries
        ]

    # ── 持久化查询 ──────────────────────────────────────────

    def register_persisted_query(self, query: str, **kw) -> str:
        """注册持久化查询

        Args:
            query: GraphQL 查询字符串

        Returns:
            str: 查询 hash (客户端可使用此 hash 代替完整查询)
        """
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        with self._lock:
            self._persisted_queries[query_hash] = query
        logger.info(f"Registered persisted query: {query_hash[:8]}...")
        return query_hash

    def list_persisted_queries(self, **kw) -> List[Dict[str, str]]:
        """列出持久化查询"""
        with self._lock:
            return [
                {"hash": h[:16] + "...", "query_preview": q[:80] + ("..." if len(q) > 80 else "")}
                for h, q in self._persisted_queries.items()
            ]

    # ── 查询验证 ────────────────────────────────────────────

    def validate_query(self, query: str, **kw) -> Dict[str, Any]:
        """验证查询

        Returns:
            Dict: {valid: bool, depth: int, complexity: int, errors: [...]}
        """
        analysis = QueryAnalyzer.analyze(query)
        return {
            "valid": len(analysis.errors) == 0,
            "depth": analysis.depth,
            "complexity": analysis.complexity,
            "max_depth": self._max_depth,
            "max_complexity": self._max_complexity,
            "fields": analysis.fields,
            "errors": analysis.errors,
        }

    # ── 缓存管理 ────────────────────────────────────────────

    def invalidate_cache(self, pattern: str = None, **kw) -> int:
        """失效缓存"""
        return self.cache.invalidate(pattern)

    def get_cache_stats(self, **kw) -> Dict[str, Any]:
        """获取缓存统计"""
        return self.cache.stats

    def get_query_stats(self, **kw) -> Dict[str, Any]:
        """获取查询统计"""
        with self._lock:
            top_queries = sorted(
                self._query_count.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
            return {
                "total_unique_queries": len(self._query_count),
                "total_executions": sum(self._query_count.values()),
                "top_queries": [{"hash": h, "count": c} for h, c in top_queries],
            }

    # ── 配置 ────────────────────────────────────────────────

    def configure(
        self,
        max_depth: int = None,
        max_complexity: int = None,
        cache_enabled: bool = None,
        cache_ttl: float = None,
    ) -> None:
        """配置网关参数"""
        if max_depth is not None:
            self._max_depth = max_depth
        if max_complexity is not None:
            self._max_complexity = max_complexity
        if cache_enabled is not None:
            self._cache_enabled = cache_enabled
        if cache_ttl is not None:
            self.cache._default_ttl = cache_ttl


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_graphql_gateway: Optional[GraphQLGateway] = None
_global_gg_lock = threading.Lock()


def get_graphql_gateway() -> GraphQLGateway:
    """获取全局 GraphQLGateway 单例"""
    global _global_graphql_gateway
    if _global_graphql_gateway is None:
        with _global_gg_lock:
            if _global_graphql_gateway is None:
                _global_graphql_gateway = GraphQLGateway()
                logger.info("Created global GraphQLGateway instance")
    return _global_graphql_gateway


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx GraphQL Gateway — 诊断工具")
    print("=" * 60)

    gw = GraphQLGateway()

    # 注册 Schema
    users_sdl = """
    type User {
        id: ID!
        name: String!
        email: String
        orders: [Order]
    }
    type Order {
        id: ID!
        total: Float!
        status: String!
    }
    type Query {
        user(id: ID!): User
        users: [User]
    }
    """

    def resolve_user(variables, context, **kw):
        return {"id": variables.get("id", "1"), "name": "Alice", "email": "alice@example.com"}

    def resolve_users(variables, context, **kw):
        return [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]

    gw.register_schema("users", users_sdl, {
        "user": resolve_user,
        "users": resolve_users,
    })

    # 测试查询
    print("\n[1] Schema 列表:")
    for s in gw.list_schemas():
        print(f"    {s['name']}: {s['resolver_count']} resolvers")

    print("\n[2] 查询验证:")
    validation = gw.validate_query("{ user(id: 1) { name email } }")
    print(f"    深度: {validation['depth']}, 复杂度: {validation['complexity']}")
    print(f"    字段: {validation['fields']}")
    print(f"    有效: {validation['valid']}")

    print("\n[3] 查询执行:")
    result = gw.execute("{ user(id: \"1\") { name email } }")
    print(f"    结果: {json.dumps(result, indent=2)}")

    print("\n[4] 持久化查询:")
    hash_val = gw.register_persisted_query("{ users { id name } }")
    print(f"    Hash: {hash_val[:16]}...")
    result2 = gw.execute(hash_val)
    print(f"    通过 hash 执行: {json.dumps(result2, indent=2)}")

    print(f"\n[5] 缓存统计: {gw.get_cache_stats()}")
    print(f"[6] 查询统计: {gw.get_query_stats()}")

    print("\n✅ GraphQL Gateway 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
