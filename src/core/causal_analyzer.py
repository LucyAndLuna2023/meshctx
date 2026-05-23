"""Causal Root Cause Analyzer — v2.77
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pearl因果推断理论落地: 超越相关,找到真正的根因

核心(Pearl, 2009):
- 相关 ≠ 因果: KeyError常与"配置文件缺失"同时出现,但根因是"权限不足"
- do-calculus: do(X=x) 干预变量,观察结果变化
- 反事实推理: "如果不做X,会不会出错?"
- 因果图: 变量间的有向因果边

解决: "同一个bug修了4次" → 不再治标,找到根因
"""
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CausalNode:
    """因果图中的节点"""
    name: str
    description: str = ""
    is_root_cause: bool = False
    intervention_count: int = 0  # do()操作次数
    observed_failures: int = 0


@dataclass
class CausalEdge:
    """因果边: from → to 表示 from 导致 to"""
    from_node: str
    to_node: str
    strength: float = 0.0     # 因果强度 [0,1]
    confidence: float = 0.0    # 置信度 [0,1]
    evidence_count: int = 0    # 支持证据数


@dataclass
class CausalDiagnosis:
    """因果诊断结果"""
    symptom: str                # 观察到的症状
    root_causes: List[Tuple[str, float]]  # (根因, 因果分数)
    causal_path: List[str]      # 因果路径
    counterfactual: str         # 反事实: "如果不做X..."
    do_recommendation: str      # do()干预建议
    confidence: float


