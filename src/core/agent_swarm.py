"""meshctx agent_swarm — 多 Agent 协同 (Manager-Worker)。

真实实现（开源版）: 纯 Python stdlib (threading / uuid / time / hmac /
hashlib / asyncio)。内存版 Manager-Worker 蜂群:

  - AgentIdentity: 身份 + HMAC-SHA256 请求签名/验签
  - ManagerAgent: worker 注册 / 心跳 / 任务分解派发 / 结果回收 / 状态查询
  - WorkerAgent: 独立 worker 端 (execute_task)
  - AgentPool: 线程池式并行子 agent 槽位管理 (spawn/wait/close)
  - 模块级单例: get_swarm_manager / get_swarm_worker / get_agent_pool

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import queue as _queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.agent_swarm")

# worker 心跳超时（秒）: 超过该时长未心跳视为离线
HEARTBEAT_TIMEOUT = 60.0


class AgentIdentity:
    """Agent 身份: 生成公私钥对并为请求做 HMAC 签名。

    - public_key: 公开标识 (十六进制)
    - secret:     签名密钥 (内部 _secret, 测试/调用方需访问)
    """

    def __init__(self, agent_id=None, **kw):
        self.agent_id = str(agent_id) if agent_id is not None \
            else f"agent_{uuid.uuid4().hex[:8]}"
        self.name = str(kw.get("name", "") or self.agent_id)
        self.public_key = str(kw.get("public_key", "") or self._gen_public_key())
        self._secret = str(kw.get("secret", "") or self._gen_secret())
        self.created_at = time.time()

    @staticmethod
    def _gen_public_key() -> str:
        return hashlib.sha256(uuid.uuid4().bytes).hexdigest()

    @staticmethod
    def _gen_secret() -> str:
        return uuid.uuid4().hex

    def _canonical(self, payload: dict) -> bytes:
        # 稳定序列化: 忽略 signature 字段, 其余键按序拼接
        parts = []
        for key in sorted(payload.keys()):
            if key == "signature":
                continue
            parts.append(f"{key}={payload[key]}")
        return "&".join(parts).encode("utf-8")

    def sign_request(self, payload, **kw):
        """对 payload 签名, 返回 {"agent_id", "timestamp", "signature", ...payload}。"""
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        signed = dict(payload)
        signed.setdefault("timestamp", time.time())
        signed["agent_id"] = signed.get("agent_id", self.agent_id)
        digest = hmac.new(self._secret.encode("utf-8"),
                          self._canonical(signed), hashlib.sha256).hexdigest()
        signed["signature"] = digest
        return signed

    def verify_request(self, signed, secret, **kw):
        """校验签名。secret 缺失签名时抛 ValueError, 不匹配返回 False。"""
        if not isinstance(signed, dict) or "signature" not in signed:
            raise ValueError("signed request missing 'signature' field")
        expected = hmac.new(str(secret).encode("utf-8"),
                            self._canonical(signed), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signed["signature"])


class TaskStatus(Enum):
    pending = 'pending'
    assigned = 'assigned'
    running = 'running'
    done = 'done'
    failed = 'failed'


@dataclass
class SwarmTask:
    task_id: str = None
    description: str = ''
    task_type: str = 'general'
    worker_id: str = ''
    status: TaskStatus = None
    result: str = ''
    error: str = ''
    created_at: float = None

    def __post_init__(self):
        if self.task_id is None:
            self.task_id = f"task_{uuid.uuid4().hex[:8]}"
        if self.status is None:
            self.status = TaskStatus.pending
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self):
        """序列化为 JSON 友好的字典。"""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "worker_id": self.worker_id,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass
class WorkerInfo:
    worker_id: str = ''
    name: str = ''
    address: str = ''
    public_key: str = ''
    capabilities: list = None
    status: str = 'online'
    last_heartbeat: float = None
    total_tasks: int = 0
    completed_tasks: int = 0

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []
        if self.last_heartbeat is None:
            self.last_heartbeat = time.time()

    def to_dict(self):
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "address": self.address,
            "public_key": self.public_key,
            "capabilities": list(self.capabilities or []),
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
        }

    def is_online(self, timeout: float = HEARTBEAT_TIMEOUT) -> bool:
        return bool(self.last_heartbeat) and (time.time() - self.last_heartbeat) <= timeout


class ManagerAgent:
    """蜂群 Manager: 管理 worker 注册、心跳、任务分解与结果回收。"""

    def __init__(self, identity, port=3099, **kw):
        self.identity = identity
        self.port = int(port)
        self.workers: Dict[str, WorkerInfo] = {}
        self.tasks: Dict[str, SwarmTask] = {}
        self._lock = threading.RLock()
        self._running = False
        self._started_at = None
        self._config = dict(kw)

    async def start(self):
        """启动 Manager（内存版: 仅置位状态）。"""
        with self._lock:
            self._running = True
            self._started_at = time.time()
        logger.info("swarm manager %s started on port %d", self.identity.agent_id, self.port)
        return self

    async def stop(self):
        """停止 Manager。"""
        with self._lock:
            self._running = False
        logger.info("swarm manager %s stopped", self.identity.agent_id)
        return None

    def register_worker(self, worker_id, name, address, public_key,
                        capabilities=None, **kw):
        """注册 worker, 返回 WorkerInfo。"""
        worker = WorkerInfo(
            worker_id=str(worker_id),
            name=str(name),
            address=str(address),
            public_key=str(public_key),
            capabilities=list(capabilities or []),
            status='online',
            last_heartbeat=time.time(),
        )
        with self._lock:
            self.workers[worker.worker_id] = worker
        logger.info("worker registered: %s (%s)", worker.worker_id, worker.name)
        return worker

    def update_heartbeat(self, worker_id, **kw):
        """更新 worker 心跳时间。"""
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker is None:
                return False
            worker.last_heartbeat = time.time()
            worker.status = 'online'
            return True

    async def submit_task(self, description, task_type='general'):
        """提交任务: 按类型分解为子任务列表 (SwarmTask) 并尝试派发。"""
        with self._lock:
            subtasks = self._decompose(description, task_type)
            for task in subtasks:
                self.tasks[task.task_id] = task
                worker = self.find_worker(task.task_type)
                if worker is not None:
                    task.worker_id = worker.worker_id
                    task.status = TaskStatus.assigned
                    worker.total_tasks += 1
            return subtasks

    def _decompose(self, description: str, task_type: str) -> List[SwarmTask]:
        """规则化任务分解。"""
        description = description or ''
        if task_type == "research":
            return [
                SwarmTask(description=f"搜索相关资料: {description}", task_type="search"),
                SwarmTask(description=f"分析整合资料: {description}", task_type="analyze"),
                SwarmTask(description=f"撰写总结报告: {description}", task_type="write"),
            ]
        if task_type == "code":
            return [
                SwarmTask(description=f"分析需求: {description}", task_type="analyze"),
                SwarmTask(description=f"设计方案: {description}", task_type="design"),
                SwarmTask(description=f"编写代码: {description}", task_type="write"),
                SwarmTask(description=f"审查代码: {description}", task_type="review"),
            ]
        if task_type == "general":
            return [SwarmTask(description=description, task_type="general")]
        # 其他类型: 按关键词猜测子任务
        if "搜索" in description or "查找" in description:
            return [
                SwarmTask(description=f"搜索: {description}", task_type="search"),
                SwarmTask(description=f"整理: {description}", task_type="write"),
            ]
        if "分析" in description:
            return [
                SwarmTask(description=f"分析: {description}", task_type="analyze"),
                SwarmTask(description=f"汇总: {description}", task_type="write"),
            ]
        if "写" in description or "生成" in description:
            return [
                SwarmTask(description=f"编写: {description}", task_type="write"),
                SwarmTask(description=f"审查: {description}", task_type="review"),
            ]
        return [SwarmTask(description=description, task_type=task_type)]

    def find_worker(self, capability, **kw):
        """按能力匹配 worker: 在线 → 空闲 → 最少任务数 → 兜底任何具备能力的。"""
        with self._lock:
            candidates = [w for w in self.workers.values()
                          if capability in (w.capabilities or [])]
            if not candidates:
                return None
            online = [w for w in candidates if w.is_online()]
            if online:
                free = [w for w in online if w.status != 'busy']
                pool = free or online
            else:
                # 无在线 worker: 兜底选取具备能力者（保证可用性）
                pool = candidates
            return min(pool, key=lambda w: (w.status == 'busy', w.total_tasks))

    async def receive_result(self, task_id, result='', error=''):
        """回收 worker 结果, 更新任务状态。"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                logger.warning("result for unknown task %s ignored", task_id)
                return False
            if error:
                task.status = TaskStatus.failed
                task.error = str(error)
            else:
                task.status = TaskStatus.done
                task.result = str(result)
                worker = self.workers.get(task.worker_id)
                if worker is not None:
                    worker.completed_tasks += 1
            return task

    def get_swarm_status(self, **kw):
        """返回蜂群整体状态。"""
        with self._lock:
            now = time.time()
            online = [w for w in self.workers.values() if w.is_online()]
            tasks = list(self.tasks.values())
            return {
                "manager_id": self.identity.agent_id,
                "status": "running" if self._running else "stopped",
                "workers": len(self.workers),
                "workers_online": len(online),
                "tasks_total": len(tasks),
                "tasks_pending": sum(1 for t in tasks if t.status in (TaskStatus.pending, TaskStatus.assigned)),
                "tasks_running": sum(1 for t in tasks if t.status == TaskStatus.running),
                "tasks_done": sum(1 for t in tasks if t.status == TaskStatus.done),
                "tasks_failed": sum(1 for t in tasks if t.status == TaskStatus.failed),
                "workers_detail": [w.to_dict() for w in self.workers.values()],
                "timestamp": now,
            }

    def get_worker(self, worker_id: str) -> Optional[WorkerInfo]:
        with self._lock:
            return self.workers.get(worker_id)


