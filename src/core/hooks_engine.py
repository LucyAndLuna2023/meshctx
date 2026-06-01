"""
MeshCtx P0-6 Hooks系统 — 事件驱动的PreToolUse/PostToolUse钩子引擎
====================================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

对标Goose CLI的Hooks系统，提供细粒度的执行生命周期钩子。

核心特性:
- 单例HookSystem: 全局唯一的钩子管理器
- 7种事件类型: pre_tool_use, post_tool_use, pre_llm_call, post_llm_call,
  pre_decision, post_decision, on_error
- 可插拔回调: 注册/注销/触发回调，支持优先级排序
- 内置安全钩子: 阻止破坏性命令、防止凭证泄露、速率限制守卫
- 线程安全: 使用RLock保护注册表并发访问
- 优雅降级: 所有集成都是可选的，不影响核心流程

用法:
    from .hooks_engine import get_hook_system

    # 注册自定义钩子
    hs = get_hook_system()
    hook_id = hs.register_hook("pre_tool_use", my_callback, priority=50)

    # 触发事件
    result = hs.fire_event("pre_tool_use", {"tool_name": "Bash", "command": "ls"})
    if not result.allowed:
        print(f"被阻止: {result.blocked_by}")

参考:
- src/core/goal_checker.py 的单例模式
- src/core/code_reviewer.py 的dataclass模式
- src/core/agent_loop.py 的OODA循环位置

纯中文注释

License: Proprietary Core.
"""
import re
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Union
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 事件类型枚举 — 对标Goose CLI的7种Hook事件
# ═══════════════════════════════════════════════════════════

class HookEvent(Enum):
    """钩子事件类型 — 覆盖完整的工具调用和LLM调用生命周期"""
    PRE_TOOL_USE = "pre_tool_use"        # 工具调用之前 — 可阻止或修改参数
    POST_TOOL_USE = "post_tool_use"       # 工具调用之后 — 可修改结果
    PRE_LLM_CALL = "pre_llm_call"         # LLM调用之前 — 可阻止或修改提示词
    POST_LLM_CALL = "post_llm_call"       # LLM调用之后 — 可修改响应
    PRE_DECISION = "pre_decision"         # OODA决策阶段之前 — 可影响决策
    POST_DECISION = "post_decision"       # OODA决策阶段之后 — 可监听决策
    ON_ERROR = "on_error"                 # 错误发生时 — 用于告警和恢复

    # ── v2.42 向后兼容别名 ──
    PRE_TOOL = "pre_tool_use"
    POST_TOOL = "post_tool_use"
    STOP = "post_decision"
    USER_PROMPT = "pre_llm_call"
    SUBAGENT_STOP = "on_error"
    SESSION_START = "pre_decision"


# ═══════════════════════════════════════════════════════════
# 数据类 — 钩子触发结果
# ═══════════════════════════════════════════════════════════

