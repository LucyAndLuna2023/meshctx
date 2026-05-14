"""Test v1.6.2 — Multi-Agent Collaboration
Covers: AgentNode, MessageBus, CollaborationProtocol, AgentManager"""
import os, sys, time, json, asyncio
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.multi_agent import (
    AgentNode, AgentMessage, MessageBus, CollaborationProtocol,
    AgentManager, AgentCapability, MessageType,
)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestAgentMessage:
    def test_create(self):
        msg = AgentMessage(sender_id="s1", target_id="t1", topic="test",
                           payload={"key": "value"})
        assert msg.msg_id
        assert msg.msg_type == MessageType.BROADCAST
        assert not msg.is_expired()

    def test_expiry(self):
        msg = AgentMessage(timestamp=time.time() - 60, ttl=10)
        assert msg.is_expired()


class TestAgentNode:
    @pytest.mark.asyncio
    async def test_create(self):
        agent = AgentNode("a1", "TestAgent")
        assert agent.agent_id == "a1"
        assert agent.status == "idle"
        assert agent.can_accept_tasks

    @pytest.mark.asyncio
    async def test_get_info(self):
        agent = AgentNode("a1", "TestAgent")
        info = agent.get_info()
        assert info["name"] == "TestAgent"
        assert info["status"] == "idle"
        assert info["processed_messages"] == 0

    @pytest.mark.asyncio
    async def test_capability_declaration(self):
        caps = [AgentCapability(name="search", description="Search tool"),
                AgentCapability(name="analyze", description="Analysis engine")]
        agent = AgentNode("a1", "SmartAgent", capabilities=caps)
        assert len(agent.capabilities) == 2
        assert agent.capabilities[0].name == "search"

    @pytest.mark.asyncio
    async def test_send_receive(self):
        bus = MessageBus()
        a1 = AgentNode("a1", "Sender")
        a2 = AgentNode("a2", "Receiver")
        bus.register(a1)
        bus.register(a2)

        await a1.send("a2", "hello", {"msg": "ping"})
        # Check receiver's queue has a message
        assert a2._message_queue.qsize() == 1
        msg = await a2._message_queue.get()
        assert msg.payload["msg"] == "ping"
        assert msg.sender_id == "a1"

    @pytest.mark.asyncio
    async def test_broadcast(self):
        bus = MessageBus()
        a1 = AgentNode("a1", "Broadcaster")
        a2 = AgentNode("a2", "Listener1")
        a3 = AgentNode("a3", "Listener2")
        bus.register(a1)
        bus.register(a2)
        bus.register(a3)

        await a1.broadcast("general", {"event": "test"})
        # a1是发送者，不应收到自己的广播
        # a2和a3应各收到1条
        assert a2._message_queue.qsize() == 1
        assert a3._message_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        agent = AgentNode("a1", "TestAgent")
        asyncio.create_task(agent.start())
        await asyncio.sleep(0.1)
        assert agent.status == "idle"
        await agent.stop()