class WorkerAgent:
    """蜂群 Worker: 从 Manager 领取任务并返回执行结果。"""

    def __init__(self, identity, manager_address='', **kw):
        self.identity = identity
        self.manager_address = str(manager_address)
        self._running = False
        self._tasks_processed = 0
        self._lock = threading.RLock()
        self._config = dict(kw)

    def start(self):
        with self._lock:
            self._running = True
        return self

    def stop(self):
        with self._lock:
            self._running = False
        return None

    async def execute_task(self, request):
        """执行一个任务请求 (dict)。

        request 支持: task_id / description / task / type
        返回: {"task_id", "status", "result", "worker_id", "task_type"}
        """
        if not isinstance(request, dict):
            raise TypeError("execute_task expects a dict request")
        task_id = request.get("task_id") or f"task_{uuid.uuid4().hex[:8]}"
        description = request.get("description") or request.get("task") or ""
        task_type = request.get("type") or request.get("task_type") or "general"
        with self._lock:
            self._tasks_processed += 1
        # 内存版执行: 生成结构化结果回执
        result = {
            "task_id": task_id,
            "status": "done",
            "result": f"[{self.identity.agent_id}] executed {task_type} task: {description[:80]}",
            "worker_id": self.identity.agent_id,
            "task_type": task_type,
            "timestamp": time.time(),
        }
        return result

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "worker_id": self.identity.agent_id,
                "manager_address": self.manager_address,
                "running": self._running,
                "tasks_processed": self._tasks_processed,
            }


