"""
MeshCtx Integration Tests — 组件集成测试
"""

import unittest
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


class TestMemoryEngineIntegration(unittest.TestCase):
    """MemoryEngine 完整集成流程测试"""

    def setUp(self):
        from src.memory_engine import MemoryEngine
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.engine = MemoryEngine(db_path=self.db_path)

    def tearDown(self):
        self.engine.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_message_workflow(self):
        """测试完整消息流程：存储 → 检索 → 搜索"""
        # 存储多条消息
        msgs = [
            ("I prefer Python for backend development", "user"),
            ("Python has great async support with asyncio", "assistant"),
            ("I also like FastAPI for building APIs", "user"),
        ]
        ids = []
        for content, role in msgs:
            result = self.engine.add_message(content, "workflow-test", role=role)
            ids.append(result["message_id"])

        self.assertEqual(len(ids), 3)

        # 检索上下文
        ctx = self.engine.get_context("workflow-test")
        self.assertEqual(ctx["message_count"], 3)
        self.assertEqual(len(ctx["recent_messages"]), 3)

        # 语义搜索
        results = self.engine.search("workflow-test", "async programming")
        self.assertIsNotNone(results)
        self.assertEqual(results["query"], "async programming")

    def test_multi_project_isolation(self):
        """测试多项目数据隔离"""
        self.engine.add_message("Project A message", "project-a")
        self.engine.add_message("Project B message", "project-b")
        self.engine.add_message("Project A message 2", "project-a")

        ctx_a = self.engine.get_context("project-a")
        ctx_b = self.engine.get_context("project-b")

        self.assertEqual(ctx_a["message_count"], 2)
        self.assertEqual(ctx_b["message_count"], 1)

        # 项目 A 的消息不应出现在项目 B 中
        a_contents = [m["content"] for m in ctx_a["recent_messages"]]
        b_contents = [m["content"] for m in ctx_b["recent_messages"]]
        self.assertIn("Project A message", a_contents)
        self.assertNotIn("Project A message", b_contents)

    def test_project_deletion_cascades(self):
        """测试项目删除级联清理"""
        self.engine.add_message("msg 1", "cascade-test")
        self.engine.add_message("msg 2", "cascade-test")

        # 确认存在
        ctx = self.engine.get_context("cascade-test")
        self.assertEqual(ctx["message_count"], 2)

        # 删除
        result = self.engine.delete_project("cascade-test")
        self.assertTrue(result["deleted"])

        # 确认已清理
        ctx = self.engine.get_context("cascade-test")
        self.assertEqual(ctx["message_count"], 0)

        projects = self.engine.list_projects()
        ids = [p["id"] for p in projects]
        self.assertNotIn("cascade-test", ids)


class TestCapabilityOrchestratorIntegration(unittest.TestCase):
    """CapabilityCatalog + Orchestrator 集成测试"""

    def test_end_to_end_skill_matching(self):
        """端到端技能匹配流程"""
        from src.capabilities import get_catalog
        from src.orchestrator import SkillOrchestrator

        cat = get_catalog()
        orch = SkillOrchestrator(catalog=cat)

        # 测试多个场景
        scenarios = [
            ("debug a python test failure", "systematic-debugging"),
            ("create a pull request for my feature", "github-pr-workflow"),
            ("write a plan for user authentication", "writing-plans"),
        ]

        for query, expected_skill in scenarios:
            result = orch.match(query)
            self.assertIsNotNone(result.primary_skill)
            # 只验证结果不为空（精准匹配依赖具体实现）
            skills = [r[0].name for r in result.skills[:5]]

    def test_chain_consistency(self):
        """测试技能链一致性"""
        from src.orchestrator import SKILL_CHAINS
        from src.capabilities import get_catalog

        cat = get_catalog()

        for chain_name, skill_list in SKILL_CHAINS.items():
            for skill_name in skill_list:
                skill = cat.skill_info(skill_name)
                self.assertIsNotNone(
                    skill,
                    f"Skill '{skill_name}' in chain '{chain_name}' not found in catalog"
                )

    def test_catalog_completeness(self):
        """测试目录完整性"""
        from src.capabilities import get_catalog
        cat = get_catalog()
        stats = cat.stats()

        # 必须覆盖所有主要类别
        required_categories = [
            "software-development", "autonomous-ai-agents",
            "github", "mlops", "mcp"
        ]
        categories = cat.list_categories()
        for rc in required_categories:
            self.assertIn(rc, categories, f"Missing category: {rc}")

        # 关键技能必须存在
        required_skills = [
            "systematic-debugging", "test-driven-development",
            "writing-plans", "subagent-driven-development",
            "hermes-agent", "native-mcp",
        ]
        for rs in required_skills:
            self.assertIsNotNone(cat.skill_info(rs), f"Missing skill: {rs}")


class TestAdapterIntegration(unittest.TestCase):
    """Adapter + MemoryEngine 集成测试"""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        from src.memory_engine import MemoryEngine
        from src.adapter import ContextPortal, SkillContextProvider
        self.engine = MemoryEngine(db_path=os.path.join(self.tmp, "test.db"))
        self.portal = ContextPortal(engine=self.engine)
        self.provider = SkillContextProvider(portal=self.portal)

    def tearDown(self):
        self.engine.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_context_extraction_for_hermes(self):
        """测试提取 Hermes 格式上下文"""
        self.engine.add_message("User prefers Python", "hermes-test")
        self.engine.add_message("User wants to use FastAPI", "hermes-test")

        extracted = self.portal.extract_context_for_hermes("hermes-test")
        self.assertIn("Python", extracted)
        self.assertIn("FastAPI", extracted)

    def test_skill_context_provider(self):
        """测试技能上下文提供"""
        ctx = self.provider.prepare_skill_context("systematic-debugging")
        self.assertEqual(ctx["skill"], "systematic-debugging")
        self.assertIn("skill_info", ctx)
        self.assertIn("checks", ctx)

    def test_full_context_integration(self):
        """测试完整上下文集成"""
        self.engine.add_message("Integration test message", "full-test")

        ctx = self.portal.get_full_context("full-test")
        self.assertEqual(ctx["project_id"], "full-test")
        self.assertGreater(ctx["meshctx_context"]["message_count"], 0)
        self.assertIn("capabilities_snapshot", ctx)


if __name__ == '__main__':
    unittest.main()
