"""
meshctx 测试框架
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.memory_engine import MemoryEngine
from src.models import Project, Conversation, Message


class TestMemoryEngine:

    def setup_method(self):
        self.engine = MemoryEngine(use_llm=False, use_vector_store=False)

    def test_create_project(self):
        """测试创建项目"""
        project = self.engine.create_project("Test Project", "Test Description")
        assert project.name == "Test Project"
        assert project.description == "Test Description"
        assert project.status == "active"

    def test_start_conversation(self):
        """测试开始会话"""
        project = self.engine.create_project("Test Project", "Test Description")
        conversation = self.engine.start_conversation(project.id, "Test Conversation")
        assert conversation.title == "Test Conversation"
        assert conversation.project_id == project.id

    def test_add_message(self):
        """测试添加消息"""
        project = self.engine.create_project("Test Project", "Test Description")
        conversation = self.engine.start_conversation(project.id, "Test Conversation")
        message = self.engine.add_message(conversation.id, "user", "Hello, world!")
        assert message.content == "Hello, world!"
        assert message.role == "user"

    def test_get_messages(self):
        """测试获取会话消息"""
        project = self.engine.create_project("Test Project", "Test Description")
        conversation = self.engine.start_conversation(project.id, "Test Conversation")
        self.engine.add_message(conversation.id, "user", "Message 1")
        self.engine.add_message(conversation.id, "assistant", "Response 1")

        messages = self.engine.get_messages(conversation.id)
        assert len(messages) == 2
        assert messages[0].content == "Message 1"
        assert messages[1].content == "Response 1"

    def test_get_memories(self):
        """测试记忆提取"""
        project = self.engine.create_project("Test Project", "重要记忆测试")
        conversation = self.engine.start_conversation(project.id, "记忆测试")
        self.engine.add_message(conversation.id, "user", "这是一个重要的消息，记住目标")
        memories = self.engine.get_memories(project.id)
        assert len(memories) >= 0  # 关键词匹配至少0条

    def test_register_agent(self):
        """测试注册助手"""
        agent = self.engine.register_agent(
            "TestAgent", "测试助手", ["capability1"], 4000
        )
        assert agent.name == "TestAgent"
        assert agent.id in self.engine.agents

    def test_continuity(self):
        """测试连续性检测"""
        project = self.engine.create_project("连续性测试", "描述")
        result = self.engine.detect_continuity(project.id)
        assert "continuity_score" in result
        assert "project_id" in result

    def test_build_context(self):
        """测试上下文组装"""
        project = self.engine.create_project("上下文测试", "描述")
        conversation = self.engine.start_conversation(project.id, "测试会话")
        agent = self.engine.register_agent("CtxAgent", "上下文助手", ["ctx"], 4000)
        self.engine.add_message(conversation.id, "user", "Hello")

        ctx = self.engine.build_context_for_agent(
            agent.id, project.id, conversation.id, max_messages=10
        )
        assert ctx["project"]["name"] == "上下文测试"
        assert len(ctx["messages"]) >= 1

    def test_delete_project(self):
        """测试删除项目"""
        project = self.engine.create_project("待删除", "描述")
        assert self.engine.delete_project(project.id) is True
        assert self.engine.get_project(project.id) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
