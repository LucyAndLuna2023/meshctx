"""
meshctx Tool Curator v3.50 — 工具策展与管理引擎
=================================================
管理工具注册表，提供工具发现、智能推荐、调用追踪、
Schema 验证和权限控制。

核心功能:
  1. 工具注册表 — 集中管理所有可用工具
  2. 工具发现 — 按名称/标签/描述搜索工具
  3. 工具推荐 — 基于任务描述推荐最佳工具
  4. 调用追踪 — 记录每次工具调用的详细日志
  5. Schema 验证 — 验证工具参数 schema
  6. 权限控制 — 工具级别的访问权限管理

设计对标:
  - OpenAI Function Calling 工具定义
  - Anthropic Tool Use
  - LangChain Tool 抽象
  - Hermes Agent 工具注册机制

使用示例:
  curator = get_tool_curator()

  # 注册工具
  curator.register(ToolSchema(
      name="read_file",
      description="Read a file from the filesystem",
      parameters={"path": "str", "encoding": "str= utf-8"},
      permissions=["filesystem:read"],
  ))

  # 推荐工具
  recs = curator.recommend("我需要读取一个文本文件的内容")
  # → [ToolRecommendation(tool="read_file", score=0.95, reason="...")]

  # 调用工具
  result = curator.invoke("read_file", {"path": "/tmp/test.txt"})

  # 追踪
  history = curator.get_call_history(tool_name="read_file")
"""

import asyncio
import hashlib
import json
import logging
import re
import time
import traceback
import uuid
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.tool_curator")


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class ToolStatus(str, Enum):
    ACTIVE = "active"           # 正常可用
    DEPRECATED = "deprecated"   # 已弃用但保留
    DISABLED = "disabled"       # 已禁用
    EXPERIMENTAL = "experimental"  # 实验性


class Permission(str, Enum):
    """标准权限"""
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    FILESYSTEM_DELETE = "filesystem:delete"
    NETWORK_READ = "network:read"
    NETWORK_WRITE = "network:write"
    SHELL_EXEC = "shell:exec"
    CODE_EXEC = "code:exec"
    API_CALL = "api:call"
    DATABASE_READ = "database:read"
    DATABASE_WRITE = "database:write"
    USER_DATA = "user:data"
    USER_CONFIG = "user:config"
    SYSTEM_ADMIN = "system:admin"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    param_type: str = "string"          # string, number, boolean, object, array
    description: str = ""
    required: bool = False
    default: Any = None
    enum: Optional[List[Any]] = None    # 允许的值列表
    minimum: Optional[float] = None     # number 类型的最小值
    maximum: Optional[float] = None     # number 类型的最大值
    pattern: Optional[str] = None       # string 类型的正则模式

    def to_dict(self, **kw) -> Dict[str, Any]:
        d = {"type": self.param_type, "description": self.description}
        if self.enum:
            d["enum"] = self.enum
        if self.minimum is not None:
            d["minimum"] = self.minimum
        if self.maximum is not None:
            d["maximum"] = self.maximum
        if self.pattern:
            d["pattern"] = self.pattern
        if self.default is not None:
            d["default"] = self.default
        return d


@dataclass
class ToolSchema:
    """工具完整定义"""
    name: str
    description: str = ""
    parameters: List[ToolParameter] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    status: ToolStatus = ToolStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    version: str = "1.0.0"
    author: str = ""
    fn: Optional[Callable] = None       # 实际执行函数
    async_fn: Optional[Callable] = None # 异步版本
    timeout: float = 30.0               # 调用超时
    max_retries: int = 1                # 失败重试次数
    rate_limit: Optional[float] = None  # 每秒最大调用数 (None=无限)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    total_calls: int = 0
    total_errors: int = 0
    avg_duration_ms: float = 0.0

    def to_openai_function(self, **kw) -> Dict[str, Any]:
        """转换为 OpenAI Function Calling 格式"""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = p.to_dict()
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [asdict(p) for p in self.parameters],
            "permissions": self.permissions,
            "status": self.status.value,
            "tags": self.tags,
            "category": self.category,
            "version": self.version,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
        }


