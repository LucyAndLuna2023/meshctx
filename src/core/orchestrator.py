"""
meshctx Multi-Agent Orchestrator (v3.115.16)
Task DAG decomposition → parallel execution → dependency resolution.
Real implementation per iron law.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import asyncio
import logging
import threading
import time
import uuid

logger = logging.getLogger("meshctx.orchestrator")


class TaskNodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentRole(str, Enum):
    CODER = "coder"
    RESEARCHER = "researcher"
    DEVOPS = "devops"
    REVIEWER = "reviewer"
    GENERAL = "general"


@dataclass
class TaskNode:
    """A single task in the DAG."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    role: AgentRole = AgentRole.GENERAL
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    dependencies: Set[str] = field(default_factory=set)
    result: Any = None
    error: Optional[str] = None
    assigned_agent: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    max_retries: int = 2


@dataclass
class AgentInstance:
    """An agent in the pool."""
    agent_id: str
    role: AgentRole
    busy: bool = False
    current_task: Optional[str] = None
    tasks_completed: int = 0
    tasks_failed: int = 0


class AgentPool:
    """Pool of specialized agents."""
    
    def __init__(self):
        self.agents: Dict[str, AgentInstance] = {}
        self._lock = threading.Lock()
    
    def add_agent(self, role: AgentRole) -> AgentInstance:
        aid = f"{role.value}-{str(uuid.uuid4())[:6]}"
        agent = AgentInstance(agent_id=aid, role=role)
        with self._lock:
            self.agents[aid] = agent
        return agent
    
    def get_available(self, role: AgentRole = None) -> Optional[AgentInstance]:
        with self._lock:
            for a in self.agents.values():
                if not a.busy and (role is None or a.role == role):
                    return a
        return None
    
    def assign(self, agent_id: str, task_id: str):
        with self._lock:
            if agent_id in self.agents:
                self.agents[agent_id].busy = True
                self.agents[agent_id].current_task = task_id
    
    def release(self, agent_id: str, success: bool):
        with self._lock:
            if agent_id in self.agents:
                a = self.agents[agent_id]
                a.busy = False
                a.current_task = None
                if success:
                    a.tasks_completed += 1
                else:
                    a.tasks_failed += 1
    
    @property
    def available_count(self) -> int:
        return sum(1 for a in self.agents.values() if not a.busy)
    
    @property
    def total(self) -> int:
        return len(self.agents)
    
    def by_role(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for a in self.agents.values():
            result[a.role.value] = result.get(a.role.value, 0) + 1
        return result


class TaskDAG:
    """Directed Acyclic Graph of tasks with dependency resolution."""
    
    def __init__(self, dag_id: str = None):
        self.dag_id = dag_id or str(uuid.uuid4())[:8]
        self.nodes: Dict[str, TaskNode] = {}
        self._execution_order: List[str] = []
        self._lock = threading.Lock()
        self.created_at = time.time()
    
    def add_task(self, description: str, role: AgentRole = AgentRole.GENERAL,
                 depends_on: List[str] = None) -> TaskNode:
        # v3.118.0: resource gate
        try:
            from .resource_manager import get_resource_manager
            ok, reason = get_resource_manager().pre_task()
            if not ok:
                raise RuntimeError(f"System overloaded — task rejected: {reason}")
        except Exception:
            pass
        node = TaskNode(description=description, role=role)
        if depends_on:
            node.dependencies = set(depends_on)
        with self._lock:
            self.nodes[node.task_id] = node
        return node
    
    def add_dependency(self, task_id: str, depends_on: str):
        with self._lock:
            if task_id in self.nodes and depends_on in self.nodes:
                self.nodes[task_id].dependencies.add(depends_on)
    
    def ready_tasks(self) -> List[TaskNode]:
        """Get tasks whose dependencies are all satisfied."""
        with self._lock:
            ready = []
            for node in self.nodes.values():
                if node.status != TaskNodeStatus.PENDING:
                    continue
                deps_met = all(
                    self.nodes[dep].status == TaskNodeStatus.COMPLETED
                    for dep in node.dependencies
                    if dep in self.nodes
                )
                if deps_met:
                    ready.append(node)
            return ready
    
    def topological_order(self) -> List[str]:
        """Kahn's algorithm for topological sort."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        
        for nid, node in self.nodes.items():
            for dep in node.dependencies:
                if dep in self.nodes:
                    adj[dep].append(nid)
                    in_degree[nid] = in_degree.get(nid, 0) + 1
        
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []
        
        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return order if len(order) == len(self.nodes) else []
    
    def is_complete(self) -> bool:
        return all(
            n.status in (TaskNodeStatus.COMPLETED, TaskNodeStatus.FAILED, TaskNodeStatus.SKIPPED)
            for n in self.nodes.values()
        )
    
    def stats(self) -> dict:
        completed = sum(1 for n in self.nodes.values() if n.status == TaskNodeStatus.COMPLETED)
        failed = sum(1 for n in self.nodes.values() if n.status == TaskNodeStatus.FAILED)
        return {
            "dag_id": self.dag_id,
            "total": len(self.nodes),
            "completed": completed,
            "failed": failed,
            "pending": sum(1 for n in self.nodes.values() if n.status == TaskNodeStatus.PENDING),
            "running": sum(1 for n in self.nodes.values() if n.status == TaskNodeStatus.RUNNING),
        }


class MemoryHub:
    """Shared memory hub for inter-agent communication."""
    
    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._namespaces: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._snapshots: List[Dict] = []
    
    def put(self, key: str, value: Any, namespace: str = "default"):
        with self._lock:
            if namespace not in self._namespaces:
                self._namespaces[namespace] = {}
            self._namespaces[namespace][key] = value
            self._notify(f"{namespace}:{key}", value)
    
    def get(self, key: str, namespace: str = "default") -> Optional[Any]:
        return self._namespaces.get(namespace, {}).get(key)
    
    def subscribe(self, pattern: str, callback: Callable[[str, Any], None]):
        with self._lock:
            self._subscribers.setdefault(pattern, []).append(callback)
    
    def _notify(self, key: str, value: Any):
        for pattern, callbacks in self._subscribers.items():
            if pattern in key or pattern == "*":
                for cb in callbacks:
                    try:
                        cb(key, value)
                    except Exception as e:
                        logger.debug(f"Subscriber error: {e}")
    
    def snapshot(self) -> dict:
        with self._lock:
            snap = {"namespaces": {
                ns: dict(data) for ns, data in self._namespaces.items()
            }}
            self._snapshots.append(snap)
            if len(self._snapshots) > 100:
                self._snapshots = self._snapshots[-50:]
            return snap
    
    def stats(self) -> dict:
        return {
            "total_keys": sum(len(d) for d in self._namespaces.values()),
            "namespaces": len(self._namespaces),
            "subscribers": len(self._subscribers),
            "snapshots": len(self._snapshots),
        }


class TaskDecomposer:
    """Decompose complex intents into task DAGs."""
    
    _ROLE_KEYWORDS = {
        AgentRole.CODER: ["code", "implement", "build", "fix", "debug", "refactor", "test"],
        AgentRole.RESEARCHER: ["research", "analyze", "find", "search", "investigate", "compare"],
        AgentRole.DEVOPS: ["deploy", "install", "configure", "setup", "docker", "server"],
        AgentRole.REVIEWER: ["review", "audit", "check", "validate", "verify", "inspect"],
    }
    
    def decompose(self, intent: str) -> TaskDAG:
        """Decompose an intent into a task DAG based on keywords."""
        dag = TaskDAG()
        intent_lower = intent.lower()
        
        # Detect phases
        phases = []
        for marker in ["first", "then", "after", "finally", "step 1", "step 2", "step 3"]:
            if marker in intent_lower:
                idx = intent_lower.index(marker)
                phases.append(idx)
        
        if phases:
            # Sequential phases
            parts = []
            sorted_phases = sorted(phases)
            for i, idx in enumerate(sorted_phases):
                end = sorted_phases[i+1] if i+1 < len(sorted_phases) else len(intent)
                parts.append(intent[idx:end].strip(" ,;"))
            
            prev_id = None
            for part in parts:
                role = self._infer_role(part)
                node = dag.add_task(part[:100], role=role,
                                     depends_on=[prev_id] if prev_id else None)
                prev_id = node.task_id
        else:
            # Single task
            role = self._infer_role(intent)
            dag.add_task(intent[:100], role=role)
        
        return dag
    
    def _infer_role(self, text: str) -> AgentRole:
        text_lower = text.lower()
        scores = {}
        for role, keywords in self._ROLE_KEYWORDS.items():
            scores[role] = sum(1 for kw in keywords if kw in text_lower)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else AgentRole.GENERAL


class Orchestrator:
    """Multi-agent orchestrator — DAG decomposition + parallel execution."""
    
    def __init__(self, max_concurrency: int = 10):
        self.agent_pool = AgentPool()
        self.memory_hub = MemoryHub()
        self.decomposer = TaskDecomposer()
        self.max_concurrency = max_concurrency
        self._active_dags: Dict[str, TaskDAG] = {}
        self._dag_history: List[Dict] = []
        self._lock = threading.Lock()
        self._total_tasks = 0
        self._total_failed = 0
        self._total_retried = 0
        self._total_latency_ms = 0.0
        self._started_at = time.time()
        
        # Initialize agent pool
        for role in AgentRole:
            self.agent_pool.add_agent(role)
            self.agent_pool.add_agent(role)
    
    def create_dag(self, intent: str) -> TaskDAG:
        """Decompose intent and create a task DAG."""
        dag = self.decomposer.decompose(intent)
        with self._lock:
            self._active_dags[dag.dag_id] = dag
        return dag
    
    async def execute_dag(self, dag: TaskDAG,
                          executor: Callable[[TaskNode], Any] = None) -> Dict[str, Any]:
        """Execute a task DAG with parallel execution of ready tasks."""
        order = dag.topological_order()
        self._total_tasks += len(dag.nodes)
        start = time.time()
        
        sem = asyncio.Semaphore(self.max_concurrency)
        
        async def run_task(node: TaskNode):
            async with sem:
                # Wait for dependencies
                for dep_id in node.dependencies:
                    if dep_id in dag.nodes:
                        dep_node = dag.nodes[dep_id]
                        while dep_node.status == TaskNodeStatus.PENDING or \
                              dep_node.status == TaskNodeStatus.RUNNING:
                            await asyncio.sleep(0.1)
                        if dep_node.status == TaskNodeStatus.FAILED:
                            node.status = TaskNodeStatus.SKIPPED
                            return
                
                # Assign agent
                agent = self.agent_pool.get_available(node.role) or \
                        self.agent_pool.get_available()
                if not agent:
                    node.status = TaskNodeStatus.FAILED
                    node.error = "No available agent"
                    return
                
                self.agent_pool.assign(agent.agent_id, node.task_id)
                node.assigned_agent = agent.agent_id
                node.status = TaskNodeStatus.RUNNING
                node.started_at = time.time()
                
                try:
                    if executor:
                        result = executor(node)
                        if asyncio.iscoroutine(result):
                            result = await result
                        node.result = result
                    else:
                        # Simulated execution
                        await asyncio.sleep(0.1)
                        node.result = f"Completed: {node.description[:50]}"
                    
                    node.status = TaskNodeStatus.COMPLETED
                    self.agent_pool.release(agent.agent_id, True)
                    
                    # Share to memory hub
                    self.memory_hub.put(node.task_id, node.result,
                                        namespace=dag.dag_id)
                    
                except Exception as e:
                    node.retries += 1
                    if node.retries <= node.max_retries:
                        self._total_retried += 1
                        node.status = TaskNodeStatus.PENDING
                        node.error = str(e)
                    else:
                        node.status = TaskNodeStatus.FAILED
                        node.error = str(e)
                        self._total_failed += 1
                    self.agent_pool.release(agent.agent_id, False)
                
                node.completed_at = time.time()
        
        # Execute all tasks
        tasks = [run_task(dag.nodes[nid]) for nid in order]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = (time.time() - start) * 1000
        self._total_latency_ms += elapsed
        
        # Archive
        stats = dag.stats()
        self._dag_history.append(stats)
        if len(self._dag_history) > 500:
            self._dag_history = self._dag_history[-250:]
        
        return {"dag_id": dag.dag_id, "stats": stats, "elapsed_ms": elapsed}
    
    def execute_sync(self, intent: str) -> Dict[str, Any]:
        """Synchronous wrapper for simple use cases."""
        dag = self.create_dag(intent)
        return asyncio.run(self.execute_dag(dag))
    
    def stats(self) -> dict:
        total_tasks_done = self._total_tasks - \
            sum(1 for n in self._active_dags.values() 
                for t in n.nodes.values() if t.status == TaskNodeStatus.PENDING)
        return {
            "orchestrator": {
                "uptime_sec": time.time() - self._started_at,
                "max_concurrency": self.max_concurrency,
                "active_dags": len(self._active_dags),
            },
            "execution": {
                "total_tasks_executed": self._total_tasks,
                "total_tasks_failed": self._total_failed,
                "total_tasks_retried": self._total_retried,
                "avg_latency_ms": round(self._total_latency_ms / max(1, self._total_tasks), 1),
                "success_rate": round(1 - self._total_failed / max(1, self._total_tasks), 3),
            },
            "agent_pool": {
                "total": self.agent_pool.total,
                "available": self.agent_pool.available_count,
                "by_role": self.agent_pool.by_role(),
            },
            "memory_hub": self.memory_hub.stats(),
            "dag_history": len(self._dag_history),
        }