@dataclass
class HookResult:
    """
    钩子事件触发后返回的结果。

    Attributes:
        allowed: 事件是否被允许继续执行 (False表示被某个钩子阻止)
        blocked_by: 如果被阻止，记录阻止者的钩子名称 (None表示未被阻止)
        modified_context: 经过所有钩子修改后的上下文字典
        hooks_fired: 本次触发执行的所有钩子ID列表 (按优先级顺序)
        warnings: 钩子产生的非致命警告列表
        metadata: 任意附加元数据
    """
    allowed: bool = True
    blocked_by: Optional[str] = None
    modified_context: Dict[str, Any] = field(default_factory=dict)
    hooks_fired: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典格式，方便API返回"""
        return {
            "allowed": self.allowed,
            "blocked_by": self.blocked_by,
            "modified_context": self.modified_context,
            "hooks_fired": self.hooks_fired,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# 钩子注册项 — 内部数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class _HookEntry:
    """
    内部存储的钩子注册项。

    Attributes:
        hook_id: 唯一标识符 (UUID)
        event: 绑定的事件类型
        callback: 回调函数 callback(context: Dict) -> Dict
        priority: 优先级 (越高越先执行, 默认50)
        enabled: 是否启用
        name: 人类可读名称 (用于日志和调试)
        created_at: 注册时间戳
        fire_count: 累计触发次数
        block_count: 累计阻止次数
    """
    hook_id: str
    event: HookEvent
    callback: Callable[[Dict[str, Any]], Dict[str, Any]]
    priority: int = 50
    enabled: bool = True
    name: str = ""
    created_at: float = field(default_factory=time.time)
    fire_count: int = 0
    block_count: int = 0

    def info(self) -> Dict[str, Any]:
        """返回钩子基本信息 (用于API列表)"""
        return {
            "hook_id": self.hook_id,
            "event": self.event.value,
            "name": self.name,
            "priority": self.priority,
            "enabled": self.enabled,
            "fire_count": self.fire_count,
            "block_count": self.block_count,
            "created_at": self.created_at,
        }


# ═══════════════════════════════════════════════════════════
# HookSystem — 单例钩子管理器
# ═══════════════════════════════════════════════════════════

class HookSystem:
    """
    P0-6 钩子系统核心类 — 对标Goose CLI的PreToolUse/PostToolUse机制。

    单例模式 — 全局唯一实例，通过 get_hook_system() 获取。

    工作流程:
    1. register_hook(event, callback) — 注册钩子回调
    2. fire_event(event, context) → HookResult — 按优先级顺序触发所有匹配钩子
    3. 每个钩子的回调返回一个Dict来控制流:
       - pre_tool_use: 返回 {"allow": True/False, "reason": "...", "modified_args": {...}}
       - post_tool_use: 返回 {"result": ..., "modified": True/False}
       - pre_llm_call: 返回 {"allow": True/False, "modified_prompt": "..."}
       - pre_decision: 返回 {"allow": True/False, "modified_decision": {...}}
       - 任何事件: 返回 {"allow": False, "reason": "..."} 来阻止

    设计理念:
    - 优先级: 高优先级钩子先执行，内置安全钩子priority=100始终最先
    - 短路: 一旦某个钩子返回 allow=False，后续钩子不再执行
    - 修改: 钩子可以修改context，修改后的context传递给下一个钩子
    - 线程安全: RLock保护注册表
    """

    # ── 单例 ──────────────────────────────────────────

    _instance: Optional["HookSystem"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "HookSystem":
        """线程安全的单例实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化钩子系统 (单例只初始化一次)"""
        if self._initialized:
            return
        self._initialized = True

        # 钩子注册表: {hook_id: _HookEntry}
        self._hooks: Dict[str, _HookEntry] = {}

        # 事件→钩子ID索引加速查找: {event: [hook_id, ...]}
        self._event_index: Dict[HookEvent, List[str]] = {
            e: [] for e in HookEvent
        }

        # 线程锁
        self._rwlock = threading.RLock()

        # 计数器
        import uuid as _uuid
        self._uuid = _uuid

        # 统计
        self._total_events_fired: int = 0
        self._total_hooks_triggered: int = 0
        self._total_blocks: int = 0

        # 注册内置安全钩子
        self._register_builtin_hooks()

        logger.info("P0-6 HookSystem 钩子系统已初始化 (含内置安全钩子)")

    # ── 公开API — 注册与注销 ─────────────────────────

    def register_hook(
        self,
        event: Union[str, HookEvent],
        callback: Callable[[Dict[str, Any]], Dict[str, Any]],
        priority: int = 50,
        name: str = "",
    ) -> str:
        """
        注册一个钩子回调。

        Args:
            event: 事件类型字符串或HookEvent枚举值
            callback: 回调函数，签名为 callback(context: Dict) -> Dict
            priority: 优先级 (0-100, 越高越先执行, 默认50)
            name: 人类可读名称 (可选, 用于日志和调试)

        Returns:
            hook_id: 唯一标识符字符串，用于后续注销

        回调签名示例:
            def my_pre_tool_hook(context):
                if context.get("tool_name") == "Bash":
                    cmd = context.get("command", "")
                    if "rm -rf" in cmd:
                        return {"allow": False, "reason": "禁止强制执行删除"}
                return {"allow": True}

        Raises:
            ValueError: 如果event类型无效
        """
        # 规范化事件类型
        if isinstance(event, str):
            try:
                event = HookEvent(event)
            except ValueError:
                raise ValueError(
                    f"无效的事件类型: '{event}'。"
                    f"支持的类型: {[e.value for e in HookEvent]}"
                )

        hook_id = str(self._uuid.uuid4())

        entry = _HookEntry(
            hook_id=hook_id,
            event=event,
            callback=callback,
            priority=max(0, min(100, priority)),  # 钳制到0-100
            name=name or f"hook_{hook_id[:8]}",
        )

        with self._rwlock:
            self._hooks[hook_id] = entry
            self._event_index[event].append(hook_id)
            # 按优先级排序 (降序: 高优先级在前)
            self._event_index[event].sort(
                key=lambda hid: self._hooks[hid].priority, reverse=True
            )

        logger.debug(
            f"钩子已注册: id={hook_id[:8]} event={event.value} "
            f"priority={entry.priority} name={entry.name}"
        )
        return hook_id

    def unregister_hook(self, hook_id: str) -> bool:
        """
        注销一个已注册的钩子。

        Args:
            hook_id: register_hook() 返回的唯一标识符

        Returns:
            True 如果成功注销, False 如果钩子不存在
        """
        with self._rwlock:
            entry = self._hooks.pop(hook_id, None)
            if entry is None:
                logger.warning(f"注销失败: 钩子不存在 id={hook_id[:8]}")
                return False

            # 从事件索引中移除
            event = entry.event
            if hook_id in self._event_index[event]:
                self._event_index[event].remove(hook_id)

        logger.debug(
            f"钩子已注销: id={hook_id[:8]} event={event.value} name={entry.name}"
        )
        return True

    def get_hook(self, hook_id: str) -> Optional[Dict[str, Any]]:
        """获取单个钩子信息"""
        with self._rwlock:
            entry = self._hooks.get(hook_id)
            return entry.info() if entry else None

    def list_hooks(
        self, event: Optional[Union[str, HookEvent]] = None
    ) -> List[Dict[str, Any]]:
        """
        列出所有注册的钩子。

        Args:
            event: 可选，按事件类型过滤 (None表示列出所有)

        Returns:
            钩子信息字典列表
        """
        with self._rwlock:
            if event is not None:
                if isinstance(event, str):
                    event = HookEvent(event)
                entries = [
                    self._hooks[hid]
                    for hid in self._event_index.get(event, [])
                    if hid in self._hooks
                ]
            else:
                entries = list(self._hooks.values())

            return [e.info() for e in entries]

    def enable_hook(self, hook_id: str) -> bool:
        """启用一个已禁用的钩子"""
        with self._rwlock:
            entry = self._hooks.get(hook_id)
            if entry:
                entry.enabled = True
                return True
        return False

    def disable_hook(self, hook_id: str) -> bool:
        """禁用一个钩子 (不删除, 可重新启用)"""
        with self._rwlock:
            entry = self._hooks.get(hook_id)
            if entry:
                entry.enabled = False
                return True
        return False

    # ── 核心方法 — 事件触发 ──────────────────────────

    def fire_event(
        self,
        event: Union[str, HookEvent],
        context: Optional[Dict[str, Any]] = None,
    ) -> HookResult:
        """
        触发一个钩子事件，按优先级顺序执行所有注册的钩子。

        执行语义:
        1. 按优先级降序排序 (priority=100最先执行)
        2. 同优先级按注册顺序 (FIFO)
        3. 每个钩子修改后的context传递给下一个钩子 (链式修改)
        4. 一旦某个钩子返回 allow=False → 短路，后续不再执行
        5. 被禁用的钩子跳过

        Args:
            event: 事件类型字符串或枚举值
            context: 上下文数据 (传递给回调的Dict)

        Returns:
            HookResult 包含是否允许、阻止者和修改后的上下文

        Raises:
            ValueError: 如果event类型无效
        """
        # 规范化事件类型
        if isinstance(event, str):
            try:
                event = HookEvent(event)
            except ValueError:
                raise ValueError(
                    f"无效的事件类型: '{event}'。"
                    f"支持的类型: {[e.value for e in HookEvent]}"
                )

        context = dict(context or {})  # 复制，避免修改调用方原始数据
        result = HookResult(modified_context=context)
        self._total_events_fired += 1

        with self._rwlock:
            hook_ids = list(self._event_index.get(event, []))

        for hook_id in hook_ids:
            with self._rwlock:
                entry = self._hooks.get(hook_id)
                if entry is None or not entry.enabled:
                    continue

            # 为每个钩子注入元数据
            ctx_with_meta = dict(context)
            ctx_with_meta["_hook_id"] = hook_id
            ctx_with_meta["_event"] = event.value
            ctx_with_meta["_timestamp"] = time.time()

            try:
                # 执行回调
                hook_result = entry.callback(ctx_with_meta)

                # 更新统计
                entry.fire_count += 1
                self._total_hooks_triggered += 1

                if not isinstance(hook_result, dict):
                    logger.warning(
                        f"钩子 {entry.name} 返回了非Dict类型: {type(hook_result)}"
                    )
                    continue

                # 合并修改后的上下文
                # 钩子可以通过 modified_context 键传递上下文修改
                if "modified_context" in hook_result:
                    modified = hook_result.pop("modified_context", {})
                    if isinstance(modified, dict):
                        context.update(modified)
                        result.modified_context = context

                # 检查是否被阻止
                if hook_result.get("allow") is False:
                    entry.block_count += 1
                    self._total_blocks += 1
                    result.allowed = False
                    result.blocked_by = entry.name
                    # 将reason添加到warnings
                    reason = hook_result.get("reason", "未指定原因")
                    result.warnings.append(f"[{entry.name}] {reason}")
                    # 保存metadata
                    result.metadata.update(hook_result.get("metadata", {}))
                    break

                # 检查警告 (非致命)
                if hook_result.get("warning"):
                    result.warnings.append(
                        f"[{entry.name}] {hook_result['warning']}"
                    )

                result.hooks_fired.append(hook_id)
                result.metadata.update(hook_result.get("metadata", {}))

            except Exception as e:
                logger.error(
                    f"钩子 {entry.name} (id={hook_id[:8]}) 执行异常: {e}",
                    exc_info=True,
                )
                # 钩子异常不阻止流程 (安全策略: 出错时允许通过)
                continue

        # 将最终context回写到result
        result.modified_context = context

        return result

    # ── 统计 ──────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取钩子系统运行统计"""
        with self._rwlock:
            total_hooks = len(self._hooks)
            enabled_hooks = sum(1 for e in self._hooks.values() if e.enabled)

            by_event = {}
            for evt in HookEvent:
                count = len([
                    hid for hid in self._event_index.get(evt, [])
                    if hid in self._hooks and self._hooks[hid].enabled
                ])
                by_event[evt.value] = count

        return {
            "total_hooks": total_hooks,
            "enabled_hooks": enabled_hooks,
            "total_events_fired": self._total_events_fired,
            "total_hooks_triggered": self._total_hooks_triggered,
            "total_blocks": self._total_blocks,
            "hooks_by_event": by_event,
        }

    def reset_stats(self) -> None:
        """重置运行统计 (测试用)"""
        self._total_events_fired = 0
        self._total_hooks_triggered = 0
        self._total_blocks = 0
        with self._rwlock:
            for entry in self._hooks.values():
                entry.fire_count = 0
                entry.block_count = 0

    # ── 内置安全钩子 ─────────────────────────────────

    def _register_builtin_hooks(self) -> None:
        """
        注册内置安全钩子 — 默认启用的三层防护。

        1. block_destructive_commands: 阻止 rm -rf /, format C:, dd if= 等破坏性命令
        2. prevent_credential_leak: 阻止API密钥、密码等敏感信息输出
        3. rate_limit_guard: 防止高频调用 (同一事件/工具短时间内重复触发)
        """
        # ── 安全钩子1: 阻止破坏性命令 ──
        self.register_hook(
            event=HookEvent.PRE_TOOL_USE,
            callback=_builtin_block_destructive_commands,
            priority=100,  # 最高优先级，最先执行
            name="内置安全钩子: 阻止破坏性命令",
        )

        # ── 安全钩子2: 防止凭证泄露 ──
        self.register_hook(
            event=HookEvent.POST_TOOL_USE,
            callback=_builtin_prevent_credential_leak,
            priority=100,
            name="内置安全钩子: 防止凭证泄露",
        )

        # ── 安全钩子3: 速率限制守卫 ──
        self.register_hook(
            event=HookEvent.PRE_TOOL_USE,
            callback=_builtin_rate_limit_guard,
            priority=90,  # 在破坏性命令检查之后
            name="内置安全钩子: 速率限制守卫",
        )

        logger.info("3个内置安全钩子已注册")


