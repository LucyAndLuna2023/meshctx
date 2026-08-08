"""
Terminal-Bench 2.0 Scorer — 评分逻辑

对齐 2026 年 Terminal-Bench 2.0 规范：
- 每个 task 有 expected_output 和 success criteria
- 通过 agent 执行 shell 命令后的输出匹配来评分
- 支持三个评分维度: timeout、exit_code、stdout_match
- 总分 = passed / total tasks

输出 JSON 格式的评分结果。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class TerminalBenchScorer:
    """Terminal-Bench 2.0 评分器"""

    # 评分权重（2026 规范）
    DEFAULT_WEIGHTS = {
        "exit_code": 0.15,      # 退出码正确性
        "timeout": 0.10,        # 是否超时
        "stdout_match": 0.50,   # 输出内容匹配
        "stderr_check": 0.10,   # 错误输出检查
        "efficiency": 0.15,     # 执行效率（命令数量、耗时）
    }

    def __init__(self, tasks_file: Optional[str] = None):
        """
        初始化评分器。

        参数:
            tasks_file: 任务文件路径
        """
        self.tasks_file = tasks_file
        self.tasks: List[Dict] = []
        self.weights = dict(self.DEFAULT_WEIGHTS)
        if tasks_file and Path(tasks_file).exists():
            with open(tasks_file, "r", encoding="utf-8") as f:
                self.tasks = json.load(f)

    def load_tasks(self, tasks_file: str) -> None:
        """加载任务文件"""
        with open(tasks_file, "r", encoding="utf-8") as f:
            self.tasks = json.load(f)

    def score_single(
        self,
        task_id: str,
        agent_output: str,
        exit_code: int,
        timed_out: bool,
        elapsed_seconds: float,
        expected_output: str = "",
        expected_exit_code: int = 0,
        success_criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        对单个 task 进行评分。

        参数:
            task_id: 任务标识
            agent_output: agent 执行的 shell 命令输出
            exit_code: agent 进程退出码
            timed_out: 是否超时
            elapsed_seconds: 耗时（秒）
            expected_output: 期望输出
            expected_exit_code: 期望退出码
            success_criteria: 成功条件列表（正则表达式）

        返回:
            评分结果字典
        """
        result = {
            "task_id": task_id,
            "passed": False,
            "total_score": 0.0,
            "dimensions": {},
        }

        dims = {}

        # 维度 1: exit_code
        dims["exit_code"] = {
            "score": 1.0 if exit_code == expected_exit_code else 0.0,
            "expected": expected_exit_code,
            "actual": exit_code,
            "weight": self.weights["exit_code"],
        }

        # 维度 2: timeout
        dims["timeout"] = {
            "score": 0.0 if timed_out else 1.0,
            "timed_out": timed_out,
            "elapsed_seconds": elapsed_seconds,
            "weight": self.weights["timeout"],
        }

        # 维度 3: stdout_match
        if expected_output:
            match_score = self._compute_stdout_match(agent_output, expected_output)
            dims["stdout_match"] = {
                "score": match_score,
                "method": "fuzzy",
                "weight": self.weights["stdout_match"],
            }
        else:
            dims["stdout_match"] = {
                "score": 1.0,  # 无期望输出时不扣分
                "method": "none",
                "weight": self.weights["stdout_match"],
            }

        # 维度 4: stderr_check
        # 检查 stderr 是否有意外错误
        has_unexpected_error = exit_code != 0 and not timed_out
        dims["stderr_check"] = {
            "score": 0.0 if has_unexpected_error else 1.0,
            "has_error": has_unexpected_error,
            "weight": self.weights["stderr_check"],
        }

        # 维度 5: efficiency (基于耗时)
        efficiency_score = self._compute_efficiency(elapsed_seconds)
        dims["efficiency"] = {
            "score": efficiency_score,
            "elapsed_seconds": elapsed_seconds,
            "weight": self.weights["efficiency"],
        }

        # 计算总分
        total_score = sum(
            d["score"] * d["weight"] for d in dims.values()
        )
        result["total_score"] = round(total_score, 4)
        result["dimensions"] = dims

        # 判断是否通过（总分 ≥ 0.80 视为通过）
        result["passed"] = result["total_score"] >= 0.80

        # 额外检查 success criteria
        if success_criteria:
            criteria_results = self._check_success_criteria(agent_output, success_criteria)
            result["success_criteria"] = criteria_results
            # 所有 success criteria 必须满足
            all_criteria_met = all(c["matched"] for c in criteria_results)
            if not all_criteria_met:
                result["passed"] = False

        return result

    def score_batch(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量评分，计算总体指标。

        参数:
            results: 单个 task 评分结果列表

        返回:
            聚合评分结果（JSON 格式）
        """
        total = len(results)
        passed = sum(1 for r in results if r.get("passed", False))
        avg_score = sum(r.get("total_score", 0) for r in results) / max(total, 1)

        # 按维度汇总
        dim_summary: Dict[str, Dict[str, float]] = {}
        for r in results:
            for dim_name, dim_data in r.get("dimensions", {}).items():
                if dim_name not in dim_summary:
                    dim_summary[dim_name] = {"total": 0, "count": 0}
                dim_summary[dim_name]["total"] += dim_data.get("score", 0)
                dim_summary[dim_name]["count"] += 1

        dimensions = {}
        for name, data in dim_summary.items():
            dimensions[name] = {
                "avg_score": round(data["total"] / max(data["count"], 1), 4),
                "weight": self.weights.get(name, 0),
            }

        score = {
            "benchmark": "Terminal-Bench 2.0",
            "version": "2026",
            "summary": {
                "total_tasks": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": round(passed / max(total, 1), 4),
                "avg_total_score": round(avg_score, 4),
            },
            "dimensions": dimensions,
            "per_task": results,
        }

        return score

    def _compute_stdout_match(self, actual: str, expected: str) -> float:
        """计算输出匹配度（模糊匹配）"""
        if not expected:
            return 1.0
        if not actual:
            return 0.0

        # 标准化: 去空白、转小写
        actual_norm = " ".join(actual.lower().split())
        expected_norm = " ".join(expected.lower().split())

        # 完全匹配
        if actual_norm == expected_norm:
            return 1.0

        # 子串匹配
        if expected_norm in actual_norm:
            return 0.90

        # 标记重合度（Jaccard-like）
        actual_tokens = set(actual_norm.split())
        expected_tokens = set(expected_norm.split())
        if not expected_tokens:
            return 1.0

        intersection = actual_tokens & expected_tokens
        jaccard = len(intersection) / len(expected_tokens)
        return round(jaccard, 4)

    def _compute_efficiency(self, elapsed: float) -> float:
        """根据耗时计算效率分"""
        if elapsed <= 5:
            return 1.0
        elif elapsed <= 15:
            return 0.90
        elif elapsed <= 30:
            return 0.75
        elif elapsed <= 60:
            return 0.60
        elif elapsed <= 120:
            return 0.40
        else:
            return 0.20

    def _check_success_criteria(
        self, output: str, criteria: List[str]
    ) -> List[Dict[str, Any]]:
        """检查 success criteria（正则表达式）"""
        results = []
        for criterion in criteria:
            try:
                matched = bool(re.search(criterion, output, re.IGNORECASE | re.DOTALL))
            except re.error:
                matched = False
            results.append({
                "criterion": criterion,
                "matched": matched,
            })
        return results


def score_from_file(
    tasks_path: str,
    predictions_path: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从文件加载任务和预测，执行评分并输出 JSON。
    """
    scorer = TerminalBenchScorer(tasks_path)

    with open(predictions_path, "r", encoding="utf-8") as f:
        predictions = json.load(f)

    results = []
    for task in scorer.tasks:
        task_id = task.get("task_id", "")
        pred = next(
            (p for p in predictions if p.get("task_id") == task_id),
            {},
        )

        single = scorer.score_single(
            task_id=task_id,
            agent_output=pred.get("output", ""),
            exit_code=pred.get("exit_code", 1),
            timed_out=pred.get("timed_out", False),
            elapsed_seconds=pred.get("elapsed_seconds", 0),
            expected_output=task.get("expected_output", ""),
            expected_exit_code=task.get("expected_exit_code", 0),
            success_criteria=task.get("success_criteria"),
        )
        results.append(single)

    score = scorer.score_batch(results)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)

    return score


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python scorer.py <tasks.json> <predictions.json> [output.json]")
        sys.exit(1)

    output = sys.argv[3] if len(sys.argv) > 3 else None
    result = score_from_file(sys.argv[1], sys.argv[2], output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
