"""
v3.107 Workflow Engine — DAG工作流引擎

功能:
- DAG工作流定义 (节点+边)
- 条件分支 + 循环
- 并行执行 (基于DAG拓扑的并行调度)
- 可视化导出 (Mermaid格式)

使用示例:
    engine = WorkflowEngine(name="my_workflow")
    engine.add_node("A", lambda: 1 + 1)
    engine.add_node("B", lambda x: x * 2, inputs=["A"])
    engine.add_conditional("C", lambda x: x > 5, "B")
    engine.add_loop("D", lambda x: x - 1, "B", while_condition=lambda x: x > 0)
    engine.add_edge("A", "B")
    result = engine.run()
    print(engine.to_mermaid())
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import traceback
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ══════════════════════════════════════════════════════════════════════════════
# Enums & Data Classes
# ══════════════════════════════════════════════════════════════════════════════

class NodeStatus(Enum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    LOOPING = "looping"


class NodeType(Enum):
    """节点类型"""
    TASK = auto()         # 普通任务节点
    CONDITION = auto()    # 条件分支节点
    LOOP = auto()         # 循环节点
    GATEWAY = auto()      # 汇聚/分发网关


@dataclass
class WorkflowNode:
    """工作流节点定义"""
    id: str
    func: Optional[Callable] = None
    inputs: List[str] = field(default_factory=list)     # 输入依赖的节点ID列表
    outputs: List[str] = field(default_factory=list)    # 输出到的节点ID列表(运行时填充)
    node_type: NodeType = NodeType.TASK
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    timeout: Optional[float] = None       # 节点超时(秒)
    retries: int = 0                      # 失败重试次数
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Conditional fields
    condition_fn: Optional[Callable] = None
    true_branch: Optional[str] = None     # 条件为真时跳转的节点ID
    false_branch: Optional[str] = None    # 条件为假时跳转的节点ID
    # Loop fields
    loop_body: Optional[str] = None       # 循环体入口节点ID
    while_condition: Optional[Callable] = None
    max_iterations: int = 100
    iteration_count: int = 0


@dataclass
class WorkflowEdge:
    """工作流边定义"""
    source: str
    target: str
    label: Optional[str] = None
    condition: Optional[str] = None       # 条件标签: "true"/"false"


@dataclass
class ExecutionContext:
    """执行上下文 — 在run期间持有共享状态"""
    results: Dict[str, Any] = field(default_factory=dict)
    statuses: Dict[str, NodeStatus] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    node_order: List[str] = field(default_factory=list)  # 实际执行顺序
    start_time: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


# ══════════════════════════════════════════════════════════════════════════════
# WorkflowEngine
# ══════════════════════════════════════════════════════════════════════════════

class WorkflowEngine:
    """DAG工作流引擎 — 定义/验证/并行执行/可视化导出"""

    def __init__(self, name: str = "workflow", max_workers: int = 8):
        """
        Args:
            name: 工作流名称
            max_workers: 线程池大小 (并行度)
        """
        self.name = name
        self.max_workers = max_workers
        self._nodes: Dict[str, WorkflowNode] = {}
        self._edges: List[WorkflowEdge] = []
        self._adj_in: Dict[str, List[str]] = defaultdict(list)   # 入边: node -> [predecessors]
        self._adj_out: Dict[str, List[str]] = defaultdict(list)  # 出边: node -> [successors]
        self._ctx: Optional[ExecutionContext] = None

    # ── Node / Edge API ────────────────────────────────────────────────────

    def add_node(
        self,
        node_id: str,
        func: Optional[Callable] = None,
        inputs: Optional[List[str]] = None,
        node_type: NodeType = NodeType.TASK,
        timeout: Optional[float] = None,
        retries: int = 0,
        **metadata,
    ) -> WorkflowNode:
        """添加一个任务节点

        Args:
            node_id: 唯一节点ID
            func: 节点执行函数。可以接受关键字参数(名字=inputs中的节点ID)，
                  也可以接受 **kwargs 接收所有上游输出。
                  如果func是async函数，会被自动用asyncio执行。
            inputs: 依赖的上游节点ID列表
            node_type: 节点类型
            timeout: 超时秒数
            retries: 失败重试次数
        """
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists")
        node = WorkflowNode(
            id=node_id,
            func=func,
            inputs=inputs or [],
            node_type=node_type,
            timeout=timeout,
            retries=retries,
            metadata=metadata,
        )
        self._nodes[node_id] = node
        # Auto-create edges from inputs
        for inp in node.inputs:
            if inp not in self._adj_out:
                self._adj_out[inp] = []
            self._adj_out[inp].append(node_id)
            self._adj_in[node_id].append(inp)
            self._edges.append(WorkflowEdge(source=inp, target=node_id))
        return node

    def add_edge(
        self,
        source: str,
        target: str,
        label: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> WorkflowEdge:
        """添加一条边"""
        if source not in self._nodes:
            raise ValueError(f"Source node '{source}' not found")
        if target not in self._nodes:
            raise ValueError(f"Target node '{target}' not found")
        edge = WorkflowEdge(source=source, target=target, label=label, condition=condition)
        self._edges.append(edge)
        self._adj_out[source].append(target)
        self._adj_in[target].append(source)
        return edge

    def add_conditional(
        self,
        node_id: str,
        condition_fn: Callable,
        source_node: str,
        true_branch: Optional[str] = None,
        false_branch: Optional[str] = None,
    ) -> WorkflowNode:
        """添加条件分支节点

        条件节点本身不产出结果，根据source_node的输出和condition_fn决定流向。

        Args:
            node_id: 条件节点ID
            condition_fn: 条件函数，接受source_node的输出，返回bool
            source_node: 条件判断基于哪个上游节点的输出
            true_branch: 条件为真时流转到的节点ID
            false_branch: 条件为假时流转到的节点ID
        """
        node = WorkflowNode(
            id=node_id,
            condition_fn=condition_fn,
            inputs=[source_node],
            node_type=NodeType.CONDITION,
            true_branch=true_branch,
            false_branch=false_branch,
        )
        self._nodes[node_id] = node
        self._adj_out[source_node].append(node_id)
        self._adj_in[node_id].append(source_node)
        self._edges.append(WorkflowEdge(source=source_node, target=node_id, label="condition"))
        # Add conditional edges
        if true_branch:
            self._edges.append(WorkflowEdge(source=node_id, target=true_branch, condition="true"))
            self._adj_out[node_id].append(true_branch)
            self._adj_in[true_branch].append(node_id)
        if false_branch:
            self._edges.append(WorkflowEdge(source=node_id, target=false_branch, condition="false"))
            self._adj_out[node_id].append(false_branch)
            self._adj_in[false_branch].append(node_id)
        return node

    def add_loop(
        self,
        node_id: str,
        loop_body_fn: Callable,
        source_node: str,
        while_condition: Optional[Callable] = None,
        max_iterations: int = 100,
    ) -> WorkflowNode:
        """添加循环节点

        循环节点重复执行loop_body_fn，直到while_condition为False或达到max_iterations。

        Args:
            node_id: 循环节点ID
            loop_body_fn: 循环体函数。每次迭代接收上一次的输出(首次接收source_node输出)
            source_node: 循环接收哪个上游节点的输出
            while_condition: 终止条件，接收当前输出，返回True则继续循环
            max_iterations: 最大迭代次数(安全上限)
        """
        node = WorkflowNode(
            id=node_id,
            func=loop_body_fn,
            inputs=[source_node],
            node_type=NodeType.LOOP,
            while_condition=while_condition,
            max_iterations=max_iterations,
        )
        self._nodes[node_id] = node
        self._adj_out[source_node].append(node_id)
        self._adj_in[node_id].append(source_node)
        self._edges.append(WorkflowEdge(source=source_node, target=node_id, label="loop_entry"))
        return node

    # ── Query API ──────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        """获取节点"""
        return self._nodes.get(node_id)

    def get_nodes(self) -> List[WorkflowNode]:
        """获取所有节点"""
        return list(self._nodes.values())

    def get_edges(self) -> List[WorkflowEdge]:
        """获取所有边"""
        return list(self._edges)

    def get_predecessors(self, node_id: str) -> List[str]:
        """获取直接前驱节点"""
        return list(self._adj_in.get(node_id, []))

    def get_successors(self, node_id: str) -> List[str]:
        """获取直接后继节点"""
        return list(self._adj_out.get(node_id, []))

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # ── Validation ─────────────────────────────────────────────────────────

    def validate(self) -> Tuple[bool, List[str]]:
        """验证DAG有效性

        Returns:
            (is_valid, errors) — 是否有效 + 错误列表
        """
        errors: List[str] = []

        # 空工作流始终合法
        if not self._nodes:
            return True, []

        # 1. 检查所有边的引用
        for edge in self._edges:
            if edge.source not in self._nodes:
                errors.append(f"Edge source '{edge.source}' not in nodes")
            if edge.target not in self._nodes:
                errors.append(f"Edge target '{edge.target}' not in nodes")

        # 2. 检查入口节点 (没有入边或只有条件边)
        entry_nodes = [nid for nid in self._nodes if not self._adj_in.get(nid)]
        conditional_entries = [
            nid for nid, ins in self._adj_in.items()
            if all(self._nodes[p].node_type == NodeType.CONDITION for p in ins)
        ]
        all_entries = set(entry_nodes + conditional_entries)
        if not all_entries:
            errors.append("No entry node found (no node without non-conditional predecessors)")

        # 3. 检查循环
        has_cycle, cycle_path = self._detect_cycle()
        if has_cycle:
            # 允许由LOOP节点引入的自循环
            cycle_has_loop = any(
                self._nodes[nid].node_type == NodeType.LOOP
                for nid in cycle_path
            )
            if not cycle_has_loop:
                errors.append(f"Cycle detected: {' -> '.join(cycle_path)}")

        # 4. 检查连通性
        if self._nodes and not errors:
            visited = self._bfs_from_entries(all_entries)
            unreachable = set(self._nodes) - visited
            if unreachable and len(unreachable) < len(self._nodes):
                errors.append(f"Unreachable nodes: {unreachable}")

        return len(errors) == 0, errors

    def _detect_cycle(self) -> Tuple[bool, List[str]]:
        """DFS检测环 (忽略LOOP节点的回边)"""
        visited: Set[str] = set()
        in_stack: Set[str] = set()
        path: List[str] = []
        has_cycle = False
        cycle_nodes: List[str] = []

        def dfs(node_id: str):
            nonlocal has_cycle, cycle_nodes
            if has_cycle:
                return
            visited.add(node_id)
            in_stack.add(node_id)
            path.append(node_id)
            for succ in self._adj_out.get(node_id, []):
                if succ in in_stack:
                    has_cycle = True
                    # Extract the cycle
                    try:
                        idx = path.index(succ)
                        cycle_nodes = list(path[idx:]) + [succ]
                    except ValueError:
                        cycle_nodes = list(path) + [succ]
                    return
                if succ not in visited:
                    dfs(succ)
            path.pop()
            in_stack.discard(node_id)

        for nid in self._nodes:
            if nid not in visited:
                dfs(nid)
                if has_cycle:
                    break
        return has_cycle, cycle_nodes

    def _bfs_from_entries(self, entries: Set[str]) -> Set[str]:
        """从入口节点BFS可达集"""
        visited: Set[str] = set()
        queue = deque(entries & set(self._nodes))
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            for succ in self._adj_out.get(nid, []):
                if succ not in visited:
                    queue.append(succ)
        return visited

    def topological_sort(self) -> List[str]:
        """拓扑排序 (忽略CONDITION/LOOP节点的非确定性边)

        Returns:
            拓扑序节点ID列表
        """
        in_degree: Dict[str, int] = {}
        for nid in self._nodes:
            # Only count TASK edges for topological ordering
            task_preds = [
                p for p in self._adj_in.get(nid, [])
                if self._nodes[p].node_type == NodeType.TASK
            ]
            in_degree[nid] = len(task_preds)

        # Entry nodes
        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result: List[str] = []

        while queue:
            nid = queue.popleft()
            result.append(nid)
            for succ in self._adj_out.get(nid, []):
                if succ in in_degree:
                    in_degree[succ] -= 1
                    if in_degree[succ] == 0:
                        queue.append(succ)

        return result

    # ── Execution ──────────────────────────────────────────────────────────

    def run(
        self,
        initial_inputs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """执行工作流

        按DAG拓扑并行执行所有节点。支持条件分支和循环。

        Args:
            initial_inputs: 初始输入 (key=节点ID, value=输入值)
            timeout: 全局超时(秒)

        Returns:
            {node_id: result} — 所有节点的执行结果
        """
        valid, errors = self.validate()
        if not valid:
            raise ValueError(f"Workflow validation failed: {'; '.join(errors)}")

        self._ctx = ExecutionContext()
        ctx = self._ctx
        initial_inputs = initial_inputs or {}

        # Reset all node statuses
        for node in self._nodes.values():
            node.status = NodeStatus.PENDING
            node.result = None
            node.error = None
            node.iteration_count = 0

        global_start = time.time()

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            self._run_dag(pool, ctx, initial_inputs, global_start, timeout)

        # Build results dict
        results = {}
        for nid, node in self._nodes.items():
            results[nid] = node.result
        return results

    def _run_dag(
        self,
        pool: ThreadPoolExecutor,
        ctx: ExecutionContext,
        initial_inputs: Dict[str, Any],
        global_start: float,
        global_timeout: Optional[float],
    ):
        """主DAG执行循环"""
        ready: deque = deque()  # 就绪节点ID队列
        completed: Set[str] = set()
        running_futures: Dict[str, Any] = {}  # node_id -> future
        loop_contexts: Dict[str, Dict[str, Any]] = {}  # 循环状态保持

        def _check_timeout() -> bool:
            if global_timeout and (time.time() - global_start) > global_timeout:
                return True
            return False

        def _predecessors_satisfied(node_id: str) -> bool:
            """检查节点的所有TASK前驱是否已完成"""
            for pred in self._adj_in.get(node_id, []):
                pred_node = self._nodes.get(pred)
                if pred_node is None:
                    continue
                # CONDITION nodes are evaluated inline
                if pred_node.node_type == NodeType.CONDITION:
                    continue
                if pred not in completed:
                    return False
            return True

        def _get_inputs(node_id: str) -> Dict[str, Any]:
            """组装节点输入"""
            node = self._nodes[node_id]
            inputs = {}
            for pred in node.inputs:
                if pred in ctx.results:
                    inputs[pred] = ctx.results[pred]
                elif pred in initial_inputs:
                    inputs[pred] = initial_inputs[pred]
            return inputs

        def _execute_node(node_id: str, inputs: Dict[str, Any]) -> Any:
            """执行单个节点 (同步/异步自适应)"""
            node = self._nodes[node_id]
            if node.func is None:
                return None

            last_error = None
            for attempt in range(node.retries + 1):
                try:
                    # Detect if async
                    if inspect.iscoroutinefunction(node.func):
                        result = asyncio.run(node.func(**inputs))
                    elif callable(node.func):
                        # Try to call with named inputs; fall back to positional
                        sig = inspect.signature(node.func)
                        if len(sig.parameters) == 0:
                            result = node.func()
                        else:
                            result = node.func(**inputs)
                    else:
                        result = None
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < node.retries:
                        time.sleep(0.1 * (attempt + 1))
            raise last_error  # type: ignore[misc]

        # Seed initial ready nodes
        for nid in self._nodes:
            if _predecessors_satisfied(nid):
                ready.append(nid)

        while ready or running_futures:
            if _check_timeout():
                # Cancel all running futures
                for fid in running_futures:
                    node = self._nodes.get(fid)
                    if node:
                        node.status = NodeStatus.FAILED
                        node.error = "Global timeout"
                break

            # Submit ready nodes up to max_workers
            submitted = set()
            while ready and len(running_futures) < self.max_workers:
                nid = ready.popleft()
                if nid in running_futures or nid in completed:
                    continue

                node = self._nodes[nid]
                # Handle CONDITION nodes inline (they are fast)
                if node.node_type == NodeType.CONDITION:
                    self._execute_condition(nid, node, ctx, initial_inputs, completed, ready)
                    continue

                # Handle LOOP nodes
                if node.node_type == NodeType.LOOP:
                    self._execute_loop(nid, node, ctx, initial_inputs, completed, ready)
                    continue

                # Regular TASK node
                inputs = _get_inputs(nid)
                node.status = NodeStatus.RUNNING
                with ctx.lock:
                    ctx.statuses[nid] = NodeStatus.RUNNING
                future = pool.submit(_execute_node, nid, inputs)
                running_futures[nid] = future
                submitted.add(nid)

            # Wait for at least one future to complete
            if running_futures:
                done_futures = set()
                for fid, fut in list(running_futures.items()):
                    try:
                        result = fut.result(timeout=0.1)
                        done_futures.add(fid)
                        node = self._nodes[fid]
                        node.result = result
                        node.status = NodeStatus.COMPLETED
                        with ctx.lock:
                            ctx.results[fid] = result
                            ctx.statuses[fid] = NodeStatus.COMPLETED
                            ctx.node_order.append(fid)
                        completed.add(fid)
                    except TimeoutError:
                        pass  # Still running
                    except Exception as e:
                        done_futures.add(fid)
                        node = self._nodes[fid]
                        node.status = NodeStatus.FAILED
                        node.error = str(e)
                        with ctx.lock:
                            ctx.statuses[fid] = NodeStatus.FAILED
                            ctx.errors[fid] = str(e)
                            ctx.node_order.append(fid)
                        completed.add(fid)

                for fid in done_futures:
                    del running_futures[fid]

                # Enqueue newly ready nodes
                for nid in self._nodes:
                    if nid in completed or nid in running_futures:
                        continue
                    if _predecessors_satisfied(nid):
                        if nid not in ready:
                            ready.append(nid)

    def _execute_condition(
        self,
        nid: str,
        node: WorkflowNode,
        ctx: ExecutionContext,
        initial_inputs: Dict[str, Any],
        completed: Set[str],
        ready: deque,
    ):
        """执行条件分支节点"""
        source_result = None
        for inp in node.inputs:
            source_result = ctx.results.get(inp, initial_inputs.get(inp))
            break  # Take first input

        try:
            cond_result = node.condition_fn(source_result) if node.condition_fn else False
        except Exception:
            cond_result = False

        node.result = cond_result
        node.status = NodeStatus.COMPLETED
        with ctx.lock:
            ctx.results[nid] = cond_result
            ctx.statuses[nid] = NodeStatus.COMPLETED
            ctx.node_order.append(nid)
        completed.add(nid)

        # Route to true/false branch
        target = node.true_branch if cond_result else node.false_branch
        if target and target in self._nodes:
            # Check if target's other predecessors are satisfied
            if self._predecessors_satisfied_ctx(target, completed):
                ready.append(target)

    def _execute_loop(
        self,
        nid: str,
        node: WorkflowNode,
        ctx: ExecutionContext,
        initial_inputs: Dict[str, Any],
        completed: Set[str],
        ready: deque,
    ):
        """执行循环节点 (同步执行，因为是串行迭代)"""
        # Get initial input
        current_value = None
        for inp in node.inputs:
            current_value = ctx.results.get(inp, initial_inputs.get(inp))
            break

        final_value = current_value
        iteration = 0
        node.status = NodeStatus.LOOPING

        while iteration < node.max_iterations:
            # Check while condition
            if node.while_condition:
                try:
                    should_continue = node.while_condition(current_value)
                except Exception:
                    should_continue = False
                if not should_continue:
                    break

            # Execute loop body
            try:
                if node.func:
                    if inspect.iscoroutinefunction(node.func):
                        new_value = asyncio.run(node.func(current_value))
                    else:
                        sig = inspect.signature(node.func)
                        if len(sig.parameters) == 0:
                            new_value = node.func()
                        elif len(sig.parameters) == 1:
                            new_value = node.func(current_value)
                        else:
                            new_value = node.func(current_value)
                    current_value = new_value
                    final_value = new_value
            except Exception as e:
                node.status = NodeStatus.FAILED
                node.error = str(e)
                node.iteration_count = iteration
                with ctx.lock:
                    ctx.statuses[nid] = NodeStatus.FAILED
                    ctx.errors[nid] = str(e)
                    ctx.node_order.append(nid)
                completed.add(nid)
                return

            iteration += 1
            node.iteration_count = iteration

        node.result = final_value
        node.status = NodeStatus.COMPLETED
        node.iteration_count = iteration
        with ctx.lock:
            ctx.results[nid] = final_value
            ctx.statuses[nid] = NodeStatus.COMPLETED
            ctx.node_order.append(nid)
        completed.add(nid)

        # Enqueue dependent nodes
        for succ in self._adj_out.get(nid, []):
            if succ not in completed and self._predecessors_satisfied_ctx(succ, completed):
                ready.append(succ)

    def _predecessors_satisfied_ctx(self, node_id: str, completed: Set[str]) -> bool:
        """检查节点的所有TASK前驱是否已完成 (使用completed集合)"""
        for pred in self._adj_in.get(node_id, []):
            pred_node = self._nodes.get(pred)
            if pred_node is None:
                continue
            if pred_node.node_type == NodeType.CONDITION:
                # CONDITION must also be completed
                if pred not in completed:
                    return False
                # Check if this node is actually the routed target
                cond = pred_node
                actual_target = cond.true_branch if cond.result else cond.false_branch
                if actual_target != node_id:
                    return False  # Not routed here, skip
            elif pred not in completed:
                return False
        return True

    def run_async(self, initial_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """同步包装器 (非阻塞调用)"""
        return self.run(initial_inputs=initial_inputs)

    # ── Visualization (Mermaid) ────────────────────────────────────────────

    def to_mermaid(
        self,
        direction: str = "TD",
        show_status: bool = False,
        show_inputs: bool = False,
    ) -> str:
        """导出为Mermaid流程图

        Args:
            direction: 图方向 (TD=上到下, LR=左到右, BT=下到上, RL=右到左)
            show_status: 是否显示节点状态
            show_inputs: 是否显示输入依赖

        Returns:
            Mermaid格式的流程图字符串
        """
        lines = [f"```mermaid", f"graph {direction}"]

        # Node shape mapping (use {label} for the display text)
        shape_map = {
            NodeType.TASK: "(({label}))",
            NodeType.CONDITION: "{{{label}}}",
            NodeType.LOOP: "[\\{label}/]",
            NodeType.GATEWAY: ">{label}]",
        }

        # Define nodes
        for nid, node in self._nodes.items():
            shape = shape_map.get(node.node_type, "({label})")
            label = nid
            extras = []
            if show_status:
                extras.append(node.status.value)
            if show_inputs and node.inputs:
                extras.append(f"in:{','.join(node.inputs)}")
            if node.node_type == NodeType.LOOP:
                extras.append(f"iter={node.iteration_count}/{node.max_iterations}")
            if node.node_type == NodeType.CONDITION and node.condition_fn:
                extras.append("?")
            if extras:
                label += f"\\n[{', '.join(extras)}]"

            # Mermaid-safe escaping
            label = label.replace('"', '\\"')
            shape_filled = shape.format(label=label)
            lines.append(f"    {nid}{shape_filled}")
            # Style
            if node.status == NodeStatus.COMPLETED:
                lines.append(f"    style {nid} fill:#4caf50,stroke:#2e7d32,color:#fff")
            elif node.status == NodeStatus.FAILED:
                lines.append(f"    style {nid} fill:#f44336,stroke:#b71c1c,color:#fff")
            elif node.status == NodeStatus.RUNNING:
                lines.append(f"    style {nid} fill:#2196f3,stroke:#0d47a1,color:#fff")
            elif node.status == NodeStatus.SKIPPED:
                lines.append(f"    style {nid} fill:#9e9e9e,stroke:#616161,color:#fff")
            elif node.status == NodeStatus.LOOPING:
                lines.append(f"    style {nid} fill:#ff9800,stroke:#e65100,color:#fff")

        # Define edges
        for edge in self._edges:
            arrow = "-->"
            if edge.condition == "true":
                arrow = "-- True -->"
            elif edge.condition == "false":
                arrow = "-- False -->"
            elif edge.label:
                arrow = f'-- "{edge.label}" -->'

            lines.append(f"    {edge.source} {arrow} {edge.target}")

        lines.append("```")
        return "\n".join(lines)

    def to_mermaid_raw(self, direction: str = "TD") -> str:
        """导出纯Mermaid代码 (不含markdown代码块)

        Args:
            direction: 图方向

        Returns:
            纯Mermaid格式字符串 (可嵌入.mmd文件或渲染器)
        """
        md = self.to_mermaid(direction=direction)
        # Strip ```mermaid and ```
        lines = md.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (仅结构，不含函数)"""
        return {
            "name": self.name,
            "nodes": {
                nid: {
                    "id": node.id,
                    "inputs": node.inputs,
                    "node_type": node.node_type.name,
                    "timeout": node.timeout,
                    "retries": node.retries,
                    "max_iterations": node.max_iterations,
                    "metadata": node.metadata,
                }
                for nid, node in self._nodes.items()
            },
            "edges": [
                {"source": e.source, "target": e.target, "label": e.label, "condition": e.condition}
                for e in self._edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], node_funcs: Optional[Dict[str, Callable]] = None) -> "WorkflowEngine":
        """从字典反序列化 (需要提供函数映射)

        Args:
            data: to_dict()的输出
            node_funcs: {node_id: callable} 节点函数映射
        """
        engine = cls(name=data.get("name", "workflow"))
        node_funcs = node_funcs or {}

        for nid, ndata in data.get("nodes", {}).items():
            ntype = NodeType[ndata.get("node_type", "TASK")]
            engine.add_node(
                node_id=nid,
                func=node_funcs.get(nid),
                inputs=ndata.get("inputs", []),
                node_type=ntype,
                timeout=ndata.get("timeout"),
                retries=ndata.get("retries", 0),
                **ndata.get("metadata", {}),
            )

        for edata in data.get("edges", []):
            source, target = edata["source"], edata["target"]
            if source in engine._nodes and target in engine._nodes:
                engine.add_edge(
                    source=source,
                    target=target,
                    label=edata.get("label"),
                    condition=edata.get("condition"),
                )

        return engine

    def __repr__(self) -> str:
        return f"WorkflowEngine(name='{self.name}', nodes={self.node_count}, edges={self.edge_count})"


# ══════════════════════════════════════════════════════════════════════════════
# Singleton access
# ══════════════════════════════════════════════════════════════════════════════

_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine(name: str = "default", max_workers: int = 8) -> WorkflowEngine:
    """获取或创建全局单例WorkflowEngine"""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine(name=name, max_workers=max_workers)
    return _workflow_engine


def reset_workflow_engine():
    """重置全局单例"""
    global _workflow_engine
    _workflow_engine = None
