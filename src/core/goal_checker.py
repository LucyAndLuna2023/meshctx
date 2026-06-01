"""
MeshCtx P0-5 Goal自检机制 — Goal Self-Check Module
====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

P0-5优先级: 目标达成度自检机制。
在OODA循环的Act阶段后自动评估当前目标完成情况，
结合简单关键词匹配与LLM深层分析，输出达成度评分、未完成项、补救建议。

特性:
- 单例模式: 全局唯一GoalChecker实例
- 双重检查: 快速关键词匹配 + LLM深度分析
- OODA集成: Act阶段后自动调用
- API端点: GET/POST /api/goal/check

用法:
    checker = GoalChecker()
    checker.set_goal("创建一个FastAPI服务")
    result = checker.check_completion()
    print(result["score"], result["unfinished"], result["suggestions"])

License: AGPLv3 for non-commercial use only.
"""
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据类 — 目标检查结果
# ═══════════════════════════════════════════════════════════

@dataclass
class GoalCheckResult:
    """单次目标检查结果"""
    goal: str = ""                          # 当前目标文本
    score: int = 0                          # 达成度评分 0-100
    unfinished: List[str] = field(default_factory=list)    # 未完成项列表
    suggestions: List[str] = field(default_factory=list)   # 补救建议列表
    llm_analysis: str = ""                  # LLM原始分析文本
    source: str = "keyword"                 # 分析来源: keyword / llm / mixed
    checked_at: float = 0.0                 # 检查时间戳

    def to_dict(self) -> Dict[str, Any]:
        """转为字典格式，方便API返回"""
        return {
            "goal": self.goal,
            "score": self.score,
            "unfinished": self.unfinished,
            "suggestions": self.suggestions,
            "llm_analysis": self.llm_analysis,
            "source": self.source,
            "checked_at": self.checked_at,
        }


# ═══════════════════════════════════════════════════════════
# 目标自检器 — 单例模式
# ═══════════════════════════════════════════════════════════