# ═══════════════════════════════════════════════════════════
# 内置安全钩子回调函数
# ═══════════════════════════════════════════════════════════

# 破坏性命令模式列表
_DESTRUCTIVE_PATTERNS: List[re.Pattern] = [
    # Unix/Linux 破坏性命令
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRf]+[a-zA-Z]*\s+)*/", re.IGNORECASE),
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRf]+[a-zA-Z]*\s+)*~", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+\*", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/(usr|etc|var|home|boot|opt|srv|tmp)\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bmkfs\.", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;:", re.IGNORECASE),  # fork bomb
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/", re.IGNORECASE),
    re.compile(r"\bchown\s+(-R\s+)?\S+:\S+\s+/", re.IGNORECASE),
    re.compile(r"\bshutdown\s+(-[a-zA-Z]*\s+)?(now|0)", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bhalt\b", re.IGNORECASE),
    re.compile(r"\bmv\s+/[^ ]+\s+/dev/null", re.IGNORECASE),
    # Windows 破坏性命令
    re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE),
    re.compile(r"\bdel\s+/[fF]\s+/[sS]\s+[A-Za-z]:\\", re.IGNORECASE),
    re.compile(r"\brmdir\s+/[sS]\s+[A-Za-z]:\\", re.IGNORECASE),
    re.compile(r"\bdiskpart\b", re.IGNORECASE),
    re.compile(r"\bsc\s+delete\b", re.IGNORECASE),
    re.compile(r"\breg\s+delete\s+HKLM", re.IGNORECASE),
    # Git 危险操作
    re.compile(r"\bgit\s+push\s+.*--force.*\bmain\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*--force.*\bmaster\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\s+HEAD", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*[f]+[a-zA-Z]*", re.IGNORECASE),
    # 管道注入危险 (curl pipe bash)
    re.compile(r"\b(curl|wget)\s+.*\|\s*(bash|sh|zsh)", re.IGNORECASE),
    re.compile(r"\b(curl|wget)\s+.*\|\s*sudo\s+(bash|sh)", re.IGNORECASE),
    # 数据库危险操作
    re.compile(r"\bDROP\s+(DATABASE|TABLE)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+\w+\s*;?\s*$", re.IGNORECASE),  # 无条件DELETE
]


