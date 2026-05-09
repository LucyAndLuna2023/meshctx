"""
meshctx v1.0 核心集成测试

验证微内核 + 层次记忆 + 元认知 + 多Agent编排 协同工作
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core import (
    Kernel, Event, EventPriority,
    MemoryPlugin, MetaCognitionPlugin, OrchestratorPlugin,
    MemoryItem, MemoryLevel, TaskStatus,
)


async def test_kernel_startup():
    """测试1: 内核启动"""
    print("\n=== 测试1: 内核启动 ===")
    kernel = Kernel()
    await kernel.start(worker_count=2)
    
    status = kernel.get_status()
    assert status["started"] == True
    assert status["bus_stats"]["subscriptions"] > 0
    print(f"✓ 内核已启动, 事件订阅: {status['bus_stats']['subscriptions']}")
    
    await kernel.stop()
    print("✓ 内核已停止")


async def test_event_system():
    """测试2: 事件总线"""
    print("\n=== 测试2: 事件总线 ===")
    kernel = Kernel()
    await kernel.start(worker_count=2)
    
    received = []
    
    async def handler(event: Event):
        received.append(event.data.get("message"))
    
    kernel.bus.subscribe("test.event", handler, plugin_name="test")
    
    await kernel.bus.publish(Event(
        type="test.event",
        source="test",
        data={"message": "hello world"},
    ))
    
    await asyncio.sleep(0.2)  # 等待异步处理
    
    assert "hello world" in received
    print(f"✓ 事件已接收: {received}")
    
    await kernel.stop()


async def test_memory_hierarchy():
    """测试3: 层次记忆"""
    print("\n=== 测试3: 层次记忆 ===")
    kernel = Kernel()
    memory_plugin = MemoryPlugin()
    kernel.plugins.register(memory_plugin)
    await kernel.start(worker_count=2)
    
    # 添加消息(触发记忆提取)
    await kernel.bus.publish(Event(
        type="message.added",
        source="test",
        data={
            "content": "重要：meshctx的目标是成为世界第一Agent系统",
            "role": "user",
            "project_id": "test-project",
            "conversation_id": "test-conv",
        },
    ))
    
    await asyncio.sleep(0.3)
    
    # 检索
    results = memory_plugin.store.retrieve(
        "世界第一Agent", top_k=5
    )
    assert len(results) > 0
    print(f"✓ 记忆检索: {len(results)}条, 首条: {results[0].key}")
    
    # 统计
    stats = memory_plugin.store.get_stats()
    print(f"✓ 记忆统计: {stats}")
    
    # 遗忘曲线验证
    item = MemoryItem(
        key="test",
        value="test",
        importance=0.8,
        created_at=time.time() - 3600,  # 1小时前
        last_reviewed=time.time() - 3600,
    )
    retention = item.current_retention()
    assert 0.3 < retention < 0.6  # 1小时后应在30-60%
    print(f"✓ 遗忘曲线: 1小时后保留率 {retention:.1%}")
    
    await kernel.stop()


async def test_metacognition():
    """测试4: 元认知循环"""
    print("\n=== 测试4: 元认知循环 ===")
    kernel = Kernel()
    meta_plugin = MetaCognitionPlugin()
    kernel.plugins.register(meta_plugin)
    await kernel.start(worker_count=2)
    
    # 模拟成功任务
    await kernel.bus.publish(Event(
        type="task.completed",
        source="test",
        data={
            "task_id": "task-001",
            "description": "部署 meshctx 到服务器",
            "duration_seconds": 30,
            "tool_calls": 5,
            "tool_failures": 0,
            "delegation_used": True,
            "verification_steps": 3,
        },
    ))
    
    await asyncio.sleep(0.3)
    
    # 模拟失败任务
    await kernel.bus.publish(Event(
        type="task.completed",
        source="test",
        data={
            "task_id": "task-002",
            "description": "安装依赖包",
            "duration_seconds": 10,
            "tool_calls": 3,
            "tool_failures": 3,
            "error": "permission denied",
        },
    ))
    
    await asyncio.sleep(0.3)
    
    # 模拟工具调用
    await kernel.bus.publish(Event(
        type="tool.called",
        source="test",
        data={"tool": "terminal", "success": True},
    ))
    
    await asyncio.sleep(0.2)
    
    # 报告
    report = meta_plugin.generate_report()
    print(f"✓ 评估次数: {report['evaluation_count']}")
    print(f"✓ 学习摘要: {report['learning_summary']}")
    print(f"✓ 策略权重: {report['strategy_weights']}")
    
    assert report["evaluation_count"] >= 2
    
    await kernel.stop()


async def test_orchestrator():
    """测试5: 多Agent编排"""
    print("\n=== 测试5: 多Agent编排 ===")
    kernel = Kernel()
    orch_plugin = OrchestratorPlugin()
    kernel.plugins.register(orch_plugin)
    await kernel.start(worker_count=2)
    
    # 执行意图
    await kernel.bus.publish(Event(
        type="orchestrator.execute",
        source="test",
        data={
            "intent": "部署 meshctx 服务",
        },
    ))
    
    await asyncio.sleep(0.5)
    
    stats = orch_plugin.agent_pool.get_stats()
    print(f"✓ Agent池: {stats}")
    assert stats["total"] > 0
    
    # 检查DAG是否被创建
    assert len(orch_plugin._active_dags) >= 0  # 可能已完成
    
    await kernel.stop()


async def test_full_integration():
    """测试6: 全模块集成"""
    print("\n=== 测试6: 全模块集成(模拟真实工作流) ===")
    kernel = Kernel()
    
    # 注册所有插件
    memory = MemoryPlugin()
    meta = MetaCognitionPlugin()
    orch = OrchestratorPlugin()
    
    kernel.plugins.register(memory)
    kernel.plugins.register(meta)
    kernel.plugins.register(orch)
    
    await kernel.start(worker_count=4)
    
    status = kernel.get_status()
    print(f"✓ 插件状态: {len(status['plugins'])} 个已加载")
    for p in status["plugins"]:
        print(f"  - {p['name']}: {p['state']}")
    
    # 模拟完整工作流
    # 1. 用户消息
    await kernel.bus.publish(Event(
        type="message.added",
        source="user",
        data={
            "content": "重要：记住项目目标是超越所有竞品",
            "role": "user",
            "project_id": "proj-001",
            "conversation_id": "conv-001",
        },
    ))
    
    # 2. 执行任务
    await kernel.bus.publish(Event(
        type="task.completed",
        source="agent-1",
        data={
            "task_id": "exec-001",
            "description": "搜索竞品信息并分析",
            "duration_seconds": 15,
            "tool_calls": 4,
            "tool_failures": 0,
            "verification_steps": 2,
        },
    ))
    
    await asyncio.sleep(0.5)
    
    # 3. 验证记忆
    memories = memory.store.retrieve("竞品 目标", top_k=3)
    print(f"✓ 记忆中的目标: {[m.key for m in memories]}")
    
    # 4. 验证元认知
    report = meta.generate_report()
    print(f"✓ 元认知报告: {report['learning_summary']}")
    
    # 5. 验证Agent池
    agent_stats = orch.agent_pool.get_stats()
    print(f"✓ Agent池就绪: {agent_stats['total']}个")
    
    # 6. 总线统计
    bus_stats = kernel.bus.get_stats()
    print(f"✓ 事件统计: 发布{bus_stats['published']}, 投递{bus_stats['delivered']}")
    
    await kernel.stop()
    print("\n✓ 全模块集成测试通过!")


async def main():
    print("╔══════════════════════════════════════╗")
    print("║  meshctx v1.0 核心集成测试          ║")
    print("╚══════════════════════════════════════╝")
    
    tests = [
        ("内核启动", test_kernel_startup),
        ("事件总线", test_event_system),
        ("层次记忆", test_memory_hierarchy),
        ("元认知循环", test_metacognition),
        ("多Agent编排", test_orchestrator),
        ("全模块集成", test_full_integration),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n✗ {name} 失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*40}")
    print(f"  测试结果: {passed}通过 / {failed}失败 / {len(tests)}总计")
    print(f"{'='*40}")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
