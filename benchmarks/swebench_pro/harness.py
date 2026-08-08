"""
SWE-bench Pro Harness — 测试框架对接

本 harness 负责：
1. 加载 SWE-bench Pro 任务
2. 通过 MeshctxAdapter 调用 meshctx agent 修复每个 instance
3. 收集 agent 输出并交给 scorer 评分
4. 输出最终的 JSON 评分报告

2026 规范对齐:
- 每个 instance 独立运行，agent 需生成 patch
- 支持 docker 沙箱内测试验证（可选）
- resolve_rate = resolved / total instances
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加父目录到路径，以便导入适配器
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult

from scorer import SWEBenchProScorer


class SWEBenchProHarness:
    """SWE-bench Pro 测试框架"""

    def __init__(
        self,
        tasks_file: str,
        model: Optional[str] = None,
        timeout: int = 600,
        max_steps: int = 30,
        output_dir: Optional[str] = None,
    ):
        """
        初始化 harness。

        参数:
            tasks_file: 任务文件路径
            model: 使用的模型 ID
            timeout: 每个 instance 的超时（秒）
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
        self.scorer = SWEBenchProScorer(str(tasks_file))

        # 加载任务
        with open(tasks_file, "r", encoding="utf-8") as f:
            self.tasks = json.load(f)

        self.results: List[Dict[str, Any]] = []

    def run(self, instance_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        运行所有任务（或指定的 instance）。

        参数:
            instance_ids: 要运行的 instance ID 列表，None 表示全部

        返回:
            完整的评分报告
        """
        tasks_to_run = self.tasks
        if instance_ids:
            tasks_to_run = [t for t in self.tasks if t.get("instance_id") in instance_ids]

        print(f"SWE-bench Pro Harness — 开始运行 {len(tasks_to_run)} 个 instance")
        print(f"模型: {self.adapter.model}")
        print(f"超时: {self.adapter.timeout}s, 最大步数: {self.adapter.max_steps}")
        print("=" * 60)

        for i, task in enumerate(tasks_to_run):
            instance_id = task.get("instance_id", f"task_{i}")
            print(f"\n[{i+1}/{len(tasks_to_run)}] {instance_id}...")

            result = self._run_single(task)
            self.results.append(result)

            status = "✓ RESOLVED" if result["resolved"] else "✗ UNRESOLVED"
            print(f"  {status} (similarity={result['patch_similarity']:.2%})")

        # 汇总评分
        score = self.scorer.score_batch(self.results)

        # 保存结果
        self._save_results(score)

        return score

    def _run_single(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个 instance"""
        instance_id = task.get("instance_id", "unknown")
        problem = task.get("problem_statement", task.get("problem", ""))
        repo = task.get("repo", "")
        base_commit = task.get("base_commit", "")
        hint = task.get("hint", "")
        gold_patch = task.get("gold_patch", "")

        # 构建任务描述
        task_description = f"""请修复以下软件工程问题。

## 仓库
{repo}

## 基准提交
{base_commit}

## 问题描述
{problem}
"""

        if hint:
            task_description += f"\n## 提示\n{hint}\n"

        task_description += f"""
## 要求
1. 分析问题的根本原因
2. 在仓库中定位需要修改的文件
3. 生成 unified diff 格式的补丁（patch）
4. 补丁应以 ```diff 代码块包裹
5. 确保修改最小化，只改必要的代码

请立即开始修复。实例ID: {instance_id}
"""

        # 上下文信息
        context = f"仓库: {repo}\n基准提交: {base_commit}\n实例ID: {instance_id}"

        # 运行 agent
        adapter_result = self.adapter.run_with_retry(
            task=task_description,
            context=context,
            max_retries=1,
        )

        # 评分
        single_score = self.scorer.score_single(
            instance_id=instance_id,
            agent_output=adapter_result.output,
            gold_patch=gold_patch,
            test_output=adapter_result.error if adapter_result.error else None,
        )

        # 附加 agent 运行信息
        single_score["agent"] = {
            "elapsed_seconds": adapter_result.elapsed_seconds,
            "exit_code": adapter_result.exit_code,
            "timed_out": adapter_result.timed_out,
            "output_length": len(adapter_result.output),
        }

        return single_score

    def _save_results(self, score: Dict[str, Any]) -> None:
        """保存评分结果到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 完整报告
        report_path = self.output_dir / f"swebench_pro_report_{timestamp}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)

        # 摘要
        summary_path = self.output_dir / f"swebench_pro_summary_{timestamp}.json"
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
        print("  SWE-bench Pro 评分报告")
        print("=" * 60)
        print(f"  总实例数:     {s['total_instances']}")
        print(f"  已解决:       {s['resolved']}")
        print(f"  未解决:       {s['unresolved']}")
        print(f"  解决率:       {s['resolve_rate']:.2%}")
        print(f"  平均相似度:   {s['avg_patch_similarity']:.2%}")
        print("-" * 60)

        t = score.get("test_results", {})
        if t.get("tests_total", 0) > 0:
            print(f"  测试通过:     {t['tests_passed']}/{t['tests_total']} ({t['test_pass_rate']:.2%})")

        print("=" * 60)


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="SWE-bench Pro Harness — 运行 meshctx agent 并评分",
    )
    parser.add_argument(
        "-t", "--tasks",
        default="sample_tasks.json",
        help="任务文件路径 (默认: sample_tasks.json)",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        help="模型 ID (默认: 环境变量 MESHCTX_MODEL)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="每个 instance 的超时秒数 (默认: 600)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=30,
        help="agent 最大步数 (默认: 30)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="输出目录 (默认: ./results)",
    )
    parser.add_argument(
        "--instance",
        nargs="+",
        help="仅运行指定的 instance ID",
    )

    args = parser.parse_args()

    harness = SWEBenchProHarness(
        tasks_file=args.tasks,
        model=args.model,
        timeout=args.timeout,
        max_steps=args.max_steps,
        output_dir=args.output_dir,
    )

    score = harness.run(instance_ids=args.instance)
    harness.print_summary()

    # 命令行返回 JSON 汇总
    print("\nJSON 汇总:")
    print(json.dumps(score["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
