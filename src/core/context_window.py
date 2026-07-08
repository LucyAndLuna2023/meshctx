"""
meshctx ContextWindow — sliding window context manager.

Sliding window message management with token counting and truncation
strategies: keep_first (preserve system prompt), keep_last (recency),
smart (hybrid: keep first N + last M, trim middle).

Token counting: chars/4 heuristic, injectable via set_token_counter().
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional


class TruncationStrategy(Enum):
    KEEP_FIRST = "keep_first"
    KEEP_LAST = "keep_last"
    SMART = "smart"


@dataclass
class Message:
    role: str
    content: str
    tokens: int = 0

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = max(1, len(self.content) // 4)


class ContextWindow:
    """Sliding-window context manager with token-aware truncation.

    cw = ContextWindow(max_tokens=4096, strategy=TruncationStrategy.SMART)
    cw.add("system", "You are a helpful assistant.")
    cw.add("user", "Hello!")
    print(cw.token_count)
    """

    def __init__(self, max_tokens: int = 8192,
                 strategy: TruncationStrategy = TruncationStrategy.SMART,
                 keep_first: int = 2, keep_last: int = 10):
        self.max_tokens = max_tokens
        self.strategy = strategy
        self.keep_first = keep_first
        self.keep_last = keep_last
        self._messages: List[Message] = []
        self._lock = threading.Lock()
        self._token_counter: Optional[Callable[[str], int]] = None

    @property
    def token_count(self) -> int:
        return sum(m.tokens for m in self._messages)

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def set_token_counter(self, counter: Callable[[str], int]) -> None:
        self._token_counter = counter

    def _count_tokens(self, text: str) -> int:
        if self._token_counter:
            return self._token_counter(text)
        return max(1, len(text) // 4)

    def add(self, role: str, content: str) -> Message:
        """Add a message; triggers truncation if over token budget."""
        tokens = self._count_tokens(content)
        msg = Message(role=role, content=content, tokens=tokens)
        with self._lock:
            self._messages.append(msg)
            self._truncate()
        return msg

    def get_messages(self) -> List[Message]:
        with self._lock:
            return list(self._messages)

    def get_dicts(self) -> List[dict]:
        with self._lock:
            return [{"role": m.role, "content": m.content} for m in self._messages]

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def __len__(self) -> int:
        return self.message_count

    def trim(self) -> int:
        """Manually trim to fit within max_tokens. Returns dropped count."""
        with self._lock:
            before = len(self._messages)
            self._truncate()
            return before - len(self._messages)

    # ── truncation ──────────────────────────────────────────

    def _truncate(self) -> None:
        while self.token_count > self.max_tokens and len(self._messages) > 1:
            if self.strategy == TruncationStrategy.KEEP_FIRST:
                self._messages.pop()
            elif self.strategy == TruncationStrategy.KEEP_LAST:
                self._messages.pop(0)
            else:  # SMART
                self._smart_truncate()
                return

    def _smart_truncate(self) -> None:
        n, m = self.keep_first, self.keep_last
        if len(self._messages) <= n + m:
            while self.token_count > self.max_tokens and len(self._messages) > 1:
                self._messages.pop(0)
            return

        head = self._messages[:n]
        tail = self._messages[-m:]
        middle = self._messages[n:-m]

        budget = self.max_tokens - sum(x.tokens for x in head) - sum(x.tokens for x in tail)
        kept: List[Message] = []
        used = 0
        for msg in reversed(middle):
            if used + msg.tokens <= budget:
                kept.insert(0, msg)
                used += msg.tokens
            else:
                break
        self._messages = head + kept + tail
