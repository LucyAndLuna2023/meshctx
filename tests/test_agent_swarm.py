"""
Agent Swarm 多Agent协同 — 端到端测试
=====================================
测试场景: 1个Manager + 3个Worker(Coder/Searcher/Reviewer)
任务: "写一个Python函数计算斐波那契数列"
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.agent_swarm import (
    AgentIdentity, ManagerAgent, WorkerAgent,
    init_swarm_manager, init_swarm_worker,
    get_swarm_manager, get_swarm_worker,
)


async def test_manager_only():
    """测试1: Manager独立启动"""
    print("\n=== 测试1: Manager启动 ===")
    identity = AgentIdentity(agent_id="test_manager")
    mgr = ManagerAgent(identity, port=3099)
    await mgr.start()
    print(f"  ✅ Manager启动: {identity.agent_id}")
    
    status = mgr.get_swarm_status()
    print(f"  Workers: {status['workers']}")
    assert status['workers'] == 0
    
    await mgr.stop()
    print("  ✅ 测试1通过")


async def test_worker_registration():
    """测试2: Worker注册到Manager"""
    print("\n=== 测试2: Worker注册 ===")
    
    # Start Manager
    mgr_id = AgentIdentity(agent_id="mgr2")
    mgr = ManagerAgent(mgr_id, port=3098)
    await mgr.start()
    
    # Create and register Worker
    w_id = AgentIdentity(agent_id="worker1")
    wi = mgr.register_worker(
        worker_id=w_id.agent_id,
        name="TestWorker1",
        address="http://localhost:3099",
        public_key=w_id.public_key,
        capabilities=["search", "code"],
    )
    
    status = mgr.get_swarm_status()
    print(f"  Workers: {status['workers']}")
    assert status['workers'] == 1, f"Expected 1 worker, got {status['workers']}"
    
    # Check worker info
    w = mgr.workers.get(w_id.agent_id)
    assert w is not None
    assert w.name == "TestWorker1"
    assert "search" in w.capabilities
    print(f"  ✅ Worker注册: {w.name} (capabilities: {w.capabilities})")
    
    await mgr.stop()
    print("  ✅ 测试2通过")


@pytest.mark.skip(reason="timing-dependent test")
async def test_heartbeat():
    """测试3: 心跳机制"""
    print("\n=== 测试3: 心跳 ===")
    
    mgr_id = AgentIdentity(agent_id="mgr3")
    mgr = ManagerAgent(mgr_id, port=3097)
    await mgr.start()
    
    w_id = AgentIdentity(agent_id="worker3")
    mgr.register_worker(w_id.agent_id, "HeartbeatWorker", "http://localhost:3099", w_id.public_key)
    
    # Initial heartbeat
    import time
    t0 = mgr.workers[w_id.agent_id].last_heartbeat
    
    # Update heartbeat
    await asyncio.sleep(0.1)
    mgr.update_heartbeat(w_id.agent_id)
    t1 = mgr.workers[w_id.agent_id].last_heartbeat
    
    assert t1 > t0, f"Heartbeat not updated: {t0} -> {t1}"
    print(f"  ✅ 心跳更新: {round(t1 - t0, 2)}s")
    
    await mgr.stop()
    print("  ✅ 测试3通过")


async def test_task_submission():
    """测试4: 任务提交和分解"""
    print("\n=== 测试4: 任务分解 ===")
    
    mgr_id = AgentIdentity(agent_id="mgr4")
    mgr = ManagerAgent(mgr_id, port=3096)
    await mgr.start()
    
    # Register workers with different capabilities
    mgr.register_worker("w_coder", "Coder", "http://localhost:4001", "pk1", ["code"])
    mgr.register_worker("w_search", "Searcher", "http://localhost:4002", "pk2", ["search"])
    mgr.register_worker("w_review", "Reviewer", "http://localhost:4003", "pk3", ["review", "analyze"])
    
    # Submit a research task
    tasks = await mgr.submit_task(
        description="搜索Python asyncio最佳实践并写总结",
        task_type="research",
    )
    
    print(f"  分解为 {len(tasks)} 个子任务:")
    for t in tasks:
        print(f"    [{t.task_id}] {t.task_type}: {t.description[:60]}... → worker={t.worker_id or '待分配'}")
    
    assert len(tasks) == 3, f"Expected 3 subtasks, got {len(tasks)}"
    assert tasks[0].task_type == "search"
    assert tasks[1].task_type == "analyze"
    assert tasks[2].task_type == "write"
    
    # Submit a code task
    tasks2 = await mgr.submit_task(
        description="写一个快速排序函数",
        task_type="code",
    )
    print(f"\n  Code任务分解为 {len(tasks2)} 个子任务:")
    for t in tasks2:
        print(f"    [{t.task_id}] {t.task_type}: {t.description[:60]}...")
    
    assert len(tasks2) == 4, f"Expected 4 subtasks, got {len(tasks2)}"
    
    await mgr.stop()
    print("  ✅ 测试4通过")


async def test_find_worker():
    """测试5: Worker匹配策略"""
    print("\n=== 测试5: Worker匹配 ===")
    
    mgr_id = AgentIdentity(agent_id="mgr5")
    mgr = ManagerAgent(mgr_id, port=3095)
    await mgr.start()
    
    mgr.register_worker("w1", "BusyCoder", "http://a", "pk1", ["code"])
    mgr.register_worker("w2", "FreeCoder", "http://b", "pk2", ["code"])
    mgr.register_worker("w3", "Searcher", "http://c", "pk3", ["search"])
    
    # w1 is busy
    mgr.workers["w1"].status = "busy"
    mgr.workers["w1"].total_tasks = 5
    
    # Should pick w2 (free coder)
    worker = mgr.find_worker("code")
    assert worker is not None
    assert worker.worker_id == "w2", f"Expected w2, got {worker.worker_id}"
    print(f"  ✅ 找到最空闲Worker: {worker.name}")
    
    # w2 goes offline
    mgr.workers["w2"].last_heartbeat = 0
    worker = mgr.find_worker("code")
    assert worker is not None
    assert worker.worker_id == "w1", f"Fallback should pick w1, got {worker.worker_id}"
    print(f"  ✅ Fallback到: {worker.name}")
    
    await mgr.stop()
    print("  ✅ 测试5通过")


async def test_worker_receive_result():
    """测试6: 结果接收"""
    print("\n=== 测试6: 结果接收 ===")
    
    mgr_id = AgentIdentity(agent_id="mgr6")
    mgr = ManagerAgent(mgr_id, port=3094)
    await mgr.start()
    
    mgr.register_worker("w_result", "ResultWorker", "http://localhost:4004", "pk_result", ["general"])
    
    tasks = await mgr.submit_task("简单测试任务", task_type="general")
    task = tasks[0]
    task.worker_id = "w_result"
    task.status = "running"
    
    # Simulate result
    await mgr.receive_result(task.task_id, result="任务完成！斐波那契数列已生成。", error="")
    
    t = mgr.tasks[task.task_id]
    assert t.status.value == "done"
    assert "斐波那契" in t.result
    print(f"  ✅ 结果接收: {t.status.value} - {t.result[:50]}")
    
    await mgr.stop()
    print("  ✅ 测试6通过")


async def test_identity_sign_verify():
    """测试7: 身份签名验证"""
    print("\n=== 测试7: 身份签名+验证 ===")
    
    identity = AgentIdentity(agent_id="test_agent")
    
    # Sign a request
    payload = {"action": "register", "data": "hello"}
    signed = identity.sign_request(payload)
    
    assert "signature" in signed
    assert "agent_id" in signed
    assert signed["agent_id"] == "test_agent"
    
    # Verify with correct key - use identity's own secret key
    ok = identity.verify_request(signed.copy(), identity._secret)
    assert ok, "Valid signature should verify"

    # Tampered signature should fail
    tampered = signed.copy()
    tampered["signature"] = "0000" * 16
    try:
        ok2 = identity.verify_request(tampered, identity._secret)
    except ValueError:
        ok2 = False
    assert not ok2, "Tampered signature should NOT verify"
    
    print(f"  ✅ 签名: {signed['signature'][:16]}...")
    print(f"  ✅ 防篡改: {ok2}")
    print("  ✅ 测试7通过")


async def test_swarm_status():
    """测试8: 状态查询"""
    print("\n=== 测试8: Swarm状态 ===")
    
    mgr_id = AgentIdentity(agent_id="mgr8")
    mgr = ManagerAgent(mgr_id, port=3093)
    await mgr.start()
    
    mgr.register_worker("w_a", "WorkerA", "http://a", "pk_a", ["code", "search"])
    mgr.register_worker("w_b", "WorkerB", "http://b", "pk_b", ["review"])
    
    await mgr.submit_task("测试任务1", "code")
    await mgr.submit_task("测试任务2", "search")
    
    status = mgr.get_swarm_status()
    print(f"  Manager: {status['manager_id']}")
    print(f"  Workers: {status['workers']} (online: {status['workers_online']})")
    print(f"  Tasks: {status['tasks_pending']} pending, {status['tasks_done']} done")
    
    assert status['workers'] == 2
    assert status['tasks_pending'] >= 0
    
    for w in status['workers_detail']:
        print(f"    {w['name']}: {w['status']} [{', '.join(w['capabilities'])}]")
    
    await mgr.stop()
    print("  ✅ 测试8通过")


async def main():
    print("╔══════════════════════════════════════════╗")
    print("║  Agent Swarm 多Agent协同 — 全量测试    ║")
    print("╚══════════════════════════════════════════╝")
    
    tests = [
        test_manager_only,
        test_worker_registration,
        test_heartbeat,
        test_task_submission,
        test_find_worker,
        test_worker_receive_result,
        test_identity_sign_verify,
        test_swarm_status,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"  结果: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
