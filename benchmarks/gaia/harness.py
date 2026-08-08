"""
GAIA Benchmark Harness — 测试框架对接

本 harness 负责：
1. 加载 GAIA 任务
2. 通过 MeshctxAdapter 调用 meshctx agent 回答问题
3. 收集 agent 答案并交给 scorer 评分
4. 输出按 Level 分组的 JSON 评分报告

2026 规范对齐:
- 三级难度: L1 (基础), L2 (中等), L3 (高级)
- 评分方式: exact match / normalized match / F1
- 2026 leaderboard: Manus AI 86.5% L1
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult  # noqa: E402

from scorer import GAIAScorer  # noqa: E402


class GAIAHarness:
    """GAIA Benchmark 测试框架"""

    LEVEL_NAMES = {
        1: "L1 — 基础信息检索与推理",
        2: "L2 — 多步推理与工具使用",
        3: "L3 — 复杂推理与多模态理解",
    }

    def __init__(
        self,
        tasks_file: str,
        model: Optional[str] = None,
        timeout: int = 600,
        max_steps: int = 40,
        output_dir: Optional[str] = None,
    ):
        """
        初始化 harness。

        参数:
            tasks_file: 任务文件路径
            model: 使用的模型 ID
            timeout: 每个 task 的超时（秒）
            max_steps: agent 最大步数
            output_dir: 输出目录
        """
        self.tasks_file = Path(tasks_file)
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "results"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.adapter = MeshctxAdapter(
            model=model,
            timeout=timeout,
            max_steps=max_steps,
        )
        self.scorer = GAIAScorer(str(tasks_file))

        with open(tasks_file, "r", encoding="utf-8") as f:
            self.tasks = json.load(f)

        self.results: List[Dict[str, Any]] = []

    def run(
        self,
        task_ids: Optional[List[str]] = None,
        levels: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        运行所有任务（可按 task_id 或 level 筛选）。

        参数:
            task_ids: 要运行的 task ID 列表
            levels: 要运行的 level 列表 (e.g., [1, 2])

        返回:
            完整的评分报告
        """
        tasks_to_run = self.tasks

        if task_ids:
            tasks_to_run = [t for t in tasks_to_run if t.get("task_id") in task_ids]
        if levels:
            tasks_to_run = [t for t in tasks_to_run if t.get("level") in levels]

        print(f"GAIA Harness — 开始运行 {len(tasks_to_run)} 个任务")
        print(f"模型: {self.adapter.model}")
        print(f"超时: {self.adapter.timeout}s, 最大步数: {self.adapter.max_steps}")
        print("=" * 60)

        for i, task in enumerate(tasks_to_run):
            task_id = task.get("task_id", f"task_{i}")
            level = task.get("level", 1)
            level_name = self.LEVEL_NAMES.get(level, f"L{level}")

            print(f"\n[{i+1}/{len(tasks_to_run)}] [{level_name}] {task_id}...")

            result = self._run_single(task)
            self.results.append(result)

            status = "✓ CORRECT" if result["correct"] else "✗ INCORRECT"
            match_type = "exact" if result["exact_match"] else ("norm" if result.get("normalized_match") else f"f1={result['f1_score']:.2f}")
            print(f"  {status} ({match_type})")

        score = self.scorer.score_batch(self.results)
        self._save_results(score)

        return score

    def _run_single(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个 GAIA task"""
        task_id = task.get("task_id", "unknown")
        question = task.get("question", task.get("Question", ""))
        level = task.get("level", 1)
        ground_truth = task.get("ground_truth", task.get("Ground truth", ""))
        answer_type = task.get("answer_type", "text")
        file_name = task.get("file_name", "")
        file_path = task.get("file_path", "")
        hint = task.get("hint", "")

        # 构建任务描述
        task_description = f"""请回答以下 GAIA 基准测试问题。回答时请直接给出最终答案，格式为 "答案: <your answer>"。

## 问题
{question}

## 难度级别
Level {level} — {self.LEVEL_NAMES.get(level, '')}

## 答案类型
{answer_type}

## 要求
1. 仔细分析问题，确定需要哪些信息
2. 使用工具（搜索、浏览网页、读取文件等）获取必要信息
3. 执行必要的推理步骤
4. 最终以 "答案: <answer>" 格式输出你的回答
5. 答案应简洁准确，如果是数字只给出数字，如果是名称只给出名称

任务ID: {task_id}
"""

        context = f"任务ID: {task_id}\n难度: Level {level}\n答案类型: {answer_type}"
        if file_name:
            context += f"\n附件: {file_name}"
        if hint:
            context += f"\n提示: {hint}"

        # 运行 agent
        adapter_result = self.adapter.run_with_retry(
            task=task_description,
            context=context,
            max_retries=1,
        )

        # 官方 agent 协议：优先解析 ---MESHCTX_JSON_OUTPUT--- 标记中的 final_answer
        # 有标记 → 提取 final_answer 直接提交（submit 语义）
        # 无标记 → 维持 observation→action 提取兜底
        answer = self._extract_json_answer(adapter_result.output)
        if answer is None:
            answer = self._extract_answer(adapter_result.output)

        # 评分
        single_score = self.scorer.score_single(
            task_id=task_id,
            agent_answer=answer,
            ground_truth=ground_truth,
            level=level,
            answer_type=answer_type,
        )

        single_score["agent"] = {
            "raw_answer": answer,
            "elapsed_seconds": adapter_result.elapsed_seconds,
            "exit_code": adapter_result.exit_code,
            "timed_out": adapter_result.timed_out,
            "output_length": len(adapter_result.output),
        }
        single_score["ground_truth"] = ground_truth

        return single_score

    @staticmethod
    def _extract_json_answer(agent_output: str) -> Optional[str]:
        """解析 ---MESHCTX_JSON_OUTPUT--- 标记，提取 final_answer 字段。

        官方 agent 协议：agent 输出含该标记时，其后 JSON 的 final_answer
        即为最终答案，harness 直接提取提交（submit 语义）。
        无标记或解析失败返回 None（调用方走 observation→action 兜底）。
        """
        if not agent_output:
            return None
        import re
        m = re.search(r"---MESHCTX_JSON_OUTPUT---\s*(\{.*?\})\s*---END_MESHCTX_JSON_OUTPUT---",
                      agent_output, re.DOTALL)
        if not m:
            return None
        try:
            import json
            data = json.loads(m.group(1))
            answer = data.get("final_answer", "")
            if answer is not None and str(answer).strip():
                return str(answer).strip()
        except Exception:
            return None
        return None

    @staticmethod
    def _extract_answer(text: str) -> str:
        """从 agent 输出中提取最终答案"""
        if not text:
            return ""

        # 查找 "答案:" / "Answer:" 标记
        import re

        patterns = [
            r"答案[：:]\s*(.+?)(?:\n|$)",
            r"(?i)answer[：:]\s*(.+?)(?:\n|$)",
            r"最终答案[：:]\s*(.+?)(?:\n|$)",
            r"(?i)final answer[：:]\s*(.+?)(?:\n|$)",
            r"结果是[：:]\s*(.+?)(?:\n|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        # 如果没有显式标记，取最后一段非空文本作为答案
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            # 跳过明显的非答案行
            skip_prefixes = [
                "```", "好的", "我来", "让我", "首先", "接下来", "执行",
                "task", "任务", "level", "难度", "badge", "badge",
            ]
            for line in reversed(lines):
                if not any(line.lower().startswith(p) for p in skip_prefixes):
                    return line

        return text.strip()

    def _save_results(self, score: Dict[str, Any]) -> None:
        """保存评分结果到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_path = self.output_dir / f"gaia_report_{timestamp}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)

        summary_path = self.output_dir / f"gaia_summary_{timestamp}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(score["summary"], f, ensure_ascii=False, indent=2)

        print(f"\n报告已保存: {report_path}")
        print(f"摘要已保存: {summary_path}")

    def print_summary(self) -> None:
        """打印评分摘要"""
        if not self.results:
            print("尚未运行任何任务。")
            return

        score = self.scorer.score_batch(self.results)
        s = score["summary"]

        print("\n" + "=" * 60)
        print("  GAIA Benchmark 评分报告")
        print("=" * 60)
        print(f"  总任务数:     {s['total_tasks']}")
        print(f"  正确:         {s['correct']}")
        print(f"  错误:         {s['incorrect']}")
        print(f"  准确率:       {s['accuracy']:.2%}")
        print(f"  精确匹配率:   {s['exact_match_rate']:.2%}")
        print(f"  平均 F1:      {s['avg_f1']:.2%}")
        print("-" * 60)
        print("  按 Level 分组:")
        for level, data in score.get("by_level", {}).items():
            level_name = self.LEVEL_NAMES.get(level, f"L{level}")
            print(f"    {level_name}: {data['correct']}/{data['total']} ({data['accuracy']:.2%})")
        print("=" * 60)


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="GAIA Benchmark Harness — 运行 meshctx agent 并评分",
    )
    parser.add_argument(
        "-t", "--tasks",
        default="sample_tasks.json",
        help="任务文件路径 (默认: sample_tasks.json)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="模型 ID",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="每个 task 的超时秒数 (默认: 600)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=40,
        help="agent 最大步数 (默认: 40)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="输出目录 (默认: ./results)",
    )
    parser.add_argument(
        "--task",
        nargs="+",
        help="仅运行指定的 task ID",
    )
    parser.add_argument(
        "--level",
        type=int,
        nargs="+",
        choices=[1, 2, 3],
        help="仅运行指定 level 的任务",
    )

    args = parser.parse_args()

    harness = GAIAHarness(
        tasks_file=args.tasks,
        model=args.model,
        timeout=args.timeout,
        max_steps=args.max_steps,
        output_dir=args.output_dir,
    )

    score = harness.run(task_ids=args.task, levels=args.level)
    harness.print_summary()

    print("\nJSON 汇总:")
    print(json.dumps(score["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