# ═══════════════════════════════════════════════════════════
# AgentPool — 并行子 agent 槽位管理
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentPoolEntry:
    agent_id: str = None
    task: SwarmTask = None
    spawned_at: float = None
    status: str = 'running'   # running | queued | done | failed | closed
    result: str = ''


class AgentPool:
    """Agent pool with slot management for parallel sub-agents.

    线程模型: spawn() 在有可用槽位时立即启动 daemon 线程执行任务,
    无槽位时进入 pending 队列, 槽位释放后自动补位。
    """

    def __init__(self, max_slots: int = 5):
        if max_slots <= 0:
            raise ValueError("max_slots must be a positive integer")
        self.max_slots = int(max_slots)
        self._entries: Dict[str, AgentPoolEntry] = {}
        self._active: Dict[str, AgentPoolEntry] = {}
        self._pending: "queue.Queue[tuple]" = _queue.Queue()
        self._done_events: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def spawn(self, task: SwarmTask) -> str:
        """Spawn agent, return agent_id. Queues if no slots available."""
        if not isinstance(task, SwarmTask):
            raise TypeError("task must be a SwarmTask")
        agent_id = f"agent_{uuid.uuid4().hex[:6]}"
        entry = AgentPoolEntry(
            agent_id=agent_id,
            task=task,
            spawned_at=time.time(),
            status='queued',
        )
        with self._lock:
            self._entries[agent_id] = entry
            self._done_events[agent_id] = threading.Event()
            if len(self._active) < self.max_slots:
                self._start(entry)
            else:
                self._pending.put(agent_id)
        return agent_id

    def _start(self, entry: AgentPoolEntry):
        self._active[entry.agent_id] = entry
        entry.status = 'running'
        thread = threading.Thread(
            target=self._run_task, args=(entry,),
            daemon=True, name=f"pool-{entry.agent_id}",
        )
        thread.start()

    def _run_task(self, entry: AgentPoolEntry):
        task = entry.task
        try:
            task.status = TaskStatus.running
            # 内存版模拟执行 (轻微延迟让 wait() 语义真实可测)
            time.sleep(0.05)
            task.result = f"Completed: {task.description or entry.agent_id}"
            task.status = TaskStatus.done
            entry.result = task.result
            entry.status = 'done'
        except Exception as e:  # 显式处理: 任务失败状态落盘, 不吞异常
            logger.exception("pool agent %s task failed", entry.agent_id)
            task.error = str(e)
            task.status = TaskStatus.failed
            entry.status = 'failed'
        finally:
            event = self._done_events.get(entry.agent_id)
            if event is not None:
                event.set()
            with self._lock:
                self._active.pop(entry.agent_id, None)
                self._process_queue_locked()

    def _process_queue_locked(self):
        while len(self._active) < self.max_slots and not self._pending.empty():
            agent_id = self._pending.get_nowait()
            entry = self._entries.get(agent_id)
            if entry is not None:
                self._start(entry)

    def _process_queue(self):
        """Dequeue pending tasks if slots available."""
        with self._lock:
            self._process_queue_locked()

    def wait(self, agent_id: str, timeout: float = 300) -> Optional[SwarmTask]:
        """Block until agent completes or timeout. Returns completed task or None."""
        with self._lock:
            entry = self._entries.get(agent_id)
            event = self._done_events.get(agent_id)
        if entry is None:
            return None
        if event is not None:
            event.wait(timeout=float(timeout))
        if entry.status in ('done', 'failed'):
            return entry.task
        return None

    def close(self, agent_id: str) -> bool:
        """Release slot, remove agent. Returns True if slot freed."""
        with self._lock:
            entry = self._entries.pop(agent_id, None)
            if entry is None:
                return False
            self._done_events.pop(agent_id, None)
            entry.status = 'closed'
            if entry.agent_id in self._active:
                # 正在运行: 释放槽位并补位
                self._active.pop(entry.agent_id, None)
                self._process_queue_locked()
                return True
            # 已完成/排队中: 已从注册表移除 (排队项出队时会因
            # entry 不存在而自动跳过)
            return True

    def available_slots(self) -> int:
        """Return number of free slots."""
        with self._lock:
            return max(0, self.max_slots - len(self._active))

    def status(self) -> dict:
        """Return pool status."""
        with self._lock:
            return {
                "max_slots": self.max_slots,
                "active": len(self._active),
                "queued": self._pending.qsize(),
                "total": len(self._entries),
                "available_slots": max(0, self.max_slots - len(self._active)),
                "done": sum(1 for e in self._entries.values() if e.status in ('done', 'failed')),
            }


