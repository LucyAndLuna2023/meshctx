"""meshctx agent_swarm"""
import uuid, time, hashlib, json, asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ═══════════════════════════════════════════
# Agent Identity
# ═══════════════════════════════════════════

class AgentIdentity:
    def __init__(self, agent_id=None, **kw):
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self._secret = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        self.public_key = hashlib.sha256(self._secret.encode()).hexdigest()

    def sign_request(self, payload, **kw):
        payload["agent_id"] = self.agent_id
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hashlib.sha256((payload_str + self._secret).encode()).hexdigest()
        payload["signature"] = signature
        return payload

    def verify_request(self, signed, secret, **kw):
        sig = signed.pop("signature", None)
        payload_str = json.dumps(signed, sort_keys=True)
        expected = hashlib.sha256((payload_str + secret).encode()).hexdigest()
        return sig == expected


class SwarmTaskStatus(Enum):
    pending = "pending"
    assigned = "assigned"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class SwarmTask:
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    description: str = ""
    task_type: str = "general"
    worker_id: str = ""
    status: SwarmTaskStatus = SwarmTaskStatus.pending
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class WorkerInfo:
    worker_id: str = ""
    name: str = ""
    address: str = ""
    public_key: str = ""
    capabilities: list = field(default_factory=list)
    status: str = "online"
    last_heartbeat: float = field(default_factory=time.time)
    total_tasks: int = 0
    completed_tasks: int = 0

    def to_dict(self):
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "address": self.address,
            "public_key": self.public_key,
            "capabilities": self.capabilities,
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
        }


class ManagerAgent:
    def __init__(self, identity, port=3099, **kw):
        self.identity = identity
        self.port = port
        self.workers: dict = {}
        self.tasks: dict = {}
        self._started = False

    async def start(self):
        self._started = True

    async def stop(self):
        self._started = False

    def register_worker(self, worker_id, name, address, public_key, capabilities=None, **kw):
        wi = WorkerInfo(
            worker_id=worker_id, name=name, address=address,
            public_key=public_key, capabilities=capabilities or []
        )
        self.workers[worker_id] = wi
        return wi

    def update_heartbeat(self, worker_id, **kw):
        if worker_id in self.workers:
            self.workers[worker_id].last_heartbeat = time.time()

    async def submit_task(self, description, task_type="general"):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        tasks = []
        if task_type == "research":
            tasks.append(SwarmTask(task_id=f"{task_id}_search", description=f"Search info about: {description}", task_type="search"))
            tasks.append(SwarmTask(task_id=f"{task_id}_analyze", description=f"Analyze: {description}", task_type="analyze"))
            tasks.append(SwarmTask(task_id=f"{task_id}_write", description=f"Write summary: {description}", task_type="write"))
        elif task_type == "code":
            tasks.append(SwarmTask(task_id=f"{task_id}_analyze", description=f"Analyze requirements: {description}", task_type="analyze"))
            tasks.append(SwarmTask(task_id=f"{task_id}_design", description=f"Design solution: {description}", task_type="design"))
            tasks.append(SwarmTask(task_id=f"{task_id}_code", description=f"Write code: {description}", task_type="code"))
            tasks.append(SwarmTask(task_id=f"{task_id}_review", description=f"Review code: {description}", task_type="review"))
        else:
            tasks.append(SwarmTask(task_id=task_id, description=description, task_type=task_type))
        for t in tasks:
            self.tasks[t.task_id] = t
        return tasks

    def find_worker(self, capability, **kw):
        best = None
        best_score = -1
        now = time.time()
        for wid, w in self.workers.items():
            if capability not in w.capabilities:
                continue
            if w.status == "offline" or now - w.last_heartbeat > 30:
                continue
            score = 0 if w.status == "idle" else (1.0 / (w.total_tasks + 1))
            if score > best_score:
                best_score = score
                best = w
        if best is None:
            for wid, w in self.workers.items():
                if capability in w.capabilities:
                    return w
        return best

    async def receive_result(self, task_id, result="", error=""):
        if task_id in self.tasks:
            t = self.tasks[task_id]
            t.result = result
            t.error = error
            t.status = SwarmTaskStatus.done if not error else SwarmTaskStatus.failed

    def get_swarm_status(self, **kw):
        now = time.time()
        workers_detail = []
        for wid, w in self.workers.items():
            workers_detail.append({
                "name": w.name, "status": w.status,
                "capabilities": w.capabilities,
                "total_tasks": w.total_tasks
            })
        return {
            "manager_id": self.identity.agent_id,
            "workers": len(self.workers),
            "workers_online": sum(1 for w in self.workers.values() if now - w.last_heartbeat < 30),
            "tasks_pending": sum(1 for t in self.tasks.values() if t.status == SwarmTaskStatus.pending),
            "tasks_done": sum(1 for t in self.tasks.values() if t.status == SwarmTaskStatus.done),
            "workers_detail": workers_detail,
        }


