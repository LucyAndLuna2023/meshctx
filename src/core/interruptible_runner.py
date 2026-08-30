#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interruptible Runner — 任务执行中可继续输入 + 打断置顶新消息 (三平台 Win/Linux/Mac)

对标 Hermes / Codex / DeepSeek Harness 的交互模型：
- 任务（agent_loop）正在执行时，用户仍可继续输入新消息（不丢、排队）；
- 新消息可打断当前任务并置顶（最高优先级立即执行）；
- 同一套机制供 CLI（threading + queue）与 Web（asyncio 会话级）共用。

设计：
- `InterruptibleRunner`：一个线程安全的"任务队列 + 打断通道"容器。
    - `submit(messages)`：置顶提交（打断语义：中断当前任务，新消息优先执行）。
    - `enqueue(messages)`：排队提交（不打断，当前任务完成后按序处理）。
    - `interrupt_check()`：任务循环内每轮/每工具前调用；检测到打断请求则抛
      `InterruptSignal(new_messages)`，由外层捕获后以新消息置顶重跑。
    - `next_task_blocking()`：阻塞取下一个任务（置顶优先，其次队列）。
- `InterruptSignal`：携带打断消息的异常，用于把"用户新输入"作为最高优先级注入。
- CLI 用法（cmd_chat）：
    runner = InterruptibleRunner()
    reader = StdinReader(runner, mode=...)   # 后台线程持续读 stdin
    reader.start()
    while True:
        msgs = runner.next_task_blocking()    # 阻塞等用户输入
        if msgs is None: break                # EOF
        if not msgs: continue                 # Ctrl+C 停止信号
        try:
            _chat_loop(..., interrupt_check=runner.interrupt_check)
        except InterruptSignal as sig:
            runner.apply_interrupt(sig.messages)   # 新消息置顶，下轮取到并执行
- Web 用法（/api/chat/stream）：每个 conversation_id 一个 runner；新请求带
  `interrupt: true` 时先取消正在跑的生成任务，再以新消息置顶执行。