class TestMessageBus:
    @pytest.mark.asyncio
    async def test_register(self):
        bus = MessageBus()
        agent = AgentNode("a1", "Test")
        bus.register(agent)
        assert bus.get_agent("a1") is agent

    @pytest.mark.asyncio
    async def test_unregister(self):
        bus = MessageBus()
        bus.register(AgentNode("a1", "Test"))
        bus.unregister("a1")
        assert bus.get_agent("a1") is None

    @pytest.mark.asyncio
    async def test_send(self):
        bus = MessageBus()
        a1 = AgentNode("a1", "S")
        a2 = AgentNode("a2", "R")
        bus.register(a1)
        bus.register(a2)

        msg = AgentMessage(sender_id="a1", target_id="a2", topic="test")
        result = await bus.send(msg)
        assert result is True
        assert a2._message_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_send_to_nonexistent(self):
        bus = MessageBus()
        msg = AgentMessage(sender_id="x", target_id="nonexistent", topic="t")
        result = await bus.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_find_by_capability(self):
        bus = MessageBus()
        a1 = AgentNode("a1", "Searcher",
                       [AgentCapability(name="search")])
        a2 = AgentNode("a2", "Analyst",
                       [AgentCapability(name="analyze")])
        bus.register(a1)
        bus.register(a2)

        searchers = bus.find_agents_by_capability("search")
        assert len(searchers) == 1
        assert searchers[0].agent_id == "a1"

    @pytest.mark.asyncio
    async def test_find_idle_agent(self):
        bus = MessageBus()
        a1 = AgentNode("a1", "Busy", [AgentCapability(name="work")])
        a1._task_count = 5  # 满负载
        a2 = AgentNode("a2", "Free", [AgentCapability(name="work")])
        bus.register(a1)
        bus.register(a2)

        idle = bus.find_idle_agent("work")
        assert idle is not None
        assert idle.agent_id == "a2"

    @pytest.mark.asyncio
    async def test_get_stats(self):
        bus = MessageBus()
        bus.register(AgentNode("a1", "T1", [AgentCapability(name="chat")]))
        bus.register(AgentNode("a2", "T2", [AgentCapability(name="search")]))
        stats = bus.get_stats()
        assert stats["total_agents"] == 2
        assert "chat" in stats["topics"]


class TestCollaborationProtocol:
    @pytest.mark.asyncio
    async def test_delegate_finds_idle(self):
        bus = MessageBus()
        protocol = CollaborationProtocol(bus)
        a1 = AgentNode("a1", "Manager")
        a2 = AgentNode("a2", "Worker", [AgentCapability(name="work")])
        bus.register(a1)
        bus.register(a2)

        result = await protocol.delegate(a1, "work", {"task": "do_something"})
        assert result is not None
        assert result.agent_id == "a2"
        assert a2._task_count == 1  # task count incremented

    @pytest.mark.asyncio
    async def test_delegate_no_idle_agent(self):
        bus = MessageBus()
        protocol = CollaborationProtocol(bus)
        a1 = AgentNode("a1", "Manager")
        bus.register(a1)

        result = await protocol.delegate(a1, "nonexistent_cap", {})
        assert result is None


class TestAgentManager:
    @pytest.mark.asyncio
    async def test_create_and_summary(self):
        manager = AgentManager()
        a1 = manager.create_agent("a1", "Agent1", [AgentCapability(name="chat")])
        a2 = manager.create_agent("a2", "Agent2", [AgentCapability(name="search")])
        assert len(manager._agents) == 2

        summary = manager.get_summary()
        assert summary["agent_count"] == 2
        assert "a1" in summary["agents"]
        assert "a2" in summary["agents"]
        assert summary["bus"]["total_agents"] == 2

    @pytest.mark.asyncio
    async def test_agent_with_custom_capabilities(self):
        manager = AgentManager()
        caps = [
            AgentCapability(name="analyze", description="Data analysis",
                            inputs=["data"], outputs=["report"]),
            AgentCapability(name="visualize", description="Data viz"),
        ]
        agent = manager.create_agent("a1", "Analyst", caps)
        assert len(agent.capabilities) == 2
        assert agent.capabilities[0].name == "analyze"
        assert agent.capabilities[0].description == "Data analysis"

    @pytest.mark.asyncio
    async def test_bus_stats(self):
        manager = AgentManager()
        manager.create_agent("a1", "A1", [AgentCapability(name="chat")])
        manager.create_agent("a2", "A2", [AgentCapability(name="search")])
        manager.create_agent("a3", "A3", [AgentCapability(name="chat")])

        stats = manager.get_summary()
        bus = stats["bus"]
        assert bus["total_agents"] == 3
        assert bus["topics"]["chat"] == 2  # a1 + a3
        assert bus["topics"]["search"] == 1  # a2
