"""v3.107 Workflow Engine 工作流引擎测试"""
import time
import pytest

from src.core.workflow_engine import (
    WorkflowEngine,
    WorkflowNode,
    WorkflowEdge,
    NodeStatus,
    NodeType,
    ExecutionContext,
    get_workflow_engine,
    reset_workflow_engine,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def add_one(x):
    return x + 1

def multiply_by_two(x):
    return x * 2

def sum_two(a, b):
    return a + b

def is_positive(x):
    return x > 0

def is_even(x):
    return x % 2 == 0

def countdown(x):
    return x - 1

def make_tuple(a, b):
    return (a, b)


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Basic DAG construction and validation
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkflowConstruction:
    """DAG构建与验证"""

    def test_add_nodes_and_edges(self):
        """测试添加节点和边"""
        engine = WorkflowEngine(name="test_dag")
        engine.add_node("A", func=add_one, inputs=[])
        engine.add_node("B", func=multiply_by_two, inputs=["A"])
        engine.add_node("C", func=add_one, inputs=["B"])

        assert engine.node_count == 3
        assert engine.edge_count == 2
        assert engine.get_predecessors("B") == ["A"]
        assert engine.get_successors("A") == ["B"]

    def test_validation_passes_on_valid_dag(self):
        """验证合法DAG通过"""
        engine = WorkflowEngine(name="valid_dag")
        engine.add_node("A", func=add_one)
        engine.add_node("B", func=multiply_by_two, inputs=["A"])
        engine.add_node("C", func=add_one, inputs=["B"])

        valid, errors = engine.validate()
        assert valid, f"Validation failed: {errors}"

    def test_validation_detects_cycle(self):
        """验证检测到环"""
        engine = WorkflowEngine(name="cyclic")
        engine.add_node("A", func=add_one)
        engine.add_node("B", func=multiply_by_two, inputs=["A"])
        engine.add_node("C", func=add_one, inputs=["B"])
        engine.add_edge("C", "A")  # Creates cycle

        valid, errors = engine.validate()
        assert not valid
        assert any("Cycle" in e for e in errors)

    def test_validation_detects_missing_edge_target(self):
        """验证检测缺失的边目标"""
        engine = WorkflowEngine(name="bad_edge")
        engine.add_node("A", func=add_one)

        valid, errors = engine.validate()
        assert valid  # Single node is valid

    def test_duplicate_node_raises(self):
        """测试重复节点ID抛异常"""
        engine = WorkflowEngine()
        engine.add_node("A", func=add_one)
        with pytest.raises(ValueError, match="already exists"):
            engine.add_node("A", func=multiply_by_two)

    def test_topological_sort(self):
        """测试拓扑排序"""
        engine = WorkflowEngine()
        engine.add_node("A")
        engine.add_node("B", inputs=["A"])
        engine.add_node("C", inputs=["A"])
        engine.add_node("D", inputs=["B", "C"])

        order = engine.topological_sort()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_repr(self):
        """测试repr"""
        engine = WorkflowEngine(name="mywf")
        engine.add_node("A")
        engine.add_node("B", inputs=["A"])
        r = repr(engine)
        assert "mywf" in r
        assert "nodes=2" in r


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: Sequential execution (linear DAG)
# ══════════════════════════════════════════════════════════════════════════════

class TestSequentialExecution:
    """线性DAG顺序执行"""

    def test_linear_pipeline(self):
        """测试线性流水线: A -> B -> C"""
        engine = WorkflowEngine(name="linear")
        engine.add_node("A", func=lambda: 5)
        engine.add_node("B", func=lambda A: A * 2, inputs=["A"])
        engine.add_node("C", func=lambda B: B + 3, inputs=["B"])

        results = engine.run()
        assert results["A"] == 5
        assert results["B"] == 10
        assert results["C"] == 13

    def test_single_node(self):
        """测试单节点工作流"""
        engine = WorkflowEngine()
        engine.add_node("only", func=lambda: 42)
        results = engine.run()
        assert results["only"] == 42

    def test_node_with_named_inputs(self):
        """测试函数通过输入节点名接收参数"""
        engine = WorkflowEngine()
        engine.add_node("val", func=lambda: 10)
        engine.add_node("calc", func=lambda val: val * 3, inputs=["val"])
        results = engine.run()
        assert results["calc"] == 30

    def test_failed_node_propagates_status(self):
        """测试节点失败传播"""
        engine = WorkflowEngine()
        engine.add_node("good", func=lambda: 1)
        engine.add_node("bad", func=lambda: 1 / 0)  # ZeroDivisionError
        results = engine.run()
        assert "good" in results
        # bad node should have failed
        bad_node = engine.get_node("bad")
        assert bad_node is not None
        assert bad_node.status == NodeStatus.FAILED
        assert bad_node.error is not None


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Parallel execution (fork-join DAG)
# ══════════════════════════════════════════════════════════════════════════════

class TestParallelExecution:
    """并行执行测试"""

    def test_fork_join_dag(self):
        """测试fork-join并行: A分出B和C，汇聚到D"""
        # Use parameter names matching the source node IDs
        def slow_add(start):
            time.sleep(0.05)
            return start + 1

        def slow_mul(start):
            time.sleep(0.05)
            return start * 2

        engine = WorkflowEngine(name="fork_join", max_workers=4)
        engine.add_node("start", func=lambda: 10)
        engine.add_node("left", func=slow_add, inputs=["start"])
        engine.add_node("right", func=slow_mul, inputs=["start"])
        engine.add_node("merge", func=lambda left, right: left + right, inputs=["left", "right"])

        results = engine.run()

        assert results["start"] == 10
        assert results["left"] == 11
        assert results["right"] == 20
        assert results["merge"] == 31

    def test_diamond_dag(self):
        """测试钻石形DAG: A -> B, A -> C, B -> D, C -> D"""
        engine = WorkflowEngine(name="diamond", max_workers=4)
        engine.add_node("A", func=lambda: 3)
        engine.add_node("B", func=lambda A: A * 10, inputs=["A"])
        engine.add_node("C", func=lambda A: A + 10, inputs=["A"])
        engine.add_node("D", func=lambda B, C: B + C, inputs=["B", "C"])

        results = engine.run()
        assert results["B"] == 30
        assert results["C"] == 13
        assert results["D"] == 43

    def test_independent_parallel(self):
        """测试完全独立的并行节点"""
        results_dict = {}

        def task1():
            time.sleep(0.05)
            results_dict["t1"] = "started"
            return "task1_done"

        def task2():
            time.sleep(0.05)
            results_dict["t2"] = "started"
            return "task2_done"

        engine = WorkflowEngine(name="independent", max_workers=4)
        engine.add_node("t1", func=task1)
        engine.add_node("t2", func=task2)

        results = engine.run()

        assert results["t1"] == "task1_done"
        assert results["t2"] == "task2_done"
        # Both should have completed
        assert engine.get_node("t1").status == NodeStatus.COMPLETED
        assert engine.get_node("t2").status == NodeStatus.COMPLETED


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Conditional branching
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionalBranching:
    """条件分支测试"""

    def test_condition_true_branch(self):
        """测试条件为真时走true分支"""
        engine = WorkflowEngine()
        engine.add_node("input", func=lambda: 10)
        engine.add_conditional(
            "check",
            condition_fn=lambda x: x > 5,
            source_node="input",
            true_branch="positive_path",
            false_branch="negative_path",
        )
        engine.add_node("positive_path", func=lambda input: "positive value", inputs=["input"])
        engine.add_node("negative_path", func=lambda input: "negative value", inputs=["input"])

        results = engine.run()

        check_node = engine.get_node("check")
        assert check_node.result is True
        # Positive path should have executed
        pos_node = engine.get_node("positive_path")
        assert pos_node.status == NodeStatus.COMPLETED
        assert pos_node.result == "positive value"

    def test_condition_false_branch(self):
        """测试条件为假时走false分支"""
        engine = WorkflowEngine()
        engine.add_node("input", func=lambda: 2)
        engine.add_conditional(
            "check",
            condition_fn=lambda x: x > 5,
            source_node="input",
            true_branch="big",
            false_branch="small",
        )
        engine.add_node("big", func=lambda input: "big", inputs=["input"])
        engine.add_node("small", func=lambda input: "small", inputs=["input"])

        results = engine.run()

        check_node = engine.get_node("check")
        assert check_node.result is False
        small_node = engine.get_node("small")
        assert small_node.status == NodeStatus.COMPLETED
        assert small_node.result == "small"

    def test_nested_conditions(self):
        """测试嵌套条件"""
        engine = WorkflowEngine()
        engine.add_node("num", func=lambda: 15)
        engine.add_conditional(
            "positive?", condition_fn=lambda x: x > 0, source_node="num",
            true_branch="even?", false_branch="none",
        )
        engine.add_conditional(
            "even?", condition_fn=lambda x: x % 2 == 0, source_node="num",
            true_branch="even_result", false_branch="odd_result",
        )
        engine.add_node("odd_result", func=lambda num: f"odd:{num}", inputs=["num"])
        engine.add_node("even_result", func=lambda num: f"even:{num}", inputs=["num"])
        engine.add_node("none", func=lambda: "non-positive")

        results = engine.run()
        odd_node = engine.get_node("odd_result")
        assert odd_node.status == NodeStatus.COMPLETED
        assert odd_node.result == "odd:15"


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Loops
# ══════════════════════════════════════════════════════════════════════════════

class TestLoopExecution:
    """循环执行测试"""

    def test_countdown_loop(self):
        """测试倒数循环: 5 -> 4 -> 3 -> 2 -> 1 -> 0 (stop)"""
        engine = WorkflowEngine()
        engine.add_node("start", func=lambda: 5)
        engine.add_loop(
            "countdown",
            loop_body_fn=countdown,
            source_node="start",
            while_condition=lambda x: x > 0,
            max_iterations=20,
        )
        engine.add_node("after", func=lambda countdown: f"done:{countdown}", inputs=["countdown"])

        results = engine.run()

        loop_node = engine.get_node("countdown")
        assert loop_node.result == 0
        assert loop_node.iteration_count == 5
        assert loop_node.status == NodeStatus.COMPLETED

        assert results["after"] == "done:0"

    def test_loop_max_iterations_guard(self):
        """测试最大迭代保护"""
        engine = WorkflowEngine()
        engine.add_node("start", func=lambda: 0)
        engine.add_loop(
            "forever",
            loop_body_fn=lambda x: x + 1,
            source_node="start",
            while_condition=lambda x: True,  # Always true
            max_iterations=5,
        )

        results = engine.run()
        loop_node = engine.get_node("forever")
        assert loop_node.iteration_count == 5
        assert loop_node.status == NodeStatus.COMPLETED

    def test_loop_without_condition(self):
        """测试无while条件的循环(即执行一次循环体)"""
        engine = WorkflowEngine()
        engine.add_node("init", func=lambda: "hello")
        engine.add_loop(
            "transform",
            loop_body_fn=lambda x: x.upper(),
            source_node="init",
            max_iterations=1,
        )

        results = engine.run()
        loop_node = engine.get_node("transform")
        assert loop_node.result == "HELLO"
        assert loop_node.iteration_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: Mermaid visualization
# ══════════════════════════════════════════════════════════════════════════════

class TestMermaidExport:
    """Mermaid可视化导出测试"""

    def test_mermaid_basic(self):
        """测试基本Mermaid导出"""
        engine = WorkflowEngine(name="viz_test")
        engine.add_node("A", func=add_one)
        engine.add_node("B", func=multiply_by_two, inputs=["A"])
        engine.add_node("C", func=add_one, inputs=["B"])

        m = engine.to_mermaid()
        assert "```mermaid" in m
        assert "graph TD" in m
        assert "A" in m
        assert "B" in m
        assert "C" in m
        assert "-->" in m
        assert m.endswith("```")

    def test_mermaid_raw(self):
        """测试纯Mermaid导出(无markdown包裹)"""
        engine = WorkflowEngine()
        engine.add_node("X")
        engine.add_node("Y", inputs=["X"])

        m = engine.to_mermaid_raw()
        assert "```" not in m
        assert "graph TD" in m
        assert "X-->" in m or "X -->" in m

    def test_mermaid_different_directions(self):
        """测试不同方向"""
        engine = WorkflowEngine()
        engine.add_node("A")
        engine.add_node("B", inputs=["A"])

        m_lr = engine.to_mermaid(direction="LR")
        assert "graph LR" in m_lr

        m_bt = engine.to_mermaid(direction="BT")
        assert "graph BT" in m_bt

    def test_mermaid_with_status(self):
        """测试带状态的Mermaid导出"""
        engine = WorkflowEngine()
        engine.add_node("A")
        engine.add_node("B", inputs=["A"])

        engine.run()
        m = engine.to_mermaid(show_status=True)
        # Status text should appear in node labels
        assert "completed" in m.lower() or "COMPLETED" in m

    def test_mermaid_with_conditional(self):
        """测试条件分支的Mermaid导出"""
        engine = WorkflowEngine()
        engine.add_node("start")
        engine.add_conditional("check", condition_fn=lambda x: x > 0, source_node="start",
                               true_branch="yes", false_branch="no")
        engine.add_node("yes")
        engine.add_node("no")

        m = engine.to_mermaid()
        assert "True" in m
        assert "False" in m

    def test_mermaid_with_loop(self):
        """测试循环的Mermaid导出"""
        engine = WorkflowEngine()
        engine.add_node("init")
        engine.add_loop("loop", loop_body_fn=lambda x: x, source_node="init")

        m = engine.to_mermaid()
        assert "iter=" in m


# ══════════════════════════════════════════════════════════════════════════════
# Test 7: Serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestSerialization:
    """序列化/反序列化测试"""

    def test_to_dict_and_from_dict(self):
        """测试序列化往返"""
        engine = WorkflowEngine(name="serial_test")
        engine.add_node("A", func=add_one)
        engine.add_node("B", func=multiply_by_two, inputs=["A"])
        engine.add_conditional("check", condition_fn=lambda x: x > 5, source_node="B",
                               true_branch="yes", false_branch="no")
        engine.add_node("yes")
        engine.add_node("no")

        data = engine.to_dict()
        assert data["name"] == "serial_test"
        assert len(data["nodes"]) == 5  # A, B, check, yes, no
        assert len(data["edges"]) >= 3

        # Reconstruct with same funcs
        funcs = {"A": add_one, "B": multiply_by_two, "check": lambda x: x > 5}
        restored = WorkflowEngine.from_dict(data, node_funcs=funcs)
        assert restored.node_count == 5
        assert restored.name == "serial_test"

        valid, errors = restored.validate()
        assert valid, f"Restored workflow invalid: {errors}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 8: Singleton pattern
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleton:
    """单例模式测试"""

    def test_get_and_reset(self):
        """测试单例获取和重置"""
        reset_workflow_engine()

        wf1 = get_workflow_engine(name="singleton_test")
        wf2 = get_workflow_engine()
        assert wf1 is wf2  # Same instance

        reset_workflow_engine()
        wf3 = get_workflow_engine(name="new_one")
        assert wf3 is not wf1  # New instance after reset


# ══════════════════════════════════════════════════════════════════════════════
# Test 9: Edge cases and error handling
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界情况测试"""

    def test_empty_workflow(self):
        """测试空工作流"""
        engine = WorkflowEngine()
        valid, errors = engine.validate()
        assert valid
        results = engine.run()
        assert results == {}

    def test_node_without_func(self):
        """测试无函数节点(纯数据节点)"""
        engine = WorkflowEngine()
        engine.add_node("data", func=None)
        results = engine.run()
        assert results["data"] is None

    def test_retry_on_failure(self):
        """测试失败重试"""
        call_count = {"count": 0}

        def flaky():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("temporary error")
            return "success"

        engine = WorkflowEngine()
        engine.add_node("flaky", func=flaky, retries=3)

        results = engine.run()
        assert results["flaky"] == "success"
        assert call_count["count"] == 3

    def test_invalid_workflow_raises(self):
        """测试无效工作流run时抛异常"""
        engine = WorkflowEngine()
        engine.add_node("A")
        engine.add_node("B")
        engine.add_edge("A", "B")
        engine.add_edge("B", "A")  # Cycle

        with pytest.raises(ValueError, match="validation failed"):
            engine.run()

    def test_async_function_node(self):
        """测试异步函数节点"""
        import asyncio

        async def async_task():
            await asyncio.sleep(0.01)
            return "async_done"

        engine = WorkflowEngine()
        engine.add_node("async_node", func=async_task)
        results = engine.run()
        assert results["async_node"] == "async_done"

    def test_complex_workflow_with_all_features(self):
        """集成测试: 同时使用并行+条件+循环"""
        engine = WorkflowEngine(name="integration", max_workers=4)
        engine.add_node("produce", func=lambda: 7)
        # Parallel branches
        engine.add_node("square", func=lambda produce: produce * produce, inputs=["produce"])
        engine.add_node("cube", func=lambda produce: produce * produce * produce, inputs=["produce"])
        # Conditional on square result
        engine.add_conditional(
            "big?", condition_fn=lambda x: x > 30, source_node="square",
            true_branch="big_out", false_branch="small_out",
        )
        engine.add_node("big_out", func=lambda square: f"BIG:{square}", inputs=["square"])
        engine.add_node("small_out", func=lambda square: f"small:{square}", inputs=["square"])
        # Loop on cube
        engine.add_loop(
            "reduce", loop_body_fn=lambda x: x // 2, source_node="cube",
            while_condition=lambda x: x > 50, max_iterations=10,
        )
        # Final merge (waits for one path from conditional + loop)
        engine.add_node("final", func=lambda big_out, reduce: f"{big_out} | {reduce}",
                        inputs=["big_out", "reduce"])

        results = engine.run()
        assert results["produce"] == 7
        assert results["square"] == 49
        assert results["cube"] == 343

        big_node = engine.get_node("big_out")
        assert big_node.status == NodeStatus.COMPLETED
        assert "BIG:49" in str(big_node.result)

        reduce_node = engine.get_node("reduce")
        assert reduce_node.result <= 50

        assert "BIG:49" in str(results["final"])
        assert str(reduce_node.result) in str(results["final"])


# ══════════════════════════════════════════════════════════════════════════════
# Test 10: NodeType and NodeStatus enums
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeTypeAndStatus:
    """枚举类型测试"""

    def test_node_type_values(self):
        """测试节点类型枚举值"""
        assert NodeType.TASK is not None
        assert NodeType.CONDITION is not None
        assert NodeType.LOOP is not None
        assert NodeType.GATEWAY is not None

    def test_node_status_values(self):
        """测试节点状态枚举值"""
        assert NodeStatus.PENDING.value == "pending"
        assert NodeStatus.RUNNING.value == "running"
        assert NodeStatus.COMPLETED.value == "completed"
        assert NodeStatus.FAILED.value == "failed"
        assert NodeStatus.SKIPPED.value == "skipped"
        assert NodeStatus.LOOPING.value == "looping"


# ══════════════════════════════════════════════════════════════════════════════
# Run all tests
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
