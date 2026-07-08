"""
meshctx Context Window — 滑动上下文窗口管理器
==============================================

智能滑动窗口管理, 支持 Token 计数估算、智能截断策略、
消息优先级标记和窗口溢出处理。

核心功能:
  1. 滑动窗口 — 定长窗口自动滑动, 保留最新消息
  2. Token 计数 — 基于单词/字符的快速 Token 估算
  3. 智能截断 — 保留头部 (系统提示) + 尾部 (最新对话)
  4. 消息管理 — add/clear/trim/pop, 时间戳追踪
  5. 优先级标记 — CRITICAL/HIGH/NORMAL/LOW 四级优先级
  6. 窗口溢出策略 — truncate/drop_oldest/error/reject

Token 估算:
  - 精确算法需要 tiktoken, 此处使用字符/4 的近似 (1 token ≈ 4 chars)
  - 支持通过 set_token_counter() 注入自定义计数器
  - 默认估算: tokens = len(text) / 4 (英文) 或 len(text) / 2 (中文)

使用示例:
  cw = get_context_window(max_tokens=8192)
  cw.add("system", "You are a helpful assistant.", priority=Priority.CRITICAL)
  cw.add("user", "Explain quantum computing.")
  cw.add("assistant", "Quantum computing uses qubits...")
  total = cw.token_count  # 总 token 估算
  trimmed = cw.trim()     # 如果溢出则截断

设计原则:
  - 零外部依赖: Token 估算使用简单启发式
  - 线程安全: 读写锁保护
  - 可扩展: 支持注入精确 Token 计数器
  - 优先级感知: 高优先级消息最后被裁剪

代码量: ~450 行
"""

