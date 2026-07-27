"""agent_registry 单元测试"""
import asyncio
import pytest
import sys
sys.path.insert(0, "..")

from agent_registry import AgentRegistry, AgentInfo, AgentStatus, AgentCapability


@pytest.fixture
def registry():
    return AgentRegistry(backend="memory")


@pytest.fixture
def sample_agent():
    return AgentInfo(
        agent_id="test-001",
        role="test_role",
        status=AgentStatus.IDLE,
        capabilities=[AgentCapability(name="echo", proficiency=0.9)],
    )


def test_register(registry, sample_agent):
    agent_id = asyncio.run(registry.register(sample_agent))
    assert agent_id == "test-001"


def test_heartbeat(registry, sample_agent):
    asyncio.run(registry.register(sample_agent))
    ok = asyncio.run(registry.heartbeat("test-001", load=0.5))
    assert ok is True


def test_discover_by_capability(registry, sample_agent):
    asyncio.run(registry.register(sample_agent))
    agents = asyncio.run(registry.discover(capability="echo"))
    assert len(agents) == 1
    assert agents[0].agent_id == "test-001"


def test_discover_nonexistent(registry):
    agents = asyncio.run(registry.discover(capability="nonexistent"))
    assert len(agents) == 0


def test_route(registry, sample_agent):
    asyncio.run(registry.register(sample_agent))
    best = asyncio.run(registry.route({"capability": "echo"}))
    assert best is not None
    assert best.agent_id == "test-001"


def test_drain(registry, sample_agent):
    asyncio.run(registry.register(sample_agent))
    asyncio.run(registry.drain("test-001"))
    agent = asyncio.run(registry.list_all())[0]
    assert agent.status == AgentStatus.OFFLINE


def test_gen_id_unique():
    ids = set()
    import agent_registry as ar
    for _ in range(100):
        ids.add(ar._gen_id("test"))
    assert len(ids) == 100, f"只有 {len(ids)} 个唯一ID"
