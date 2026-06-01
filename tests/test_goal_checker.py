"""
P0-5 Goal自检机制 单元测试
================================
测试 GoalChecker 核心功能:
- 单例模式
- set_goal / check_completion
- 关键词快速匹配
- 评分逻辑
- 历史记录
- 重置功能
- API端点集成
"""
import pytest
import time
from src.core.goal_checker import (
    GoalChecker,
    GoalCheckResult,
    get_goal_checker,
    reset_goal_checker,
)


# ═══════════════════════════════════════════════════════════
# 测试夹具 — 每个测试独立重置
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset():
    """每个测试前重置 GoalChecker 单例"""
    reset_goal_checker()
    yield
    reset_goal_checker()


# ═══════════════════════════════════════════════════════════
# 1. 单例模式测试
# ═══════════════════════════════════════════════════════════

class TestSingleton:
    """单例模式 — 确保全局唯一实例"""

    def test_singleton_same_instance(self):
        """get_goal_checker() 多次调用返回同一实例"""
        c1 = get_goal_checker()
        c2 = get_goal_checker()
        assert c1 is c2

    def test_singleton_after_reset(self):
        """reset_goal_checker() 后获取新实例"""
        c1 = get_goal_checker()
        reset_goal_checker()
        c2 = get_goal_checker()
        assert c1 is not c2

    def test_goal_checker_direct_new(self):
        """GoalChecker() 直接构造也返回同一单例"""
        c1 = GoalChecker()
        c2 = GoalChecker()
        assert c1 is c2


# ═══════════════════════════════════════════════════════════
# 2. 数据类测试
# ═══════════════════════════════════════════════════════════

class TestGoalCheckResult:
    """GoalCheckResult 数据类"""

    def test_to_dict_contains_all_fields(self):
        """to_dict() 包含所有必要字段"""
        result = GoalCheckResult(
            goal="测试目标",
            score=85,
            unfinished=["未完成项1"],
            suggestions=["建议1"],
            llm_analysis="LLM分析文本",
            source="keyword",
            checked_at=1234567890.0,
        )
        d = result.to_dict()
        assert d["goal"] == "测试目标"
        assert d["score"] == 85
        assert len(d["unfinished"]) == 1
        assert len(d["suggestions"]) == 1
        assert d["source"] == "keyword"

    def test_default_values(self):
        """默认值测试"""
        result = GoalCheckResult()
        assert result.goal == ""
        assert result.score == 0
        assert result.unfinished == []
        assert result.suggestions == []


# ═══════════════════════════════════════════════════════════
# 3. set_goal / get_goal 测试
# ═══════════════════════════════════════════════════════════

class TestSetGoal:
    """目标设置测试"""

    def test_set_and_get_goal(self):
        """设置目标后 get_goal() 返回相同值"""
        checker = get_goal_checker()
        checker.set_goal("创建一个FastAPI服务")
        assert checker.get_goal() == "创建一个FastAPI服务"

    def test_set_goal_strips_whitespace(self):
        """set_goal 去除首尾空白"""
        checker = get_goal_checker()
        checker.set_goal("  部署到生产环境  ")
        assert checker.get_goal() == "部署到生产环境"

    def test_get_goal_empty_initially(self):
        """初始状态下 get_goal() 返回空字符串"""
        checker = get_goal_checker()
        assert checker.get_goal() == ""


# ═══════════════════════════════════════════════════════════
# 4. 关键词快速匹配测试
# ═══════════════════════════════════════════════════════════