"""
import collections
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional


class InterruptSignal(Exception):
    """任务循环内被新用户消息打断。携带要置顶执行的消息列表。"""

    def __init__(self, messages: List[Dict], meta: Optional[Dict] = None):
        super().__init__("interrupted by new user message")
        self.messages = messages
        self.meta = meta or {}


class InterruptibleRunner:
    """一个会话（CLI 会话 或 conversation_id）的任务执行器。

    线程安全：CLI 的后台 stdin 线程调用 submit/enqueue；任务主协程调用
    interrupt_check / next_task_blocking。Web 场景下全部在 asyncio 事件循环内使用。
    """

    def __init__(self, interrupt_check_interval: float = 0.25):
        self.interrupt_check_interval = interrupt_check_interval
        self._cv = threading.Condition()
        self._tasks: "collections.deque[List[Dict]]" = collections.deque()
        self._pending_top: List[Dict] = []      # 打断通道：待抛出的新消息
        self._interrupt_requested = False
        self._busy = False
        self._last_check = 0.0
        self._stats = {"interrupts": 0, "queued": 0, "runs": 0}
        self._eof = False

    # ── 状态 ──
    @property
    def busy(self) -> bool:
        with self._cv:
            return self._busy

    def status(self) -> Dict:
        with self._cv:
            return {
                "busy": self._busy,
                "pending_top": bool(self._pending_top),
                "queued": len(self._tasks),
                "interrupts": self._stats["interrupts"],
                "queued_total": self._stats["queued"],
                "runs": self._stats["runs"],
                "eof": self._eof,
            }

    # ── 提交 ──
    def submit(self, messages: List[Dict]) -> None:
        """置顶提交：打断当前任务，新消息成为最高优先级（打断语义）。"""
        with self._cv:
            self._pending_top = list(messages)
            self._interrupt_requested = True
            self._stats["interrupts"] += 1
            self._cv.notify_all()

    def enqueue(self, messages: List[Dict]) -> None:
        """排队提交：不打断当前任务，完成后按序执行（不丢消息）。"""
        with self._cv:
            self._tasks.append(list(messages))
            self._stats["queued"] += 1
            self._cv.notify_all()

    def set_eof(self) -> None:
        """stdin EOF/退出信号：唤醒阻塞的 next_task_blocking 返回 None。"""
        with self._cv:
            self._eof = True
            self._cv.notify_all()

    # ── 任务循环内调用 ──
    def interrupt_check(self) -> None:
        """在 agent_loop 每轮/每工具前调用。有打断请求则抛 InterruptSignal。

        - 置顶新消息: InterruptSignal(messages) 非空, 外层捕获后 apply_interrupt 重跑;
        - 停止信号 (/stop / Ctrl+C): submit([]) → InterruptSignal([]) 空消息,
          外层捕获后 if not _msgs: continue 停止当前任务继续等待输入。
        轮询节流：interrupt_check_interval 秒内重复调用直接返回（避免高频轮询开销）。
        """
        now = time.monotonic()
        if now - self._last_check < self.interrupt_check_interval:
            return
        self._last_check = now
        with self._cv:
            if self._interrupt_requested:
                msgs = list(self._pending_top)
                self._pending_top = []
                self._interrupt_requested = False
                raise InterruptSignal(msgs)

    def apply_interrupt(self, messages: List[Dict]) -> None:
        """捕获 InterruptSignal 后，把打断消息置顶为当前任务（下轮执行）。"""
        with self._cv:
            self._tasks.appendleft(list(messages))
            self._cv.notify_all()

    # ── 取任务 ──
    def next_task_blocking(self) -> Optional[List[Dict]]:
        """阻塞取下一个要执行的任务（置顶优先）。EOF 返回 None；停止信号返回 []。"""
        with self._cv:
            while True:
                if self._tasks:
                    return self._tasks.popleft()
                if self._eof:
                    return None
                self._cv.wait()

    def next_task_nowait(self) -> Optional[List[Dict]]:
        """非阻塞取下一个任务；无任务返回 None。"""
        with self._cv:
            if self._tasks:
                return self._tasks.popleft()
            return None

    # ── 执行 ──
    def run_loop(self, run_coro: Callable[[], Awaitable[Any]]) -> Any:
        """同步包装：跑一个异步任务；期间维护 busy 状态。"""
        with self._cv:
            self._busy = True
            self._stats["runs"] += 1
        try:
            import asyncio
            try:
                asyncio.get_running_loop()
                # 已在事件循环内（Web）：由调用方 await
                raise RuntimeError("run_loop is for sync contexts; use async await in Web")
            except RuntimeError:
                pass
            return asyncio.run(run_coro())
        finally:
            with self._cv:
                self._busy = False


# ── CLI stdin 后台读取线程 ──
class ConversationInterruptManager:
    """Web 会话级打断管理 (2026-08-29): "最新请求优先"语义。

    每个流式请求注册一个 request_id; 新请求到来 → 旧请求的 should_interrupt()
    变 True → 旧流在下一轮 interrupt_check 抛 InterruptSignal 优雅结束。
    新请求自身 should_interrupt() = False, 正常执行 (不自打断)。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current = None

    def register(self, request_id: str) -> str:
        """注册新请求, 返回被取代的旧 request_id (若无返回 None)。"""
        with self._lock:
            old = self._current
            self._current = request_id
            return old

    def should_interrupt(self, request_id: str) -> bool:
        """该请求是否已被更新的请求取代 (应打断)。"""
        with self._lock:
            return self._current is not None and self._current != request_id

    def unregister(self, request_id: str) -> None:
        with self._lock:
            if self._current == request_id:
                self._current = None


class StdinReader(threading.Thread):
    """后台线程持续读 stdin，把用户输入提交给 runner。

    - 单行输入即提交（与简单 REPL 一致）；EOF/Ctrl+D → set_eof。
    - `mode="interrupt"`（默认）：新消息打断置顶。
    - `mode="queue"`：新消息排队（当前任务不中断）。
    - Ctrl+C（KeyboardInterrupt）→ submit([])（停止/打断当前任务）。
    - 支持多行粘贴（空行提交，与原有 REPL 一致）。
    """

    def __init__(self, runner: InterruptibleRunner,
                 mode: str = "interrupt",
                 prompt: str = "You> ",
                 stop_marker: str = "/stop"):
        super().__init__(daemon=True, name="meshctx-stdin-reader")
        self.runner = runner
        self.mode = mode
        self.prompt = prompt
        self.stop_marker = stop_marker
        self._alive = True

    def run(self):
        while self._alive:
            try:
                print(f"\n[{self.prompt}] ", end="", flush=True)
                # 多行输入：空行提交（与 REPL 一致）
                lines = []
                first = True
                while True:
                    p = f"\n[{self.prompt}] " if first else "... "
                    first = False
                    try:
                        line = input(p)
                    except EOFError:
                        self.runner.set_eof()
                        self._alive = False
                        return
                    except KeyboardInterrupt:
                        self.runner.submit([])   # Ctrl+C：停止当前任务
                        lines = []
                        break
                    if line == "":
                        break
                    lines.append(line)
                user = "\n".join(lines).strip()
                if not user:
                    continue
                if user == self.stop_marker:
                    self.runner.submit([])       # /stop：停止当前任务
                    continue
                msgs = [{"role": "user", "content": user}]
                if self.mode == "queue":
                    self.runner.enqueue(msgs)
                else:
                    self.runner.submit(msgs)
            except Exception:
                self.runner.set_eof()
                self._alive = False
                return

    def stop(self):
        self._alive = False