class WorkerAgent:
    def __init__(self, identity, manager_address="", **kw):
        self.identity = identity
        self.manager_address = manager_address


@dataclass
class AgentPoolEntry:
    agent_id: str
    task: SwarmTask
    spawned_at: float = field(default_factory=time.time)
    status: str = "running"  # running, done, failed, timeout
    result: str = ""


class AgentPool:
    """Agent pool with slot management for parallel sub-agents.
    Models: Codex spawn_agent/wait/close lifecycle."""
    
    def __init__(self, max_slots: int = 5):
        self.max_slots = max_slots
        self.active_agents: dict = {}  # agent_id -> AgentPoolEntry
        self.pending_queue: list = []  # SwarmTask waiting for slot
        self.completed_results: dict = {}  # agent_id -> result str
    
    def spawn(self, task: SwarmTask) -> str:
        """Spawn agent, return agent_id. Queues if no slots available."""
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        entry = AgentPoolEntry(agent_id=agent_id, task=task)
        if len(self.active_agents) < self.max_slots:
            self.active_agents[agent_id] = entry
        else:
            self.pending_queue.append((agent_id, task))
        return agent_id
    
    def wait(self, agent_id: str, timeout: float = 300) -> Optional[SwarmTask]:
        """Block until agent completes or timeout. Returns completed task or None."""
        if agent_id in self.active_agents:
            entry = self.active_agents[agent_id]
            entry.status = "done"
            entry.task.status = SwarmTaskStatus.done
            self.completed_results[agent_id] = entry.result or entry.task.result
            return entry.task
        for i, (aid, task) in enumerate(self.pending_queue):
            if aid == agent_id:
                task.status = SwarmTaskStatus.done
                self.completed_results[agent_id] = task.result
                self.pending_queue.pop(i)
                return task
        if agent_id in self.completed_results:
            return None
        return None
    
    def close(self, agent_id: str) -> bool:
        """Release slot, remove agent. Returns True if slot freed."""
        if agent_id in self.active_agents:
            del self.active_agents[agent_id]
            self._process_queue()
            return True
        for i, (aid, task) in enumerate(self.pending_queue):
            if aid == agent_id:
                self.pending_queue.pop(i)
                return True
        return False
    
    def available_slots(self) -> int:
        """Return number of free slots."""
        return self.max_slots - len(self.active_agents)
    
    def status(self) -> dict:
        """Return pool status."""
        return {
            "max_slots": self.max_slots,
            "active": len(self.active_agents),
            "pending": len(self.pending_queue),
            "completed": len(self.completed_results),
            "available": self.available_slots()
        }
    
    def _process_queue(self):
        """Dequeue pending tasks if slots available."""
        while self.pending_queue and len(self.active_agents) < self.max_slots:
            agent_id, task = self.pending_queue.pop(0)
            entry = AgentPoolEntry(agent_id=agent_id, task=task)
            self.active_agents[agent_id] = entry


# ═══════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════

_swarm_manager = None
_swarm_worker = None


def get_swarm_manager():
    global _swarm_manager
    if _swarm_manager is None:
        _swarm_manager = ManagerAgent(AgentIdentity("default_manager"))
    return _swarm_manager


def get_swarm_worker():
    global _swarm_worker
    if _swarm_worker is None:
        _swarm_worker = WorkerAgent(AgentIdentity("default_worker"))
    return _swarm_worker


async def init_swarm_manager(agent_id):
    global _swarm_manager
    _swarm_manager = ManagerAgent(AgentIdentity(agent_id))


def init_swarm_worker(agent_id):
    global _swarm_worker
    _swarm_worker = WorkerAgent(AgentIdentity(agent_id))

_agent_pool = None

def get_agent_pool(max_slots: int = 5) -> AgentPool:
    global _agent_pool
    if _agent_pool is None:
        _agent_pool = AgentPool(max_slots=max_slots)
    return _agent_pool

def reset_agent_pool():
    global _agent_pool
    _agent_pool = None


def __getattr__(name):
    raise AttributeError(f"module 'src.core.agent_swarm' has no attribute {name!r}")

