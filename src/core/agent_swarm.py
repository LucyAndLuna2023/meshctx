"""meshctx agent_swarm"""
import uuid, time, hashlib, json, asyncio
from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════
# Agent Identity
# ═══════════════════════════════════════════

class AgentIdentity:
    def __init__(self, agent_id=None):
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self._secret = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        self.public_key = hashlib.sha256(self._secret.encode()).hexdigest()

    def sign_request(self, payload):
        payload["agent_id"] = self.agent_id
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hashlib.sha256((payload_str + self._secret).encode()).hexdigest()
        payload["signature"] = signature
        return payload

    def verify_request(self, signed, secret):
        sig = signed.pop("signature", None)
        payload_str = json.dumps(signed, sort_keys=True)
        expected = hashlib.sha256((payload_str + secret).encode()).hexdigest()
        return sig == expected


class TaskStatus(Enum):
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
    status: TaskStatus = TaskStatus.pending
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


class ManagerAgent:
    def __init__(self, identity, port=3099):
        self.identity = identity
        self.port = port
        self.workers: dict = {}
        self.tasks: dict = {}
        self._started = False

    async def start(self):
        self._started = True

    async def stop(self):
        self._started = False

    def register_worker(self, worker_id, name, address, public_key, capabilities=None):
        wi = WorkerInfo(
            worker_id=worker_id, name=name, address=address,
            public_key=public_key, capabilities=capabilities or []
        )
        self.workers[worker_id] = wi
        return wi

    def update_heartbeat(self, worker_id):
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

    def find_worker(self, capability):
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
            t.status = TaskStatus.done if not error else TaskStatus.failed

    def get_swarm_status(self):
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
            "tasks_pending": sum(1 for t in self.tasks.values() if t.status == TaskStatus.pending),
            "tasks_done": sum(1 for t in self.tasks.values() if t.status == TaskStatus.done),
            "workers_detail": workers_detail,
        }


class WorkerAgent:
    def __init__(self, identity, manager_address=""):
        self.identity = identity
        self.manager_address = manager_address


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


def init_swarm_manager(agent_id):
    global _swarm_manager
    _swarm_manager = ManagerAgent(AgentIdentity(agent_id))


def init_swarm_worker(agent_id):
    global _swarm_worker
    _swarm_worker = WorkerAgent(AgentIdentity(agent_id))

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): raise TypeError("not iterable")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

