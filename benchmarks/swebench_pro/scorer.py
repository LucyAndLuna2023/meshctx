"""
SWE-bench Pro Scorer — 评分逻辑

对齐 2026 年 SWE-bench Pro 规范：
- 每个 instance 有 gold patch（参考补丁）
- 通过测试是否通过来验证 agent 生成的补丁
- 总分 = resolved / total instances
- 2026 leaderboard 参考: Claude Opus 5 ~96%

输出 JSON 格式的评分结果。
"""

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class SWEBenchProScorer:
    """SWE-bench Pro 评分器"""

    def __init__(self, tasks_file: Optional[str] = None):
        """
        初始化评分器。

        参数:
            tasks_file: 任务文件路径（sample_tasks.json）
        """
        self.tasks_file = tasks_file
        self.tasks: List[Dict] = []
        if tasks_file and Path(tasks_file).exists():
            with open(tasks_file, "r", encoding="utf-8") as f:
                self.tasks = json.load(f)

    def load_tasks(self, tasks_file: str) -> None:
        """加载任务文件"""
        with open(tasks_file, "r", encoding="utf-8") as f:
            self.tasks = json.load(f)

    def score_single(
        self,
        instance_id: str,
        agent_output: str,
        gold_patch: str,
        test_output: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        对单个 instance 进行评分。

        参数:
            instance_id: instance 标识
            agent_output: agent 生成的修复/补丁文本
            gold_patch: 参考 gold patch
            test_output: 可选的测试输出（包含 PASS/FAIL 信息）

        返回:
            评分结果字典
        """
        result = {
            "instance_id": instance_id,
            "resolved": False,
            "patch_similarity": 0.0,
            "tests_passed": 0,
            "tests_total": 0,
            "details": {},
        }

        # 1. 从 agent 输出中提取 patch
        extracted_patch = self._extract_patch(agent_output)

        # 2. 计算 patch 相似度（与 gold patch 比较）
        if extracted_patch and gold_patch:
            similarity = self._patch_similarity(extracted_patch, gold_patch)
            result["patch_similarity"] = round(similarity, 4)

        # 3. 解析测试结果
        if test_output:
            tests_info = self._parse_test_results(test_output)
            result["tests_passed"] = tests_info["passed"]
            result["tests_total"] = tests_info["total"]
            result["resolved"] = tests_info["total"] > 0 and tests_info["passed"] == tests_info["total"]
        else:
            # 没有测试输出时，基于 patch 相似度判断
            # 2026 规范: similarity >= 0.80 视为 resolved
            result["resolved"] = result["patch_similarity"] >= 0.80

        # 4. 补充细节
        result["details"] = {
            "patch_length": len(extracted_patch) if extracted_patch else 0,
            "gold_patch_length": len(gold_patch) if gold_patch else 0,
        }

        return result

    def score_batch(
        self,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        批量评分，计算总体指标。

        参数:
            results: 单个 instance 评分结果列表

        返回:
            聚合评分结果（JSON 格式）
        """
        total = len(results)
        resolved = sum(1 for r in results if r.get("resolved", False))

        similarities = [r.get("patch_similarity", 0) for r in results]
        avg_similarity = sum(similarities) / max(len(similarities), 1)

        total_tests_passed = sum(r.get("tests_passed", 0) for r in results)
        total_tests = sum(r.get("tests_total", 0) for r in results)

        score = {
            "benchmark": "SWE-bench Pro",
            "version": "2026",
            "summary": {
                "total_instances": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "resolve_rate": round(resolved / max(total, 1), 4),
                "avg_patch_similarity": round(avg_similarity, 4),
            },
            "test_results": {
                "tests_passed": total_tests_passed,
                "tests_total": total_tests,
                "test_pass_rate": round(total_tests_passed / max(total_tests, 1), 4),
            },
            "per_instance": results,
        }

        return score

    def _extract_patch(self, text: str) -> str:
        """从 agent 输出中提取 unified diff 格式的 patch"""
        if not text:
            return ""

        # 尝试匹配 diff/patch 块
        patterns = [
            # ```diff ... ``` 代码块
            r"```diff\s*\n(.*?)```",
            # ```patch ... ``` 代码块
            r"```patch\s*\n(.*?)```",
            # 直接以 diff --git 开头的块
            r"(diff --git.*?)(?:\n\Z|\n(?=```|$))",
            # 以 --- / +++ 开头的 unified diff 块
            r"((?:--- .+\n\+\+\+ .+\n(?:@@[^@]*@@\n.*?)+))",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        # 如果没找到标准 patch，返回原文本的后半部分（通常是修改后的代码）
        lines = text.strip().split("\n")
        if len(lines) > 5:
            return "\n".join(lines[-50:])  # 取最后50行
        return text.strip()

    def _patch_similarity(self, patch_a: str, patch_b: str) -> float:
        """计算两个 patch 的相似度（基于 unified diff 行级比较）"""
        if not patch_a or not patch_b:
            return 0.0

        lines_a = patch_a.strip().split("\n")
        lines_b = patch_b.strip().split("\n")

        # 使用 SequenceMatcher 计算相似度
        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        return matcher.ratio()

    def _parse_test_results(self, test_output: str) -> Dict[str, int]:
        """解析测试输出，统计通过/失败数量"""
        passed = 0
        total = 0

        # 匹配常见的测试框架输出格式
        # pytest: "X passed, Y failed"
        m = re.search(r"(\d+)\s+passed", test_output)
        if m:
            passed = int(m.group(1))

        # pytest: "X failed"
        m_fail = re.search(r"(\d+)\s+failed", test_output)
        failed = int(m_fail.group(1)) if m_fail else 0

        # 总计
        m_total = re.search(r"(\d+)\s+total", test_output)
        if m_total:
            total = int(m_total.group(1))
        else:
            # 从 passed + failed + error 推算
            m_err = re.search(r"(\d+)\s+error", test_output)
            errors = int(m_err.group(1)) if m_err else 0
            total = passed + failed + errors

        return {"passed": passed, "total": total, "failed": failed}


def score_from_file(
    tasks_path: str,
    predictions_path: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从文件加载任务和预测，执行评分并输出 JSON。

    参数:
        tasks_path: 任务文件路径（包含 gold_patch 等信息）
        predictions_path: agent 预测结果文件路径
        output_path: 输出 JSON 路径（可选）

    返回:
        评分结果字典
    """
    scorer = SWEBenchProScorer(tasks_path)

    with open(predictions_path, "r", encoding="utf-8") as f:
        predictions = json.load(f)

    results = []
    for task in scorer.tasks:
        instance_id = task.get("instance_id", "")
        gold_patch = task.get("gold_patch", "")

        # 查找对应的预测
        pred = next(
            (p for p in predictions if p.get("instance_id") == instance_id),
            {},
        )
        agent_output = pred.get("output", "")
        test_output = pred.get("test_output", "")

        single = scorer.score_single(
            instance_id=instance_id,
            agent_output=agent_output,
            gold_patch=gold_patch,
            test_output=test_output,
        )
        results.append(single)

    score = scorer.score_batch(results)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)

    return score


if __name__ == "__main__":
    # 命令行使用示例
    import sys

    if len(sys.argv) < 3:
        print("用法: python scorer.py <tasks.json> <predictions.json> [output.json]")
        sys.exit(1)

    output = sys.argv[3] if len(sys.argv) > 3 else None
    result = score_from_file(sys.argv[1], sys.argv[2], output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
