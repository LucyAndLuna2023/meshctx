"""Tests for Agent Teams — v2.42"""
import pytest
import tempfile, os
from src.core.agent_teams import (
    AgentTeamManager, AgentProfile, AgentRole, AgentTask,
    BUILTIN_AGENTS, get_teams,
)


class TestAgentProfile:
    def test_builtin_coder(self):
        coder = BUILTIN_AGENTS["coder"]
        assert coder.role == AgentRole.CODER
        assert "软件工程师" in coder.system_prompt

    def test_to_dict(self):
        profile = AgentProfile(name="test", role=AgentRole.CUSTOM,
                              system_prompt="test prompt")
        d = profile.to_dict()
        assert d["name"] == "test"
        assert d["role"] == "custom"


class TestAgentTeamManager:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.tm = AgentTeamManager(storage_dir=self.tmp)

    def test_builtin_agents_exist(self):
        assert len(self.tm.agents) >= 6
        assert "coder" in self.tm.agents
        assert "reviewer" in self.tm.agents

    def test_register_custom(self):
        custom = AgentProfile(name="security-bot", role=AgentRole.CUSTOM,
                             system_prompt="You are a security expert")
        self.tm.register(custom)
        assert "security-bot" in self.tm.agents

    def test_cannot_delete_builtin(self):
        assert not self.tm.unregister("coder")

    def test_delete_custom(self):
        self.tm.register(AgentProfile(name="temp", role=AgentRole.CUSTOM,
                                      system_prompt="temp"))
        assert self.tm.unregister("temp")

    def test_dispatch_task(self):
        task = self.tm.dispatch("coder", "写一个排序函数")
        assert task.agent_name == "coder"
        assert task.status == "pending"
        assert task.task_id != ""

    def test_dispatch_invalid_agent(self):
        with pytest.raises(ValueError):
            self.tm.dispatch("nonexistent", "test")

    def test_complete_task(self):
        task = self.tm.dispatch("tester", "测试登录功能")
        self.tm.complete_task(task.task_id, result="测试完成: 5个用例通过")
        assert task.status == "done"
        assert len(self.tm.task_history) == 1

    def test_complete_task_error(self):
        task = self.tm.dispatch("coder", "写bug")
        self.tm.complete_task(task.task_id, error="语法错误")
        assert task.status == "failed"

    def test_dispatch_parallel(self):
        tasks = self.tm.dispatch_parallel([
            ("coder", "写API", ""),
            ("tester", "测试API", ""),
            ("reviewer", "审查API", ""),
        ])
        assert len(tasks) == 3
        assert tasks[0].agent_name == "coder"
        assert tasks[1].agent_name == "tester"

    def test_review_pattern(self):
        result = self.tm.review_pattern("用户认证系统")
        assert result["pattern"] == "review"
        assert "coder" in result["tasks"]
        assert "reviewer" in result["tasks"]

    def test_brainstorm_pattern(self):
        result = self.tm.brainstorm_pattern("微服务架构")
        assert result["pattern"] == "brainstorm"
        assert "researcher" in result["tasks"]
        assert "architect" in result["tasks"]

    def test_divide_conquer_pattern(self):
        result = self.tm.divide_conquer_pattern(
            "电商系统", ["用户模块", "订单模块", "支付模块"])
        assert result["pattern"] == "divide_conquer"
        assert len(result["tasks"]) == 3

    def test_get_active_tasks(self):
        self.tm.dispatch("coder", "task1")
        self.tm.dispatch("tester", "task2")
        active = self.tm.get_active_tasks()
        assert len(active) == 2

    def test_team_result(self):
        t1 = self.tm.dispatch("coder", "写代码")
        t2 = self.tm.dispatch("tester", "写测试")
        self.tm.complete_task(t1.task_id, result="print('hello')", tokens=100)
        self.tm.complete_task(t2.task_id, result="test passed", tokens=50)
        result = self.tm.get_team_result([t1, t2])
        assert result.success_count == 2
        assert result.total_tokens == 150

    def test_stats(self):
        task = self.tm.dispatch("coder", "test")
        self.tm.complete_task(task.task_id, result="ok")
        stats = self.tm.get_stats()
        assert stats["total_agents"] >= 6
        assert stats["completed_tasks"] == 1

    def test_list_agents(self):
        agents = self.tm.list_agents()
        assert len(agents) >= 6
        names = [a["name"] for a in agents]
        assert "coder" in names


class TestPersistence:
    def test_save_load_custom(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        tm1 = AgentTeamManager(storage_dir=tmp)
        tm1.register(AgentProfile(name="my-agent", role=AgentRole.CUSTOM,
                                  system_prompt="custom prompt"))

        tm2 = AgentTeamManager(storage_dir=tmp)
        assert "my-agent" in tm2.agents