# ═══════════════════════════════════════════════════════════
# 模块级单例
# ═══════════════════════════════════════════════════════════

_swarm_manager = None
_swarm_worker = None
_agent_pool = None
_singleton_lock = threading.Lock()


def get_swarm_manager():
    """返回全局 Manager（未初始化返回 None, 调用方自行 503）。"""
    global _swarm_manager
    return _swarm_manager


def get_swarm_worker():
    """返回全局 Worker（未初始化返回 None）。"""
    global _swarm_worker
    return _swarm_worker


async def init_swarm_manager(agent_id):
    """初始化并启动全局 Manager。"""
    global _swarm_manager
    identity = AgentIdentity(agent_id=agent_id)
    manager = ManagerAgent(identity)
    await manager.start()
    with _singleton_lock:
        _swarm_manager = manager
    return manager


def init_swarm_worker(agent_id):
    """初始化全局 Worker。"""
    global _swarm_worker
    identity = AgentIdentity(agent_id=agent_id)
    worker = WorkerAgent(identity)
    worker.start()
    with _singleton_lock:
        _swarm_worker = worker
    return worker


def get_agent_pool(max_slots: int = 5) -> AgentPool:
    """返回全局 AgentPool 单例。"""
    global _agent_pool
    with _singleton_lock:
        if _agent_pool is None:
            _agent_pool = AgentPool(max_slots=max_slots)
        return _agent_pool


def reset_agent_pool():
    """测试辅助: 重置全局 AgentPool。"""
    global _agent_pool
    with _singleton_lock:
        _agent_pool = None


__all__ = [
    "AgentIdentity", "TaskStatus", "SwarmTask", "WorkerInfo",
    "ManagerAgent", "WorkerAgent", "AgentPoolEntry", "AgentPool",
    "get_swarm_manager", "get_swarm_worker",
    "init_swarm_manager", "init_swarm_worker",
    "get_agent_pool", "reset_agent_pool",
]
