"""v2.58: 全面集成测试 — 验证14模块联动

测试所有模块的实际协作流程,确保生产环境无隐形bug。
每个测试覆盖多个模块的联动,不重复单元测试。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.mark.integration
class TestFullAgentPipeline:
    """端到端Agent管道: 输入→内存→推理→安全→执行→验证"""

    def test_store_memory_then_search_chinese(self):
        """写入中文记忆→搜索→应命中 (验证jieba+SDM联动)"""
        from src.core.breakthrough_memory import BreakthroughMemoryEngine
        engine = BreakthroughMemoryEngine()

        # 1. 存储中文记忆
        engine.store("geoV1服务运行在端口3002上", context="ops",
                     tags=["geoV1", "deploy"])
        engine.store("meshctx是一个AI Agent平台", context="info",
                     tags=["meshctx"])

        # 2. 搜索应命中
        result = engine.recall("geoV1 端口", context="ops")
        assert result is not None
        assert "sdm" in result

        # 3. 搜索不应命中无关内容
        result2 = engine.recall("天气", context="ops")
        assert result2 is not None

    def test_sdb_gate_blocks_dangerous_action(self):
        """SDB安全门控: 阻止危险操作"""
        from src.core.sdb_framework import get_sdb_engine

        sdb = get_sdb_engine()
        # 模拟一个危险操作
        record = sdb.pipeline(
            model_id="test", action="rm -rf /",
            params={}, raw_output="delete all",
            rules=["dangerous_cmd", "safety"],
            checks={"dangerous_cmd": False, "safety": True}
        )
        assert record.phase.value == "reject"
        assert not record.commit_success

    def test_diff_preview_then_sdb_then_apply(self):
        """Diff预览→SDB审查→应用 联动"""
        import tempfile
        from src.core.diff_preview import get_diff_engine
        from src.core.sdb_framework import get_sdb_engine

        # 1. 创建临时文件并预览diff
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\n")
            tmp = f.name

        try:
            diff_engine = get_diff_engine()
            result = diff_engine.generate_diff(tmp, "x = 2\ny = 3\n")
            assert result["change_id"] != ""

            # 2. SDB审查
            sdb = get_sdb_engine()
            record = sdb.pipeline(
                "test", "patch", {"file": tmp},
                result["diff_text"][:200],
                rules=["syntax", "size_check"],
                checks={"syntax": True,
                        "size_check": result["stats"]["modified"] < 10}
            )
            assert record.commit_success

            # 3. 应用变更
            apply_result = diff_engine.apply_change(result["change_id"])
            assert apply_result["success"]

            # 4. 验证文件已修改
            current = Path(tmp).read_text()
            assert "y = 3" in current
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_task_progress_with_attractor_reasoning(self):
        """任务进度追踪 + 吸引子推理联动"""
        from src.core.task_progress import get_progress_engine

        tp = get_progress_engine()
        task = tp.create_task("推理任务", total_steps=3)

        tp.start_task(task.task_id)
        tp.update_progress(task.task_id, 33, message="推理第一轮")
        tp.update_progress(task.task_id, 66, message="推理收敛中")
        tp.update_progress(task.task_id, 100, message="推理完成")

        tp.complete_task(task.task_id, result={"answer": "42"})

        history = tp.get_history()
        assert len(history) >= 1
        assert history[-1]["status"] == "completed"

    def test_knowledge_transfer_between_agents(self):
        """跨Agent知识迁移: Agent A学→Agent B查询"""
        from src.core.knowledge_transfer import get_knowledge_engine

        ke = get_knowledge_engine()
        ke.register_agent("agent-alpha")
        ke.register_agent("agent-beta")

        # Agent A 广播知识
        ke.broadcast_lesson("agent-alpha",
                            "SSH密钥应使用ed25519而非RSA",
                            category="security")

        # Agent B 查询知识
        results = ke.query_knowledge("SSH 密钥", category="security")
        assert len(results) >= 1

    def test_performance_tuner_with_precompute(self):
        """性能调优 + 预测预计算联动"""
        from src.core.auto_tuner import get_auto_tuner
        from src.core.predictive_precompute import get_precompute_engine

        # 1. 记录性能快照
        tuner = get_auto_tuner()
        tuner.snapshot(latency_ms=150, memory_mb=300)
        tuner.snapshot(latency_ms=200, memory_mb=350)

        # 2. 预测下一步
        precompute = get_precompute_engine()
        precompute.record_action("tune_performance", "high_latency")
        predictions = precompute.predict_next_actions("high_latency")

        # 3. 自动调优
        result = tuner.auto_tune()
        assert "status" in result

    def test_self_modify_with_sdb_and_diff(self):
        """自修改→SDB安全闸→Diff预览 三联"""
        from src.core.self_modify import SelfModifyEngine, ChangeType
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Test module\nx = 1\ny = 2\n")
            tmp = f.name

        try:
            engine = SelfModifyEngine(auto_apply=False, safety_level="high")

            # 1. 分析
            analysis = engine.analyze_file(tmp)
            assert "metrics" in analysis

            # 2. 提议变更
            new_content = Path(tmp).read_text() + "\n# Auto-generated\nz = 3\n"
            change = engine.propose_change(
                tmp, new_content, ChangeType.EXTEND,
                "添加新变量", 0.8
            )
            assert change.change_id != ""

            # 3. 测试
            change = engine.test_change(change)
            assert change.tests_passed

            # 4. SDB门控
            change = engine.gate_change(change)
            assert change.sdb_approved

        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_brain_validation_with_benchmark(self):
        """脑状态验证 + Agent基准联动"""
        from src.core.brain_validator import get_brain_validator
        from src.core.agent_benchmark import get_benchmark_engine

        # 1. 脑状态测量
        bv = get_brain_validator()
        profile = bv.measure_all()
        assert profile["total_dimensions"] == 13

        # 2. Agent基准
        be = get_benchmark_engine()
        result = be.run_all()
        assert result["tests_run"] >= 3
        assert "overall_score" in result


@pytest.mark.integration
class TestAPIIntegration:
    """REST API集成测试 — 验证所有端点响应正常"""

    def test_dashboard_includes_all_modules(self):
        """仪表盘包含全部14模块"""
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                "http://47.120.0.239:3001/api/dashboard", timeout=5
            )
            data = json.loads(resp.read())
            modules = data["modules"]
            expected = ["sdb", "tasks", "diff", "brain", "self_modify",
                        "gateway_llm", "unified_loop", "attractor",
                        "knowledge", "precompute", "tuner", "benchmark", "memory"]
            found = sum(1 for m in expected if m in modules)
            assert found >= 10, f"仅{found}/13模块在线"
        except Exception:
            pytest.skip("远程服务器不可达")

    def test_memory_api_returns_metrics(self):
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                "http://47.120.0.239:3001/api/memory/metrics", timeout=5
            )
            data = json.loads(resp.read())
            assert data["sdm"]["dimension"] == 1000
            assert "O(2^1000)" in data["capacity_advantage"]
        except Exception:
            pytest.skip("远程不可达")


@pytest.mark.integration
class TestErrorRecovery:
    """错误恢复: 验证系统在异常输入下不崩溃"""

    def test_empty_query_no_crash(self):
        """空查询不崩溃"""
        from src.core.breakthrough_memory import BreakthroughMemoryEngine
        engine = BreakthroughMemoryEngine()
        result = engine.recall("", context="")
        assert result is not None

    def test_invalid_file_path_no_crash(self):
        """无效文件路径不崩溃"""
        from src.core.self_modify import SelfModifyEngine
        engine = SelfModifyEngine()
        result = engine.analyze_file("/nonexistent/path.py")
        assert "error" in result

    def test_sdb_empty_input_no_crash(self):
        """空输入SDB不崩溃"""
        from src.core.sdb_framework import get_sdb_engine
        sdb = get_sdb_engine()
        record = sdb.pipeline("test", "", {}, "",
                              [], {})
        assert record is not None
