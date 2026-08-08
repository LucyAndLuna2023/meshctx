"""
Terminal-Bench 2.0 Harness — 测试框架对接

本 harness 负责：
1. 加载 Terminal-Bench 2.0 任务
2. 通过 MeshctxAdapter 调用 meshctx agent 执行终端命令
3. 收集 agent 的 shell 输出并交给 scorer 评分
4. 输出最终的 JSON 评分报告

2026 规范对齐:
- 三个评分维度: exit_code (15%), stdout_match (50%), timeout (10%)
- 附加维度: stderr_check (10%), efficiency (15%)
- pass_rate = passed / total tasks
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult  # noqa: E402

from scorer import TerminalBenchScorer  # noqa: E402


class TerminalBenchHarness:
    """Terminal-Bench 2.0 测试框架"""

    def __init__(
        self,
        tasks_file: str,
        model: Optional[str] = None,
        timeout: int = 300,
        max_steps: int = 20,
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
        self.scorer = TerminalBenchScorer(str(tasks_file))

        with open(tasks_file, "r", encoding="utf-8") as f:
            self.tasks = json.load(f)

        self.results: List[Dict[str, Any]] = []

    def run(self, task_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        运行所有任务（或指定的 task）。

        参数:
            task_ids: 要运行的 task ID 列表，None 表示全部

        返回:
            完整的评分报告
        """
        tasks_to_run = self.tasks
        if task_ids:
            tasks_to_run = [t for t in self.tasks if t.get("task_id") in task_ids]

        print(f"Terminal-Bench 2.0 Harness — 开始运行 {len(tasks_to_run)} 个任务")
        print(f"模型: {self.adapter.model}")
        print(f"超时: {self.adapter.timeout}s, 最大步数: {self.adapter.max_steps}")
        print("=" * 60)

        for i, task in enumerate(tasks_to_run):
            task_id = task.get("task_id", f"task_{i}")
            print(f"\n[{i+1}/{len(tasks_to_run)}] {task_id}...")

            result = self._run_single(task)
            self.results.append(result)

            status = "✓ PASSED" if result["passed"] else "✗ FAILED"
            print(f"  {status} (score={result['total_score']:.2%})")

        # 汇总评分
        score = self.scorer.score_batch(self.results)
        self._save_results(score)

        return score

    def _run_single(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个 task"""
        task_id = task.get("task_id", "unknown")
        description = task.get("description", task.get("task", ""))
        prompt = task.get("prompt", description)
        expected_output = task.get("expected_output", "")
        expected_exit_code = task.get("expected_exit_code", 0)
        success_criteria = task.get("success_criteria")
        setup_commands = task.get("setup_commands", [])

        # 构建任务描述
        task_description = f"""请在终端中完成以下任务。

## 任务描述
{prompt}

## 要求
1. 使用 shell 命令在终端中完成任务
2. 确保命令执行成功（exit code 0）
3. 输出结果应符合预期格式
4. 如果任务包含多个步骤，逐步执行

任务ID: {task_id}
"""

        # 如果有 setup 命令，添加到上下文中
        context = ""
        if setup_commands:
            context = "Setup 命令:\n" + "\n".join(f"  $ {cmd}" for cmd in setup_commands)

        # 运行 agent
        adapter_result = self.adapter.run_with_retry(
            task=task_description,
            context=context,
            max_retries=1,
        )

        # 官方 agent 协议：优先解析 ---MESHCTX_JSON_OUTPUT--- 标记中的 final_answer
        # 有标记 → 提取 final_answer 直接提交（submit 语义）
        # 无标记 → 维持 observation→action 提取兜底
        extracted_output = self._extract_json_answer(adapter_result.output)
        if extracted_output is None:
            extracted_output = self._extract_shell_output(adapter_result.output)

        # 评分
        single_score = self.scorer.score_single(
            task_id=task_id,
            agent_output=extracted_output,
            exit_code=adapter_result.exit_code,
            timed_out=adapter_result.timed_out,
            elapsed_seconds=adapter_result.elapsed_seconds,
            expected_output=expected_output,
            expected_exit_code=expected_exit_code,
            success_criteria=success_criteria,
        )

        single_score["agent"] = {
            "elapsed_seconds": adapter_result.elapsed_seconds,
            "exit_code": adapter_result.exit_code,
            "timed_out": adapter_result.timed_out,
            "output_length": len(adapter_result.output),
        }

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
    def _extract_shell_output(agent_output: str) -> str:
        """从 agent 完整输出中提取 shell 执行结果"""
        if not agent_output:
            return ""

        # 查找常见的输出标记
        markers = [
            r"```\s*\n(.*?)```",   # 代码块
            r"\$\s+([^\n]+)",       # $ 开头的命令
            r">>>\s+(.+?)(?:\n|$)", # >>> 开头的输出
        ]

        import re
        extracted: List[str] = []
        for marker in markers:
            matches = re.findall(marker, agent_output, re.DOTALL)
            for m in matches:
                line = m.strip()
                if line and not line.startswith("```"):
                    extracted.append(line)

        if extracted:
            return "\n".join(extracted)

        # 去掉明显的对话文本，保留似乎是命令输出的部分
        lines = agent_output.split("\n")
        output_lines = []
        for line in lines:
            # 跳过明显的对话文本
            skip_patterns = [
                r"^(好的|我来|让我|首先|接下来|最后|执行|运行)",
                r"^(Sure|Let me|First|Next|Finally|I will)",
                r"^\[.*\].*\.\.\.$",
            ]
            should_skip = any(re.match(p, line) for p in skip_patterns)
            if not should_skip and line.strip():
                output_lines.append(line)

        return "\n".join(output_lines) if output_lines else agent_output

    def _save_results(self, score: Dict[str, Any]) -> None:
        """保存评分结果到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_path = self.output_dir / f"terminal_bench_report_{timestamp}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)

        summary_path = self.output_dir / f"terminal_bench_summary_{timestamp}.json"
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
        print("  Terminal-Bench 2.0 评分报告")
        print("=" * 60)
        print(f"  总任务数:     {s['total_tasks']}")
        print(f"  通过:         {s['passed']}")
        print(f"  失败:         {s['failed']}")
        print(f"  通过率:       {s['pass_rate']:.2%}")
        print(f"  平均分:       {s['avg_total_score']:.2%}")
        print("-" * 60)
        print("  各维度平均分:")
        for name, dim in score.get("dimensions", {}).items():
            print(f"    {name:20s}: {dim['avg_score']:.2%} (权重={dim['weight']:.0%})")
        print("=" * 60)


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Terminal-Bench 2.0 Harness — 运行 meshctx agent 并评分",
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
        default=300,
        help="每个 task 的超时秒数 (默认: 300)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="agent 最大步数 (默认: 20)",
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

    args = parser.parse_args()

    harness = TerminalBenchHarness(
        tasks_file=args.tasks,
        model=args.model,
        timeout=args.timeout,
        max_steps=args.max_steps,
        output_dir=args.output_dir,
    )

    score = harness.run(task_ids=args.task)
    harness.print_summary()

    print("\nJSON 汇总:")
    print(json.dumps(score["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
