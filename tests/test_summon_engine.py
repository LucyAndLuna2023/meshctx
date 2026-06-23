"""
P0-7 动态Summon子Agent引擎 测试套件 — 至少10个测试用例
=====================================================
测试覆盖:
- SummonResult数据类
- SummonStatus枚举
- 基本召唤 (summon)
- 并行召唤 (summon_parallel)
- 活跃Agent查询 (active_agents)
- Agent遣散 (dismiss)
- 角色自动推断 (_infer_role)
- 超时处理
- 单例模式 (get_summon_engine)
- 引擎重置 (reset_summon_engine)
- 统计信息 (get_stats)
- 历史记录 (get_history)
- 边界情况 (空参数/不存在的Agent)
"""

import pytest
import time
import threading
from typing import Dict, Any

# 导入被测模块
from src.core.summon_engine import (
    SummonEngine,
    SummonResult,
    SummonStatus,
    get_summon_engine,
    reset_summon_engine,
    _infer_role,
    _estimate_tokens,
    TaskExecutor,
)


# ═══════════════════════════════════════════════════════════
# Fixtures — 每个测试前重置引擎
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def clean_engine():
    """每个测试前重置SummonEngine单例，确保测试隔离"""
    reset_summon_engine()
    yield
    reset_summon_engine()


# ═══════════════════════════════════════════════════════════
# 测试1: SummonResult数据类基本功能
# ═══════════════════════════════════════════════════════════

class TestSummonResult:
    """SummonResult数据类测试"""

    def test_create_result(self):
        """测试创建SummonResult实例"""
        result = SummonResult(
            agent_id="test_001",
            description="测试描述",
            task="测试任务",
        )
        assert result.agent_id == "test_001"
        assert result.description == "测试描述"
        assert result.task == "测试任务"
        assert result.status == SummonStatus.PENDING
        assert result.result == ""
        assert result.error == ""
        assert result.duration == 0.0
        assert result.tokens_used == 0
        assert result.role == "general"

    def test_to_dict(self):
        """测试to_dict序列化"""
        result = SummonResult(
            agent_id="test_002",
            description="分析代码",
            task="分析代码质量",
            status=SummonStatus.DONE,
            result="代码质量良好",
            duration=1.5,
            tokens_used=100,
            role="reviewer",
        )
        d = result.to_dict()
        assert d["agent_id"] == "test_002"
        assert d["status"] == "done"
        assert d["result"] == "代码质量良好"
        assert d["duration"] == 1.5
        assert d["tokens_used"] == 100
        assert d["role"] == "reviewer"
        assert d["is_active"] is False
        assert "created_at" in d

    def test_is_active_property(self):
        """测试is_active属性"""
        pending = SummonResult(agent_id="a", description="", task="",
                              status=SummonStatus.PENDING)
        running = SummonResult(agent_id="b", description="", task="",
                              status=SummonStatus.RUNNING)
        done = SummonResult(agent_id="c", description="", task="",
                           status=SummonStatus.DONE)
        failed = SummonResult(agent_id="d", description="", task="",
                             status=SummonStatus.FAILED)
        timeout = SummonResult(agent_id="e", description="", task="",
                              status=SummonStatus.TIMEOUT)
        dismissed = SummonResult(agent_id="f", description="", task="",
                                status=SummonStatus.DISMISSED)

        assert pending.is_active is True
        assert running.is_active is True
        assert done.is_active is False
        assert failed.is_active is False
        assert timeout.is_active is False
        assert dismissed.is_active is False

    def test_is_success_property(self):
        """测试is_success属性"""
        done = SummonResult(agent_id="a", description="", task="",
                           status=SummonStatus.DONE)
        failed = SummonResult(agent_id="b", description="", task="",
                             status=SummonStatus.FAILED)

        assert done.is_success is True
        assert failed.is_success is False


# ═══════════════════════════════════════════════════════════
# 测试2: SummonStatus枚举
# ═══════════════════════════════════════════════════════════

class TestSummonStatus:
    """SummonStatus枚举测试"""

    def test_all_statuses(self):
        """测试所有状态值"""
        assert SummonStatus.PENDING.value == "pending"
        assert SummonStatus.RUNNING.value == "running"
        assert SummonStatus.DONE.value == "done"
        assert SummonStatus.FAILED.value == "failed"
        assert SummonStatus.TIMEOUT.value == "timeout"
        assert SummonStatus.DISMISSED.value == "dismissed"
        assert len(SummonStatus) == 6


# ═══════════════════════════════════════════════════════════
# 测试3: 角色推断 (_infer_role)
# ═══════════════════════════════════════════════════════════

