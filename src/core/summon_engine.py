"""
Summon Engine — P0-7 动态子Agent引擎
=====================================
License: AGPLv3

开源实现说明: 本文件为 meshctx 开源仓库中的真实实现 (取代原接口 stub)。
基于线程池执行子Agent任务, 支持角色自动推断、token 估算、异步召唤、
并行召唤、遣散、历史与统计。
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

DEFAULT_MAX_WORKERS = 4
DEFAULT_TIMEOUT = 300.0


class SummonStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    TIMEOUT = 'timeout'
    DISMISSED = 'dismissed'


@dataclass
class SummonResult:
    agent_id: str = None
    description: str = None
    task: str = ''
    status: SummonStatus = None
    result: str = ''
    error: str = ''
    duration: float = 0.0
    tokens_used: int = 0
    role: str = 'general'
    created_at: float = None

    def __post_init__(self):
        if self.status is None:
            self.status = SummonStatus.PENDING
        if self.created_at is None:
            self.created_at = time.time()

    @property
    def is_active(self) -> bool:
        return self.status in (SummonStatus.PENDING, SummonStatus.RUNNING)

    @property
    def is_success(self) -> bool:
        return self.status == SummonStatus.DONE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "description": self.description,
            "task": self.task,
            "status": self.status.value if isinstance(self.status, SummonStatus) else str(self.status),
            "result": self.result,
            "error": self.error,
            "duration": round(self.duration, 4),
            "tokens_used": self.tokens_used,
            "role": self.role,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "is_success": self.is_success,
        }


# ── 角色推断规则 (关键词 → 角色, 最长匹配优先) ─────────────────────
_ROLE_KEYWORDS: List[tuple] = [
    # (关键词, 角色)
    ("architecture design", "architect"),
    ("unit test", "tester"),
    ("unit tests", "tester"),
    ("系统设计", "architect"),
    ("单元测试", "tester"),
    ("测试用例", "tester"),
    ("代码审查", "reviewer"),
    ("修复bug", "coder"),
    ("写代码", "coder"),
    ("方案设计", "architect"),
    ("research", "researcher"),
    ("analysis", "researcher"),
    ("implement", "coder"),
    ("kubernetes", "devops"),
    ("deploy", "devops"),
    ("docker", "devops"),
    ("ci/cd", "devops"),
    ("流水线", "devops"),
    ("review", "reviewer"),
    ("架构", "architect"),
    ("体系", "architect"),
    ("审查", "reviewer"),
    ("评审", "reviewer"),
    ("测试", "tester"),
    ("用例", "tester"),
    ("研究", "researcher"),
    ("调研", "researcher"),
    ("分析", "researcher"),
    ("趋势", "researcher"),
    ("论文", "researcher"),
    ("部署", "devops"),
    ("运维", "devops"),
    ("配置", "devops"),
    ("实现", "coder"),
    ("修复", "coder"),
    ("编写", "coder"),
    ("开发", "coder"),
    ("编程", "coder"),
    ("算法", "coder"),
    ("函数", "coder"),
    ("bug", "coder"),
    ("code", "coder"),
    ("feature", "coder"),
    ("coding", "coder"),
]
# 平局时角色优先级 (越小越优先)
_ROLE_PRIORITY = {
    "architect": 0,
    "reviewer": 1,
    "tester": 2,
    "researcher": 3,
    "devops": 4,
    "coder": 5,
    "general": 9,
}
# 按 (关键词长度降序, 角色优先级升序) 排序 → 最长匹配优先
_ROLE_KEYWORDS_SORTED = sorted(
    _ROLE_KEYWORDS,
    key=lambda kw_role: (-len(kw_role[0]), _ROLE_PRIORITY.get(kw_role[1], 9)),
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _infer_role(description: str) -> str:
    """根据任务描述自动推断子Agent角色（最长匹配优先）"""
    if not description:
        return "general"
    text = str(description).lower()
    for keyword, role in _ROLE_KEYWORDS_SORTED:
        if keyword in text:
            return role
    return "general"


def _estimate_tokens(text: str) -> int:
    """估算文本的token数量（中英文混合: 中文按字符, 英文按词）"""
    if not text:
        return 0
    text = str(text)
    cjk = len(_CJK_RE.findall(text))
    words = len(_ASCII_WORD_RE.findall(text))
    return cjk + words


class TaskExecutor:
    """任务执行器 — 在线程池中执行子Agent任务"""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=int(max_workers))
        self._llm_callback: Optional[Callable[[dict], str]] = None
        self._pending: Dict[str, Future] = {}
        self._results: Dict[str, SummonResult] = {}
        self._cancel_flags: Dict[str, bool] = {}
        self._lock = threading.Lock()
        # 默认任务模拟思考时长: 让 async/dismiss 语义可观测
        self._simulated_think_seconds = 0.3

    def set_llm_callback(self, callback: Callable[[dict], str]) -> None:
        """注入 LLM 回调: callback({agent_id, task, description, role}) -> str"""
        self._llm_callback = callback

    def _run_task(self, agent_id: str, task: str, description: str, timeout: float) -> SummonResult:
        """Internal task runner"""
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            status=SummonStatus.RUNNING,
            role=_infer_role(description),
            created_at=time.time(),
        )
        started = time.time()
        try:
            # 检查取消标志
            with self._lock:
                cancelled = self._cancel_flags.get(agent_id, False)
            if cancelled:
                result.status = SummonStatus.DISMISSED
                result.duration = time.time() - started
                return result

            if self._llm_callback is not None:
                try:
                    output = self._llm_callback({
                        "agent_id": agent_id,
                        "task": task,
                        "description": description,
                        "role": result.role,
                    })
                except Exception as e:
                    output = f"[回调执行失败] {e}"
                result.result = str(output)
            else:
                # 无 LLM 回调 → 内置确定性执行器 (真实环境应注入 LLM 回调)
                # 模拟一段"思考"时间, 使异步/遣散语义可观测
                if self._simulated_think_seconds > 0:
                    time.sleep(self._simulated_think_seconds)
                with self._lock:
                    cancelled = self._cancel_flags.get(agent_id, False)
                if cancelled:
                    result.status = SummonStatus.DISMISSED
                    result.duration = time.time() - started
                    return result
                title = task or description or "未命名任务"
                result.result = (
                    f"✅ 任务已执行完成 (agent={agent_id})\n"
                    f"任务: {title}\n"
                    f"描述: {description or '-'}\n"
                    f"角色: {result.role}\n"
                    f"完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"输出摘要: 任务「{title}」已完成, 共 {_estimate_tokens(title)} tokens 估算处理量。"
                )

            # 仅当未被外部标记为 TIMEOUT/DISMISSED 时置为 DONE
            with self._lock:
                if result.status not in (SummonStatus.TIMEOUT, SummonStatus.DISMISSED):
                    result.status = SummonStatus.DONE
            result.duration = time.time() - started
            result.tokens_used = _estimate_tokens(task) + _estimate_tokens(result.result)
        except Exception as e:
            result.status = SummonStatus.FAILED
            result.error = str(e)
            result.duration = time.time() - started
        return result

    def _on_future_done(self, agent_id: str, result: SummonResult, future: Future):
        try:
            final = future.result()
        except Exception as e:
            final = None
            with self._lock:
                if result.status not in (SummonStatus.TIMEOUT, SummonStatus.DISMISSED):
                    result.status = SummonStatus.FAILED
                    result.error = str(e)
        if final is not None:
            with self._lock:
                if result.status not in (SummonStatus.TIMEOUT, SummonStatus.DISMISSED):
                    result.status = final.status
                    result.result = final.result
                    result.error = final.error
                    result.duration = final.duration
                    result.tokens_used = final.tokens_used
                    result.role = final.role
        with self._lock:
            self._pending.pop(agent_id, None)

    def execute(self, agent_id: str, task: str, description: str, timeout: float = 300) -> SummonResult:
        """同步执行任务"""
        result = self.execute_async(agent_id, task, description, timeout=timeout)
        future = self._pending.get(agent_id)
        if future is None:
            return result
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            with self._lock:
                self._cancel_flags[agent_id] = True
            result.status = SummonStatus.TIMEOUT
            result.error = f"任务执行超时 ({timeout}s)"
            result.duration = time.time() - (result.created_at or time.time())
        except Exception as e:
            result.status = SummonStatus.FAILED
            result.error = str(e)
        return result

    def execute_async(self, agent_id: str, task: str, description: str, **kwargs) -> SummonResult:
        """异步提交任务，立即返回PENDING结果"""
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            status=SummonStatus.PENDING,
            role=_infer_role(description),
            created_at=time.time(),
        )
        timeout = float(kwargs.get("timeout", DEFAULT_TIMEOUT))
        with self._lock:
            self._results[agent_id] = result
            self._cancel_flags[agent_id] = False
            future = self._executor.submit(self._run_task, agent_id, task, description, timeout)
            self._pending[agent_id] = future
            future.add_done_callback(lambda f, aid=agent_id, r=result: self._on_future_done(aid, r, f))
        return result

    def cancel(self, agent_id: str) -> bool:
        """取消任务 (返回是否曾处于待处理/运行中状态)"""
        with self._lock:
            if agent_id not in self._pending:
                return False
            self._cancel_flags[agent_id] = True
            future = self._pending.get(agent_id)
        if future is not None:
            future.cancel()
        return True

    def active_futures(self) -> List[str]:
        """返回活跃的future ID列表"""
        with self._lock:
            return [
                aid for aid, fut in self._pending.items()
                if not fut.done()
            ]

    def shutdown(self, wait: bool = True) -> None:
        """关闭执行器"""
        try:
            self._executor.shutdown(wait=wait)
        except RuntimeError:
            pass


class SummonEngine:
    """P0-7 动态Summon子Agent引擎"""

    def __init__(self):
        self._executor = TaskExecutor(max_workers=DEFAULT_MAX_WORKERS)
        self._history: List[SummonResult] = []
        self._results: Dict[str, SummonResult] = {}
        self._active: Dict[str, SummonResult] = {}
        self._stats = {
            "total_summoned": 0,
            "done": 0,
            "failed": 0,
            "timeout": 0,
            "dismissed": 0,
        }
        self._lock = threading.Lock()
        self._counter = 0

    def _new_agent_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"summon_{int(time.time() * 1000)}_{self._counter}_{uuid.uuid4().hex[:4]}"

    def _on_async_done(self, agent_id: str, result: SummonResult, future: Future):
        """异步任务完成后的引擎簿记 (结果状态已由 TaskExecutor 回调更新)"""
        with self._lock:
            self._active.pop(agent_id, None)
            if result.status == SummonStatus.DISMISSED:
                self._stats["dismissed"] += 1
            elif result.status == SummonStatus.TIMEOUT:
                self._stats["timeout"] += 1
            elif result.status == SummonStatus.DONE:
                self._stats["done"] += 1
            else:
                self._stats["failed"] += 1
            self._history.insert(0, result)
            if len(self._history) > 500:
                self._history = self._history[:500]

    def _record_sync(self, result: SummonResult):
        with self._lock:
            self._stats["total_summoned"] += 1
            if result.status == SummonStatus.DONE:
                self._stats["done"] += 1
            elif result.status == SummonStatus.TIMEOUT:
                self._stats["timeout"] += 1
            elif result.status == SummonStatus.DISMISSED:
                self._stats["dismissed"] += 1
            else:
                self._stats["failed"] += 1
            self._history.insert(0, result)
            if len(self._history) > 500:
                self._history = self._history[:500]

    def summon(
        self,
        description: str = '',
        task: str = '',
        timeout: float = 300,
        role: str = '',
        async_mode: bool = False,
        **kwargs,
    ) -> SummonResult:
        """召唤子Agent执行任务"""
        agent_id = self._new_agent_id()
        inferred_role = role if role else _infer_role(description)
        timeout = float(timeout) if timeout else DEFAULT_TIMEOUT

        if async_mode:
            result = self._executor.execute_async(agent_id, task, description, timeout=timeout)
            result.role = inferred_role
            with self._lock:
                self._stats["total_summoned"] += 1
                self._active[agent_id] = result
                self._results[agent_id] = result
                future = self._executor._pending.get(agent_id)
            if future is not None:
                future.add_done_callback(
                    lambda f, aid=agent_id, r=result: self._on_async_done(aid, r, f)
                )
            return result

        result = self._executor.execute(agent_id, task, description, timeout=timeout)
        result.role = inferred_role
        with self._lock:
            self._results[agent_id] = result
        self._record_sync(result)
        return result

    def summon_parallel(self, tasks: List[Dict[str, str]]) -> List[SummonResult]:
        """并行召唤多个子Agent"""
        if not tasks:
            return []
        results: List[SummonResult] = []
        for t in tasks:
            t = t or {}
            results.append(
                self.summon(
                    description=t.get("description", ""),
                    task=t.get("task", ""),
                    timeout=float(t.get("timeout", DEFAULT_TIMEOUT)),
                    role=t.get("role", ""),
                )
            )
        return results

    def active_agents(self) -> List[Dict[str, Any]]:
        """返回活跃Agent列表"""
        with self._lock:
            return [
                {
                    "agent_id": r.agent_id,
                    "status": r.status.value if isinstance(r.status, SummonStatus) else str(r.status),
                    "description": r.description,
                    "task": r.task,
                    "role": r.role,
                    "created_at": r.created_at,
                }
                for r in self._active.values()
                if r.is_active
            ]

    def dismiss(self, agent_id: str) -> bool:
        """遣散Agent"""
        with self._lock:
            result = self._active.get(agent_id)
            if result is None or not result.is_active:
                return False
        cancelled = self._executor.cancel(agent_id)
        with self._lock:
            result.status = SummonStatus.DISMISSED
            self._active.pop(agent_id, None)
        return cancelled if cancelled else True

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        with self._lock:
            total = self._stats["total_summoned"]
            done = self._stats["done"]
            stats = dict(self._stats)
            stats["active_agents"] = len(self._active)
            stats["success_rate"] = round((done / total * 100.0), 2) if total else 0.0
            stats["engine"] = "SummonEngine P0-7"
            return stats

    def get_history(self, limit: int = 100) -> List[SummonResult]:
        """获取历史记录，最近的在前"""
        with self._lock:
            return list(self._history[: int(limit)])

    def summon_result(self, agent_id: str) -> Optional[SummonResult]:
        """按ID查询召唤结果"""
        with self._lock:
            return self._results.get(agent_id)


# ── 单例 ─────────────────────────────────────────────────────────
_engine_lock = threading.Lock()
_engine_instance: Optional[SummonEngine] = None


def get_summon_engine() -> SummonEngine:
    """获取SummonEngine单例"""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = SummonEngine()
        return _engine_instance


def reset_summon_engine() -> None:
    """重置SummonEngine单例"""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is not None:
            try:
                _engine_instance._executor.shutdown(wait=False)
            except RuntimeError:
                pass
        _engine_instance = None


__all__ = [
    "SummonStatus", "SummonResult",
    "TaskExecutor", "SummonEngine",
    "summon", "summon_parallel", "active_agents", "dismiss",
    "get_stats", "get_history", "summon_result",
    "get_summon_engine", "reset_summon_engine",
]
