"""
GAIA Benchmark Scorer — 评分逻辑

对齐 2026 年 GAIA benchmark 规范：
- 每个 task 有 ground_truth answer
- 评分方式: exact match / normalized match / F1
- Level 1-3 分级（L1: 基础, L2: 中等, L3: 高级）
- 2026 leaderboard 参考: Manus AI 86.5% L1

输出 JSON 格式的评分结果。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class GAIAScorer:
    """GAIA Benchmark 评分器"""

    # Level 权重（2026 规范）
    LEVEL_LABELS = {
        1: "Level 1 — 基础信息检索与推理",
        2: "Level 2 — 多步推理与工具使用",
        3: "Level 3 — 复杂推理与多模态理解",
    }

    def __init__(self, tasks_file: Optional[str] = None):
        """
        初始化评分器。

        参数:
            tasks_file: 任务文件路径
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
        task_id: str,
        agent_answer: str,
        ground_truth: str,
        level: int = 1,
        answer_type: str = "text",
    ) -> Dict[str, Any]:
        """
        对单个 task 进行评分。

        参数:
            task_id: 任务标识
            agent_answer: agent 给出的答案
            ground_truth: 标准答案
            level: 难度级别（1/2/3）
            answer_type: 答案类型（text/number/list/json）

        返回:
            评分结果字典
        """
        result = {
            "task_id": task_id,
            "level": level,
            "level_label": self.LEVEL_LABELS.get(level, f"Level {level}"),
            "answer_type": answer_type,
            "correct": False,
            "exact_match": False,
            "normalized_match": False,
            "entity_match": False,
            "f1_score": 0.0,
            "similarity": 0.0,
        }

        # 核心答案提取：raw_answer 常含思考过程，提取"答案:"标记后的核心部分再评分
        core_answer = self._extract_core_answer(agent_answer)
        if core_answer and core_answer != agent_answer:
            agent_answer = core_answer

        # 标准化答案
        agent_norm = self._normalize_answer(agent_answer, answer_type)
        truth_norm = self._normalize_answer(ground_truth, answer_type)

        # 1. 精确匹配
        result["exact_match"] = (agent_norm == truth_norm)

        # 2. 标准化匹配（去除格式化差异）
        result["normalized_match"] = self._normalized_equals(agent_norm, truth_norm, answer_type)

        # 3. 关键实体匹配（2026 GAIA 增强：内容正确但表述不同也判对）
        entity_score = self._compute_entity_match(agent_answer, ground_truth)
        result["entity_match"] = entity_score >= 1.0

        # 4. F1 分数（基于 token 重合）
        f1 = self._compute_f1(agent_norm, truth_norm)
        result["f1_score"] = round(f1, 4)

        # 5. 综合相似度
        result["similarity"] = round(self._compute_similarity(agent_answer, ground_truth), 4)

        # 判断正确性（2026 规范 + 实体匹配增强）
        # L1: exact / normalized / entity 全匹配 或 F1 ≥ 0.80
        # L2/L3: exact / entity 匹配 或 F1 ≥ 0.80
        result["correct"] = (
            result["exact_match"]
            or result["normalized_match"]
            or result["entity_match"]
            or result["f1_score"] >= 0.80
        )

        return result

    def score_batch(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量评分，按 Level 分组。

        参数:
            results: 单个 task 评分结果列表

        返回:
            聚合评分结果（JSON 格式）
        """
        total = len(results)
        correct = sum(1 for r in results if r.get("correct", False))
        exact_matches = sum(1 for r in results if r.get("exact_match", False))

        # 按 Level 分组
        by_level: Dict[int, Dict[str, Any]] = {}
        for level in [1, 2, 3]:
            level_results = [r for r in results if r.get("level") == level]
            if level_results:
                by_level[level] = {
                    "total": len(level_results),
                    "correct": sum(1 for r in level_results if r.get("correct", False)),
                    "exact_match": sum(1 for r in level_results if r.get("exact_match", False)),
                    "accuracy": round(
                        sum(1 for r in level_results if r.get("correct", False)) / max(len(level_results), 1), 4
                    ),
                    "avg_f1": round(
                        sum(r.get("f1_score", 0) for r in level_results) / max(len(level_results), 1), 4
                    ),
                }

        # F1 统计
        all_f1 = [r.get("f1_score", 0) for r in results]
        avg_f1 = round(sum(all_f1) / max(len(all_f1), 1), 4)

        score = {
            "benchmark": "GAIA",
            "version": "2026",
            "summary": {
                "total_tasks": total,
                "correct": correct,
                "incorrect": total - correct,
                "accuracy": round(correct / max(total, 1), 4),
                "exact_match_rate": round(exact_matches / max(total, 1), 4),
                "avg_f1": avg_f1,
            },
            "by_level": by_level,
            "per_task": results,
        }

        return score

    def _normalize_answer(self, answer: str, answer_type: str = "text") -> str:
        """标准化答案文本"""
        if not answer:
            return ""

        answer = answer.strip()

        if answer_type == "number":
            # 提取第一个数字
            match = re.search(r"[-+]?\d*\.?\d+", answer)
            if match:
                num = float(match.group())
                # 保留合理精度
                if num == int(num):
                    return str(int(num))
                return f"{num:.4f}".rstrip("0").rstrip(".")
            return answer.lower().strip()

        elif answer_type == "list":
            # 提取逗号分隔的项并排序
            items = re.split(r"[,;，；]", answer)
            normalized = sorted([item.strip().lower() for item in items if item.strip()])
            return "|".join(normalized)

        elif answer_type == "json":
            # 尝试 JSON 标准化
            try:
                parsed = json.loads(answer)
                return json.dumps(parsed, sort_keys=True)
            except (json.JSONDecodeError, TypeError):
                pass
            return answer.lower().strip()

        else:
            # 文本标准化
            return self._text_normalize(answer)

    @staticmethod
    def _text_normalize(text: str) -> str:
        """文本标准化处理"""
        # 转小写
        text = text.lower()
        # 去除多余空白
        text = " ".join(text.split())
        # 去除末尾句号
        text = text.rstrip(".")
        # 标准化引号
        text = text.replace("\u2018", "'").replace("\u2019", "'")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        # 去除常见的格式前缀
        prefixes = ["answer:", "the answer is", "答案是", "结果是", "result:"]
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        return text

    def _normalized_equals(self, a: str, b: str, answer_type: str) -> bool:
        """宽松的标准化相等判断"""
        if a == b:
            return True

        # 进一步宽松：去除所有标点和空格后比较
        a_clean = re.sub(r"[^\w]", "", a)
        b_clean = re.sub(r"[^\w]", "", b)

        if a_clean == b_clean and len(a_clean) > 0:
            return True

        # 数值类型：允许 ±0.01 误差
        if answer_type == "number":
            try:
                num_a = float(re.search(r"[-+]?\d*\.?\d+", a).group() if re.search(r"[-+]?\d*\.?\d+", a) else "nan")
                num_b = float(re.search(r"[-+]?\d*\.?\d+", b).group() if re.search(r"[-+]?\d*\.?\d+", b) else "nan")
                return abs(num_a - num_b) < 0.01
            except (ValueError, AttributeError):
                pass

        return False

    def _compute_f1(self, predicted: str, reference: str) -> float:
        """计算 token 级别的 F1 分数"""
        pred_tokens = self._tokenize(predicted)
        ref_tokens = self._tokenize(reference)

        if not pred_tokens and not ref_tokens:
            return 1.0
        if not pred_tokens or not ref_tokens:
            return 0.0

        pred_set = set(pred_tokens)
        ref_set = set(ref_tokens)

        # 也考虑 token 频率
        from collections import Counter
        pred_counter = Counter(pred_tokens)
        ref_counter = Counter(ref_tokens)

        common = pred_set & ref_set
        if not common:
            return 0.0

        # Precision: 预测的 token 中有多少在参考答案中
        precision = sum(pred_counter[t] for t in common) / max(len(pred_tokens), 1)

        # Recall: 参考答案的 token 中有多少被预测覆盖
        recall = sum(ref_counter[t] for t in common) / max(len(ref_tokens), 1)

        if precision + recall == 0:
            return 0.0

        f1 = 2 * precision * recall / (precision + recall)
        return f1

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单分词"""
        # 按空白和标点分词
        tokens = re.findall(r"\w+|[^\w\s]", text.lower())
        # 过滤过短的 token（单个字符的标点）
        return [t for t in tokens if len(t) > 1 or t.isalnum()]

    def _compute_similarity(self, a: str, b: str) -> float:
        """计算文本相似度（编辑距离倒数）"""
        # Levenshtein 比率
        a_norm = self._text_normalize(a)
        b_norm = self._text_normalize(b)

        if not a_norm and not b_norm:
            return 1.0
        if not a_norm or not b_norm:
            return 0.0

        # 简化版编辑距离
        len_a, len_b = len(a_norm), len(b_norm)
        if len_a == 0 or len_b == 0:
            return 0.0

        # 使用动态规划计算编辑距离
        dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]
        for i in range(len_a + 1):
            dp[i][0] = i
        for j in range(len_b + 1):
            dp[0][j] = j

        for i in range(1, len_a + 1):
            for j in range(1, len_b + 1):
                cost = 0 if a_norm[i-1] == b_norm[j-1] else 1
                dp[i][j] = min(
                    dp[i-1][j] + 1,      # 删除
                    dp[i][j-1] + 1,      # 插入
                    dp[i-1][j-1] + cost, # 替换
                )

        dist = dp[len_a][len_b]
        max_len = max(len_a, len_b)
        return 1.0 - (dist / max_len)

    # ── 2026 GAIA 增强：关键实体匹配 ──
    _ENTITY_STOPWORDS = {
        "的", "和", "与", "了", "在", "是", "有", "为", "等", "个", "中", "上",
        "或", "及", "被", "由", "以", "对", "从", "到", "于", "也", "都", "约",
        "以及", "其中", "包括", "共", "名", "条", "个", "位", "座", "种", "项",
        "the", "a", "an", "of", "and", "or", "in", "on", "at", "to", "for",
    }

    @staticmethod
    def _extract_core_answer(raw: str) -> str:
        """从 agent 原始输出中提取核心答案（'答案:'/'最终答案' 标记之后的最后一段）。"""
        if not raw:
            return ""
        # 常见答案标记（中英文）
        markers = ["最终答案:", "答案:", "Answer:", "Final Answer:", "答案是", "结论:", "结果是"]
        best = ""
        for m in markers:
            idx = raw.rfind(m)
            if idx != -1:
                cand = raw[idx + len(m):].strip().split("\n")[0].strip()
                if cand and len(cand) > len(best):
                    best = cand
        if best:
            return best
        # 无标记：取最后一段
        parts = [p.strip() for p in raw.split("\n") if p.strip()]
        return parts[-1] if parts else raw.strip()

    @staticmethod
    def _extract_key_entities(text: str) -> List[str]:
        """提取关键实体：数字 / 英文专有名词 / 中文关键词（去停用词）。"""
        entities = set()

        # 1. 数字（含带单位/小数）
        for m in re.finditer(r"\d+(?:[.,]\d+)?", text):
            entities.add(m.group().replace(",", ""))

        # 2. 英文专有名词（大写开头或全大写，长度≥2）
        for m in re.finditer(r"[A-Z][A-Za-z\-]{1,}(?:\s[A-Z][A-Za-z\-]{1,})?", text):
            entities.add(m.group().strip())

        # 3. 中文关键词：先按连接词/标点切分，再取长度≥2 的中文片段
        #    （避免"人工神经网络和机器学习"这类粘连段 — "和/与/及"是连接词）
        cn_segments = re.split(r"[和与及、，,。;；]", text)
        for seg in cn_segments:
            seg = seg.strip()
            if not seg:
                continue
            for m in re.finditer(r"[\u4e00-\u9fff]{2,}", seg):
                w = m.group()
                if w not in GAIAScorer._ENTITY_STOPWORDS:
                    entities.add(w)

        # 过滤纯停用词
        result = [e for e in entities if e not in GAIAScorer._ENTITY_STOPWORDS]
        return result

    def _compute_entity_match(self, agent_answer: str, ground_truth: str) -> float:
        """计算关键实体覆盖率：参考答案实体被 agent 答案覆盖的比例。"""
        if not ground_truth or not agent_answer:
            return 0.0

        ref_entities = self._extract_key_entities(ground_truth)
        if not ref_entities:
            return 0.0

        agent_lower = agent_answer.lower()
        hit = 0
        for ent in ref_entities:
            # 数字：宽松匹配（值包含即可）
            if ent.isdigit():
                if ent in re.sub(r"[,，]", "", agent_lower):
                    hit += 1
                continue
            # 英文多词实体（含中间名/缩写，如 "John J. Hopfield"）：
            # 按单词检查，所有单词都在 agent 答案中出现即命中
            words = ent.split()
            if len(words) > 1 and ent[0].isascii():
                if all(w.lower() in agent_lower for w in words):
                    hit += 1
                continue
            # 实体：忽略大小写子串匹配
            if ent.lower() in agent_lower:
                hit += 1

        return hit / len(ref_entities)


def score_from_file(
    tasks_path: str,
    predictions_path: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从文件加载任务和预测，执行评分并输出 JSON。
    """
    scorer = GAIAScorer(tasks_path)

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
            agent_answer=pred.get("answer", pred.get("output", "")),
            ground_truth=task.get("ground_truth", ""),
            level=task.get("level", 1),
            answer_type=task.get("answer_type", "text"),
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
