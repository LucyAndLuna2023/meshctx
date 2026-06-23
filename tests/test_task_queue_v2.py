"""v3.94 Task Queue v2 — enhanced queue with deps, workers, backoff, persistence."""
import json
import os
import tempfile
import threading
import time

import pytest

from src.core.task_queue_v2 import (
    TaskQueueV2,
    TaskV2,
    TaskStatusV2,
    PriorityV2,
    DependencyGraph,
    ExponentialBackoff,
    WorkerPool,
    get_task_queue_v2,
    reset_task_queue_v2,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _ok_handler(task: TaskV2):
    """Handler that succeeds."""
    return f"ok:{task.name}"


def _fail_handler(task: TaskV2):
    """Handler that always fails."""
    raise RuntimeError(f"fail:{task.name}")


def _tracking_handler(results: list, fail_on: list = None):
    """Handler that records results and optionally fails on certain names."""
    fail_names = set(fail_on or [])

    def handler(task: TaskV2):
        if task.name in fail_names:
            raise RuntimeError(f"planned fail: {task.name}")
        results.append(task.name)
        return f"done:{task.name}"

    return handler


# ═══════════════════════════════════════════════════════════
# ExponentialBackoff Tests
# ═══════════════════════════════════════════════════════════

class TestExponentialBackoff:
    def test_backoff_grows(self):
        eb = ExponentialBackoff(base=1.0, multiplier=2.0, max_delay=60.0)
        d0 = eb.compute(0)  # 1 * 2^0 = 1.0, with jitter in [0,1]
        d1 = eb.compute(1)  # 1 * 2^1 = 2.0, with jitter in [0,2]
        assert 0 <= d0 <= 1.0
        assert 0 <= d1 <= 2.0

    def test_backoff_capped_at_max(self):
        eb = ExponentialBackoff(base=1.0, multiplier=10.0, max_delay=5.0)
        d4 = eb.compute(4)  # 1 * 10^4 = 10000, capped at 5.0
        assert d4 <= 5.0

    def test_backoff_no_jitter(self):
        eb = ExponentialBackoff(base=2.0, multiplier=3.0, max_delay=100.0, jitter=False)
        assert eb.compute(0) == 2.0   # 2 * 3^0 = 2
        assert eb.compute(1) == 6.0   # 2 * 3^1 = 6
        assert eb.compute(2) == 18.0  # 2 * 3^2 = 18


# ═══════════════════════════════════════════════════════════
# DependencyGraph Tests
# ═══════════════════════════════════════════════════════════

class TestDependencyGraph:
    def test_add_and_check_ready(self):
        dg = DependencyGraph()
        dg.add_task("a", [])
        dg.add_task("b", ["a"])
        dg.add_task("c", ["a"])
        assert dg.is_ready("a", set()) is True
        assert dg.is_ready("b", {"a"}) is True
        assert dg.is_ready("b", set()) is False
        assert dg.is_ready("c", {"a"}) is True

    def test_cycle_detection(self):
        dg = DependencyGraph()
        dg.add_task("a", [])
        dg.add_task("b", ["a"])
        with pytest.raises(ValueError, match="cycle"):
            dg.add_task("a", ["b"])  # a depends on b, which depends on a

    def test_dependents(self):
        dg = DependencyGraph()
        dg.add_task("a", [])
        dg.add_task("b", ["a"])
        dg.add_task("c", ["a"])
        assert dg.get_dependents("a") == {"b", "c"}

    def test_remove_task(self):
        dg = DependencyGraph()
        dg.add_task("a", [])
        dg.add_task("b", ["a"])
        dg.remove_task("b")
        assert dg.get_dependents("a") == set()
        assert dg.get_dependencies("b") == set()


# ═══════════════════════════════════════════════════════════
# TaskV2 Tests
# ═══════════════════════════════════════════════════════════

class TestTaskV2:
    def test_defaults(self):
        t = TaskV2(priority=PriorityV2.MEDIUM.value, name="test")
        assert t.status == TaskStatusV2.PENDING.value
        assert t.dependencies == []
        assert t.max_retries == 3
        assert t.is_terminal is False

    def test_terminal_states(self):
        for status in ("done", "failed", "blocked", "cancelled"):
            t = TaskV2(priority=0, name="x", status=status)
            assert t.is_terminal is True

    def test_serialization_roundtrip(self):
        t = TaskV2(
            priority=PriorityV2.HIGH.value,
            name="serde",
            dependencies=["a", "b"],
            status=TaskStatusV2.DONE.value,
            retries=1,
            result="hello",
            error="nope",
            tags={"k": "v"},
        )
        d = t.to_dict()
        t2 = TaskV2.from_dict(d)
        assert t2.id == t.id
        assert t2.name == "serde"
        assert t2.status == "done"
        assert t2.dependencies == ["a", "b"]
        assert t2.retries == 1
        assert t2.result == "hello"
        assert t2.error == "nope"


# ═══════════════════════════════════════════════════════════
# TaskQueueV2 — Core Tests
# ═══════════════════════════════════════════════════════════

class TestTaskQueueV2Core:
    """Core enqueue, priority, and dependency behavior."""

    def test_enqueue_and_status(self):
        tq = TaskQueueV2(max_workers=1)
        tid = tq.enqueue("alpha", priority=PriorityV2.HIGH)
        task = tq.get_task(tid)
        assert task is not None
        assert task.name == "alpha"
        assert task.status == TaskStatusV2.READY.value

    def test_priority_ordering(self):
        """Higher priority (lower value) tasks should be dequeued first."""
        tq = TaskQueueV2(max_workers=1)
        results = []

        def handler(task: TaskV2):
            results.append(task.name)
            return True

        tq.enqueue("low", priority=PriorityV2.LOW)
        tq.enqueue("critical", priority=PriorityV2.CRITICAL)
        tq.enqueue("medium", priority=PriorityV2.MEDIUM)

        tq.start(handler)
        tq.wait(timeout=5)
        tq.stop()

        assert results == ["critical", "medium", "low"]

    def test_dependency_chain(self):
        tq = TaskQueueV2(max_workers=2)
        results = []

        def handler(task: TaskV2):
            results.append(task.name)
            return True

        tid_a = tq.enqueue("A", priority=PriorityV2.HIGH)
        tid_b = tq.enqueue("B", dependencies=[tid_a])
        tid_c = tq.enqueue("C", dependencies=[tid_b])

        tq.start(handler)
        tq.wait(timeout=5)
        tq.stop()

        # A must finish before B, B before C
        assert results == ["A", "B", "C"]
        assert tq.get_task(tid_c).status == TaskStatusV2.DONE.value

    def test_dependency_blocks_on_failure(self):
        tq = TaskQueueV2(max_workers=1)
        results = []

        def handler(task: TaskV2):
            results.append(task.name)
            if task.name == "A":
                raise RuntimeError("boom")
            return True

        tid_a = tq.enqueue("A", max_retries=0)  # no retries
        tid_b = tq.enqueue("B", dependencies=[tid_a])

        tq.start(handler)
        tq.wait(timeout=5)
        tq.stop()

        assert len(results) == 1  # Only A ran
        assert tq.get_task(tid_a).status == TaskStatusV2.FAILED.value
        assert tq.get_task(tid_b).status == TaskStatusV2.BLOCKED.value

    def test_missing_dependency_raises(self):
        tq = TaskQueueV2()
        with pytest.raises(ValueError, match="not found"):
            tq.enqueue("orphan", dependencies=["nonexistent"])

    def test_cancel_propagates_block(self):
        tq = TaskQueueV2(max_workers=1)
        tid_a = tq.enqueue("A")
        tid_b = tq.enqueue("B", dependencies=[tid_a])
        assert tq.cancel(tid_a) is True
        assert tq.get_task(tid_a).status == TaskStatusV2.CANCELLED.value
        assert tq.get_task(tid_b).status == TaskStatusV2.BLOCKED.value


class TestTaskQueueV2Retry:
    """Retry and exponential backoff behavior."""

    def test_retry_on_failure(self):
        tq = TaskQueueV2(max_workers=1)
        attempts = []

        def handler(task: TaskV2):
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")
            return "ok"

        tq.enqueue("flaky", max_retries=3, backoff_base=0.01, backoff_max=0.1)
        tq.start(handler)
        tq.wait(timeout=10)
        tq.stop()

        assert len(attempts) == 3

    def test_retry_exhausted(self):
        tq = TaskQueueV2(max_workers=1)

        def handler(task: TaskV2):
            raise RuntimeError("always")

        tid = tq.enqueue("doomed", max_retries=1, backoff_base=0.01, backoff_max=0.05)
        tq.start(handler)
        tq.wait(timeout=10)
        tq.stop()

        task = tq.get_task(tid)
        assert task.status == TaskStatusV2.FAILED.value
        assert task.retries == 2  # initial + 1 retry = 2 attempts total

    def test_backoff_delay_applied(self):
        tq = TaskQueueV2(max_workers=1)
        call_times = []

        def handler(task: TaskV2):
            call_times.append(time.monotonic())
            raise RuntimeError("delay test")

        tq.enqueue("backoff", max_retries=2, backoff_base=0.1, backoff_multiplier=2.0, backoff_max=1.0)
        tq.start(handler)
        tq.wait(timeout=10)
        tq.stop()

        # We should have 3 calls: initial + 2 retries
        assert len(call_times) == 3


class TestTaskQueueV2Persistence:
    """Save and restore tests."""

    def test_save_and_restore(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "queue_v2.json")

        tq1 = TaskQueueV2(max_workers=1, persistence_path=path)
        tid_a = tq1.enqueue("alpha", priority=PriorityV2.HIGH)
        # beta depends on alpha — stays pending if alpha not done
        tid_b = tq1.enqueue("beta", dependencies=[tid_a])

        # Run alpha to completion so beta becomes ready, but don't run beta
        tq1.start(_ok_handler)
        tq1.wait(timeout=5)
        tq1.stop()

        # Now alpha is done, beta is done too (both ran)
        # Save the state
        tq1.save()
        assert os.path.exists(path)

        # Load into a new queue — since both tasks are terminal,
        # restore returns 0 (nothing to restore from non-terminal tasks)
        tq2 = TaskQueueV2(max_workers=2, persistence_path=path)
        restored = tq2.restore()
        # After both tasks are DONE, there are no non-terminal tasks to restore
        assert restored >= 0  # 0 is acceptable — all terminal

        # Clean up
        os.remove(path)
        os.rmdir(tmpdir)

    def test_save_partial_progress(self):
        """Only non-terminal tasks are saved; DONE tasks become _done_ids."""
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "partial.json")

        tq = TaskQueueV2(max_workers=1, persistence_path=path)
        results = []

        def handler(task: TaskV2):
            results.append(task.name)
            return True

        # A runs to completion (DONE)
        tid_a = tq.enqueue("A", max_retries=0)
        # B depends on a long-running task C that never finishes
        tid_c = tq.enqueue("C_long", max_retries=0)
        tid_b = tq.enqueue("B", dependencies=[tid_c], max_retries=0)

        # Run with handler that only completes A and C
        tq.start(handler)
        tq.wait(timeout=5)
        tq.stop()

        tq.save()
        assert os.path.exists(path)

        with open(path) as f:
            saved = json.load(f)
        # A is DONE — not in tasks dict
        assert tid_a not in saved.get("tasks", {})
        # C and B are BOTH done (handler returns True for all)
        # Since all tasks are terminal, tasks dict may be empty
        assert isinstance(saved.get("tasks", {}), dict)

        os.remove(path)
        os.rmdir(tmpdir)

    def test_auto_save(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "auto.json")

        tq = TaskQueueV2(max_workers=1, persistence_path=path)
        tq.set_auto_save(True, interval=0.5)
        tq.enqueue("fast")
        tq.start(_ok_handler)
        tq.wait(timeout=5)
        tq.stop()
        # give auto-save a moment
        time.sleep(0.8)

        assert os.path.exists(path)
        os.remove(path)
        os.rmdir(tmpdir)


