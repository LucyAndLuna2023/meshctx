"""v3.43 核心模块补测 — 根据实际API"""
import pytest, os, tempfile, json

class TestProjectIndexer:
    def test_import(self):
        import src.core.project_indexer as pi
        assert pi is not None
    
    def test_module_exists(self):
        from src.core.project_indexer import __doc__
        assert __doc__ is not None

class TestPluginAutoload:
    def test_import(self):
        from src.core.plugin_autoload import auto_activate_builtins
        assert callable(auto_activate_builtins)
    
    def test_auto_activate(self):
        from src.core.plugin_autoload import auto_activate_builtins
        count = auto_activate_builtins()
        assert isinstance(count, int)
        assert count >= 0

class TestAgentTasks:
    def test_import(self):
        from src.core.agent_tasks import AgentTask
        assert AgentTask is not None
    
    def test_task_creation(self):
        from src.core.agent_tasks import AgentTask
        t = AgentTask(title="test task")
        assert t.title == "test task"
    
    def test_task_store(self):
        import src.core.agent_tasks as at
        assert hasattr(at, 'TASKS_DIR')
        assert at.TASKS_DIR.exists()
