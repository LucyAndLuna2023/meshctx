"""
Summon Engine — P0-7 动态子Agent引擎
=====================================
License: MIT
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.summon_engine")


# ── Enums ──

class SummonStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DISMISSED = "dismissed"


# ── Data Classes ──

@dataclass
class SummonResult:
    agent_id: str
    description: str
    task: str = ""
    status: SummonStatus = SummonStatus.PENDING
    result: str = ""
    error: str = ""
    duration: float = 0.0
    tokens_used: int = 0
    role: str = "general"
    created_at: float = field(default_factory=time.time)

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
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "duration": self.duration,
            "tokens_used": self.tokens_used,
            "role": self.role,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


# ── Role Inference ──

_ROLE_KEYWORDS: Dict[str, List[str]] = {
    "coder": [
        "写代码", "实现", "修复bug", "修复", "bug", "代码", "算法", "implement",
        "code", "feature", "fix", "编写程序", "编程", "开发",
    ],
    "reviewer": [
        "审查", "review", "代码审查", "审计", "安全漏洞", "pull request",
        "pr", "code review", "检查代码",
    ],
    "architect": [
        "设计", "架构", "architecture", "design", "系统设计", "方案",
        "microservices", "微服务",
    ],
    "tester": [
        "测试", "test", "单元测试", "用例", "覆盖", "unit test",
        "write test", "编写测试",
    ],
    "researcher": [
        "研究", "research", "分析", "技术趋势", "最佳实践", "调研",
        "analyze", "趋势",
    ],
    "devops": [
        "部署", "deploy", "CI/CD", "流水线", "kubernetes", "k8s",
        "配置", "生产环境", "docker", "容器",
    ],
}


def _infer_role(description: str) -> str:
    """根据任务描述自动推断子Agent角色（最长匹配优先）"""
    if not description:
        return "general"
    desc_lower = description.lower()
    best_role = "general"
    best_len = 0
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in desc_lower:
                if len(kw) > best_len:
                    best_len = len(kw)
                    best_role = role
    return best_role


def _estimate_tokens(text: str) -> int:
    """估算文本的token数量（中英文混合）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    # Chinese: ~1.5 tokens/char, English: ~0.25 tokens/char
    return max(1, int(chinese_chars * 1.5 + other_chars * 0.25))


# ── Task Executor ──

class TaskExecutor:
    """任务执行器 — 在线程池中执行子Agent任务"""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: Dict[str, Future] = {}
        self._llm_callback: Optional[Callable] = None
        self._lock = threading.Lock()

    def set_llm_callback(self, callback: Callable[[dict], str]) -> None:
        self._llm_callback = callback

    def _run_task(self, agent_id: str, task: str, description: str,
                  timeout: float) -> SummonResult:
        """Internal task runner"""
        start = time.time()
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            status=SummonStatus.RUNNING,
        )

        try:
            if self._llm_callback:
                params = {
                    "task": task or description,
                    "description": description,
                    "agent_id": agent_id,
                }
                response = self._llm_callback(params)
                result.result = response
            else:
                # Simulated execution
                result.result = (
                    f"[模拟] 子Agent '{agent_id}' 完成了任务: {task or description}"
                )
            result.status = SummonStatus.DONE
            result.tokens_used = _estimate_tokens(result.result)
        except Exception as e:
            result.status = SummonStatus.FAILED
            result.error = str(e)
        finally:
            result.duration = time.time() - start

        return result

    def execute(self, agent_id: str, task: str, description: str,
                timeout: float = 300) -> SummonResult:
        """同步执行任务"""
        future = self._executor.submit(
            self._run_task, agent_id, task, description, timeout
        )
        with self._lock:
            self._futures[agent_id] = future
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            with self._lock:
                self._futures.pop(agent_id, None)
            return SummonResult(
                agent_id=agent_id,
                description=description,
                task=task,
                status=SummonStatus.TIMEOUT,
                error="任务超时",
                duration=timeout,
            )
        finally:
            with self._lock:
                self._futures.pop(agent_id, None)

    def execute_async(self, agent_id: str, task: str,
                      description: str, **kwargs) -> SummonResult:
        """异步提交任务，立即返回PENDING结果"""
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            status=SummonStatus.PENDING,
        )
        future = self._executor.submit(
            self._run_task, agent_id, task, description, 300
        )
        with self._lock:
            self._futures[agent_id] = future

        def _update_result(f: Future) -> None:
            try:
                r = f.result(timeout=300)
                result.status = r.status
                result.result = r.result
                result.error = r.error
                result.duration = r.duration
                result.tokens_used = r.tokens_used
            except Exception as e:
                result.status = SummonStatus.FAILED
                result.error = str(e)
            finally:
                with self._lock:
                    self._futures.pop(agent_id, None)

        future.add_done_callback(_update_result)
        return result

    def cancel(self, agent_id: str) -> bool:
        """取消任务"""
        with self._lock:
            future = self._futures.get(agent_id)
        if future and not future.done():
            return future.cancel()
        return False

    def active_futures(self) -> List[str]:
        """返回活跃的future ID列表"""
        with self._lock:
            return [aid for aid, f in self._futures.items()
                    if not f.done()]

    def shutdown(self, wait: bool = True) -> None:
        """关闭执行器"""
        self._executor.shutdown(wait=wait)


