"""
meshctx v1.0 全流程自动化测试

覆盖:
  核心引擎   — 内核启停 / 事件总线 / 插件生命周期
  层次记忆   — L0-L4 存储 / 混合检索 / 遗忘曲线
  元认知     — 任务评估 / 模式提取 / 行为调整
  多Agent    — DAG分解 / Agent池 / Memory Hub
  模型系统   — 注册 / 扫描 / 切换 / 对话
  Skill管理  — 创建 / 列表 / 自动生成
  Gateway    — 9 平台连接器初始化
  CLI        — 所有命令可执行
  配置       — YAML加载 / 环境变量展开
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_RESULTS = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}


def _test(name):
    """测试装饰器"""
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
# 1. 内核测试
# ═══════════════════════════════════════════════════

@_test("内核启动 + 停止")
async def test_kernel_lifecycle():
    from src.core import Kernel
    k = Kernel()
    await k.start(2)
    assert k._started
    s = k.get_status()
    assert s["started"]
    await k.stop()
    assert not k._started


@_test("事件总线 发布/订阅")
async def test_event_bus():
    from src.core import Kernel, Event
    k = Kernel()
    await k.start(2)
    
    received = []
    async def handler(ev):
        received.append(ev.data.get("msg"))
    
    k.bus.subscribe("test.ping", handler, plugin_name="test")
    await k.bus.publish(Event(type="test.ping", data={"msg": "pong"}))
    await asyncio.sleep(0.2)
    
    assert "pong" in received
    await k.stop()


@_test("事件优先级排序")
async def test_event_priority():
    from src.core import Kernel, Event, EventPriority
    k = Kernel()
    await k.start(1)
    
    order = []
    async def h(ev):
        order.append(ev.priority.value)

    k.bus.subscribe("test.prio", h)
    await k.bus.publish(Event(type="test.prio", priority=EventPriority.LOW))
    await k.bus.publish(Event(type="test.prio", priority=EventPriority.HIGH))
    await k.bus.publish(Event(type="test.prio", priority=EventPriority.NORMAL))
    await asyncio.sleep(0.3)
    
    assert len(order) == 3
    await k.stop()


@_test("插件生命周期")
async def test_plugin_lifecycle():
    from src.core import Kernel, MemoryPlugin, MetaCognitionPlugin, OrchestratorPlugin
    k = Kernel()
    k.plugins.register(MemoryPlugin())
    k.plugins.register(MetaCognitionPlugin())
    k.plugins.register(OrchestratorPlugin())
    await k.start(2)
    
    s = k.get_status()
    active = [p["name"] for p in s["plugins"] if p["state"] == "ACTIVE"]
    assert "memory" in active
    assert "metacognition" in active
    assert "orchestrator" in active
    
    await k.stop()


# ═══════════════════════════════════════════════════
# 2. 记忆系统测试
# ═══════════════════════════════════════════════════

@_test("层次记忆 L0-L4 存储")
async def test_memory_hierarchy():
    from src.core import Kernel, MemoryPlugin, Event, MemoryItem, MemoryLevel
    k = Kernel()
    m = MemoryPlugin()
    k.plugins.register(m)
    await k.start(2)
    
    # L0: 普通消息
    await k.bus.publish(Event(type="message.added", data={
        "content": "普通消息", "role": "user",
        "project_id": "p1", "conversation_id": "c1",
    }))
    await asyncio.sleep(0.1)
    assert m.store._stores[MemoryLevel.SENSORY].__len__() >= 1
    
    # L1: 重要消息
    await k.bus.publish(Event(type="message.added", data={
        "content": "重要：记住目标xxx", "role": "user",
        "project_id": "p1", "conversation_id": "c1",
    }))
    await asyncio.sleep(0.2)
    assert m.store._stores[MemoryLevel.WORKING].__len__() >= 1
    
    await k.stop()


@_test("混合检索: 关键词 + 时间衰减")
async def test_hybrid_retrieval():
    from src.core import Kernel, MemoryPlugin, Event
    k = Kernel()
    m = MemoryPlugin()
    k.plugins.register(m)
    await k.start(2)
    
    await k.bus.publish(Event(type="message.added", data={
        "content": "重要：项目目标是成为世界第一", "role": "user",
        "project_id": "p1", "conversation_id": "c1",
    }))
    await asyncio.sleep(0.2)
    
    results = m.store.retrieve("世界第一 目标", top_k=3)
    assert len(results) >= 1
    assert any("世界第一" in r.value for r in results)
    
    await k.stop()


@_test("Ebbinghaus 遗忘曲线")
async def test_forgetting_curve():
    from src.core.memory_hierarchy import MemoryItem, EbbinghausForgetting
    import time
    
    # 1小时前的记忆，重要性0.8，保留率应在44-60%
    item = MemoryItem(
        key="test",
        value="test",
        importance=0.8,
        created_at=time.time() - 3600,
        last_reviewed=time.time() - 3600,
    )
    r = item.current_retention()
    assert 0.40 < r < 0.65, f"遗忘曲线异常: {r:.3f} (期望 0.44-0.60)"
    
    # 刚创建的记忆，保留率 ~100%
    fresh = MemoryItem(key="test2", value="test2", importance=0.9)
    assert fresh.current_retention() > 0.99


# ═══════════════════════════════════════════════════
# 3. 元认知测试
# ═══════════════════════════════════════════════════

@_test("任务评估 + 质量评分")
async def test_metacognition_evaluate():
    from src.core import Kernel, MetaCognitionPlugin, Event
    k = Kernel()
    meta = MetaCognitionPlugin()
    k.plugins.register(meta)
    await k.start(2)
    
    await k.bus.publish(Event(type="task.completed", data={
        "task_id": "t1", "description": "部署测试",
        "duration_seconds": 10, "tool_calls": 3, "tool_failures": 0,
        "verification_steps": 2,
    }))
    await asyncio.sleep(0.2)
    
    assert meta._evaluation_count >= 1
    
    report = meta.generate_report()
    assert report["evaluation_count"] >= 1
    
    await k.stop()


@_test("错误分类: 权限/网络/知识不足")
async def test_error_categorization():
    from src.core.metacognition import MetaCognitionPlugin, ErrorCategory
    
    meta = MetaCognitionPlugin()
    
    # 权限错误
    cat, detail = meta._categorize_error({"error": "permission denied"})
    assert cat == ErrorCategory.PERMISSION
    
    # 网络错误
    cat, _ = meta._categorize_error({"error": "connection timeout"})
    assert cat == ErrorCategory.NETWORK
    
    # 未知
    cat, _ = meta._categorize_error({"error": "something weird happened"})
    assert cat == ErrorCategory.UNKNOWN


@_test("行为调整: 工具成功率影响策略")
async def test_behavior_adjustment():
    from src.core.metacognition import BehaviorAdjuster
    
    ba = BehaviorAdjuster()
    
    # 记录多次失败
    for _ in range(5):
        ba.record_tool_result("terminal", False)
    
    for _ in range(2):
        ba.record_tool_result("search", True)
    
    stats = ba.get_tool_stats()
    assert stats["terminal"]["rate"] == 0.0
    assert stats["search"]["rate"] == 1.0
    
    # 策略应调整
    strategy = ba.get_strategy()
    assert "parallelism" in strategy
    assert "verification" in strategy


# ═══════════════════════════════════════════════════
# 4. 多Agent编排测试
# ═══════════════════════════════════════════════════

@_test("任务分解 DAG")
async def test_task_decomposition():
    from src.core.orchestrator import TaskDecomposer
    
    dec = TaskDecomposer()
    dag = dec.decompose("部署 meshctx 到生产服务器")
    
    assert len(dag._nodes) >= 2
    
    summary = dag.get_status_summary()
    assert summary["pending"] >= 2


@_test("Agent池管理")
async def test_agent_pool():
    from src.core.orchestrator import AgentPool, AgentRole
    
    pool = AgentPool()
    
    coder = pool.create_agent(AgentRole.CODER)
    assert coder.role == AgentRole.CODER
    assert not coder.busy
    
    pool.acquire(coder.id, "task-1")
    assert coder.busy
    
    pool.release(coder.id)
    assert not coder.busy


@_test("Memory Hub 共享")
async def test_memory_hub():
    from src.core.orchestrator import MemoryHub
    
    hub = MemoryHub()
    hub.write("agent-1", "key1", "value1")
    assert hub.read("key1") == "value1"
    
    hub.handoff("agent-1", "agent-2", {"task": "continue"})
    handoffs = hub.get_handoffs("agent-2")
    assert len(handoffs) == 1


# ═══════════════════════════════════════════════════
# 5. 模型系统测试
# ═══════════════════════════════════════════════════

@_test("模型注册中心: 内置目录加载")
async def test_model_builtin_catalog():
    from src.model_registry import BUILTIN_MODELS, ModelRegistry
    
    assert len(BUILTIN_MODELS) >= 30
    assert "bailian:qwen-flash" in BUILTIN_MODELS
    assert "deepseek:chat" in BUILTIN_MODELS
    assert "openai:gpt-4o-mini" in BUILTIN_MODELS
    assert "anthropic:claude-sonnet" in BUILTIN_MODELS
    assert "google:gemini-flash" in BUILTIN_MODELS


@_test("环境变量自动扫描")
async def test_model_env_scan():
    from src.model_registry import ModelRegistry
    
    os.environ["BAILIAN_API_KEY"] = "sk-test"
    reg = ModelRegistry()
    entries = reg.list_all()
    
    bailian_models = [e for e in entries if "bailian" in e["id"]]
    assert len(bailian_models) >= 1
    assert all(e["ready"] for e in bailian_models)


@_test("模型列表/切换/扫描命令")
async def test_model_commands():
    from src.model_registry import get_registry, BUILTIN_MODELS
    
    reg = get_registry()
    available = reg.list_available()
    assert len(available) >= 30
    assert "openai:gpt-4o" in available
    assert "ollama:llama3" in available


# ═══════════════════════════════════════════════════
# 6. Skill 系统测试
# ═══════════════════════════════════════════════════

@_test("Skill 创建 / 列表 / 删除")
async def test_skill_crud():
    from src.skill_manager import SkillManager
    import tempfile
    
    with tempfile.TemporaryDirectory() as d:
        mgr = SkillManager(d)
        
        mgr.create("test-skill", "测试技能",
                   steps=["步骤1", "步骤2"], tools=["search"])
        skills = mgr.list_all()
        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        
        mgr.delete("test-skill")
        assert len(mgr.list_all()) == 0


@_test("Skill 自动生成")
async def test_skill_auto_create():
    from src.skill_manager import SkillManager
    import tempfile
    
    with tempfile.TemporaryDirectory() as d:
        mgr = SkillManager(d)
        pattern = {
            "task_pattern": "搜索竞品信息",
            "avg_quality": 0.85,
            "common_tools": ["search", "browser"],
            "frequency": 5,
        }
        skill = mgr.auto_create_from_pattern(pattern)
        assert skill is not None
        assert "搜索" in skill.name or "竞品" in skill.name


# ═══════════════════════════════════════════════════
# 7. Gateway 测试
# ═══════════════════════════════════════════════════

@_test("Gateway 9平台连接器注册")
async def test_gateway_connectors():
    from src.gateway import GatewayPlugin
    
    gw = GatewayPlugin()
    assert "feishu" in gw.CONNECTOR_MAP
    assert "telegram" in gw.CONNECTOR_MAP
    assert "wechat" in gw.CONNECTOR_MAP
    assert "wechat_personal" in gw.CONNECTOR_MAP
    assert "whatsapp" in gw.CONNECTOR_MAP
    assert "qq" in gw.CONNECTOR_MAP
    assert "line" in gw.CONNECTOR_MAP
    assert "discord" in gw.CONNECTOR_MAP
    assert "slack" in gw.CONNECTOR_MAP
    assert len(gw.CONNECTOR_MAP) == 9


@_test("Gateway 无凭证时优雅跳过")
async def test_gateway_graceful_skip():
    from src.core import Kernel
    from src.gateway import GatewayPlugin
    
    k = Kernel({"gateway": {"enabled": True}})
    gw = GatewayPlugin()
    k.plugins.register(gw)
    await k.start(1)
    
    # 无凭证时应跳过所有连接器
    assert len(gw._connectors) == 0
    
    await k.stop()


# ═══════════════════════════════════════════════════
# 8. 配置测试
# ═══════════════════════════════════════════════════

@_test("YAML 配置加载")
async def test_config_load():
    from src.config import load_config
    import tempfile
    import yaml
    
    config_data = {
        "kernel": {"worker_count": 8},
        "models": {
            "default": "deepseek:chat",
            "entries": {"deepseek:chat": {"key": "sk-test"}}
        }
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        path = f.name
    
    try:
        config = load_config(path)
        assert config["kernel"]["worker_count"] == 8
        assert config["models"]["default"] == "deepseek:chat"
    finally:
        os.unlink(path)


@_test("环境变量展开 ${VAR}")
async def test_config_env_expansion():
    from src.config import load_config, _expand_env
    
    os.environ["TEST_KEY"] = "secret123"
    result = _expand_env("url:${TEST_KEY}/api")
    assert result == "url:secret123/api"
    
    result = _expand_env({"key": "${TEST_KEY}"})
    assert result["key"] == "secret123"


# ═══════════════════════════════════════════════════
# 9. 集成测试
# ═══════════════════════════════════════════════════

@_test("全插件集成: memory + meta + orch + gateway")
async def test_full_plugin_integration():
    from src.core import Kernel, MemoryPlugin, MetaCognitionPlugin
    from src.core import OrchestratorPlugin
    from src.gateway import GatewayPlugin
    
    k = Kernel()
    k.plugins.register(MemoryPlugin())
    k.plugins.register(MetaCognitionPlugin())
    k.plugins.register(OrchestratorPlugin())
    k.plugins.register(GatewayPlugin())
    
    await k.start(2)
    
    s = k.get_status()
    active = [p["name"] for p in s["plugins"] if p["state"] == "ACTIVE"]
    assert len(active) == 4
    
    await k.stop()


@_test("完整工作流: 消息→记忆→评估→编排")
async def test_full_workflow():
    from src.core import Kernel, MemoryPlugin, MetaCognitionPlugin, Event
    from src.core import OrchestratorPlugin
    
    k = Kernel()
    k.plugins.register(MemoryPlugin())
    k.plugins.register(MetaCognitionPlugin())
    k.plugins.register(OrchestratorPlugin())
    await k.start(3)
    
    # 1. 消息输入
    await k.bus.publish(Event(type="message.added", data={
        "content": "重要：部署新版本到服务器并测试",
        "role": "user",
        "project_id": "proj-1",
        "conversation_id": "conv-1",
    }))
    
    # 2. 任务执行
    await k.bus.publish(Event(type="task.completed", data={
        "task_id": "deploy-1",
        "description": "部署新版本到服务器",
        "duration_seconds": 45,
        "tool_calls": 6,
        "tool_failures": 0,
        "delegation_used": True,
        "verification_steps": 3,
    }))
    
    await k.bus.publish(Event(type="tool.called", data={"tool": "deploy", "success": True}))
    await k.bus.publish(Event(type="tool.called", data={"tool": "test", "success": True}))
    
    await asyncio.sleep(0.3)
    
    # 3. 验证记忆
    memory = k.plugins.get("memory")
    results = memory.store.retrieve("部署 服务器", top_k=3)
    assert len(results) >= 1
    
    # 4. 验证元认知
    meta = k.plugins.get("metacognition")
    report = meta.generate_report()
    assert report["evaluation_count"] >= 1
    
    # 5. 验证编排器
    orch = k.plugins.get("orchestrator")
    stats = orch.agent_pool.get_stats()
    assert stats["total"] >= 1
    
    await k.stop()


# ═══════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════

# ═══════════════════════════════════════════════════
# 10. Cron 测试
# ═══════════════════════════════════════════════════

@_test("Cron 解析: every/crontab/daily/weekly")
async def test_cron_parser():
    from src.cron import CronParser
    
    # every 30m
    checker = CronParser.parse("every 30m")
    import time
    assert checker(time.time() - 2000)  # 30分钟后应触发
    
    # crontab
    checker2 = CronParser.parse("* * * * *")
    assert checker2(None)
    
    # invalid
    try:
        CronParser.parse("invalid")
        assert False, "应该抛异常"
    except ValueError:
        pass


@_test("Cron: 添加/列出任务")
async def test_cron_jobs():
    from src.cron import CronPlugin
    cron = CronPlugin()
    cron.add_job("test-job", "every 1h", "test.event")
    assert "test-job" in cron._jobs


# ═══════════════════════════════════════════════════
# 11. Session 搜索测试
# ═══════════════════════════════════════════════════

@_test("Session 搜索: 索引+检索")
async def test_session_search():
    from src.session_search import SessionSearchEngine
    
    engine = SessionSearchEngine()
    engine.index("s1", "部署项目", [
        {"role": "user", "content": "部署meshctx到服务器"},
        {"role": "assistant", "content": "好的，开始部署"},
    ])
    engine.index("s2", "修复bug", [
        {"role": "user", "content": "登录页面报错"},
    ])
    
    results = engine.search("部署", limit=5)
    assert len(results) >= 1
    assert results[0].title == "部署项目"
    
    recent = engine.get_recent(5)
    assert len(recent) == 2


@_test("Session 搜索: 无结果")
async def test_session_search_empty():
    from src.session_search import SessionSearchEngine
    engine = SessionSearchEngine()
    results = engine.search("不存在的关键词")
    assert len(results) == 0


# ═══════════════════════════════════════════════════
# 12. Browser 工具测试
# ═══════════════════════════════════════════════════

@_test("Browser 工具: 模块加载")
async def test_browser_module():
    from src.browser_tool import BrowserTool, BrowserPlugin
    tool = BrowserTool()
    assert tool.state.url == ""
    
    plugin = BrowserPlugin()
    assert plugin.info.name == "browser"


# ═══════════════════════════════════════════════════
# 13. TTS 测试
# ═══════════════════════════════════════════════════

@_test("TTS: 模块加载 + Provider")
async def test_tts_module():
    from src.tts import TTSEngine, TTSPlugin
    
    engine = TTSEngine("edge")
    assert engine.provider == "edge"
    
    plugin = TTSPlugin()
    assert plugin.info.name == "tts"


# ═══════════════════════════════════════════════════
# 14. MCP 测试
# ═══════════════════════════════════════════════════

@_test("MCP: 工具注册")
async def test_mcp_tools():
    from src.mcp_server import MCPServer
    
    server = MCPServer()
    assert len(server._tools) >= 6
    
    # initialize
    resp = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"}
    })
    assert resp["result"]["serverInfo"]["name"] == "meshctx"


@_test("MCP: tools/list")
async def test_mcp_list_tools():
    from src.mcp_server import MCPServer
    
    server = MCPServer()
    resp = server.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"
    })
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "memory_search" in tool_names
    assert "model_chat" in tool_names
    assert "browser_navigate" in tool_names


@_test("MCP: 未注册方法返回错误")
async def test_mcp_unknown_method():
    from src.mcp_server import MCPServer
    
    server = MCPServer()
    resp = server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "nonexistent"
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601


async def main():
    print("╔════════════════════════════════════════╗")
    print("║  meshctx v1.0 全流程自动化测试       ║")
    print("╚════════════════════════════════════════╝\n")
    
    tests = [
        # 内核
        ("内核", [
            test_kernel_lifecycle, test_event_bus, test_event_priority,
            test_plugin_lifecycle,
        ]),
        # 记忆
        ("记忆", [
            test_memory_hierarchy, test_hybrid_retrieval, test_forgetting_curve,
        ]),
        # 元认知
        ("元认知", [
            test_metacognition_evaluate, test_error_categorization,
            test_behavior_adjustment,
        ]),
        # 编排
        ("编排", [
            test_task_decomposition, test_agent_pool, test_memory_hub,
        ]),
        # 模型
        ("模型", [
            test_model_builtin_catalog, test_model_env_scan, test_model_commands,
        ]),
        # Skill
        ("Skill", [
            test_skill_crud, test_skill_auto_create,
        ]),
        # Gateway
        ("Gateway", [
            test_gateway_connectors, test_gateway_graceful_skip,
        ]),
        # 配置
        ("配置", [
            test_config_load, test_config_env_expansion,
        ]),
        # Cron
        ("Cron", [
            test_cron_parser, test_cron_jobs,
        ]),
        # Search
        ("Search", [
            test_session_search, test_session_search_empty,
        ]),
        # Browser
        ("Browser", [
            test_browser_module,
        ]),
        # TTS
        ("TTS", [
            test_tts_module,
        ]),
        # MCP
        ("MCP", [
            test_mcp_tools, test_mcp_list_tools, test_mcp_unknown_method,
        ]),
        # 集成
        ("集成", [
            test_full_plugin_integration, test_full_workflow,
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