class GoalChecker:
    """
    P0-5 目标自检机制核心类。

    单例模式 — 全局唯一实例，通过 get_goal_checker() 获取。

    工作流程:
    1. set_goal(goal_text) — 设置当前目标任务目标
    2. check_completion() → Dict — 执行双重检查:
       a. 快速关键词匹配 (毫秒级)
       b. LLM深度分析 (通过 gateway_llm)
       c. 合并结果 → 0-100分评分 + 未完成项 + 补救建议
    3. check_completion_sync() — 同步版本的快速检查 (无LLM)

    设计理念:
    - 快速检查: 基于关键词词典，亚毫秒级完成
    - 深度检查: 调用LLM进行语义理解，评估真实达成度
    - 优雅降级: LLM不可用时回退到关键词匹配结果
    """

    # ── 关键词匹配词典 ──────────────────────────────────
    # 关键词 → (贡献分数, 类别标签)
    # 用于快速评估目标是否达成
    _KEYWORDS: Dict[str, Dict[str, tuple]] = {
        # 完成信号 — 出现这些词表示任务接近完成
        "完成": {
            "完成": (15, "done"), "成功": (15, "done"), "通过": (12, "done"),
            "已实现": (18, "done"), "已部署": (18, "done"), "已修复": (18, "done"),
            "已创建": (15, "done"), "已更新": (12, "done"), "已删除": (12, "done"),
            "已验证": (15, "done"), "已测试": (12, "done"), "已合并": (15, "done"),
            "已提交": (12, "done"), "已发布": (18, "done"), "已上线": (18, "done"),
            "已安装": (12, "done"), "已配置": (12, "done"), "pass": (10, "done"),
            "success": (10, "done"), "ok": (8, "done"), "done": (10, "done"),
        },
        # 进行中信号 — 出现这些词表示任务仍有未完成部分
        "进行中": {
            "进行中": (-10, "in_progress"), "处理中": (-10, "in_progress"),
            "等待": (-8, "in_progress"), "pending": (-10, "in_progress"),
            "待完成": (-15, "in_progress"), "还需要": (-12, "in_progress"),
            "尚未": (-15, "in_progress"), "未完成": (-15, "in_progress"),
            "working": (-8, "in_progress"), "in progress": (-8, "in_progress"),
            "to do": (-10, "in_progress"), "todo": (-10, "in_progress"),
        },
        # 失败/错误信号 — 出现这些词表示任务有严重问题
        "失败": {
            "失败": (-20, "failure"), "错误": (-15, "failure"),
            "error": (-15, "failure"), "failed": (-20, "failure"),
            "异常": (-15, "failure"), "exception": (-15, "failure"),
            "崩溃": (-30, "failure"), "crash": (-30, "failure"),
            "中断": (-20, "failure"), "abort": (-20, "failure"),
            "无法": (-15, "failure"), "不能": (-12, "failure"),
            "blocked": (-15, "failure"), "拒绝": (-15, "failure"),
        },
    }

    # 单例
    _instance: Optional["GoalChecker"] = None

    def __new__(cls) -> "GoalChecker":
        """单例模式 — 确保全局唯一实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._current_goal: str = ""
        self._last_result: Optional[GoalCheckResult] = None
        self._check_history: List[GoalCheckResult] = []
        self._max_history: int = 50  # 最多保留50条检查历史
        logger.info("P0-5 GoalChecker 目标自检器已初始化")

    # ── 公开API ──────────────────────────────────────────

    def set_goal(self, goal_text: str) -> None:
        """
        设置当前目标任务目标。

        Args:
            goal_text: 目标描述文本，例如 "创建一个FastAPI服务并添加CORS中间件"
        """
        self._current_goal = goal_text.strip()
        logger.info(f"目标已设置: {self._current_goal[:80]}...")

    def get_goal(self) -> str:
        """获取当前目标"""
        return self._current_goal

    def check_completion(self) -> Dict[str, Any]:
        """
        执行目标达成度检查 (双重检查模式)。

        流程:
        1. 快速关键词匹配获得基准评分
        2. 尝试LLM深度分析 (异步调用)
        3. 合并结果，输出最终评估

        Returns:
            {
                "goal": str,            # 当前目标文本
                "score": int,           # 达成度评分 0-100
                "unfinished": [str],    # 未完成项列表
                "suggestions": [str],   # 补救建议
                "llm_analysis": str,    # LLM原始分析文本
                "source": str,          # 分析来源
                "checked_at": float,    # 检查时间戳
            }
        """
        import time

        if not self._current_goal:
            logger.warning("未设置目标，无法检查")
            return self._empty_result("未设置检查目标")

        # 步骤1: 快速关键词匹配
        keyword_result = self._keyword_check(self._current_goal)

        # 步骤2: 尝试LLM深度分析
        llm_result = None
        analysis_text = ""
        try:
            llm_result = self._llm_analyze(self._current_goal, keyword_result)
            analysis_text = llm_result.get("content", "")
        except Exception as e:
            logger.warning(f"LLM分析失败，回退到关键词匹配: {e}")
            analysis_text = f"LLM分析不可用: {e}"

        # 步骤3: 合并结果
        final_score = keyword_result["score"]
        unfinished = keyword_result["unfinished"]
        suggestions = list(keyword_result["suggestions"])
        source = "keyword"

        if llm_result and llm_result.get("success"):
            # LLM分析成功 — 取LLM评分和关键词评分的加权平均
            try:
                llm_score = self._parse_llm_score(analysis_text)
                if 0 <= llm_score <= 100:
                    final_score = int(keyword_result["score"] * 0.4 + llm_score * 0.6)
                    source = "mixed"
            except Exception:
                pass  # LLM评分解析失败，保持关键词评分

            # 从LLM分析中提取未完成项和补救建议
            llm_unfinished = self._parse_llm_unfinished(analysis_text)
            if llm_unfinished:
                unfinished = llm_unfinished
            llm_suggestions = self._parse_llm_suggestions(analysis_text)
            if llm_suggestions:
                suggestions = llm_suggestions

        # 最终评分钳制
        final_score = max(0, min(100, final_score))

        # 基于未完成项调整
        if unfinished:
            penalty = min(30, len(unfinished) * 10)
            final_score = max(0, final_score - penalty)

        # 构建结果
        import time as _time
        result = GoalCheckResult(
            goal=self._current_goal,
            score=final_score,
            unfinished=unfinished,
            suggestions=suggestions,
            llm_analysis=analysis_text,
            source=source,
            checked_at=_time.time(),
        )
        self._last_result = result
        self._check_history.append(result)

        # 限制历史长度
        if len(self._check_history) > self._max_history:
            self._check_history = self._check_history[-self._max_history:]

        return result.to_dict()

    # ── 关键词快速检查 ──────────────────────────────────

    def _keyword_check(self, goal_text: str) -> Dict[str, Any]:
        """
        基于关键词词典的快速检查。

        对目标文本和最近执行结果进行关键词匹配，
        计算基础达成度评分。

        Args:
            goal_text: 目标文本

        Returns:
            {
                "score": int,           # 0-100
                "unfinished": [str],    # 检测到的未完成信号
                "suggestions": [str],   # 基于关键词的建议
                "matched": [str],      # 匹配到的关键词
            }
        """
        base_score = 50  # 基准分 — 不确定状态
        matched_keywords: List[str] = []
        unfinished_items: List[str] = []
        suggestions: List[str] = []

        text_lower = goal_text.lower()

        for category, patterns in self._KEYWORDS.items():
            for keyword, (weight, label) in patterns.items():
                if keyword.lower() in text_lower:
                    base_score += weight
                    matched_keywords.append(f"{keyword}({label}, {weight:+d})")

                    if label == "in_progress":
                        unfinished_items.append(f"任务仍在进行中: 检测到'{keyword}'信号")
                    elif label == "failure":
                        unfinished_items.append(f"检测到失败信号: '{keyword}'")
                        suggestions.append(f"检查并修复'{keyword}'相关的问题")

        # 如果目标包含多个步骤标记 (如 "1.", "步驟", "Step")
        step_markers = re.findall(r'(?:步骤|step|阶段|phase)\s*\d+', text_lower)
        if step_markers:
            # 有步骤标记但未确认全部完成
            all_complete_patterns = ["全部完成", "所有步骤已完成", "全部通过", "all done",
                                     "all steps completed", "所有阶段完成"]
            if not any(kw in text_lower for kw in all_complete_patterns):
                unfinished_items.append(f"目标包含{len(step_markers)}个步骤，未确认全部完成")
                suggestions.append("确认所有步骤是否已完成，列出各步骤完成状态")

        # 如果完全没有匹配到任何关键词
        if not matched_keywords:
            base_score = 40  # 信息不足
            suggestions.append("目标描述缺少明确的完成/进行中/失败信号，建议补充状态说明")

        # 钳制评分
        base_score = max(0, min(100, base_score))

        return {
            "score": base_score,
            "unfinished": unfinished_items,
            "suggestions": suggestions,
            "matched": matched_keywords,
        }

    # ── LLM深度分析 ─────────────────────────────────────

    def _llm_analyze(self, goal_text: str,
                     keyword_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用LLM进行深度目标达成度分析。

        通过 gateway_llm.send_message 调用LLM，
        让AI模型评估目标达成情况。

        Args:
            goal_text: 目标文本
            keyword_result: 关键词匹配结果

        Returns:
            {
                "success": bool,
                "content": str,     # LLM回复文本
                "model": str,       # 使用的模型
                "latency_ms": float,
            }
        """
        try:
            from .gateway_llm import get_gateway_llm
            adapter = get_gateway_llm()

            # 构造提示词
            prompt = self._build_llm_prompt(goal_text, keyword_result)

            # 使用非流式调用
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在事件循环中运行 — 需要特殊处理
                    # 这里使用同步方式：直接调用 chat
                    result = adapter.fallback_to_template  # 暂存
                    # 尝试同步调用
                    result = loop.run_until_complete(
                        adapter.chat("goal_checker", prompt,
                                     system_prompt=self._goal_checker_system_prompt())
                    )
                else:
                    result = loop.run_until_complete(
                        adapter.chat("goal_checker", prompt,
                                     system_prompt=self._goal_checker_system_prompt())
                    )
            except RuntimeError:
                # 没有事件循环 — 创建新的
                result = asyncio.run(
                    adapter.chat("goal_checker", prompt,
                                 system_prompt=self._goal_checker_system_prompt())
                )
            except Exception:
                # 回退：尝试直接用 model_registry
                result = self._llm_direct_call(prompt)

            return result

        except ImportError:
            logger.warning("gateway_llm 模块不可用，回退到直接调用")
            return self._llm_direct_call(
                self._build_llm_prompt(goal_text, keyword_result)
            )
        except Exception as e:
            logger.error(f"LLM分析异常: {e}")
            return {"success": False, "content": f"LLM分析失败: {e}"}

    def _llm_direct_call(self, prompt: str) -> Dict[str, Any]:
        """
        直接通过 model_registry 调用LLM (绕过 gateway_llm)。

        用于 gateway_llm 不可用时的回退方案。
        """
        try:
            from src.model_registry import get_registry
            registry = get_registry()
            # 尝试获取可用模型
            available = [e for e in registry.list_all() if e.get("ready")]
            if not available:
                return {"success": False, "content": "无可用模型"}

            model_id = available[0]["id"]
            client = registry.get(model_id)
            if client is None:
                return {"success": False, "content": f"模型 {model_id} 不可用"}

            messages = [
                {"role": "system", "content": self._goal_checker_system_prompt()},
                {"role": "user", "content": prompt},
            ]

            result = client.chat(messages)
            content = result.get("content", "") if isinstance(result, dict) else str(result)

            return {
                "success": True,
                "content": content,
                "model": model_id,
                "latency_ms": 0,
            }
        except ImportError:
            return {"success": False, "content": "model_registry 不可用"}
        except Exception as e:
            return {"success": False, "content": f"直接调用失败: {e}"}

    def _goal_checker_system_prompt(self) -> str:
        """目标自检器专用系统提示词"""
        return (
            "你是一个目标达成度评估专家。你的任务是严格评估给定目标的完成情况。\n\n"
            "返回格式要求 (必须严格遵守):\n"
            "1. 评分: [0-100的整数]\n"
            "2. 未完成项: [列出所有未完成的具体事项，每项用 - 开头]\n"
            "3. 补救建议: [针对每个未完成项给出具体建议，每项用 * 开头]\n\n"
            "评分标准:\n"
            "- 100: 所有任务完全完成，无任何遗漏\n"
            "- 80-99: 主要任务完成，仅剩小细节\n"
            "- 60-79: 核心任务完成，仍有部分未完成\n"
            "- 40-59: 半数任务完成，多数仍在进行\n"
            "- 20-39: 仅少量任务完成\n"
            "- 0-19: 基本未启动或全部失败\n\n"
            "请用中文回复。"
        )

    def _build_llm_prompt(self, goal_text: str,
                          keyword_result: Dict[str, Any]) -> str:
        """
        构建LLM分析提示词。

        将目标文本和关键词匹配结果组合成结构化的提示词，
        引导LLM输出评分、未完成项和补救建议。
        """
        score = keyword_result.get("score", 50)
        matched = keyword_result.get("matched", [])
        unfinished_kw = keyword_result.get("unfinished", [])
        suggestions_kw = keyword_result.get("suggestions", [])

        prompt_parts = [
            f"请评估以下目标的完成情况:\n",
            f"=== 目标 ===\n{goal_text}\n",
            f"=== 关键词快速检查结果 ===\n",
            f"初步评分: {score}/100",
        ]

        if matched:
            prompt_parts.append(f"匹配关键词: {', '.join(matched[:10])}")
        if unfinished_kw:
            prompt_parts.append(f"检测到未完成信号: {'; '.join(unfinished_kw[:5])}")

        prompt_parts.append("\n请按以下格式回复:\n"
                          "评分: [0-100]\n"
                          "未完成项:\n"
                          "- [事项1]\n"
                          "- [事项2]\n"
                          "补救建议:\n"
                          "* [建议1]\n"
                          "* [建议2]")

        return "\n".join(prompt_parts)

    def _parse_llm_score(self, llm_text: str) -> int:
        """
        从LLM回复中解析达成度评分。

        匹配模式: "评分: XX" 或 "score: XX" 或 "达成度: XX%"
        """
        # 模式1: "评分: 85"
        m = re.search(r'评分[：:]\s*(\d+)', llm_text)
        if m:
            return int(m.group(1))

        # 模式2: "score: 85"
        m = re.search(r'score[：:]\s*(\d+)', llm_text, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # 模式3: "达成度: 85%"
        m = re.search(r'达成度[：:]\s*(\d+)\s*%?', llm_text)
        if m:
            return int(m.group(1))

        # 模式4: "80/100"
        m = re.search(r'(\d+)\s*/\s*100', llm_text)
        if m:
            return int(m.group(1))

        # 未找到 — 返回默认分
        return -1

    def _parse_llm_unfinished(self, llm_text: str) -> List[str]:
        """
        从LLM回复中解析未完成项列表。

        匹配以 "- " 或 "• " 开头的行 (在"未完成项:"标题之后)
        """
        unfinished: List[str] = []

        # 查找 "未完成项:" 之后的内容
        section = re.search(
            r'未完成项[：:]\s*\n((?:[-•]\s*.+\n?)*)',
            llm_text
        )
        if section:
            for line in section.group(1).strip().split('\n'):
                line = line.strip()
                if line and re.match(r'^[-•]\s+', line):
                    item = re.sub(r'^[-•]\s+', '', line).strip()
                    if item:
                        unfinished.append(item)

        # 如果没找到专门段落，搜索全文中以 "- " 开头的行
        if not unfinished:
            for line in llm_text.split('\n'):
                line = line.strip()
                if re.match(r'^[-•]\s+', line) and len(line) > 3:
                    item = re.sub(r'^[-•]\s+', '', line).strip()
                    if item and len(item) > 3:
                        unfinished.append(item)

        # 去重并限制数量
        seen = set()
        result = []
        for item in unfinished:
            if item not in seen and len(item) < 200:
                seen.add(item)
                result.append(item)
        return result[:10]

    def _parse_llm_suggestions(self, llm_text: str) -> List[str]:
        """
        从LLM回复中解析补救建议列表。

        匹配以 "* " 开头的行 (在"补救建议:"标题之后)
        """
        suggestions: List[str] = []

        # 查找 "补救建议:" 之后的内容
        section = re.search(
            r'补救建议[：:]\s*\n((?:\*\s*.+\n?)*)',
            llm_text
        )
        if section:
            for line in section.group(1).strip().split('\n'):
                line = line.strip()
                if line and line.startswith('*'):
                    item = line[1:].strip()
                    if item:
                        suggestions.append(item)

        # 如果没找到专门段落，搜索全文中以 "* " 开头的行
        if not suggestions:
            for line in llm_text.split('\n'):
                line = line.strip()
                if line.startswith('* ') and len(line) > 3:
                    item = line[1:].strip()
                    if item and len(item) > 3:
                        suggestions.append(item)

        # 去重并限制数量
        seen = set()
        result = []
        for item in suggestions:
            if item not in seen and len(item) < 300:
                seen.add(item)
                result.append(item)
        return result[:10]

    def _empty_result(self, reason: str) -> Dict[str, Any]:
        """生成空结果 (无目标或检查失败时)"""
        import time
        return GoalCheckResult(
            goal=self._current_goal or "",
            score=0,
            unfinished=[reason],
            suggestions=["请先使用 set_goal() 设置检查目标"],
            checked_at=time.time(),
        ).to_dict()

    # ── 辅助方法 ────────────────────────────────────────

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """获取最近一次检查结果"""
        if self._last_result:
            return self._last_result.to_dict()
        return None

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取检查历史"""
        return [r.to_dict() for r in self._check_history[-limit:]]

    def reset(self) -> None:
        """重置检查器状态"""
        self._current_goal = ""
        self._last_result = None
        self._check_history.clear()
        logger.info("GoalChecker 已重置")

    def get_stats(self) -> Dict[str, Any]:
        """获取检查器统计信息"""
        history = self._check_history
        scores = [r.score for r in history] if history else []
        return {
            "current_goal": self._current_goal[:100] if self._current_goal else "",
            "total_checks": len(history),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "last_check_at": self._last_result.checked_at if self._last_result else 0,
        }


# ═══════════════════════════════════════════════════════════
# 单例工厂函数
# ═══════════════════════════════════════════════════════════

_goal_checker: Optional[GoalChecker] = None


def get_goal_checker() -> GoalChecker:
    """
    获取GoalChecker单例实例。

    首次调用时自动创建，后续调用返回同一实例。

    Returns:
        GoalChecker: 全局唯一的目标自检器实例
    """
    global _goal_checker
    if _goal_checker is None:
        _goal_checker = GoalChecker()
    return _goal_checker


def reset_goal_checker() -> None:
    """重置GoalChecker单例 (主要用于测试)"""
    global _goal_checker
    if _goal_checker:
        _goal_checker.reset()
    _goal_checker = None
    GoalChecker._instance = None