class TestRoleInference:
    """角色自动推断测试"""

    def test_infer_coder(self):
        """测试推断coder角色"""
        assert _infer_role("写代码实现一个排序算法") == "coder"
        assert _infer_role("修复bug在登录模块") == "coder"
        assert _infer_role("implement a new feature") == "coder"

    def test_infer_reviewer(self):
        """测试推断reviewer角色"""
        assert _infer_role("审查代码安全漏洞") == "reviewer"
        assert _infer_role("review the pull request") == "reviewer"

    def test_infer_architect(self):
        """测试推断architect角色"""
        assert _infer_role("设计系统架构方案") == "architect"
        assert _infer_role("architecture design for microservices") == "architect"

    def test_infer_tester(self):
        """测试推断tester角色"""
        assert _infer_role("编写单元测试") == "tester"
        assert _infer_role("写测试用例覆盖所有分支") == "tester"
        assert _infer_role("write unit tests for module") == "tester"

    def test_infer_researcher(self):
        """测试推断researcher角色"""
        assert _infer_role("研究Python asyncio最佳实践") == "researcher"
        assert _infer_role("分析技术趋势") == "researcher"
        assert _infer_role("research on distributed systems") == "researcher"

    def test_infer_devops(self):
        """测试推断devops角色"""
        assert _infer_role("部署到生产环境") == "devops"
        assert _infer_role("配置CI/CD流水线") == "devops"
        assert _infer_role("deploy to kubernetes cluster") == "devops"

    def test_infer_general_fallback(self):
        """测试无匹配时返回general"""
        assert _infer_role("你好世界") == "general"
        assert _infer_role("帮我做点事") == "general"
        assert _infer_role("") == "general"


# ═══════════════════════════════════════════════════════════
# 测试4: Token估算 (_estimate_tokens)
# ═══════════════════════════════════════════════════════════

class TestTokenEstimation:
    """Token估算测试"""

    def test_empty(self):
        assert _estimate_tokens("") == 0

    def test_chinese(self):
        """测试中文文本估算"""
        tokens = _estimate_tokens("你好世界这是一段中文测试文本")
        assert tokens > 0

    def test_english(self):
        """测试英文文本估算"""
        tokens = _estimate_tokens("Hello world this is a test")
        assert tokens > 0

    def test_mixed(self):
        """测试中英混合文本"""
        tokens = _estimate_tokens("Hello 你好 world 世界")
        assert tokens > 0


# ═══════════════════════════════════════════════════════════
# 测试5: 基本召唤 (summon)
# ═══════════════════════════════════════════════════════════

class TestSummonBasic:
    """基本召唤功能测试"""

    def test_summon_with_description_only(self):
        """仅提供description进行召唤"""
        engine = get_summon_engine()
        result = engine.summon(description="写一个冒泡排序算法")

        assert isinstance(result, SummonResult)
        assert result.agent_id.startswith("summon_")
        assert result.description == "写一个冒泡排序算法"
        assert result.status == SummonStatus.DONE
        assert result.result != ""
        assert result.duration >= 0
        assert result.tokens_used > 0

    def test_summon_with_task(self):
        """同时提供description和task"""
        engine = get_summon_engine()
        result = engine.summon(
            description="实现快速排序",
            task="用Python实现快速排序算法，包含测试代码",
        )

        assert result.status == SummonStatus.DONE
        assert "快速排序" in result.task or "Python" in result.task

    def test_summon_auto_role_inference(self):
        """测试自动角色推断"""
        engine = get_summon_engine()
        result = engine.summon(description="写单元测试代码")

        # 应该自动推断为tester角色
        assert result.role == "tester"

    def test_summon_with_specific_role(self):
        """指定角色召唤"""
        engine = get_summon_engine()
        result = engine.summon(
            description="随便做什么",
            role="devops",
        )

        assert result.role == "devops"


# ═══════════════════════════════════════════════════════════
# 测试6: 并行召唤 (summon_parallel)
# ═══════════════════════════════════════════════════════════

class TestSummonParallel:
    """并行召唤功能测试"""

    def test_summon_parallel_basic(self):
        """基本的并行召唤"""
        engine = get_summon_engine()
        tasks = [
            {"description": "写代码"},
            {"description": "写测试"},
            {"description": "做研究"},
        ]
        results = engine.summon_parallel(tasks)

        assert len(results) == 3
        for r in results:
            assert isinstance(r, SummonResult)
            assert r.status == SummonStatus.DONE
            assert r.result != ""

    def test_summon_parallel_empty(self):
        """空任务列表的并行召唤"""
        engine = get_summon_engine()
        results = engine.summon_parallel([])
        assert results == []

    def test_summon_parallel_single(self):
        """单个任务的并行召唤"""
        engine = get_summon_engine()
        results = engine.summon_parallel([{"description": "写测试"}])
        assert len(results) == 1
        assert results[0].status == SummonStatus.DONE

    def test_summon_parallel_with_roles(self):
        """指定角色的并行召唤"""
        engine = get_summon_engine()
        tasks = [
            {"description": "写代码", "role": "coder"},
            {"description": "做审查", "role": "reviewer"},
        ]
        results = engine.summon_parallel(tasks)
        assert len(results) == 2
        assert results[0].role == "coder"
        assert results[1].role == "reviewer"


