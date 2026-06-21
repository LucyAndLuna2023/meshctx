"""meshctx workflow_engine — v3.107 DAG Workflow Engine"""

import asyncio
import inspect
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class NodeStatus(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    LOOPING = "looping"


class NodeType(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    TASK = "task"
    CONDITION = "condition"
    LOOP = "loop"
    GATEWAY = "gateway"


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowNode:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    id: str
    func: Optional[Callable] = None
    inputs: List[str] = field(default_factory=list)
    type: NodeType = NodeType.TASK
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    iteration_count: int = 0
    retries: int = 0
    _max_retries: int = 0


@dataclass
class WorkflowEdge:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    source: str
    target: str
    label: Optional[str] = None


@dataclass
class ExecutionContext:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    variables: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# WorkflowEngine
# ═══════════════════════════════════════════════════════════════

@dataclass
class _ConditionalDef:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    source_node: str
    condition_fn: Callable
    true_branch: str
    false_branch: str


@dataclass
class _LoopDef:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    source_node: str
    loop_body_fn: Callable
    while_condition: Optional[Callable] = None
    max_iterations: int = 100


class WorkflowEngine:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """DAG-based workflow execution engine."""

    def __init__(self, name: str = "workflow", max_workers: int = 8, **kw):
        self.name = name
        self.max_workers = max_workers
        self._nodes: Dict[str, WorkflowNode] = {}
        self._edges: List[WorkflowEdge] = []
        self._conditionals: Dict[str, _ConditionalDef] = {}
        self._loops: Dict[str, _LoopDef] = {}

    # ── Construction ──────────────────────────────────────────

    @property
    def node_count(self, **kw) -> int:
        return len(self._nodes)

    @property
    def edge_count(self, **kw) -> int:
        return len(self._edges)

    def add_node(
        self,
        node_id: str,
        func: Optional[Callable] = None,
        inputs: Optional[List[str]] = None,
        retries: int = 0,
    ) -> WorkflowNode:
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists")
        node = WorkflowNode(
            id=node_id,
            func=func,
            inputs=inputs or [],
            _max_retries=retries,
            retries=retries,
        )
        self._nodes[node_id] = node
        # Auto-create edges from inputs
        if inputs:
            for src in inputs:
                self._edges.append(WorkflowEdge(source=src, target=node_id))
        return node

    def add_edge(self, source: str, target: str, label: Optional[str] = None, **kw):
        self._edges.append(WorkflowEdge(source=source, target=target, label=label))

    def add_conditional(
        self,
        node_id: str,
        condition_fn: Callable,
        source_node: str,
        true_branch: str,
        false_branch: str,
    ):
        self._conditionals[node_id] = _ConditionalDef(
            source_node=source_node,
            condition_fn=condition_fn,
            true_branch=true_branch,
            false_branch=false_branch,
        )
        self._nodes[node_id] = WorkflowNode(
            id=node_id,
            type=NodeType.CONDITION,
        )
        # Edges: source → conditional, conditional → branches
        self._edges.append(WorkflowEdge(source=source_node, target=node_id))
        self._edges.append(WorkflowEdge(source=node_id, target=true_branch, label="True"))
        self._edges.append(WorkflowEdge(source=node_id, target=false_branch, label="False"))

    def add_loop(
        self,
        node_id: str,
        loop_body_fn: Callable,
        source_node: str,
        while_condition: Optional[Callable] = None,
        max_iterations: int = 100,
    ):
        self._loops[node_id] = _LoopDef(
            source_node=source_node,
            loop_body_fn=loop_body_fn,
            while_condition=while_condition,
            max_iterations=max_iterations,
        )
        self._nodes[node_id] = WorkflowNode(
            id=node_id,
            type=NodeType.LOOP,
        )
        self._edges.append(WorkflowEdge(source=source_node, target=node_id))

    # ── Query ─────────────────────────────────────────────────

    def get_node(self, node_id: str, **kw) -> Optional[WorkflowNode]:
        return self._nodes.get(node_id)

    def get_predecessors(self, node_id: str, **kw) -> List[str]:
        return [e.source for e in self._edges if e.target == node_id]

    def get_successors(self, node_id: str, **kw) -> List[str]:
        return [e.target for e in self._edges if e.source == node_id]

    # ── Validation ────────────────────────────────────────────

    def validate(self, **kw) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # Check for cycles
        if self._has_cycle():
            errors.append("Cycle detected in workflow graph")

        # Check all edge targets exist (if not conditional/loop)
        for edge in self._edges:
            if edge.target not in self._nodes:
                errors.append(f"Edge target '{edge.target}' not found")
            if edge.source not in self._nodes:
                # Source might be a conditional/loop
                if edge.source not in self._conditionals and edge.source not in self._loops:
                    errors.append(f"Edge source '{edge.source}' not found")

        return len(errors) == 0, errors

    def _has_cycle(self, **kw) -> bool:
        """DFS cycle detection."""
        WHITE, GRAY, BLACK = 0, 1, 2
        colors: Dict[str, int] = {nid: WHITE for nid in self._nodes}

        def dfs(nid: str, **kw) -> bool:
            colors[nid] = GRAY
            for succ in self.get_successors(nid):
                if succ not in colors:
                    continue
                if colors[succ] == GRAY:
                    return True
                if colors[succ] == WHITE and dfs(succ):
                    return True
            colors[nid] = BLACK
            return False

        for nid in self._nodes:
            if colors[nid] == WHITE and dfs(nid):
                return True
        return False

    def topological_sort(self, **kw) -> List[str]:
        """Return nodes in topological order."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for edge in self._edges:
            if edge.target in in_degree:
                in_degree[edge.target] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for succ in self.get_successors(nid):
                if succ in in_degree:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        queue.append(succ)

        # Add any remaining nodes not reached (e.g. disconnected)
        for nid in self._nodes:
            if nid not in result:
                result.append(nid)

        return result

    # ── Execution ─────────────────────────────────────────────

    def run(self, **kw) -> Dict[str, Any]:
        """Execute the workflow DAG."""
        valid, errors = self.validate()
        if not valid:
            raise ValueError(f"Workflow validation failed: {'; '.join(errors)}")

        # Reset all nodes
        for node in self._nodes.values():
            node.status = NodeStatus.PENDING
            node.result = None
            node.error = None
            node.iteration_count = 0

        results: Dict[str, Any] = {}
        completed: Set[str] = set()

        # Process nodes in topological order, with parallel execution
        # for nodes at the same depth
        order = self.topological_sort()

        # Build dependency graph: node → nodes that depend on it
        dependents: Dict[str, Set[str]] = {}
        for edge in self._edges:
            if edge.target in self._nodes:
                dependents.setdefault(edge.source, set()).add(edge.target)

        # Ready queue: nodes whose inputs are all satisfied
        # Exclude conditional/loop nodes — they are triggered by their source nodes.
        # All inputs (including conditionals/loops) must be in completed.
        ready: List[str] = [
            nid for nid in order
            if nid not in self._conditionals and nid not in self._loops
            and all(
                src in completed
                for src in self._nodes[nid].inputs
            )
        ]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while ready:
                # Submit all ready nodes in parallel
                futures: Dict[Any, str] = {}
                for nid in ready:
                    futures[executor.submit(self._execute_node, nid, results)] = nid

                ready = []

                for future in as_completed(futures):
                    nid = futures[future]
                    result = None
                    try:
                        result = future.result()
                        results[nid] = result
                    except Exception:
                        results[nid] = None

                    node = self._nodes[nid]
                    if node.status == NodeStatus.COMPLETED:
                        completed.add(nid)
                        # Check which dependent nodes become ready
                        for dep in dependents.get(nid, set()):
                            dep_node = self._nodes[dep]
                            if all(
                                src in completed
                                for src in dep_node.inputs
                            ):
                                if dep not in ready and dep_node.status == NodeStatus.PENDING:
                                    ready.append(dep)

                    # Handle conditionals that point to this node
                    for cid, cdef in self._conditionals.items():
                        if cdef.source_node == nid and cid not in completed:
                            cnode = self._nodes[cid]
                            if cnode.status == NodeStatus.PENDING:
                                try:
                                    cond_result = cdef.condition_fn(result)
                                except Exception as e:
                                    cnode.status = NodeStatus.FAILED
                                    cnode.error = str(e)
                                    cond_result = False
                                cnode.result = cond_result
                                cnode.status = NodeStatus.COMPLETED
                                completed.add(cid)
                                results[cid] = cond_result

                                # Activate the chosen branch
                                chosen = cdef.true_branch if cond_result else cdef.false_branch
                                if chosen in self._nodes:
                                    branch_node = self._nodes[chosen]
                                    if all(
                                        src in completed
                                        for src in branch_node.inputs
                                    ):
                                        if chosen not in ready and branch_node.status == NodeStatus.PENDING:
                                            ready.append(chosen)

                    # Handle loops that source from this node
                    for lid, ldef in self._loops.items():
                        if ldef.source_node == nid and lid not in completed:
                            lnode = self._nodes[lid]
                            if lnode.status == NodeStatus.PENDING:
                                lnode.status = NodeStatus.LOOPING
                                # Execute loop
                                val = result
                                for i in range(ldef.max_iterations):
                                    lnode.iteration_count = i + 1
                                    try:
                                        if inspect.iscoroutinefunction(ldef.loop_body_fn):
                                            val = asyncio.get_event_loop().run_until_complete(
                                                ldef.loop_body_fn(val)
                                            )
                                        else:
                                            val = ldef.loop_body_fn(val)
                                    except Exception as e:
                                        lnode.status = NodeStatus.FAILED
                                        lnode.error = str(e)
                                        break
                                    if ldef.while_condition and not ldef.while_condition(val):
                                        break
                                else:
                                    # Reached max_iterations
                                    pass
                                if lnode.status == NodeStatus.LOOPING:
                                    lnode.status = NodeStatus.COMPLETED
                                lnode.result = val
                                completed.add(lid)
                                results[lid] = val

                                # Activate dependents
                                for dep in dependents.get(lid, set()):
                                    dep_node = self._nodes[dep]
                                    if all(
                                        src in completed
                                        for src in dep_node.inputs
                                    ):
                                        if dep not in ready and dep_node.status == NodeStatus.PENDING:
                                            ready.append(dep)

        return results

    def _execute_node(self, node_id: str, previous_results: Dict[str, Any], **kw) -> Any:
        """Execute a single node with retries."""
        node = self._nodes[node_id]
        if node.func is None:
            node.status = NodeStatus.COMPLETED
            node.result = None
            return None

        # Build kwargs from input dependencies
        kwargs = {}
        for inp in node.inputs:
            if inp in previous_results:
                kwargs[inp] = previous_results[inp]

        remaining_retries = node._max_retries
        while True:
            node.status = NodeStatus.RUNNING
            try:
                if inspect.iscoroutinefunction(node.func):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(
                            node.func(**kwargs) if kwargs else node.func()
                        )
                    finally:
                        loop.close()
                elif inspect.signature(node.func).parameters:
                    result = node.func(**kwargs)
                else:
                    result = node.func()
                node.result = result
                node.status = NodeStatus.COMPLETED
                return result
            except Exception as e:
                if remaining_retries > 0:
                    remaining_retries -= 1
                    time.sleep(0.01)
                    continue
                node.status = NodeStatus.FAILED
                node.error = str(e)
                node.result = None
                return None

    # ── Mermaid Visualization ─────────────────────────────────

    def to_mermaid(self, direction: str = "TD", show_status: bool = False, **kw) -> str:
        lines = ["```mermaid", f"graph {direction}"]
        for node in self._nodes.values():
            label = node.id
            if show_status and node.status != NodeStatus.PENDING:
                label += f"[{node.status.value}]"
            if node.type == NodeType.CONDITION:
                label = f"{{{label}}}"
            lines.append(f"    {node.id}[{label}]")

        for edge in self._edges:
            arrow = f"{edge.source} -->"
            if edge.label:
                arrow += f"|{edge.label}|"
            arrow += f" {edge.target}"
            lines.append(f"    {arrow}")

        # Add conditional labels
        for cid, cdef in self._conditionals.items():
            lines.append(f"    {cid} -->|True| {cdef.true_branch}")
            lines.append(f"    {cid} -->|False| {cdef.false_branch}")

        # Add loop labels
        for lid, ldef in self._loops.items():
            lines.append(
                f"    {lid}[{lid}<br/>iter={self._nodes[lid].iteration_count}]"
            )

        lines.append("```")
        return "\n".join(lines)

    def to_mermaid_raw(self, direction: str = "TD", **kw) -> str:
        md = self.to_mermaid(direction=direction)
        # Strip ```mermaid and final ```
        lines = md.split("\n")
        return "\n".join(lines[1:-1])

    # ── Serialization ─────────────────────────────────────────

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "name": self.name,
            "max_workers": self.max_workers,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "inputs": n.inputs,
                    "retries": n._max_retries,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target, "label": e.label}
                for e in self._edges
            ],
            "conditionals": {
                cid: {
                    "source_node": cd.source_node,
                    "true_branch": cd.true_branch,
                    "false_branch": cd.false_branch,
                }
                for cid, cd in self._conditionals.items()
            },
            "loops": {
                lid: {
                    "source_node": ld.source_node,
                    "max_iterations": ld.max_iterations,
                }
                for lid, ld in self._loops.items()
            },
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], node_funcs: Optional[Dict[str, Callable]] = None
    ) -> "WorkflowEngine":
        engine = cls(name=data.get("name", "workflow"), max_workers=data.get("max_workers", 8))
        node_funcs = node_funcs or {}

        for ndata in data.get("nodes", []):
            nid = ndata["id"]
            ntype = NodeType(ndata["type"])
            func = node_funcs.get(nid)
            engine._nodes[nid] = WorkflowNode(
                id=nid,
                func=func,
                inputs=ndata.get("inputs", []),
                type=ntype,
                _max_retries=ndata.get("retries", 0),
                retries=ndata.get("retries", 0),
            )

        for edata in data.get("edges", []):
            engine._edges.append(WorkflowEdge(
                source=edata["source"],
                target=edata["target"],
                label=edata.get("label"),
            ))

        # Reconstruct conditionals
        for cid, cdata in data.get("conditionals", {}).items():
            # The conditional func needs to be provided by caller in node_funcs
            cond_fn = node_funcs.get(cid)
            engine._conditionals[cid] = _ConditionalDef(
                source_node=cdata["source_node"],
                condition_fn=cond_fn if cond_fn else (lambda x: True),
                true_branch=cdata["true_branch"],
                false_branch=cdata["false_branch"],
            )
            if cid not in engine._nodes:
                engine._nodes[cid] = WorkflowNode(id=cid, type=NodeType.CONDITION)

        for lid, ldata in data.get("loops", {}).items():
            loop_fn = node_funcs.get(lid)
            engine._loops[lid] = _LoopDef(
                source_node=ldata["source_node"],
                loop_body_fn=loop_fn if loop_fn else (lambda x: x),
                max_iterations=ldata.get("max_iterations", 100),
            )
            if lid not in engine._nodes:
                engine._nodes[lid] = WorkflowNode(id=lid, type=NodeType.LOOP)

        return engine

    # ── Repr ──────────────────────────────────────────────────

    def __repr__(self, **kw) -> str:
        return f"WorkflowEngine(name={self.name!r}, nodes={self.node_count}, edges={self.edge_count})"


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_workflow_engine_instance: Optional[WorkflowEngine] = None


def get_workflow_engine(name: Optional[str] = None) -> WorkflowEngine:
    global _workflow_engine_instance
    if _workflow_engine_instance is None:
        _workflow_engine_instance = WorkflowEngine(name=name or "default")
    return _workflow_engine_instance


def reset_workflow_engine():
    global _workflow_engine_instance
    _workflow_engine_instance = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