@dataclass
class ToolRecommendation:
    """工具推荐结果"""
    tool_name: str
    score: float                # 0.0-1.0 相关度评分
    reason: str = ""
    category: str = ""
    tags_matched: List[str] = field(default_factory=list)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "tool": self.tool_name,
            "score": round(self.score, 4),
            "reason": self.reason,
            "category": self.category,
            "tags_matched": self.tags_matched,
        }


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    tool_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None
    success: bool = True
    duration_ms: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    permission_checks: List[str] = field(default_factory=list)
    retry_count: int = 0

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ═══════════════════════════════════════════════════════════
# ToolCurator
# ═══════════════════════════════════════════════════════════

class ToolCurator:
    """
    工具策展引擎。

    核心方法:
      - register(schema) → ToolSchema
      - unregister(name) → bool
      - get(name) → Optional[ToolSchema]
      - list_tools(category, tag) → List[ToolSchema]
      - search(query) → List[ToolSchema]
      - recommend(task_description) → List[ToolRecommendation]
      - invoke(name, params) → Any
      - validate_params(name, params) → (bool, str)
      - check_permission(name, required_permissions) → (bool, str)
      - get_call_history(tool_name) → List[ToolCallRecord]
    """

    def __init__(self, max_history: int = 1000, **kw):
        self._tools: Dict[str, ToolSchema] = {}
        self._call_history: List[ToolCallRecord] = []
        self._max_history = max_history
        self._total_calls: int = 0
        self._total_errors: int = 0
        self._granted_permissions: Set[str] = set()

        # 搜索索引: keyword → set of tool names
        self._keyword_index: Dict[str, Set[str]] = defaultdict(set)

    # ── 工具注册 ──────────────────────────────────────────

    def register(self, schema: ToolSchema, **kw) -> ToolSchema:
        """
        注册工具。

        Args:
            schema: 工具定义

        Returns:
            注册后的 ToolSchema
        """
        if schema.name in self._tools:
            existing = self._tools[schema.name]
            # 合并调用统计
            schema.total_calls = existing.total_calls
            schema.total_errors = existing.total_errors
            schema.avg_duration_ms = existing.avg_duration_ms
            logger.info(f"Updated tool '{schema.name}' (v{schema.version})")
        else:
            logger.info(f"Registered tool '{schema.name}' (v{schema.version})")

        self._tools[schema.name] = schema

        # 构建搜索索引
        self._index_tool(schema)
        return schema

    def unregister(self, name: str, **kw) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            # 清理索引
            for kw in list(self._keyword_index.keys()):
                self._keyword_index[kw].discard(name)
                if not self._keyword_index[kw]:
                    del self._keyword_index[kw]
            logger.info(f"Unregistered tool '{name}'")
            return True
        return False

    def get(self, name: str, **kw) -> Optional[ToolSchema]:
        """获取工具定义"""
        return self._tools.get(name)

    def list_tools(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        status: Optional[ToolStatus] = None,
    ) -> List[ToolSchema]:
        """列出工具"""
        results = list(self._tools.values())
        if category:
            results = [t for t in results if t.category == category]
        if tag:
            results = [t for t in results if tag in t.tags]
        if status:
            results = [t for t in results if t.status == status]
        return results

    def set_status(self, name: str, status: ToolStatus, **kw) -> bool:
        """设置工具状态"""
        tool = self._tools.get(name)
        if tool:
            tool.status = status
            return True
        return False

    # ── 搜索索引 ──────────────────────────────────────────

    def _index_tool(self, schema: ToolSchema, **kw):
        """为工具建立关键词索引"""
        keywords = set()

        # 名称分词
        for part in re.split(r'[_\-\s]+', schema.name.lower()):
            if len(part) >= 2:
                keywords.add(part)

        # 描述分词
        for word in re.findall(r'\b[a-zA-Z]{3,}\b', schema.description.lower()):
            keywords.add(word)

        # 中文描述分词 (简易: 按双字组合)
        zh_chars = re.findall(r'[\u4e00-\u9fff]+', schema.description)
        for zh_word in zh_chars:
            if len(zh_word) >= 2:
                keywords.add(zh_word)
                # 双字组合
                for i in range(len(zh_word) - 1):
                    keywords.add(zh_word[i:i + 2])

        # 标签
        for tag in schema.tags:
            keywords.add(tag.lower())

        # 类别
        keywords.add(schema.category.lower())

        for kw in keywords:
            self._keyword_index[kw].add(schema.name)

    # ── 工具搜索 ──────────────────────────────────────────

    def search(self, query: str, limit: int = 10, **kw) -> List[ToolSchema]:
        """
        按关键词搜索工具。

        使用关键词索引快速匹配。

        Args:
            query: 搜索查询
            limit: 最大结果数

        Returns:
            匹配的 ToolSchema 列表 (按匹配度降序)
        """
        query_lower = query.lower()
        scores: Dict[str, int] = defaultdict(int)

        # 分词查询
        query_keywords = set()

        # 英文关键词
        for word in re.findall(r'\b[a-zA-Z]{2,}\b', query_lower):
            query_keywords.add(word)

        # 中文关键词
        zh_words = re.findall(r'[\u4e00-\u9fff]+', query)
        for zh_word in zh_words:
            query_keywords.add(zh_word)
            # 双字子串
            for i in range(len(zh_word) - 1):
                query_keywords.add(zh_word[i:i + 2])

        # 全文本匹配 (作为回退)
        full_match = re.sub(r'\s+', '', query_lower)

        for kw in query_keywords:
            if kw in self._keyword_index:
                for tool_name in self._keyword_index[kw]:
                    scores[tool_name] += 1

        # 名称精确匹配加分
        for name, tool in self._tools.items():
            if query_lower in name.lower():
                scores[name] += 3
            if query_lower in tool.description.lower():
                scores[name] += 2
            # 全文本模糊匹配
            if full_match and full_match in re.sub(r'[\s_\-]+', '', tool.description.lower()):
                scores[name] += 1

        # 排序
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        tools = []
        for name, _ in ranked[:limit]:
            tool = self._tools.get(name)
            if tool:
                tools.append(tool)

        return tools

    # ── 工具推荐 ──────────────────────────────────────────

    def recommend(
        self,
        task_description: str,
        limit: int = 5,
        min_score: float = 0.1,
    ) -> List[ToolRecommendation]:
        """
        基于任务描述推荐最佳工具。

        使用多维度评分:
          1. 关键词匹配 (描述 ↔ 工具名/tags/描述)
          2. 语义类别匹配
          3. 工具使用频率加权

        Args:
            task_description: 任务描述
            limit: 最大推荐数
            min_score: 最低相关度阈值

        Returns:
            ToolRecommendation 列表 (按 score 降序)
        """
        if not self._tools:
            return []

        task_lower = task_description.lower()
        recommendations = []

        for tool in self._tools.values():
            if tool.status == ToolStatus.DISABLED:
                continue

            score = 0.0
            reasons = []
            tags_matched = []

            # 1. 工具名匹配
            name_parts = re.split(r'[_\-\s]+', tool.name.lower())
            for part in name_parts:
                if len(part) >= 2 and part in task_lower:
                    score += 0.3
                    reasons.append(f"name match: '{part}'")
                    break

            # 2. 描述关键词匹配
            desc_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', tool.description.lower()))
            task_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', task_lower))
            common_en = desc_words & task_words
            if common_en:
                match_ratio = len(common_en) / max(len(task_words), 1)
                score += match_ratio * 0.4
                reasons.append(f"description match: {len(common_en)} words")

            # 3. 中文关键词匹配
            tool_zh = set(re.findall(r'[\u4e00-\u9fff]{2,}', tool.description))
            task_zh = set(re.findall(r'[\u4e00-\u9fff]{2,}', task_description))
            common_zh = tool_zh & task_zh
            if common_zh:
                zh_ratio = len(common_zh) / max(len(task_zh), 1)
                score += zh_ratio * 0.35
                reasons.append(f"Chinese match: {len(common_zh)} terms")

            # 4. 标签匹配
            for tag in tool.tags:
                if tag.lower() in task_lower:
                    score += 0.2
                    tags_matched.append(tag)
                    if not reasons:
                        reasons.append(f"tag match: '{tag}'")

            # 5. 类别加权 (启发式映射)
            category_map = {
                "filesystem": ["file", "read", "write", "directory", "folder", "文件", "读取", "写入", "目录"],
                "network": ["http", "api", "request", "download", "网络", "请求", "下载"],
                "code": ["code", "python", "execute", "run", "代码", "执行", "运行"],
                "database": ["database", "sql", "query", "数据库", "查询"],
                "shell": ["shell", "bash", "command", "terminal", "命令行", "终端"],
                "search": ["search", "find", "grep", "搜索", "查找"],
                "security": ["security", "scan", "audit", "vulnerability", "安全", "扫描", "审计"],
            }
            for cat, keywords in category_map.items():
                if tool.category == cat and any(kw in task_lower for kw in keywords):
                    score += 0.15
                    if not reasons:
                        reasons.append(f"category match: {cat}")

            # 6. 使用频率加权 (热门工具小幅加分)
            if tool.total_calls > 0:
                freq_bonus = min(0.1, tool.total_calls / 1000 * 0.1)
                score += freq_bonus

            # 7. 弃用惩罚
            if tool.status == ToolStatus.DEPRECATED:
                score *= 0.5

            if score >= min_score:
                recommendations.append(ToolRecommendation(
                    tool_name=tool.name,
                    score=min(score, 1.0),
                    reason="; ".join(reasons) if reasons else "general relevance",
                    category=tool.category,
                    tags_matched=tags_matched,
                ))

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:limit]

    # ── 参数验证 ──────────────────────────────────────────

    def validate_params(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        验证工具调用参数。

        Args:
            tool_name: 工具名
            params: 参数字典

        Returns:
            (is_valid, error_message)
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return False, f"Tool '{tool_name}' not found"

        if tool.status == ToolStatus.DISABLED:
            return False, f"Tool '{tool_name}' is disabled"

        # 检查必填参数
        for param_def in tool.parameters:
            if param_def.required and param_def.name not in params:
                # 检查是否有默认值
                if param_def.default is None:
                    return False, f"Missing required parameter: '{param_def.name}'"

        # 检查参数类型和约束
        for param_name, param_value in params.items():
            param_def = None
            for p in tool.parameters:
                if p.name == param_name:
                    param_def = p
                    break

            if param_def is None:
                continue  # 允许额外参数

            # 类型检查
            type_map = {
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict,
            }
            expected_type = type_map.get(param_def.param_type)
            if expected_type:
                if not isinstance(param_value, expected_type):
                    return False, (
                        f"Parameter '{param_name}': expected {param_def.param_type}, "
                        f"got {type(param_value).__name__}"
                    )

            # 枚举检查
            if param_def.enum and param_value not in param_def.enum:
                return False, (
                    f"Parameter '{param_name}': value '{param_value}' not in "
                    f"allowed values: {param_def.enum}"
                )

            # 范围检查
            if isinstance(param_value, (int, float)):
                if param_def.minimum is not None and param_value < param_def.minimum:
                    return False, f"Parameter '{param_name}': {param_value} < min {param_def.minimum}"
                if param_def.maximum is not None and param_value > param_def.maximum:
                    return False, f"Parameter '{param_name}': {param_value} > max {param_def.maximum}"

            # 正则检查
            if param_def.pattern and isinstance(param_value, str):
                if not re.match(param_def.pattern, param_value):
                    return False, (
                        f"Parameter '{param_name}': '{param_value}' does not match "
                        f"pattern '{param_def.pattern}'"
                    )

        return True, None

    # ── 权限控制 ──────────────────────────────────────────

    def grant_permission(self, permission: str, **kw):
        """授予权限"""
        self._granted_permissions.add(permission)
        logger.debug(f"Granted permission: {permission}")

    def revoke_permission(self, permission: str, **kw):
        """撤销权限"""
        self._granted_permissions.discard(permission)

    def has_permission(self, permission: str, **kw) -> bool:
        """检查是否持有某权限"""
        if "*" in self._granted_permissions or "system:admin" in self._granted_permissions:
            return True
        return permission in self._granted_permissions

    def check_permission(
        self, tool_name: str, required_permissions: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        检查工具所需的权限是否满足。

        Args:
            tool_name: 工具名
            required_permissions: 额外需要的权限

        Returns:
            (has_permission, missing_permission_desc)
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return False, f"Tool '{tool_name}' not found"

        all_required = list(tool.permissions)
        if required_permissions:
            all_required.extend(required_permissions)

        for perm in all_required:
            if not self.has_permission(perm):
                return False, f"Missing permission: '{perm}' for tool '{tool_name}'"

        return True, None

    def grant_default_permissions(self, **kw):
        """授予安全的默认权限"""
        safe_perms = [
            Permission.FILESYSTEM_READ,
            Permission.NETWORK_READ,
            Permission.API_CALL,
            Permission.DATABASE_READ,
        ]
        for p in safe_perms:
            self.grant_permission(p.value)

    # ── 工具调用 ──────────────────────────────────────────

    async def invoke(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        check_perms: bool = True,
        validate: bool = True,
    ) -> ToolCallRecord:
        """
        调用工具。

        Args:
            tool_name: 工具名
            params: 调用参数
            check_perms: 是否检查权限
            validate: 是否验证参数

        Returns:
            ToolCallRecord
        """
        self._total_calls += 1
        params = dict(params or {})

        record = ToolCallRecord(
            tool_name=tool_name,
            parameters=params,
        )

        tool = self._tools.get(tool_name)
        if tool is None:
            record.success = False
            record.error = f"Tool '{tool_name}' not found"
            record.finished_at = time.time()
            self._total_errors += 1
            self._add_to_history(record)
            return record

        if tool.status == ToolStatus.DISABLED:
            record.success = False
            record.error = f"Tool '{tool_name}' is disabled"
            record.finished_at = time.time()
            self._total_errors += 1
            self._add_to_history(record)
            return record

        # 权限检查
        if check_perms:
            has_perm, perm_error = self.check_permission(tool_name)
            if not has_perm:
                record.success = False
                record.error = perm_error
                record.permission_checks = tool.permissions
                record.finished_at = time.time()
                self._total_errors += 1
                self._add_to_history(record)
                return record
            record.permission_checks = tool.permissions

        # 参数验证
        if validate:
            is_valid, val_error = self.validate_params(tool_name, params)
            if not is_valid:
                record.success = False
                record.error = val_error
                record.finished_at = time.time()
                self._total_errors += 1
                tool.total_errors += 1
                self._add_to_history(record)
                return record

        # 执行
        record.started_at = time.time()
        for attempt in range(tool.max_retries + 1):
            try:
                record.retry_count = attempt
                fn = tool.async_fn or tool.fn

                if fn is None:
                    record.error = f"Tool '{tool_name}' has no implementation function"
                    record.success = False
                    break

                if asyncio.iscoroutinefunction(fn):
                    result = await asyncio.wait_for(fn(**params), timeout=tool.timeout)
                elif tool.async_fn:
                    result = await asyncio.wait_for(fn(**params), timeout=tool.timeout)
                else:
                    result = fn(**params)

                record.result = result
                record.success = True
                record.error = None
                break

            except asyncio.TimeoutError:
                record.error = f"Tool '{tool_name}' timed out after {tool.timeout}s"
                record.success = False
            except Exception as e:
                record.error = f"{type(e).__name__}: {e}"
                record.success = False
                logger.warning(
                    f"Tool '{tool_name}' failed (attempt {attempt + 1}/{tool.max_retries + 1}): {e}"
                )

            if attempt < tool.max_retries:
                await asyncio.sleep(0.5)

        record.finished_at = time.time()
        record.duration_ms = (record.finished_at - record.started_at) * 1000

        # 更新工具统计
        tool.total_calls += 1
        if not record.success:
            tool.total_errors += 1
        # 滑动平均
        tool.avg_duration_ms = (
            tool.avg_duration_ms * 0.9 + record.duration_ms * 0.1
        )

        self._add_to_history(record)
        return record

    def invoke_sync(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        check_perms: bool = True,
        validate: bool = True,
    ) -> ToolCallRecord:
        """同步调用工具 (内部创建事件循环)"""
        try:
            loop = asyncio.get_running_loop()
            # 已经在事件循环中，创建新任务
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.invoke(tool_name, params, check_perms, validate)
                )
                return future.result(timeout=60)
        except RuntimeError:
            # 无运行中的事件循环
            return asyncio.run(
                self.invoke(tool_name, params, check_perms, validate)
            )

    # ── 调用追踪 ──────────────────────────────────────────

    def _add_to_history(self, record: ToolCallRecord, **kw):
        self._call_history.append(record)
        if len(self._call_history) > self._max_history:
            self._call_history = self._call_history[-self._max_history:]

    def get_call_history(
        self,
        tool_name: Optional[str] = None,
        limit: int = 50,
        success_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取工具调用历史。

        Args:
            tool_name: 过滤工具名 (None = 全部)
            limit: 最大数量
            success_only: True=仅成功, False=仅失败, None=全部

        Returns:
            调用记录列表
        """
        records = self._call_history
        if tool_name:
            records = [r for r in records if r.tool_name == tool_name]
        if success_only is not None:
            records = [r for r in records if r.success == success_only]
        return [r.to_dict() for r in records[-limit:]]

    # ── OpenAPI / Function Calling 转换 ───────────────────

    def to_openai_functions(self, tool_names: Optional[List[str]] = None, **kw) -> List[Dict[str, Any]]:
        """
        将工具转换为 OpenAI Function Calling 格式。

        Args:
            tool_names: 要转换的工具名 (None = 全部)

        Returns:
            OpenAI function 定义列表
        """
        tools = self._tools.values()
        if tool_names:
            tools = [t for t in tools if t.name in tool_names]
        return [t.to_openai_function() for t in tools if t.status == ToolStatus.ACTIVE]

    # ── 批量操作 ──────────────────────────────────────────

    async def invoke_batch(
        self,
        calls: List[Tuple[str, Dict[str, Any]]],
        parallel: bool = True,
    ) -> List[ToolCallRecord]:
        """
        批量调用工具。

        Args:
            calls: [(tool_name, params), ...]
            parallel: 是否并行执行

        Returns:
            ToolCallRecord 列表
        """
        if parallel:
            tasks = [
                self.invoke(name, params)
                for name, params in calls
            ]
            return list(await asyncio.gather(*tasks, return_exceptions=False))
        else:
            results = []
            for name, params in calls:
                results.append(await self.invoke(name, params))
            return results

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取统计信息"""
        recent = self._call_history[-100:] if self._call_history else []
        success_count = sum(1 for r in recent if r.success)
        return {
            "total_tools": len(self._tools),
            "active_tools": sum(1 for t in self._tools.values() if t.status == ToolStatus.ACTIVE),
            "deprecated_tools": sum(1 for t in self._tools.values() if t.status == ToolStatus.DEPRECATED),
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "recent_success_rate": success_count / max(len(recent), 1) if recent else 1.0,
            "avg_duration_ms": (
                sum(r.duration_ms for r in recent) / max(len(recent), 1)
            ) if recent else 0,
            "granted_permissions": sorted(self._granted_permissions),
            "categories": sorted(set(t.category for t in self._tools.values())),
        }

    def get_tool_stats(self, tool_name: str, **kw) -> Optional[Dict[str, Any]]:
        """获取单个工具的统计"""
        tool = self._tools.get(tool_name)
        if tool is None:
            return None
        return {
            "name": tool.name,
            "total_calls": tool.total_calls,
            "total_errors": tool.total_errors,
            "error_rate": tool.total_errors / max(tool.total_calls, 1),
            "avg_duration_ms": tool.avg_duration_ms,
            "status": tool.status.value,
            "version": tool.version,
        }

    def clear_history(self, **kw):
        """清除调用历史"""
        self._call_history.clear()


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_tool_curator: Optional[ToolCurator] = None


def get_tool_curator() -> ToolCurator:
    """获取全局 ToolCurator 单例"""
    global _tool_curator
    if _tool_curator is None:
        _tool_curator = ToolCurator()
        # 自动授予安全默认权限
        _tool_curator.grant_default_permissions()
        logger.info("ToolCurator initialized with default permissions")
    return _tool_curator


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def register_tool(
    name: str,
    description: str,
    fn: Optional[Callable] = None,
    parameters: Optional[List[ToolParameter]] = None,
    permissions: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    category: str = "general",
) -> ToolSchema:
    """快速注册工具"""
    schema = ToolSchema(
        name=name,
        description=description,
        fn=fn,
        parameters=parameters or [],
        permissions=permissions or [],
        tags=tags or [],
        category=category,
    )
    return get_tool_curator().register(schema)


async def invoke_tool(
    tool_name: str,
    params: Optional[Dict[str, Any]] = None,
) -> ToolCallRecord:
    """快速调用工具"""
    return await get_tool_curator().invoke(tool_name, params)


def recommend_tools(
    task: str,
    limit: int = 5,
) -> List[ToolRecommendation]:
    """快速推荐工具"""
    return get_tool_curator().recommend(task, limit)


def search_tools(query: str, limit: int = 10) -> List[ToolSchema]:
    """快速搜索工具"""
    return get_tool_curator().search(query, limit)