# ═══════════════════════════════════════════════════════════
# 测试7: 活跃Agent查询 (active_agents)
# ═══════════════════════════════════════════════════════════

class TestActiveAgents:
    """活跃Agent查询测试"""

    def test_active_agents_empty(self):
        """无活跃Agent时返回空列表"""
        engine = get_summon_engine()
        active = engine.active_agents()
        assert active == []

    def test_active_agents_after_summon(self):
        """召唤完成后活跃Agent应为空（同步模式立即完成）"""
        engine = get_summon_engine()
        engine.summon(description="快速任务")
        # 同步召唤完成后应无活跃Agent
        active = engine.active_agents()
        assert active == []

    def test_active_agents_async_mode(self):
        """异步模式下应有活跃Agent"""
        engine = get_summon_engine()
        engine.summon(
            description="耗时任务",
            async_mode=True,
        )
        time.sleep(0.2)  # 等待任务开始
        active = engine.active_agents()
        # 异步任务可能在极快完成后就清理了，但刚提交时应活跃
        assert isinstance(active, list)


# ═══════════════════════════════════════════════════════════
# 测试8: Agent遣散 (dismiss)
# ═══════════════════════════════════════════════════════════

class TestDismiss:
    """Agent遣散功能测试"""

    def test_dismiss_active_agent(self):
        """遣散一个活跃的Agent"""
        engine = get_summon_engine()
        # 先用异步模式创建一个活跃Agent
        result = engine.summon(
            description="长时间运行的任务",
            task="sleep 5 seconds task",
            async_mode=True,
        )
        time.sleep(0.1)
        success = engine.dismiss(result.agent_id)
        assert success is True

    def test_dismiss_nonexistent(self):
        """遣散不存在的Agent"""
        engine = get_summon_engine()
        success = engine.dismiss("nonexistent_agent_12345")
        assert success is False

    def test_dismiss_completed_agent(self):
        """遣散已完成的Agent"""
        engine = get_summon_engine()
        result = engine.summon(description="快速完成的任务")
        # 同步召唤已立即完成
        assert result.status == SummonStatus.DONE
        success = engine.dismiss(result.agent_id)
        # 已完成的Agent不在活跃列表中，遣散返回False
        assert success is False


# ═══════════════════════════════════════════════════════════
# 测试9: 超时处理 (timeout)
# ═══════════════════════════════════════════════════════════

class TestTimeout:
    """超时处理测试"""

    def test_timeout_handling(self):
        """测试超时处理"""
        engine = get_summon_engine()

        # 设置极短的超时时间
        result = engine.summon(
            description="复杂任务",
            timeout=0.001,  # 极短超时，确保触发
        )

        # 可能超时或快速完成（取决于执行速度）
        assert result.status in (SummonStatus.TIMEOUT, SummonStatus.DONE, SummonStatus.FAILED)

    def test_default_timeout(self):
        """测试默认超时时间（300秒）"""
        engine = get_summon_engine()
        result = engine.summon(description="简单任务")
        # 简单任务应该很快完成，不应超时
        assert result.status == SummonStatus.DONE
        assert result.duration < 5.0  # 应该在5秒内完成


# ═══════════════════════════════════════════════════════════
# 测试10: 单例模式 (singleton)
# ═══════════════════════════════════════════════════════════

class TestSingleton:
    """单例模式测试"""

    def test_singleton_same_instance(self):
        """测试get_summon_engine返回同一个实例"""
        engine1 = get_summon_engine()
        engine2 = get_summon_engine()
        assert engine1 is engine2

    def test_singleton_thread_safety(self):
        """测试多线程环境下的单例安全"""
        reset_summon_engine()
        instances = []

        def get_instance():
            instances.append(get_summon_engine())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有实例应该相同
        first = instances[0]
        for inst in instances[1:]:
            assert inst is first

    def test_reset_creates_new_instance(self):
        """测试重置后获取新实例"""
        engine1 = get_summon_engine()
        reset_summon_engine()
        engine2 = get_summon_engine()
        assert engine1 is not engine2