def _builtin_block_destructive_commands(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    内置安全钩子: 阻止破坏性命令执行。

    检测 rm -rf /, format C:, dd if=, fork bomb, git push --force main,
    curl | bash 等危险操作，并在执行前阻止。

    Args:
        context: 包含 tool_name, command/args 的上下文字典

    Returns:
        {"allow": False, "reason": "..."} 如果检测到破坏性命令
        {"allow": True} 正常通过
    """
    # 获取命令文本 (支持多种字段名)
    command = (
        context.get("command", "")
        or context.get("args", "")
        or context.get("input", "")
    )

    # 合并所有参数为字符串
    if isinstance(command, (list, tuple)):
        command = " ".join(str(c) for c in command)
    elif isinstance(command, dict):
        command = " ".join(f"{k}={v}" for k, v in command.items())

    command = str(command)

    if not command:
        return {"allow": True}

    for pattern in _DESTRUCTIVE_PATTERNS:
        match = pattern.search(command)
        if match:
            matched_text = match.group()
            return {
                "allow": False,
                "reason": (
                    f"检测到潜在的破坏性操作: '{matched_text}'。"
                    "该命令可能对系统造成不可逆的损坏。"
                    "如需执行，请人工确认并暂时禁用此安全钩子。"
                ),
                "metadata": {
                    "matched_pattern": pattern.pattern,
                    "matched_text": matched_text,
                },
            }

    return {"allow": True}


# 凭证泄露检测模式
_CREDENTIAL_PATTERNS: List[re.Pattern] = [
    # API Key 模式
    re.compile(r'(?:api[_-]?key|apikey|api[_-]?secret)["\s:=]+([A-Za-z0-9+/]{20,}={0,2})', re.IGNORECASE),
    re.compile(r'(?:access[_-]?key|access[_-]?token)["\s:=]+([A-Za-z0-9+/]{20,}={0,2})', re.IGNORECASE),
    re.compile(r'(?:secret[_-]?key|secret[_-]?token)["\s:=]+([A-Za-z0-9+/]{20,}={0,2})', re.IGNORECASE),
    # OpenAI / Anthropic API key 格式
    re.compile(r'sk-[A-Za-z0-9]{32,}', re.IGNORECASE),
    re.compile(r'sk-ant-[A-Za-z0-9]{32,}', re.IGNORECASE),
    # AWS Access Key
    re.compile(r'AKIA[0-9A-Z]{16}', re.IGNORECASE),
    # JWT Token
    re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', re.IGNORECASE),
    # Generic bearer token
    re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]{20,}', re.IGNORECASE),
    # Private key header
    re.compile(r'-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)\s+PRIVATE\s+KEY-----', re.IGNORECASE),
    # Password in plaintext
    re.compile(r'(?:password|passwd|pwd)["\s:=]+[\'"][^\'"]{3,}[\'"]', re.IGNORECASE),
    # Connection strings with credentials
    re.compile(r'(?:mongodb|mysql|postgresql|redis)://[^:]+:[^@]+@', re.IGNORECASE),
]


def _builtin_prevent_credential_leak(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    内置安全钩子: 防止凭证泄露到输出。

    检测工具输出中是否包含API密钥、密码、JWT Token等敏感信息，
    如果检测到则向用户发出警告 (不阻止，但标记)。

    Args:
        context: 包含 result/output 的上下文字典

    Returns:
        {"warning": "..."} 如果检测到疑似凭证
        {"allow": True} 正常通过
    """
    output = (
        context.get("result", "")
        or context.get("output", "")
        or context.get("response", "")
    )

    if isinstance(output, (list, tuple)):
        output = " ".join(str(o) for o in output)
    elif isinstance(output, dict):
        # 递归将字典转为字符串检查
        import json
        output = json.dumps(output, default=str)

    output = str(output)

    if not output:
        return {"allow": True}

    detected = []
    for pattern in _CREDENTIAL_PATTERNS:
        matches = pattern.findall(output)
        if matches:
            # 只记录模式名，不记录实际值
            detected.append(pattern.pattern[:60])

    if detected:
        return {
            "allow": True,  # 不阻止，仅警告
            "warning": (
                f"工具输出中检测到 {len(detected)} 处疑似凭证信息。"
                "请确认这些值是否应对外暴露。"
                "如为敏感信息，请使用环境变量或密钥管理服务替代硬编码。"
            ),
            "metadata": {
                "credential_detections": len(detected),
            },
        }

    return {"allow": True}


# 速率限制内部状态
_rate_limit_state: Dict[str, List[float]] = {}
_rate_limit_window: float = 5.0   # 5秒窗口
_rate_limit_max_calls: int = 10   # 窗口内最多10次调用


def _builtin_rate_limit_guard(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    内置安全钩子: 速率限制守卫。

    防止同一事件或工具在短时间内被高频触发，
    避免误操作或脚本失控导致的系统压力。

    Args:
        context: 包含 tool_name, event 的上下文字典

    Returns:
        {"allow": False, "reason": "..."} 如果触发速率限制
        {"allow": True} 正常通过
    """
    tool_name = context.get("tool_name", context.get("_event", "unknown"))
    key = f"rate_limit:{tool_name}"

    now = time.time()

    # 获取或创建时间戳列表
    if key not in _rate_limit_state:
        _rate_limit_state[key] = []

    timestamps = _rate_limit_state[key]

    # 清理过期时间戳
    cutoff = now - _rate_limit_window
    timestamps = [t for t in timestamps if t > cutoff]
    _rate_limit_state[key] = timestamps

    # 检查是否超限
    if len(timestamps) >= _rate_limit_max_calls:
        oldest = min(timestamps)
        wait_time = _rate_limit_window - (now - oldest)
        return {
            "allow": False,
            "reason": (
                f"速率限制触发: '{tool_name}' 在 {_rate_limit_window:.0f}秒内"
                f"被调用了 {len(timestamps)} 次 (上限{_rate_limit_max_calls}次)。"
                f"请在 {wait_time:.1f} 秒后重试。"
            ),
            "metadata": {
                "current_rate": len(timestamps),
                "max_rate": _rate_limit_max_calls,
                "window_s": _rate_limit_window,
                "wait_s": round(wait_time, 1),
            },
        }

    # 记录本次调用
    timestamps.append(now)
    _rate_limit_state[key] = timestamps

    return {"allow": True}


# ═══════════════════════════════════════════════════════════
# 便捷函数 — 重置 (测试用)
# ═══════════════════════════════════════════════════════════

def _reset_rate_limit_state() -> None:
    """重置速率限制内部状态 (测试用)"""
    global _rate_limit_state
    _rate_limit_state.clear()


# ═══════════════════════════════════════════════════════════
# 单例获取函数
# ═══════════════════════════════════════════════════════════

_global_hook_system: Optional[HookSystem] = None


def get_hook_system() -> HookSystem:
    """
    获取全局唯一的HookSystem单例。

    首次调用时自动初始化并注册内置安全钩子。
    线程安全。

    Returns:
        HookSystem 全局单例
    """
    global _global_hook_system
    if _global_hook_system is None:
        # 重置单例状态 (如果直接实例化过)
        HookSystem._instance = None
        _global_hook_system = HookSystem()
    return _global_hook_system


def reset_hook_system() -> None:
    """
    重置全局HookSystem (测试用)。

    清除所有注册的钩子和统计信息，
    下次调用 get_hook_system() 时会重新初始化。
    """
    global _global_hook_system
    _global_hook_system = None
    HookSystem._instance = None
    _reset_rate_limit_state()
    logger.info("P0-6 HookSystem 已全局重置")

# ── v2.42 向后兼容别名 ──
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class HookRule:
    event: HookEvent; matcher: str = ""; action: str = ""
    action_type: str = "shell"; priority: int = 50; cooldown_s: int = 0
    index: int = -1; last_triggered: float = 0.0

@dataclass
class HookContext:
    event: HookEvent; tool_name: str = ""; tool_input: Any = None
    user_message: str = ""; session_id: str = ""

class HooksEngine:
    """v2.42兼容包装器"""
    def __init__(self, config_path: Optional[str] = None):
        self._hs = HookSystem()
        self.rules: List[HookRule] = []
        self._next_idx = 0
        self._config_path = config_path
        self._load()
    
    def add_rule(self, event: HookEvent, matcher: str, action: str,
                 action_type: str = "shell", priority: int = 50, cooldown_s: int = 0) -> HookRule:
        r = HookRule(event=event, matcher=matcher, action=action,
                     action_type=action_type, priority=priority, cooldown_s=cooldown_s,
                     index=self._next_idx)
        self._next_idx += 1
        self.rules.append(r)
        return r
    
    def remove_rule(self, idx: int) -> bool:
        for i, r in enumerate(self.rules):
            if r.index == idx:
                self.rules.pop(i)
                return True
        return False
    
    def fire(self, event: HookEvent, ctx: HookContext) -> Dict:
        import fnmatch, time as _time
        fired = 0; blocked = 0
        for r in self.rules:
            if r.event != event: continue
            if r.cooldown_s > 0 and _time.time() - r.last_triggered < r.cooldown_s: continue
            tool = getattr(ctx, 'tool_name', '')
            if fnmatch.fnmatch(tool, r.matcher) or r.matcher == "" or r.matcher == "*" or r.matcher in tool:
                r.last_triggered = _time.time()
                fired += 1
                if r.action_type == "command" and r.priority >= 100:
                    blocked += 1
        return {"fired": fired, "blocked": blocked}
    
    def enable_security_defaults(self):
        for matcher, action in [("Bash(*rm *)", "exit 2"), ("Bash(*sudo *)", "exit 2"),
                                 ("Write(*.env*)", "echo blocked"), ("Bash(*curl*|*sh)", "exit 2")]:
            self.add_rule(HookEvent.PRE_TOOL, matcher, action, "command", 100)
    
    def _save(self):
        if self._config_path:
            import json
            try:
                with open(self._config_path, 'w') as f:
                    json.dump([{"event": r.event.value, "matcher": r.matcher, "action": r.action,
                               "action_type": r.action_type, "priority": r.priority,
                               "cooldown_s": r.cooldown_s} for r in self.rules], f)
            except: pass
    
    def _load(self):
        if self._config_path:
            import json, os
            try:
                if os.path.exists(self._config_path):
                    with open(self._config_path) as f:
                        data = json.load(f)
                    for d in data:
                        event = HookEvent(d["event"])
                        self.add_rule(event, d["matcher"], d["action"],
                                     d.get("action_type","shell"), d.get("priority",50),
                                     d.get("cooldown_s",0))
            except: pass
    
    def get_stats(self) -> Dict:
        return {"total_rules": len(self.rules),
                "rules_by_event": {e.value: sum(1 for r in self.rules if r.event == e) for e in HookEvent}}
    
    def list_rules(self) -> List[Dict]:
        return [{"index": r.index, "event": r.event.value, "matcher": r.matcher,
                 "action": r.action, "type": r.action_type} for r in self.rules]

get_hooks = get_hook_system