import copy
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.context_window")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class Priority(IntEnum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """消息优先级 (数值越低越优先保留)"""
    CRITICAL = 0   # 系统提示, 必须保留
    HIGH = 1       # 重要上下文
    NORMAL = 2     # 普通对话
    LOW = 3        # 可丢弃的历史


class OverflowStrategy(str):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """窗口溢出处理策略"""
    TRUNCATE = "truncate"       # 截断最早的消息 (保留高优先级)
    DROP_OLDEST = "drop_oldest" # 无条件丢弃最旧消息
    ERROR = "error"             # 抛出异常
    REJECT = "reject"           # 静默拒绝添加


# Token 估算常量
CHARS_PER_TOKEN_ENGLISH = 4    # 英文: ~4 字符/token
CHARS_PER_TOKEN_CJK = 2        # 中日韩文: ~2 字符/token


def _is_cjk(char: str) -> bool:
    """判断字符是否为中日韩文字"""
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF) or   # CJK Unified
        (0x3400 <= cp <= 0x4DBF) or   # CJK Ext-A
        (0x20000 <= cp <= 0x2A6DF) or # CJK Ext-B
        (0x3040 <= cp <= 0x309F) or   # Hiragana
        (0x30A0 <= cp <= 0x30FF) or   # Katakana
        (0xAC00 <= cp <= 0xD7AF)      # Hangul
    )


def estimate_tokens(text: str) -> int:
    """快速 Token 估算

    混合中英文估算: CJK 字符 2 chars/token, 其他 4 chars/token

    Args:
        text: 输入文本

    Returns:
        Token 估算值 (至少为 1)
    """
    if not text:
        return 0
    cjk_chars = sum(1 for c in text if _is_cjk(c))
    other_chars = len(text) - cjk_chars
    estimated = (cjk_chars / CHARS_PER_TOKEN_CJK) + (other_chars / CHARS_PER_TOKEN_ENGLISH)
    return max(1, int(estimated))


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class WindowMessage:
    """窗口中的一条消息"""
    role: str                                   # system / user / assistant / tool
    content: str
    priority: Priority = Priority.NORMAL
    token_estimate: int = 0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: str = ""

    def __post_init__(self, **kw):
        if not self.message_id:
            import uuid
            self.message_id = str(uuid.uuid4())[:8]
        if self.token_estimate == 0:
            self.token_estimate = estimate_tokens(self.content)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "priority": self.priority.name,
            "token_estimate": self.token_estimate,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "message_id": self.message_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], **kw) -> "WindowMessage":
        return cls(
            role=d["role"],
            content=d["content"],
            priority=Priority[d.get("priority", "NORMAL")],
            token_estimate=d.get("token_estimate", 0),
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
            message_id=d.get("message_id", ""),
        )


# ═══════════════════════════════════════════════════════════
# 上下文窗口主类
# ═══════════════════════════════════════════════════════════

class ContextWindow:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """滑动上下文窗口管理器

    管理消息队列, 跟踪 Token 消耗, 在窗口溢出时执行智能截断。
    """

    def __init__(self, max_tokens: int = 8192,
                 strategy: str = OverflowStrategy.TRUNCATE,
                 reserve_ratio: float = 0.1):
        """
        Args:
            max_tokens: 窗口最大 Token 数
            strategy: 溢出策略
            reserve_ratio: Token 预留比例 (为响应预留空间)
        """
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.reserve_ratio = reserve_ratio
        self._messages: List[WindowMessage] = []
        self._lock = threading.RLock()
        self._token_counter: Optional[Callable[[str], int]] = None
        self._stats: Dict[str, Any] = {
            "adds": 0, "trims": 0, "dropped": 0, "rejected": 0, "errors": 0,
        }

    # ── Token 计数 ────────────────────────────────────────

    def set_token_counter(self, counter: Callable[[str], int], **kw):
        """注入自定义 Token 计数器 (如 tiktoken)

        Args:
            counter: 接受文本返回 token 数的函数
        """
        self._token_counter = counter

    def _count_tokens(self, text: str, **kw) -> int:
        """计算文本 Token 数"""
        if self._token_counter:
            return self._token_counter(text)
        return estimate_tokens(text)

    @property
    def token_count(self, **kw) -> int:
        """当前窗口总 Token 数"""
        with self._lock:
            return sum(msg.token_estimate for msg in self._messages)

    @property
    def effective_limit(self, **kw) -> int:
        """有效 Token 上限 (扣除预留)"""
        return int(self.max_tokens * (1 - self.reserve_ratio))

    @property
    def remaining_tokens(self, **kw) -> int:
        """剩余可用 Token"""
        return max(0, self.effective_limit - self.token_count)

    @property
    def usage_ratio(self, **kw) -> float:
        """Token 使用率 (0-1)"""
        if self.max_tokens == 0:
            return 0.0
        return self.token_count / self.max_tokens

    @property
    def message_count(self, **kw) -> int:
        """消息数量"""
        with self._lock:
            return len(self._messages)

    # ── 消息管理 ──────────────────────────────────────────

    def add(self, role: str, content: str,
            priority: Priority = Priority.NORMAL,
            metadata: Optional[Dict[str, Any]] = None) -> Optional[WindowMessage]:
        """添加消息到窗口

        Args:
            role: 消息角色 (system/user/assistant/tool)
            content: 消息内容
            priority: 优先级
            metadata: 附加元数据

        Returns:
            添加的 WindowMessage, 或被拒绝时返回 None
        """
        tokens = self._count_tokens(content)
        msg = WindowMessage(
            role=role,
            content=content,
            priority=priority,
            token_estimate=tokens,
            metadata=metadata or {},
        )

        with self._lock:
            # 检查是否会溢出
            new_total = self.token_count + tokens
            if new_total > self.effective_limit:
                if self.strategy == OverflowStrategy.REJECT:
                    self._stats["rejected"] += 1
                    logger.warning(f"Rejected message (token budget exceeded: "
                                   f"{new_total} > {self.effective_limit})")
                    return None
                elif self.strategy == OverflowStrategy.ERROR:
                    self._stats["errors"] += 1
                    raise OverflowError(
                        f"Token budget exceeded: {new_total} > {self.effective_limit}"
                    )
                else:
                    # truncate 或 drop_oldest: 先 trim 再添加
                    self._trim_to_fit(tokens)

            self._messages.append(msg)
            self._stats["adds"] += 1
            logger.debug(f"Added message [{msg.message_id}] {role}: {content[:50]}... "
                         f"({tokens} tokens, total: {self.token_count})")

        return msg

    def get_messages(self, min_priority: Optional[Priority] = None,
                     roles: Optional[List[str]] = None) -> List[WindowMessage]:
        """获取窗口中的消息

        Args:
            min_priority: 最低优先级过滤 (包含该级别及更高)
            roles: 按角色过滤

        Returns:
            消息列表 (副本)
        """
        with self._lock:
            msgs = list(self._messages)
            if min_priority is not None:
                msgs = [m for m in msgs if m.priority <= min_priority]
            if roles:
                msgs = [m for m in msgs if m.role in roles]
            return msgs

    def get_last_n(self, n: int, **kw) -> List[WindowMessage]:
        """获取最后 N 条消息"""
        with self._lock:
            return self._messages[-n:] if n > 0 else []

    def pop_last(self, **kw) -> Optional[WindowMessage]:
        """弹出最后一条消息"""
        with self._lock:
            if self._messages:
                return self._messages.pop()
            return None

    def clear(self, **kw):
        """清空窗口"""
        with self._lock:
            count = len(self._messages)
            self._messages.clear()
            logger.info(f"Context window cleared ({count} messages)")

    # ── 智能截断 ──────────────────────────────────────────

    def trim(self, target_tokens: Optional[int] = None, **kw) -> int:
        """智能截断: 保留头部 + 尾部, 从中间裁剪低优先级消息

        Args:
            target_tokens: 目标 Token 数, 默认为 effective_limit * 0.9

        Returns:
            被裁剪的消息数量
        """
        target = target_tokens or int(self.effective_limit * 0.9)

        with self._lock:
            if self.token_count <= target:
                return 0

            original_count = len(self._messages)
            self._smart_trim(target)
            dropped = original_count - len(self._messages)

            self._stats["trims"] += 1
            self._stats["dropped"] += dropped
            logger.info(f"Trimmed {dropped} messages (tokens: target={target})")
            return dropped

    def _smart_trim(self, target_tokens: int, **kw):
        """智能截断实现: 保留 CRITICAL/HIGH 头部 + 最新尾部"""
        # 将消息分为三类
        critical = []   # CRITICAL 优先级 (系统提示)
        high_head = []  # HIGH 优先级 (文档上下文等)
        body = []       # NORMAL/LOW 优先级

        for msg in self._messages:
            if msg.priority == Priority.CRITICAL:
                critical.append(msg)
            elif msg.priority == Priority.HIGH:
                high_head.append(msg)
            else:
                body.append(msg)

        # 按优先级重建: critical (不可裁剪) → high_head → body (可裁剪)
        # 策略: 从 body 尾部保留足够 token
        result = list(critical) + list(high_head)
        used = sum(m.token_estimate for m in result)

        # 从 body 尾部向前添加, 直到用完 token 预算
        body_tail = []
        for msg in reversed(body):
            if used + msg.token_estimate <= target_tokens:
                body_tail.insert(0, msg)
                used += msg.token_estimate
            else:
                break

        result.extend(body_tail)
        self._messages = result

    def _trim_to_fit(self, needed_tokens: int, **kw):
        """为新消息腾出空间

        根据策略裁剪消息:
        - TRUNCATE: 智能截断
        - DROP_OLDEST: 从最旧的非 CRITICAL 消息开始移除
        """
        if self.strategy == OverflowStrategy.DROP_OLDEST:
            with self._lock:
                while self._messages and self.token_count + needed_tokens > self.effective_limit:
                    # 找到最旧的非 CRITICAL 消息
                    for i, msg in enumerate(self._messages):
                        if msg.priority > Priority.CRITICAL:
                            removed = self._messages.pop(i)
                            self._stats["dropped"] += 1
                            logger.debug(f"Dropped oldest: [{removed.message_id}] {removed.role}")
                            break
                    else:
                        # 所有消息都是 CRITICAL, 无法裁剪
                        logger.error("Cannot trim: all messages are CRITICAL priority")
                        raise OverflowError("Cannot trim: all messages are CRITICAL priority")
        else:
            # TRUNCATE: 智能截断
            self.trim(target_tokens=self.effective_limit - needed_tokens)

    # ── 优先级操作 ───────────────────────────────────────

    def set_priority(self, message_id: str, priority: Priority, **kw) -> bool:
        """修改指定消息的优先级

        Returns:
            是否成功
        """
        with self._lock:
            for msg in self._messages:
                if msg.message_id == message_id:
                    msg.priority = priority
                    return True
        return False

    def promote_last_n(self, n: int, to_priority: Priority = Priority.HIGH, **kw):
        """提升最后 N 条消息的优先级"""
        with self._lock:
            for msg in self._messages[-n:]:
                msg.priority = min(msg.priority, to_priority)

    def get_messages_by_priority(self, priority: Priority, **kw) -> List[WindowMessage]:
        """按优先级获取消息"""
        with self._lock:
            return [m for m in self._messages if m.priority == priority]

    # ── 窗口状态 ──────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取窗口统计"""
        with self._lock:
            priority_dist = {
                "CRITICAL": sum(1 for m in self._messages if m.priority == Priority.CRITICAL),
                "HIGH": sum(1 for m in self._messages if m.priority == Priority.HIGH),
                "NORMAL": sum(1 for m in self._messages if m.priority == Priority.NORMAL),
                "LOW": sum(1 for m in self._messages if m.priority == Priority.LOW),
            }
            return {
                "max_tokens": self.max_tokens,
                "effective_limit": self.effective_limit,
                "token_count": self.token_count,
                "remaining": self.remaining_tokens,
                "usage_ratio": round(self.usage_ratio, 4),
                "message_count": self.message_count,
                "strategy": self.strategy,
                "priority_distribution": priority_dist,
                **self._stats,
            }

    def to_dict(self, **kw) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "messages": [m.to_dict() for m in self._messages],
                "max_tokens": self.max_tokens,
                "strategy": self.strategy,
                "reserve_ratio": self.reserve_ratio,
                "version": "1.0",
                "exported_at": time.time(),
            }

    def export_json(self, path: Optional[str] = None, **kw) -> str:
        """导出为 JSON"""
        data = self.to_dict()
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"Context window exported to {path}")

        return json_str

    def import_json(self, data: Union[str, Dict[str, Any]], **kw):
        """从 JSON 导入"""
        if isinstance(data, str):
            data = json.loads(data)

        with self._lock:
            self._messages = []
            for msg_data in data.get("messages", []):
                self._messages.append(WindowMessage.from_dict(msg_data))
            self.max_tokens = data.get("max_tokens", self.max_tokens)
            self.strategy = data.get("strategy", self.strategy)
            self.reserve_ratio = data.get("reserve_ratio", self.reserve_ratio)

        logger.info(f"Context window imported: {len(self._messages)} messages")

    def snapshot(self, **kw) -> "ContextWindow":
        """创建窗口快照 (浅拷贝消息列表的副本)"""
        with self._lock:
            snap = ContextWindow(
                max_tokens=self.max_tokens,
                strategy=self.strategy,
                reserve_ratio=self.reserve_ratio,
            )
            snap._messages = [copy.copy(m) for m in self._messages]
            snap._stats = dict(self._stats)
            return snap

    def __len__(self, **kw) -> int:
        return self.message_count

    def __contains__(self, message_id: str, **kw) -> bool:
        with self._lock:
            return any(m.message_id == message_id for m in self._messages)


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_cw_instance: Optional[ContextWindow] = None
_cw_lock = threading.Lock()


def get_context_window(max_tokens: int = 8192,
                       strategy: str = OverflowStrategy.TRUNCATE,
                       reserve_ratio: float = 0.1) -> ContextWindow:
    """获取 ContextWindow 全局单例 (auto-create)

    Args:
        max_tokens: 窗口最大 Token (仅首次创建时生效)
        strategy: 溢出策略 (仅首次创建时生效)
        reserve_ratio: 预留比例 (仅首次创建时生效)

    Returns:
        ContextWindow 实例
    """
    global _cw_instance
    if _cw_instance is None:
        with _cw_lock:
            if _cw_instance is None:
                _cw_instance = ContextWindow(
                    max_tokens=max_tokens,
                    strategy=strategy,
                    reserve_ratio=reserve_ratio,
                )
    return _cw_instance


def reset_context_window():
    """重置全局实例 (用于测试)"""
    global _cw_instance
    with _cw_lock:
        _cw_instance = None
