"""
MeshCtx Unit Tests — 核心引擎单元测试
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


class TestMemoryEngine(unittest.TestCase):
    """MemoryEngine 核心功能测试"""

    def test_initialization(self):
        """测试 MemoryEngine 正确初始化所有子组件"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        self.assertTrue(hasattr(engine, 'cross_platform_engine'))
        self.assertTrue(hasattr(engine, 'vector_store'))
        self.assertTrue(hasattr(engine, 'llm_extractor'))
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))

    def test_add_message(self):
        """测试添加消息并返回正确结果"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        result = engine.add_message("Hello, test message", "unit-test")
        
        self.assertIn("message_id", result)
        self.assertIn("project_id", result)
        self.assertIn("vector_key", result)
        self.assertIn("facts_extracted", result)
        self.assertIn("facts", result)
        self.assertEqual(result["project_id"], "unit-test")
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))

    def test_get_context(self):
        """测试获取上下文"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        engine.add_message("Test message 1", "ctx-test")
        engine.add_message("Test message 2", "ctx-test")
        
        ctx = engine.get_context("ctx-test")
        
        self.assertEqual(ctx["message_count"], 2)
        self.assertEqual(len(ctx["recent_messages"]), 2)
        self.assertEqual(ctx["project_id"], "ctx-test")
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))

    def test_search(self):
        """测试语义和关键词搜索"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        engine.add_message("Python is a great programming language", "search-test")
        engine.add_message("I love JavaScript too", "search-test")
        
        results = engine.search("search-test", "Python")
        
        self.assertEqual(results["query"], "Python")
        self.assertIn("semantic_matches", results)
        self.assertIn("keyword_matches", results)
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))

    def test_list_projects(self):
        """测试列出项目"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        engine.add_message("msg", "proj-a")
        engine.add_message("msg", "proj-b")
        
        projects = engine.list_projects()
        ids = [p["id"] for p in projects]
        
        self.assertIn("proj-a", ids)
        self.assertIn("proj-b", ids)
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))

    def test_delete_project(self):
        """测试删除项目"""
        from src.memory_engine import MemoryEngine
        engine = MemoryEngine()
        
        engine.add_message("msg", "delete-me")
        result = engine.delete_project("delete-me")
        
        self.assertTrue(result["deleted"])
        
        # 确认已删除
        ctx = engine.get_context("delete-me")
        self.assertEqual(ctx["message_count"], 0)
        
        engine.close()
        if os.path.exists(str(engine.cross_platform_engine.db_path)):
            os.remove(str(engine.cross_platform_engine.db_path))


class TestCapabilityCatalog(unittest.TestCase):
    """CapabilityCatalog 能力目录测试"""

    def test_catalog_stats(self):
        """测试目录统计"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        stats = cat.stats()
        
        self.assertGreater(stats["skills_total"], 40)
        self.assertGreater(stats["categories"], 10)
        self.assertGreater(stats["tools_total"], 15)

    def test_find_skills(self):
        """测试技能搜索"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        
        results = cat.find_skills("debug python error")
        self.assertGreater(len(results), 0)
        self.assertIn("systematic-debugging", [r[0].name for r in results[:3]])

    def test_get_by_tag(self):
        """测试按标签搜索"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        
        testing_skills = cat.get_by_tag("testing")
        names = [s.name for s in testing_skills]
        self.assertIn("test-driven-development", names)

    def test_get_by_category(self):
        """测试按类别搜索"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        
        dev_skills = cat.get_by_category("software-development")
        names = [s.name for s in dev_skills]
        self.assertIn("writing-plans", names)
        self.assertIn("systematic-debugging", names)

    def test_export_skill_index(self):
        """测试导出技能索引"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        
        index = cat.export_skill_index()
        self.assertGreater(len(index), 40)
        for entry in index:
            self.assertIn("name", entry)
            self.assertIn("category", entry)
            self.assertIn("description", entry)


class TestOrchestrator(unittest.TestCase):
    """SkillOrchestrator 编排器测试"""

    def test_match_returns_result(self):
        """测试意图匹配"""
        from src.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator()
        
        result = orch.match("debug my python error")
        self.assertIsNotNone(result.intent)
        self.assertIsNotNone(result.primary_skill)

    def test_plan_has_steps(self):
        """测试计划生成"""
        from src.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator()
        
        plan = orch.plan("add authentication to flask app")
        # "add authentication" 可能匹配 implement/setup/unknown
        # 但至少应该有意图或步骤
        self.assertIsNotNone(plan.intent)
        self.assertGreater(len(plan.steps), 0)

    def test_feature_chain(self):
        """测试功能开发技能链"""
        from src.orchestrator import SKILL_CHAINS
        
        self.assertIn("feature-development", SKILL_CHAINS)
        chain = SKILL_CHAINS["feature-development"]
        self.assertEqual(len(chain), 4)
        self.assertEqual(chain[0], "writing-plans")
        self.assertEqual(chain[-1], "requesting-code-review")

    def test_get_recommended_skills(self):
        """测试技能推荐"""
        from src.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator()
        
        recs = orch.get_recommended_skills("write test for my code", top_k=5)
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertIn("name", r)
            self.assertIn("score", r)


class TestAdapter(unittest.TestCase):
    """ContextPortal 适配器测试"""

    def test_portal_creation(self):
        """测试适配器创建"""
        from src.adapter import ContextPortal
        portal = ContextPortal()
        self.assertIsNotNone(portal.engine)
        self.assertIsNotNone(portal.catalog)

    def test_full_context(self):
        """测试完整上下文获取"""
        from src.adapter import ContextPortal
        from src.memory_engine import get_engine
        
        engine = get_engine()
        engine.add_message("Test context message", "portal-test")
        
        portal = ContextPortal(engine=engine)
        ctx = portal.get_full_context("portal-test")
        
        self.assertEqual(ctx["project_id"], "portal-test")
        self.assertIn("meshctx_context", ctx)
        self.assertIn("hermes_sync", ctx)
        self.assertIn("capabilities_snapshot", ctx)

    def test_skill_context(self):
        """测试技能上下文"""
        from src.adapter import ContextPortal
        portal = ContextPortal()
        
        ctx = portal.get_skill_context("debug error")
        
        self.assertIn("recommended_skills", ctx)
        self.assertGreater(len(ctx["recommended_skills"]), 0)


if __name__ == '__main__':
    unittest.main()