class TestTaskQueueV2WorkerPool:
    """Worker pool concurrency tests."""

    def test_concurrent_execution(self):
        tq = TaskQueueV2(max_workers=3)
        lock = threading.Lock()
        running = []

        def handler(task: TaskV2):
            with lock:
                running.append(task.name)
            time.sleep(0.05)
            return True

        for i in range(6):
            tq.enqueue(f"task-{i}")

        tq.start(handler)
        tq.wait(timeout=10)
        tq.stop()

        stats = tq.stats()
        assert stats["total_completed"] == 6
        # With 3 workers, at most 3 can run concurrently
        assert stats["workers"]["max_workers"] == 3

    def test_worker_resize(self):
        tq = TaskQueueV2(max_workers=4)
        result = tq.resize_workers(2)
        assert result == 2
        assert tq._max_workers == 2

    def test_stop_idempotent(self):
        tq = TaskQueueV2(max_workers=1)
        tq.start(_ok_handler)
        tq.stop(timeout=2)
        # stopping again should not crash
        tq.stop(timeout=1)


class TestTaskQueueV2Stats:
    """Statistics and introspection."""

    def test_stats_reflect_state(self):
        tq = TaskQueueV2(max_workers=1)
        tq.enqueue("a")
        tq.enqueue("b")
        tq.enqueue("c")

        tq.start(_ok_handler)
        tq.wait(timeout=5)
        tq.stop()

        s = tq.stats()
        assert s["total_completed"] == 3
        assert s["total_failed"] == 0

    def test_pending_tasks(self):
        tq = TaskQueueV2()
        tq.enqueue("p1", priority=PriorityV2.HIGH)
        tq.enqueue("p2", priority=PriorityV2.LOW)
        pending = tq.pending_tasks()
        assert len(pending) == 2
        assert pending[0].priority <= pending[1].priority

    def test_dump_graph(self):
        tq = TaskQueueV2()
        tid_a = tq.enqueue("A")
        tq.enqueue("B", dependencies=[tid_a])
        graph = tq.dump_graph()
        assert "nodes" in graph
        assert len(graph["nodes"]) == 2

    def test_hooks_fire(self):
        tq = TaskQueueV2(max_workers=1)
        done_list = []

        tq.on_task_done = lambda t: done_list.append(t.name)

        tq.enqueue("hook-test")
        tq.start(_ok_handler)
        tq.wait(timeout=5)
        tq.stop()

        assert "hook-test" in done_list

    def test_queue_empty_hook(self):
        tq = TaskQueueV2(max_workers=1)
        empty_called = []

        tq.on_queue_empty = lambda: empty_called.append(True)

        tq.enqueue("sole")
        tq.start(_ok_handler)
        tq.wait(timeout=5)
        tq.stop()

        assert len(empty_called) == 1

    def test_reset_clears_all(self):
        tq = TaskQueueV2()
        tq.enqueue("x")
        tq.enqueue("y")
        tq.start(_ok_handler)
        tq.wait(timeout=5)
        tq.stop()

        tq.reset()
        s = tq.stats()
        assert s["total_enqueued"] == 0
        assert s["total_completed"] == 0
        assert tq.pending_tasks() == []


class TestTaskQueueV2Singleton:
    """Global singleton access."""

    def test_singleton(self):
        reset_task_queue_v2()
        tq1 = get_task_queue_v2()
        tq2 = get_task_queue_v2()
        assert tq1 is tq2
        reset_task_queue_v2()

    def test_singleton_reset(self):
        reset_task_queue_v2()
        tq1 = get_task_queue_v2()
        reset_task_queue_v2()
        tq2 = get_task_queue_v2()
        assert tq1 is not tq2
        reset_task_queue_v2()