class TestKeywordCheck:
    """关键词快速匹配"""

    def test_completed_keywords_boost_score(self):
        """完成关键词提升评分"""
        checker = get_goal_checker()
        result = checker._keyword_check("任务已成功完成并通过测试")
        assert result["score"] > 50  # 应高于基准分
        assert any("完成" in kw for kw in result["matched"])

    def test_failure_keywords_reduce_score(self):
        """失败关键词降低评分"""
        checker = get_goal_checker()
        result = checker._keyword_check("任务执行失败，出现崩溃错误")
        assert result["score"] < 50  # 应低于基准分
        assert any("失败" in kw for kw in result["matched"])

    def test_in_progress_keywords_detect_unfinished(self):
        """进行中关键词检测未完成项"""
        checker = get_goal_checker()
        result = checker._keyword_check("功能仍在进行中，还需要完善")
        assert len(result["unfinished"]) > 0
        assert any("进行中" in kw for kw in result["matched"])

    def test_neutral_text_default_score(self):
        """无关键词时返回基准分"""
        checker = get_goal_checker()
        result = checker._keyword_check("一些与状态无关的普通文本")
        assert result["score"] <= 50
        assert len(result["suggestions"]) > 0  # 建议补充状态

    def test_mixed_signals(self):
        """混合信号: 既有完成又有进行中"""
        checker = get_goal_checker()
        result = checker._keyword_check("功能已完成但测试仍在进行中")
        # 两种信号都有，但最终评分应偏向中间
        assert 30 <= result["score"] <= 70

    def test_step_markers_detection(self):
        """步骤标记检测 — 多步骤未确认全部完成"""
        checker = get_goal_checker()
        result = checker._keyword_check("步骤1已完成，步骤2已完成，步骤3...")
        # 应检测到步骤标记但未确认全部完成
        assert any("步骤" in item for item in result["unfinished"])


# ═══════════════════════════════════════════════════════════
# 5. check_completion 完整流程测试
# ═══════════════════════════════════════════════════════════

class TestCheckCompletion:
    """check_completion 完整流程"""

    def test_empty_goal_returns_error(self):
        """未设置目标时返回错误信息"""
        checker = get_goal_checker()
        result = checker.check_completion()
        assert result["score"] == 0
        assert len(result["unfinished"]) > 0
        assert "未设置" in result["unfinished"][0]

    def test_completed_goal_high_score(self):
        """已完成目标获得高分"""
        checker = get_goal_checker()
        checker.set_goal("API服务已部署成功并通过全部测试完成")
        result = checker.check_completion()
        assert result["score"] >= 50  # 关键词应推高评分
        assert result["source"] in ("keyword", "mixed")

    def test_failed_goal_low_score(self):
        """失败目标获得低分"""
        checker = get_goal_checker()
        checker.set_goal("部署失败崩溃异常错误")
        result = checker.check_completion()
        assert result["score"] < 60

    def test_result_includes_all_fields(self):
        """返回结果包含所有必要字段"""
        checker = get_goal_checker()
        checker.set_goal("测试目标")
        result = checker.check_completion()
        for key in ("goal", "score", "unfinished", "suggestions",
                     "llm_analysis", "source", "checked_at"):
            assert key in result, f"缺少字段: {key}"

    def test_score_in_valid_range(self):
        """评分在 0-100 范围内"""
        checker = get_goal_checker()
        checker.set_goal("任意文本")
        result = checker.check_completion()
        assert 0 <= result["score"] <= 100

    def test_unfinished_penalty(self):
        """未完成项数量影响评分"""
        checker = get_goal_checker()
        # 目标包含多个进行中信号
        checker.set_goal("功能1进行中 功能2尚未完成 功能3待完成 功能4处理中")
        result = checker.check_completion()
        assert result["score"] < 40  # 每项扣10分
        assert len(result["unfinished"]) > 0


# ═══════════════════════════════════════════════════════════
# 6. 历史记录测试
# ═══════════════════════════════════════════════════════════

