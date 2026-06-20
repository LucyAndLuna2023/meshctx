"""Agent Swarm — 多Agent协同 Manager-Worker (开源版 stub)"""
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger("meshctx.swarm")


class WorkerInfo:
    def __init__(self, worker_id="", name="", address="", public_key="", capabilities=None):
        self.worker_id = worker_id
        self.name = name
        self.address = address
        self.public_key = public_key
        self.capabilities = capabilities or []

    def to_dict(self):
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "address": self.address,
            "capabilities": self.capabilities,
        }


class TaskInfo:
    def __init__(self, task_id="", description="", task_type="general", priority=5):
        self.task_id = task_id
        self.description = description
        self.task_type = task_type
        self.priority = priority

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "priority": self.priority,
        }


class _SwarmManager:
    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}
        self._started = False

    async def start(self, host="0.0.0.0", port=3000):
        self._started = True
        logger.info(f"Swarm Manager started on {host}:{port}")

    def register_worker(self, worker_id="", name="", address="", public_key="", capabilities=None):
        wi = WorkerInfo(worker_id=worker_id, name=name, address=address, public_key=public_key, capabilities=capabilities)
        self._workers[worker_id] = wi
        return wi

    def update_heartbeat(self, agent_id: str):
        if agent_id in self._workers:
            logger.debug(f"Swarm heartbeat: {agent_id}")

    async def receive_result(self, task_id="", result="", error=""):
        logger.debug(f"Swarm result: {task_id} ok={not error}")

    async def submit_task(self, description="", task_type="general", context="", priority=5):
        import uuid
        tid = str(uuid.uuid4())[:8]
        return [TaskInfo(task_id=tid, description=description, task_type=task_type, priority=priority)]

    def get_swarm_status(self) -> dict:
        return {
            "status": "running" if self._started else "stopped",
            "workers": len(self._workers),
            "workers_list": [w.to_dict() for w in self._workers.values()],
        }


class _SwarmWorker:
    def __init__(self):
        self._started = False

    async def start(self, manager_host="localhost", manager_port=3000):
        self._started = True
        logger.info(f"Swarm Worker connected to {manager_host}:{manager_port}")

    async def execute_task(self, request: dict) -> dict:
        return {"status": "ok", "result": "stub worker executed"}


_mgr: Optional[_SwarmManager] = None
_worker: Optional[_SwarmWorker] = None


async def init_swarm_manager(host="0.0.0.0", port=3000):
    global _mgr
    _mgr = _SwarmManager()
    await _mgr.start(host=host, port=port)


def get_swarm_manager() -> Optional[_SwarmManager]:
    return _mgr


def get_swarm_worker() -> Optional[_SwarmWorker]:
    global _worker
    if _worker is None:
        _worker = _SwarmWorker()
    return _worker
