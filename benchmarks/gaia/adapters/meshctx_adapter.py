"""
GAIA Meshctx 适配器

GAIA benchmark 专用的适配器扩展，继承自通用 MeshctxAdapter，
添加了网页浏览、文件处理和答案提取功能。

GAIA 任务通常需要:
- 网页浏览和信息检索
- 多模态文件处理（图片、PDF、音频）
- 多步推理和答案合成
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_adapter_dir = str(Path(__file__).resolve().parent.parent.parent / "adapters")
if _adapter_dir not in sys.path:
    sys.path.insert(0, _adapter_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult  # noqa: E402


class GAIAAdapter(MeshctxAdapter):
    """
    GAIA Benchmark 专用适配器

    扩展功能:
    - 增强的答案提取（支持多种输出格式）
    - 分级难度处理策略
    - 文件附件处理提示
    """

    # GAIA Level 配置
    LEVEL_CONFIG = {
        1: {
            "name": "L1 — 基础",
            "max_steps": 10,
            "timeout": 180,
            "tools_hint": "使用 web_search 和信息检索工具",
            "prompt_template": "请回答以下问题，答案应简洁明确。\n\n{question}\n\n请以 '答案: <your answer>' 格式输出。",
        },
        2: {
            "name": "L2 — 中等",
            "max_steps": 25,
            "timeout": 300,
            "tools_hint": "使用 web_search、browser 和多步推理",
            "prompt_template": (
                "请回答以下问题。这可能需要进行多步推理和工具使用。\n\n"
                "{question}\n\n"
                "请分步骤思考，最终以 '答案: <your answer>' 格式输出。"
            ),
        },
        3: {
            "name": "L3 — 高级",
            "max_steps": 40,
            "timeout": 600,
            "tools_hint": "使用所有可用工具，包括浏览器、代码执行、文件处理",
            "prompt_template": (
                "请回答以下复杂问题。这可能涉及多步推理、多模态理解和外部工具。\n\n"
                "{question}\n\n"
                "请深入分析，逐步推理，最终以 '答案: <your answer>' 格式输出。"
            ),
        },
    }

    def run_gaia_task(
        self,
        task: Dict,
        level: Optional[int] = None,
    ) -> Dict:
        """
        运行 GAIA 任务。

        参数:
            task: 任务字典
            level: 强制指定 level（覆盖 task 中的 level）

        返回:
            包含答案和元信息的字典
        """
        task_id = task.get("task_id", "unknown")
        question = task.get("question", task.get("Question", ""))
        level = level or task.get("level", 1)
        answer_type = task.get("answer_type", "text")
        file_name = task.get("file_name", "")
        ground_truth = task.get("ground_truth", "")

        config = self.LEVEL_CONFIG.get(level, self.LEVEL_CONFIG[1])

        # 构建 prompt
        prompt = config["prompt_template"].format(question=question)

        # 上下文
        context_parts = [
            f"任务ID: {task_id}",
            f"难度: Level {level}",
            f"答案类型: {answer_type}",
            f"推荐工具: {config['tools_hint']}",
        ]
        if file_name:
            context_parts.append(f"附件文件: {file_name}")

        context = "\n".join(context_parts)

        # 运行 agent（使用 level 特定的超时和步数）
        adapter_result = self.run_with_retry(
            task=prompt,
            context=context,
            timeout=config["timeout"],
            max_steps=config["max_steps"],
        )

        # 提取答案
        answer = self._extract_gaia_answer(adapter_result.output, answer_type)

        return {
            "task_id": task_id,
            "level": level,
            "question": question,
            "answer": answer,
            "ground_truth": ground_truth,
            "answer_type": answer_type,
            "agent_result": adapter_result.to_dict(),
        }

    def run_batch(
        self,
        tasks: List[Dict],
        levels: Optional[List[int]] = None,
    ) -> List[Dict]:
        """
        批量运行 GAIA 任务。

        参数:
            tasks: 任务列表
            levels: 要运行的 level 列表

        返回:
            结果列表
        """
        results = []
        filtered = tasks
        if levels:
            filtered = [t for t in tasks if t.get("level") in levels]

        for task in filtered:
            result = self.run_gaia_task(task)
            results.append(result)

        return results

    @staticmethod
    def _extract_gaia_answer(text: str, answer_type: str = "text") -> str:
        """从 agent 输出中提取 GAIA 格式的答案"""
        if not text:
            return ""

        # 查找明确的答案标记
        patterns = [
            r"答案[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
            r"(?i)answer[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
            r"最终答案[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
            r"(?i)final answer[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
            r"结果是[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
            r"输出[：:]\s*(.+?)(?:\n\n|\n\Z|\Z)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                answer = match.group(1).strip()
                # 清理常见后缀
                for suffix in ["。", ".", "，", ",", "；", ";"]:
                    if answer.endswith(suffix):
                        answer = answer[:-1].strip()
                return answer

        # 如果没有标记，取最后一个有意义段落
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            skip_prefixes = [
                "```", "好的", "我来", "让我", "首先", "接下来",
                "执行", "运行", "任务", "level", "难度", "步骤",
                "badge", "badge", "note", "注意", "提示", "分析",
            ]
            for line in reversed(lines):
                lower = line.lower()
                if not any(lower.startswith(p) for p in skip_prefixes):
                    if len(line) < 500:  # 避免过长的输出
                        return line

        return text.strip()[:200]  # 最多取 200 字符
