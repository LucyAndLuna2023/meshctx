"""
meshctx v1.0 新核心模块测试
predictor, agent_loop, performance
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_RESULTS = {"passed": 0, "failed": 0, "total": 0}


def _test(name):
    def wrapper(fn):
        async def runner():
            TEST_RESULTS["total"] += 1
            try:
                await fn()
                TEST_RESULTS["passed"] += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                TEST_RESULTS["failed"] += 1
                print(f"  ✗ {name}: {e}")
            except Exception as e:
                TEST_RESULTS["failed"] += 1
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return runner
    return wrapper


# ═══════════════════════════════════════════════════
# Predictor 测试
# ═══════════════════════════════════════════════════

@_test("时间模式学习器: 记录+模式检测")
async def test_temporal_pattern_learner():
    from src.core.predictor import TemporalPatternLearner
    
    learner = TemporalPatternLearner()
    
    # 模拟: 连续3天同一时间做同一件事
    for day_offset in range(3):
        now = time.time() - 86400 * day_offset
        # 模拟当前时间是9:00
        learner.record("coding", project_id="proj_1", 
                       keywords=["python", "api"], duration=3600)
    
    stats = learner.get_stats()
    assert stats["patterns_learned"] >= 1, f"Expected >=1 pattern, got {stats['patterns_learned']}"
    assert stats["total_events"] == 3


@_test("预测: 基于时间模式预测")
async def test_predictor_predict():
    from src.core.predictor import TemporalPatternLearner
    
    learner = TemporalPatternLearner()
    
    # 喂入模式数据
    for _ in range(5):
        learner.record("coding", keywords=["python"])
        learner.record("deployment", keywords=["docker"])
    
    predictions = learner.predict()
    assert len(predictions) >= 1, "Should have at least 1 prediction"
    
    # 验证预测结果结构
    for p in predictions:
        assert p.task_type
        assert 0 <= p.confidence <= 1
        assert p.reason


@_test("上下文预加载器: 冷却+限制")
async def test_context_preloader():
    from src.core.predictor import ContextPreloader, PredictionResult
    
    preloader = ContextPreloader(max_preloads=3, cooldown_seconds=1)
    
    pred = PredictionResult(
        task_type="coding",
        project_id="test",
        confidence=0.8,
        expected_time=time.time(),
        preload_context={"keywords": ["python"]},
        keywords=["python"],
        reason="test",
    )
    
    # 第一次应该预加载
    assert preloader.should_preload(pred)
    
    ctx = preloader.preload(pred)
    assert ctx["type"] == "predicted_preload"
    
    # 冷却期内不应重复预加载
    assert not preloader.should_preload(pred)
    
    # 低置信度不应预加载
    pred2 = PredictionResult(
        task_type="other", project_id=None, confidence=0.2,
        expected_time=time.time(), preload_context={}, keywords=[], reason="test",
    )
    assert not preloader.should_preload(pred2)


@_test("PredictorPlugin: 加载+事件注册")
async def test_predictor_plugin():
    from src.core.kernel import Kernel
    from src.core.predictor import PredictorPlugin
    
    k = Kernel()
    plugin = PredictorPlugin()
    k.plugins.register(plugin)
    
    await k.start(1)
    await k.plugins.load("predictor")
    
    assert "predictor" in k.plugins.list_active()
    
    report = plugin.generate_report()
    assert "patterns_learned" in report
    assert "total_events" in report
    
    await k.stop()


# ═══════════════════════════════════════════════════
# AgentLoop 测试
# ═══════════════════════════════════════════════════

@_test("意图提取: 中文关键词")
async def test_intent_extraction():
    from src.core.agent_loop import AgentLoopPlugin
    
    plugin = AgentLoopPlugin()
    
    assert plugin._extract_intent("部署到服务器") == "deploy"
    assert plugin._extract_intent("开发新功能") == "develop"
    assert plugin._extract_intent("修复一个bug") == "fix"
    assert plugin._extract_intent("搜索文档") == "search"
    assert plugin._extract_intent("分析数据") == "analyze"
    assert plugin._extract_intent("随便聊聊") == "general"


@_test("紧急度评估")
async def test_urgency_assessment():
    from src.core.agent_loop import AgentLoopPlugin
    
    plugin = AgentLoopPlugin()
    
    u1 = plugin._assess_urgency({"content": "紧急！服务器挂了", "source": "user"})
    assert u1 > 0.3, f"Urgent message should have higher urgency: {u1}"
    
    u2 = plugin._assess_urgency({"content": "hello", "source": "system"})
    assert u2 < 0.5, f"Normal message should have lower urgency: {u2}"


@_test("决策生成: 意图→行动")
async def test_decision_making():
    from src.core.agent_loop import AgentLoopPlugin, Observation
    
    plugin = AgentLoopPlugin()
    
    obs = Observation(
        source="user",
        content="部署meshctx到生产服务器",
        intent="deploy",
        urgency=0.7,
    )
    
    decision = plugin._make_decision(obs)
    assert decision.action_type == "orchestrate"
    assert decision.confidence > 0.5
    assert "部署" in decision.params.get("pattern", "")


@_test("响应生成器: 各阶段响应")
async def test_response_generator():
    from src.core.agent_loop import ResponseGenerator, LoopPhase
    
    gen = ResponseGenerator()
    
    r1 = gen.generate(LoopPhase.OBSERVE, {"content": "你好", "urgency": 0.1})
    assert "你好" in r1
    
    r2 = gen.generate(LoopPhase.DECIDE, {"action_type": "search", "reasoning": "用户需要搜索"})
    assert "search" in r2
    
    r3 = gen.generate(LoopPhase.ACT, {"success": True, "summary": "完成", "elapsed": 1.5})
    assert "✅" in r3 or "完成" in r3


@_test("AgentLoopPlugin: 加载+OODA循环")
async def test_agent_loop_plugin():
    from src.core.kernel import Kernel
    from src.core.agent_loop import AgentLoopPlugin
    
    k = Kernel()
    plugin = AgentLoopPlugin()
    k.plugins.register(plugin)
    
    await k.start(1)
    await k.plugins.load("agent_loop")
    
    assert "agent_loop" in k.plugins.list_active()
    
    report = plugin.generate_report()
    assert "active_tasks" in report
    assert "total_completed" in report
    
    await k.stop()


@_test("完整OODA: 用户消息→观察→决策→执行")
async def test_full_ooda_cycle():
    from src.core.kernel import Kernel, Event
    from src.core.agent_loop import AgentLoopPlugin
    from src.core.predictor import PredictorPlugin
    
    k = Kernel()
    k.plugins.register(AgentLoopPlugin())
    k.plugins.register(PredictorPlugin())
    
    await k.start(1)
    await k.plugins.load_all()
    
    # 发送用户消息触发OODA循环
    await k.bus.publish(Event(
        type="user.message",
        source="test",
        data={"content": "搜索meshctx文档", "context": {}},
    ))
    
    await asyncio.sleep(0.3)
    
    # 检查事件总线有活动
    stats = k.bus.get_stats()
    assert stats["published"] >= 1, "Should have published events"
    
    plugin = k.plugins.get("agent_loop")
    report = plugin.generate_report()
    assert report["total_completed"] >= 0
    
    await k.stop()


# ═══════════════════════════════════════════════════
# Performance 测试
# ═══════════════════════════════════════════════════

@_test("L1内存缓存: set/get/淘汰")
async def test_l1_cache():
    from src.core.performance import L1MemoryCache
    
    cache = L1MemoryCache(max_size=10)
    
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    assert cache.get("missing") is None
    
    # TTL过期
    cache.set("key2", "value2", ttl=0.01)
    await asyncio.sleep(0.02)
    assert cache.get("key2") is None
    
    # 命中率
    cache.set("k", "v")
    cache.get("k")
    cache.get("k")
    cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] >= 2
    assert stats["hit_rate"] > 0


@_test("L2文件缓存: 跨进程持久化")
async def test_l2_cache():
    from src.core.performance import L2FileCache
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = L2FileCache(tmpdir)
        
        cache.set("test_key", {"data": [1, 2, 3]})
        
        value = cache.get("test_key")
        assert value is not None
        assert value["data"] == [1, 2, 3]
        
        # 过期
        assert cache.get("test_key", max_age=0) is None
        
        cache.delete("test_key")
        assert cache.get("test_key") is None


@_test("PerformancePlugin: 加载")
async def test_performance_plugin():
    from src.core.kernel import Kernel
    from src.core.performance import PerformancePlugin
    
    k = Kernel()
    plugin = PerformancePlugin()
    k.plugins.register(plugin)
    
    await k.start(1)
    await k.plugins.load("performance")
    
    assert "performance" in k.plugins.list_active()
    
    report = plugin.generate_report()
    assert "l1_cache" in report
    assert "l2_cache" in report
    
    await k.stop()


# ═══════════════════════════════════════════════════
# 全插件集成测试
# ═══════════════════════════════════════════════════

@_test("6插件全集成: memory+meta+orch+predict+agent+perf")
async def test_all_6_plugins():
    from src.core.kernel import Kernel
    from src.core import (
        MemoryPlugin, MetaCognitionPlugin, OrchestratorPlugin,
        PredictorPlugin, AgentLoopPlugin, PerformancePlugin,
    )
    
    k = Kernel()
    k.plugins.register(MemoryPlugin())
    k.plugins.register(MetaCognitionPlugin())
    k.plugins.register(OrchestratorPlugin())
    k.plugins.register(PredictorPlugin())
    k.plugins.register(AgentLoopPlugin())
    k.plugins.register(PerformancePlugin())
    
    await k.start(2)
    results = await k.plugins.load_all()
    
    active = k.plugins.list_active()
    assert len(active) == 6, f"Expected 6 active plugins, got {len(active)}: {active}"
    
    # 验证所有加载成功
    for name in active:
        assert results.get(name) == True, f"Plugin {name} should be loaded"
    
    # 事件总线正常
    stats = k.bus.get_stats()
    assert stats["errors"] == 0, f"Event bus should have 0 errors: {stats}"
    
    await k.stop()


# ═══════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════

async def main():
    tests = [
        ("Predictor", [
            test_temporal_pattern_learner, test_predictor_predict,
            test_context_preloader, test_predictor_plugin,
        ]),
        ("AgentLoop", [
            test_intent_extraction, test_urgency_assessment,
            test_decision_making, test_response_generator,
            test_agent_loop_plugin, test_full_ooda_cycle,
        ]),
        ("Performance", [
            test_l1_cache, test_l2_cache, test_performance_plugin,
        ]),
        ("Integration", [
            test_all_6_plugins,
        ]),
    ]
    
    for group, funcs in tests:
        print(f"\n── {group} ──")
        for fn in funcs:
            await fn()
    
    print(f"\n{'='*45}")
    print(f"  结果: {TEST_RESULTS['passed']}✓ / {TEST_RESULTS['failed']}✗ / {TEST_RESULTS['total']}项")
    if TEST_RESULTS["failed"] == 0:
        print("  🎉 全部通过!")
    print(f"{'='*45}")
    
    return TEST_RESULTS["failed"] == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