# ── Summon Engine ──

class SummonEngine:
    """P0-7 动态Summon子Agent引擎"""

    def __init__(self):
        self._executor = TaskExecutor(max_workers=4)
        self._history: List[SummonResult] = []
        self._lock = threading.Lock()
        self._active: Dict[str, SummonResult] = {}
        self._counter: int = 0

    def summon(self, description: str = "", task: str = "",
               timeout: float = 300, role: str = "",
               async_mode: bool = False, **kwargs) -> SummonResult:
        """召唤子Agent执行任务"""
        agent_id = f"summon_{uuid.uuid4().hex[:8]}"
        actual_task = task or description
        actual_role = role or _infer_role(description)

        if async_mode:
            result = SummonResult(
                agent_id=agent_id,
                description=description,
                task=actual_task,
                role=actual_role,
                status=SummonStatus.PENDING,
            )
            with self._lock:
                self._active[agent_id] = result

            # Submit async execution — fires add_done_callback internally
            self._executor.execute_async(
                agent_id=agent_id,
                task=actual_task,
                description=description,
            )

            return result

        # Synchronous mode
        result = self._executor.execute(
            agent_id=agent_id,
            task=actual_task,
            description=description,
            timeout=timeout,
        )
        result.role = actual_role

        with self._lock:
            self._history.insert(0, result)
            self._counter += 1

        return result

    def summon_parallel(self, tasks: List[Dict[str, str]]) -> List[SummonResult]:
        """并行召唤多个子Agent"""
        results = []
        futures_and_ids = []

        for task_spec in tasks:
            desc = task_spec.get("description", "")
            tsk = task_spec.get("task", desc)
            role = task_spec.get("role", "")
            agent_id = f"summon_{uuid.uuid4().hex[:8]}"
            actual_role = role or _infer_role(desc)

            future = self._executor._executor.submit(
                self._executor._run_task,
                agent_id, tsk, desc, 300,
            )
            futures_and_ids.append((agent_id, future, desc, tsk, actual_role))

        for agent_id, future, desc, tsk, actual_role in futures_and_ids:
            try:
                result = future.result(timeout=300)
            except FutureTimeoutError:
                result = SummonResult(
                    agent_id=agent_id,
                    description=desc,
                    task=tsk,
                    status=SummonStatus.TIMEOUT,
                    error="任务超时",
                    duration=300,
                )
            except Exception as e:
                result = SummonResult(
                    agent_id=agent_id,
                    description=desc,
                    task=tsk,
                    status=SummonStatus.FAILED,
                    error=str(e),
                )
            result.role = actual_role
            results.append(result)
            with self._lock:
                self._history.insert(0, result)
                self._counter += 1

        return results

    def active_agents(self) -> List[Dict[str, Any]]:
        """返回活跃Agent列表"""
        with self._lock:
            return [a.to_dict() for a in self._active.values()
                    if a.is_active]

    def dismiss(self, agent_id: str) -> bool:
        """遣散Agent"""
        with self._lock:
            if agent_id in self._active:
                entry = self._active.pop(agent_id)
                entry.status = SummonStatus.DISMISSED
                self._history.insert(0, entry)
                return True
        # Also try to cancel in executor
        self._executor.cancel(agent_id)
        return False

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        with self._lock:
            total = len(self._history)
            done = sum(1 for r in self._history
                      if r.status == SummonStatus.DONE)
            failed = sum(1 for r in self._history
                        if r.status == SummonStatus.FAILED)
            timed_out = sum(1 for r in self._history
                           if r.status == SummonStatus.TIMEOUT)
            active = sum(1 for r in self._active.values() if r.is_active)

            return {
                "engine": "SummonEngine P0-7",
                "active_agents": active,
                "total_summoned": total,
                "done": done,
                "failed": failed,
                "timeout": timed_out,
                "success_rate": round(done / max(total, 1) * 100, 1),
            }

    def get_history(self, limit: int = 100) -> List[SummonResult]:
        """获取历史记录，最近的在前"""
        with self._lock:
            return self._history[:limit]

    def summon_result(self, agent_id: str) -> Optional[SummonResult]:
        """按ID查询召唤结果"""
        with self._lock:
            for r in self._history:
                if r.agent_id == agent_id:
                    return r
            if agent_id in self._active:
                return self._active[agent_id]
        return None


# ── Singleton ──

_engine: Optional[SummonEngine] = None
_engine_lock = threading.Lock()


def get_summon_engine() -> SummonEngine:
    """获取SummonEngine单例"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SummonEngine()
    return _engine


def reset_summon_engine() -> None:
    """重置SummonEngine单例"""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine._executor.shutdown(wait=False)
        _engine = None