class TestHistory:
    """检查历史记录"""

    def test_history_records_checks(self):
        """每次检查记录到历史"""
        checker = get_goal_checker()
        checker.set_goal("目标A")
        checker.check_completion()
        checker.set_goal("目标B")
        checker.check_completion()
        history = checker.get_history()
        assert len(history) >= 2

    def test_get_last_result(self):
        """get_last_result 返回最近结果"""
        checker = get_goal_checker()
        checker.set_goal("最近目标")
        checker.check_completion()
        last = checker.get_last_result()
        assert last is not None
        assert last["goal"] == "最近目标"

    def test_history_limit(self):
        """历史记录不超过最大限制"""
        checker = get_goal_checker()
        for i in range(60):
            checker.set_goal(f"目标{i}")
            checker.check_completion()
        history = checker.get_history(limit=100)
        assert len(history) <= 50  # _max_history = 50


# ═══════════════════════════════════════════════════════════
# 7. 重置测试
# ═══════════════════════════════════════════════════════════

class TestReset:
    """重置功能"""

    def test_reset_clears_goal(self):
        """重置清除目标"""
        checker = get_goal_checker()
        checker.set_goal("某目标")
        checker.reset()
        assert checker.get_goal() == ""

    def test_reset_clears_history(self):
        """重置清除历史"""
        checker = get_goal_checker()
        checker.set_goal("目标")
        checker.check_completion()
        checker.reset()
        history = checker.get_history()
        assert len(history) == 0

    def test_reset_clears_last_result(self):
        """重置清除最近结果"""
        checker = get_goal_checker()
        checker.set_goal("目标")
        checker.check_completion()
        checker.reset()
        assert checker.get_last_result() is None


# ═══════════════════════════════════════════════════════════
# 8. 统计功能测试
# ═══════════════════════════════════════════════════════════

class TestStats:
    """统计信息"""

    def test_stats_initial(self):
        """初始统计"""
        checker = get_goal_checker()
        stats = checker.get_stats()
        assert stats["total_checks"] == 0
        assert stats["avg_score"] == 0
        assert stats["current_goal"] == ""

    def test_stats_after_checks(self):
        """检查后的统计"""
        checker = get_goal_checker()
        checker.set_goal("目标1 已完成成功")
        checker.check_completion()
        checker.set_goal("目标2 已完成")
        checker.check_completion()
        stats = checker.get_stats()
        assert stats["total_checks"] == 2
        assert stats["avg_score"] > 0
        assert stats["max_score"] > 0


# ═══════════════════════════════════════════════════════════
# 9. 解析函数测试
# ═══════════════════════════════════════════════════════════

class TestParseFunctions:
    """LLM解析函数"""

    def test_parse_llm_score_chinese(self):
        """解析中文格式评分"""
        checker = get_goal_checker()
        score = checker._parse_llm_score("评分: 85")
        assert score == 85

    def test_parse_llm_score_english(self):
        """解析英文格式评分"""
        checker = get_goal_checker()
        score = checker._parse_llm_score("Score: 72")
        assert score == 72

    def test_parse_llm_score_slash_format(self):
        """解析 80/100 格式"""
        checker = get_goal_checker()
        score = checker._parse_llm_score("达成度: 80/100")
        assert score == 80

    def test_parse_llm_score_not_found(self):
        """未找到评分返回 -1"""
        checker = get_goal_checker()
        score = checker._parse_llm_score("没有评分信息")
        assert score == -1

    def test_parse_llm_unfinished(self):
        """解析LLM未完成项"""
        checker = get_goal_checker()
        text = "未完成项:\n- 需要添加单元测试\n- 需要更新文档\n补救建议:\n* 建议1"
        unfinished = checker._parse_llm_unfinished(text)
        assert "需要添加单元测试" in unfinished
        assert "需要更新文档" in unfinished

    def test_parse_llm_suggestions(self):
        """解析LLM补救建议"""
        checker = get_goal_checker()
        text = "未完成项:\n- 项目1\n补救建议:\n* 首先修复错误处理\n* 然后添加日志"
        suggestions = checker._parse_llm_suggestions(text)
        assert "首先修复错误处理" in suggestions
        assert "然后添加日志" in suggestions