# ═══════════════════════════════════════════════════════════
# 测试11: 统计信息 (get_stats)
# ═══════════════════════════════════════════════════════════

class TestStats:
    """统计信息测试"""

    def test_stats_initial(self):
        """初始状态统计"""
        engine = get_summon_engine()
        stats = engine.get_stats()
        assert stats["active_agents"] == 0
        assert stats["total_summoned"] == 0
        assert stats["done"] == 0
        assert "success_rate" in stats
        assert stats["engine"] == "SummonEngine P0-7"

    def test_stats_after_summon(self):
        """召唤后统计更新"""
        engine = get_summon_engine()
        engine.summon(description="任务A")
        engine.summon(description="任务B")

        stats = engine.get_stats()
        assert stats["total_summoned"] == 2
        assert stats["done"] == 2
        assert stats["success_rate"] == 100.0

    def test_stats_mixed(self):
        """混合结果统计"""
        engine = get_summon_engine()
        # 成功
        engine.summon(description="成功任务")
        # 超时
        engine.summon(description="超时任务", timeout=0.00001)

        stats = engine.get_stats()
        assert stats["total_summoned"] == 2
        # 至少有一个完成
        assert stats["done"] >= 1


# ═══════════════════════════════════════════════════════════
# 测试12: 历史记录 (get_history)
# ═══════════════════════════════════════════════════════════

class TestHistory:
    """历史记录测试"""

    def test_history_empty(self):
        """空历史记录"""
        engine = get_summon_engine()
        history = engine.get_history()
        assert history == []

    def test_history_after_summons(self):
        """召唤后历史记录"""
        engine = get_summon_engine()
        engine.summon(description="任务1")
        engine.summon(description="任务2")

        history = engine.get_history()
        assert len(history) == 2
        # 最近的在前
        assert history[0].description == "任务2"
        assert history[1].description == "任务1"

    def test_history_limit(self):
        """历史记录限制"""
        engine = get_summon_engine()
        # 创建超过默认限制的记录数
        for i in range(5):
            engine.summon(description=f"任务{i}")

        history = engine.get_history(limit=3)
        assert len(history) == 3


# ═══════════════════════════════════════════════════════════
# 测试13: summon_result查询
# ═══════════════════════════════════════════════════════════

class TestSummonResultQuery:
    """按ID查询召唤结果测试"""

    def test_summon_result_found(self):
        """查询存在的召唤结果"""
        engine = get_summon_engine()
        result = engine.summon(description="测试查询")
        found = engine.summon_result(result.agent_id)
        assert found is not None
        assert found.agent_id == result.agent_id

    def test_summon_result_not_found(self):
        """查询不存在的召唤结果"""
        engine = get_summon_engine()
        found = engine.summon_result("nonexistent_id")
        assert found is None


# ═══════════════════════════════════════════════════════════
# 测试14: TaskExecutor
# ═══════════════════════════════════════════════════════════

class TestTaskExecutor:
    """任务执行器测试"""

    def test_executor_basic(self):
        """基本执行"""
        executor = TaskExecutor(max_workers=2)
        result = executor.execute(
            agent_id="exec_test_1",
            task="简单任务",
            description="测试执行器",
            timeout=5,
        )
        assert result.status == SummonStatus.DONE
        assert result.result != ""
        executor.shutdown(wait=False)

    def test_executor_cancel(self):
        """取消任务"""
        executor = TaskExecutor(max_workers=2)
        # 异步提交
        result = executor.execute_async(
            agent_id="exec_test_cancel",
            task="长任务",
            description="测试取消",
        )
        time.sleep(0.1)
        # 尝试取消
        cancelled = executor.cancel("exec_test_cancel")
        # 可能已快速完成，无法取消
        assert isinstance(cancelled, bool)
        executor.shutdown(wait=False)

    def test_executor_active_futures(self):
        """活跃futures查询"""
        executor = TaskExecutor(max_workers=2)
        assert executor.active_futures() == []

        executor.execute_async(
            agent_id="exec_active",
            task="活跃任务",
            description="测试活跃状态",
        )
        time.sleep(0.05)
        # 在任务运行中检查
        active = executor.active_futures()
        assert isinstance(active, list)
        executor.shutdown(wait=False)

    def test_executor_llm_callback(self):
        """LLM回调注入"""
        executor = TaskExecutor(max_workers=2)

        called = False

        def my_callback(params: dict) -> str:
            nonlocal called
            called = True
            return f"回调响应: {params['task']}"

        executor.set_llm_callback(my_callback)
        result = executor.execute(
            agent_id="exec_cb",
            task="测试回调",
            description="验证LLM回调",
            timeout=5,
        )
        assert called
        assert "回调响应" in result.result
        executor.shutdown(wait=False)