class CausalAnalyzer:
    """因果推断根因分析器"""

    def __init__(self):
        # 因果图: 节点和边
        self._nodes: Dict[str, CausalNode] = {}
        self._edges: Dict[Tuple[str, str], CausalEdge] = {}
        self._diagnosis_history: List[CausalDiagnosis] = []

        # 初始化已知因果关系
        self._init_causal_graph()

    def _init_causal_graph(self):
        """初始化软件故障因果关系图"""
        # 节点
        node_defs = [
            ("permission_denied", "权限不足", True),
            ("disk_full", "磁盘空间不足", True),
            ("memory_exhausted", "内存耗尽", True),
            ("network_timeout", "网络超时", True),
            ("config_missing", "配置文件缺失", False),
            ("config_syntax_error", "配置语法错误", True),
            ("dependency_missing", "依赖包缺失", True),
            ("version_mismatch", "版本不兼容", True),
            ("race_condition", "竞态条件", True),
            ("module_not_found", "模块未找到", False),
            ("import_error", "导入错误", False),
            ("key_error", "键缺失", False),
            ("attribute_error", "属性错误", False),
            ("type_error", "类型错误", False),
            ("api_rate_limited", "API频率限制", True),
            ("token_exhausted", "Token耗尽", True),
            ("oom_killed", "OOM被杀", False),
            ("crash_loop", "崩溃循环", False),
            ("build_failure", "构建失败", False),
            ("test_failure", "测试失败", False),
        ]
        for name, desc, is_root in node_defs:
            self._nodes[name] = CausalNode(
                name=name, description=desc,
                is_root_cause=is_root
            )

        # 因果边: from → to (from导致to)
        edge_defs = [
            # 权限问题链
            ("permission_denied", "config_missing", 0.9),
            ("permission_denied", "module_not_found", 0.3),
            ("permission_denied", "import_error", 0.5),

            # 磁盘满链
            ("disk_full", "oom_killed", 0.8),
            ("disk_full", "build_failure", 0.7),
            ("disk_full", "config_missing", 0.4),

            # 内存链
            ("memory_exhausted", "oom_killed", 1.0),
            ("memory_exhausted", "crash_loop", 0.9),
            ("memory_exhausted", "test_failure", 0.4),

            # 依赖链
            ("dependency_missing", "module_not_found", 1.0),
            ("dependency_missing", "import_error", 0.95),
            ("dependency_missing", "build_failure", 0.7),

            # 版本链
            ("version_mismatch", "import_error", 0.6),
            ("version_mismatch", "test_failure", 0.5),
            ("version_mismatch", "build_failure", 0.4),

            # 中间节点→症状
            ("config_missing", "key_error", 0.8),
            ("config_missing", "attribute_error", 0.5),
            ("module_not_found", "import_error", 0.9),
            ("import_error", "crash_loop", 0.7),
            ("key_error", "test_failure", 0.6),
            ("oom_killed", "crash_loop", 1.0),
            ("race_condition", "test_failure", 0.5),

            # API链
            ("api_rate_limited", "network_timeout", 0.3),
            ("token_exhausted", "api_rate_limited", 0.2),
        ]
        for from_n, to_n, strength in edge_defs:
            self._edges[(from_n, to_n)] = CausalEdge(
                from_node=from_n, to_node=to_n,
                strength=strength, confidence=0.7 + 0.3 * strength,
                evidence_count=1,
            )

    # ── Causal Diagnosis ───────────────────────────────

    def diagnose(self, symptom: str,
                observed_facts: Optional[Dict[str, bool]] = None) -> CausalDiagnosis:
        """因果诊断: 给症状,找根因"""
        observed_facts = observed_facts or {}
        symptom_map = {
            "KeyError": "key_error",
            "AttributeError": "attribute_error",
            "TypeError": "type_error",
            "ModuleNotFoundError": "module_not_found",
            "ImportError": "import_error",
            "OOMKilled": "oom_killed",
            "CrashLoop": "crash_loop",
            "BuildFailure": "build_failure",
            "TestFailure": "test_failure",
        }
        node_name = symptom_map.get(symptom, symptom.lower().replace(" ", "_"))

        if node_name not in self._nodes:
            return CausalDiagnosis(
                symptom=symptom,
                root_causes=[],
                causal_path=[],
                counterfactual="未知症状,无法诊断",
                do_recommendation="请提供更多信息",
                confidence=0.0,
            )

        # 1. 反向追踪: 从症状回溯到根因 (BFS)
        root_causes, paths = self._backtrack(node_name, observed_facts)

        # 2. 计算每个根因的因果分数
        scored_causes = []
        for root, path in zip(root_causes, paths):
            score = self._compute_causal_score(path, observed_facts)
            scored_causes.append((root, score))

        scored_causes.sort(key=lambda x: x[1], reverse=True)

        # 3. 生成反事实
        counterfactual = self._generate_counterfactual(
            scored_causes[0][0] if scored_causes else "",
            symptom
        )

        # 4. do()干预建议
        do_rec = self._generate_do_recommendation(
            scored_causes[0][0] if scored_causes else "",
            symptom
        )

        diagnosis = CausalDiagnosis(
            symptom=symptom,
            root_causes=scored_causes[:3],
            causal_path=self._format_path(paths[0]) if paths else "",
            counterfactual=counterfactual,
            do_recommendation=do_rec,
            confidence=scored_causes[0][1] if scored_causes else 0.0,
        )

        self._diagnosis_history.append(diagnosis)
        return diagnosis

    def _backtrack(self, node_name: str,
                  observed: Dict[str, bool]) -> Tuple[List[str], List[List[str]]]:
        """从症状反向追踪到根因 (BFS)"""
        # 收集指向此节点的所有入边
        parents = []
        for (frm, to), edge in self._edges.items():
            if to == node_name:
                parents.append((frm, edge.strength))

        if not parents:
            # 叶子节点 → 自己就是根因
            return [node_name], [[node_name]]

        root_causes = []
        paths = []

        for parent, strength in parents:
            # 如果观察到父节点不存在,跳过此路径
            if parent in observed and not observed[parent]:
                continue

            sub_roots, sub_paths = self._backtrack(parent, observed)
            for root, path in zip(sub_roots, sub_paths):
                root_causes.append(root)
                paths.append([node_name] + path)

        # 去重
        unique = []
        seen = set()
        for rc, p in zip(root_causes, paths):
            key = tuple(p)
            if key not in seen:
                seen.add(key)
                unique.append((rc, p))

        if not unique:
            return [node_name], [[node_name]]

        return [u[0] for u in unique], [u[1] for u in unique]

    def _compute_causal_score(self, path: List[str],
                             observed: Dict[str, bool]) -> float:
        """计算因果路径的得分"""
        score = 1.0
        for i in range(len(path) - 1):
            edge = self._edges.get((path[i+1], path[i]))
            if edge:
                score *= edge.strength

        # 观察事实加权: 符合观察→加分,违背→减分
        for node in path:
            if node in observed:
                if observed[node]:
                    score *= 1.2
                else:
                    score *= 0.3

        return round(min(1.0, score), 3)

    def _generate_counterfactual(self, root_cause: str,
                                symptom: str) -> str:
        """生成反事实推理"""
        counterfactuals = {
            "permission_denied": f"如果授予足够权限,{symptom}就不会发生",
            "disk_full": f"如果磁盘有足够空间,{symptom}就不会发生",
            "memory_exhausted": f"如果分配了足够内存,{symptom}就不会发生",
            "dependency_missing": f"如果安装了缺失的依赖,{symptom}就不会发生",
            "version_mismatch": f"如果版本兼容,{symptom}就不会发生",
            "config_syntax_error": f"如果配置文件语法正确,{symptom}就不会发生",
            "race_condition": f"如果没有竞态条件,{symptom}就不会发生",
        }
        return counterfactuals.get(
            root_cause,
            f"如果{root_cause}被修复,{symptom}就不会发生"
        )

    def _generate_do_recommendation(self, root_cause: str,
                                   symptom: str) -> str:
        """生成do()干预建议"""
        recommendations = {
            "permission_denied": "do(权限)=sudo chmod 755 /path; chown user:group /path",
            "disk_full": "do(磁盘)=清理日志和缓存; 扩展磁盘空间",
            "memory_exhausted": "do(内存)=增加swap; 限制并发任务; 升级内存",
            "dependency_missing": "do(依赖)=pip install -r requirements.txt",
            "version_mismatch": "do(版本)=更新到兼容版本; 检查CHANGELOG",
            "config_syntax_error": "do(配置)=检查YAML语法; 验证必需字段",
            "race_condition": "do(并发)=添加锁机制; 使用async/await正确",
        }
        return recommendations.get(
            root_cause,
            f"do({root_cause})=针对性修复根因"
        )

    def _format_path(self, path: List[str]) -> str:
        """格式化因果路径"""
        names = []
        for p in path:
            node = self._nodes.get(p)
            names.append(node.description if node else p)
        return " → ".join(names)

    # ── Learning ───────────────────────────────────────

    def learn_from_outcome(self, symptom: str, root_cause: str,
                          confirmed: bool = True):
        """从实际结果中学习,更新因果图"""
        edge = self._edges.get((root_cause, symptom))
        if edge:
            if confirmed:
                edge.strength = min(1.0, edge.strength + 0.1)
                edge.confidence = min(1.0, edge.confidence + 0.05)
                edge.evidence_count += 1
            else:
                edge.strength = max(0.0, edge.strength - 0.1)
                edge.confidence = max(0.0, edge.confidence - 0.1)

        # 更新节点观察次数
        for name in [symptom, root_cause]:
            node = self._nodes.get(name)
            if node:
                if confirmed:
                    node.intervention_count += 1
                node.observed_failures += 1

    # ── Stats ──────────────────────────────────────────

    def get_causal_graph_stats(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "root_causes": sum(1 for n in self._nodes.values() if n.is_root_cause),
            "total_diagnoses": len(self._diagnosis_history),
            "top_root_causes": sorted(
                [(n.name, n.description, n.intervention_count)
                 for n in self._nodes.values() if n.is_root_cause],
                key=lambda x: x[2], reverse=True
            )[:5],
            "strongest_edges": sorted(
                [(f"{e.from_node}→{e.to_node}", e.strength, e.confidence)
                 for e in self._edges.values()],
                key=lambda x: x[1] + x[2], reverse=True
            )[:5],
        }

    def get_stats(self) -> Dict:
        return self.get_causal_graph_stats()


# 单例
_analyzer: Optional[CausalAnalyzer] = None


def get_causal_analyzer() -> CausalAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = CausalAnalyzer()
    return _analyzer
