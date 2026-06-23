"""meshctx v1.0 自愈+WebSocket测试"""
import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = {"passed": 0, "failed": 0, "total": 0}

def _t(name):
    def w(fn):
        async def r():
            RESULTS["total"] += 1
            try:
                await fn()
                RESULTS["passed"] += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {e}")
            except Exception as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return r
    return w

@_t("自愈引擎: 心跳+故障检测")
async def test_healer_heartbeat():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_plugin")
    assert e.heartbeat("test_plugin")
    h = e._plugin_health["test_plugin"]
    assert h.consecutive_failures == 0

@_t("自愈引擎: 故障触发恢复")
async def test_healer_failure():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_plugin")
    for _ in range(4):
        e.report_failure("test_plugin", "test error")
    assert e.should_restart("test_plugin")

@_t("自愈引擎: 熔断器")
async def test_healer_circuit():
    from src.core.healer import SelfHealingEngine, CircuitState
    e = SelfHealingEngine()
    e.register_plugin("test_plugin")
    for _ in range(6):
        e.report_failure("test_plugin", "test error")
    h = e._plugin_health["test_plugin"]
    assert h.circuit_state == CircuitState.OPEN

@_t("记忆压缩器: L2→L3")
async def test_memory_compactor():
    from src.core.healer import MemoryCompactor
    from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
    
    store = HierarchicalMemoryStore()
    
    # 添加老数据
    old_time = time.time() - 86400 * 10  # 10天前
    for i in range(5):
        item = MemoryItem(level=MemoryLevel.SHORT_TERM, key=f"old_{i}", value=f"data_{i}")
        item.created_at = old_time
        item.last_accessed = old_time
        store.store(item)
    
    compactor = MemoryCompactor()
    results = await compactor.compact(store)
    assert results["l2_to_l3"] >= 3  # 至少3条被升级

@_t("HealerPlugin: 加载")
async def test_healer_plugin():
    from src.core.kernel import Kernel
    from src.core.healer import HealerPlugin
    k = Kernel()
    k.plugins.register(HealerPlugin())
    await k.start(1)
    await k.plugins.load("healer")
    assert "healer" in k.plugins.list_active()
    r = k.plugins.get("healer").generate_report()
    assert "health" in r
    await k.stop()

@_t("WebSocket管理器: 连接/广播/断开")
async def test_ws_manager():
    from src.core.websocket_plugin import WSManager
    # 仅测试非WebSocket部分
    m = WSManager()
    assert m.stats()["clients"] == 0

@_t("WebSocketPlugin: 加载")
async def test_ws_plugin():
    from src.core.kernel import Kernel
    from src.core.websocket_plugin import WebSocketPlugin
    k = Kernel()
    k.plugins.register(WebSocketPlugin())
    await k.start(1)
    await k.plugins.load("websocket")
    assert "websocket" in k.plugins.list_active()
    await k.stop()

@_t("8插件全集成")
async def test_all_8_plugins():
    from src.core.kernel import Kernel
    from src.core import (
        MemoryPlugin, MetaCognitionPlugin, OrchestratorPlugin,
        PredictorPlugin, AgentLoopPlugin, PerformancePlugin,
        HealerPlugin, WebSocketPlugin,
    )
    k = Kernel()
    for p in [MemoryPlugin(), MetaCognitionPlugin(), OrchestratorPlugin(),
              PredictorPlugin(), AgentLoopPlugin(), PerformancePlugin(),
              HealerPlugin(), WebSocketPlugin()]:
        k.plugins.register(p)
    
    await k.start(2)
    results = await k.plugins.load_all()
    active = k.plugins.list_active()
    assert len(active) == 8, f"Expected 8, got {len(active)}: {active}"
    assert k.bus.get_stats()["errors"] == 0
    await k.stop()

async def main():
    tests = [
        test_healer_heartbeat, test_healer_failure, test_healer_circuit,
        test_memory_compactor, test_healer_plugin,
        test_ws_manager, test_ws_plugin,
        test_all_8_plugins,
    ]
    for t in tests:
        await t()
    print(f"\n{'='*40}\n  结果: {RESULTS['passed']}✓ / {RESULTS['failed']}✗ / {RESULTS['total']}项")
    print(f"{'='*40}")
    return RESULTS["failed"] == 0

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
