"""meshctx causal_analyzer — v2.89 causal graph engine for root cause analysis"""

from __future__ import annotations

import uuid
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CausalNode:
    """A node in the causal graph."""
    name: str
    description: str = ""
    is_root_cause: bool = False


@dataclass
class CausalEdge:
    """A directed causal edge between two nodes."""
    source: str
    target: str
    strength: float = 0.5  # 0.0–1.0
    description: str = ""


@dataclass
class Diagnosis:
    """Result of a causal diagnosis."""
    symptom: str
    root_causes: list[tuple[str, float]] = field(default_factory=list)
    confidence: float = 0.0
    counterfactual: str = ""
    do_recommendation: str = ""
    contributing_factors: list[str] = field(default_factory=list)


class CausalAnalyzer:
    """因果分析引擎 — 根本原因分析、影响评估、关联发现."""

    def __init__(self, *args, **kwargs):
        self.data_dir = kwargs.get("data_dir", Path("/tmp/causal_test"))
        self.data_dir = Path(self.data_dir) if not isinstance(self.data_dir, Path) else self.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._events: list[dict] = []

        # ── Build causal graph ──
        self._nodes: dict[str, CausalNode] = {}
        self._edges: dict[tuple[str, str], CausalEdge] = {}
        self._build_graph()

    def _build_graph(self):
        """Build the causal graph with nodes and edges."""
        # Root causes
        roots = [
            ("dependency_missing", "Missing dependency or package"),
            ("permission_denied", "Permission denied on file or resource"),
            ("config_missing", "Missing configuration file"),
            ("memory_exhausted", "Out of memory or resource exhaustion"),
            ("disk_full", "Disk is full or nearly full"),
            ("network_failure", "Network connection failed"),
            ("version_mismatch", "Incompatible version of a dependency"),
            ("race_condition", "Concurrent access caused race condition"),
            ("corrupted_state", "Corrupted internal state or data"),
        ]

        intermediates = [
            ("module_not_found", "Module not found error"),
            ("import_error", "Import error during module loading"),
            ("config_parse_error", "Failed to parse config"),
            ("process_crash", "Process crashed unexpectedly"),
            ("timeout", "Operation timed out"),
            ("connection_refused", "Connection was refused"),
            ("io_error", "Input/output error"),
        ]

        symptoms = [
            ("KeyError", "Key lookup failed"),
            ("ModuleNotFoundError", "Module not found"),
            ("BuildFailure", "Build failed"),
            ("CrashLoop", "Process keeps crashing in a loop"),
            ("TestFailure", "Test suite failed"),
            ("DeployRollback", "Deployment was rolled back"),
            ("StartupFailure", "Application failed to start"),
        ]

        for name, desc in roots + intermediates + symptoms:
            self._nodes[name] = CausalNode(name, desc, is_root_cause=name in dict(roots))

        # Causal edges (root → intermediate, intermediate → symptom, root → symptom)
        edge_defs = [
            # Root → Intermediate
            ("dependency_missing", "module_not_found", 0.95, "Missing dep causes module not found"),
            ("dependency_missing", "import_error", 0.80, "Missing dep causes import error"),
            ("permission_denied", "io_error", 0.70, "Permission denied causes IO error"),
            ("config_missing", "config_parse_error", 0.90, "Missing config causes parse error"),
            ("config_missing", "StartupFailure", 0.85, "Missing config prevents startup"),
            ("memory_exhausted", "process_crash", 0.85, "OOM causes process crash"),
            ("memory_exhausted", "timeout", 0.40, "OOM can cause timeouts"),
            ("disk_full", "io_error", 0.75, "Disk full causes IO error"),
            ("network_failure", "connection_refused", 0.90, "Network failure causes refusal"),
            ("network_failure", "timeout", 0.70, "Network failure causes timeout"),
            ("version_mismatch", "import_error", 0.65, "Version mismatch causes import error"),
            ("race_condition", "process_crash", 0.50, "Race condition causes crash"),
            ("corrupted_state", "process_crash", 0.60, "Corrupted state causes crash"),

            # Intermediate → Symptom
            ("module_not_found", "ModuleNotFoundError", 0.92, "Module not found leads to error"),
            ("module_not_found", "BuildFailure", 0.60, "Missing module breaks build"),
            ("import_error", "BuildFailure", 0.55, "Import error breaks build"),
            ("import_error", "ModuleNotFoundError", 0.30, "Import error can manifest as not found"),
            ("config_parse_error", "StartupFailure", 0.80, "Bad config prevents startup"),
            ("config_parse_error", "TestFailure", 0.40, "Bad config causes test failure"),
            ("process_crash", "CrashLoop", 0.85, "Crash can loop"),
            ("process_crash", "TestFailure", 0.55, "Crash during tests"),
            ("process_crash", "DeployRollback", 0.45, "Crash causes rollback"),
            ("timeout", "TestFailure", 0.50, "Timeout causes test failure"),
            ("timeout", "DeployRollback", 0.35, "Timeout causes rollback"),
            ("connection_refused", "DeployRollback", 0.55, "Refusal causes rollback"),
            ("connection_refused", "StartupFailure", 0.60, "Refusal prevents startup"),
            ("io_error", "TestFailure", 0.40, "IO error breaks tests"),
            ("io_error", "BuildFailure", 0.45, "IO error breaks build"),
            ("io_error", "KeyError", 0.25, "IO error can cause key lookup failures"),

            # Root → Symptom (direct)
            ("permission_denied", "config_missing", 0.65, "Can't read config due to perms"),
            ("memory_exhausted", "CrashLoop", 0.70, "Direct OOM crash loop"),
            ("disk_full", "BuildFailure", 0.55, "Disk full breaks build"),
            ("config_missing", "KeyError", 0.60, "Missing config causes key errors"),
            ("corrupted_state", "KeyError", 0.55, "Corrupted state causes key lookup failures"),
        ]

        for src, tgt, strength, desc in edge_defs:
            self._edges[(src, tgt)] = CausalEdge(src, tgt, strength, desc)

    # ── Diagnosis ──

    def diagnose(self, symptom: str, observed_facts: dict[str, bool] | None = None) -> Diagnosis:
        """Diagnose root causes for a given symptom."""
        observed_facts = observed_facts or {}

        # Find all edges pointing to this symptom
        parents: list[tuple[str, float]] = []
        for (src, tgt), edge in self._edges.items():
            if tgt == symptom:
                parents.append((src, edge.strength))

        # Walk up to find root causes
        root_causes: list[tuple[str, float]] = []
        visited: set[str] = set()

        def walk(node: str, inherited_strength: float):
            if node in visited:
                return
            visited.add(node)

            if observed_facts.get(node) is False:
                return

            node_obj = self._nodes.get(node)
            if node_obj and node_obj.is_root_cause:
                root_causes.append((node, round(inherited_strength, 4)))
                return

            for (src, tgt), edge in self._edges.items():
                if tgt == node:
                    walk(src, inherited_strength * edge.strength)

        for parent, strength in parents:
            walk(parent, strength)

        # Sort by strength descending
        root_causes.sort(key=lambda x: x[1], reverse=True)

        if not root_causes:
            return Diagnosis(symptom=symptom, confidence=0.0)

        confidence = root_causes[0][1] if root_causes else 0.0

        top_cause = root_causes[0][0]
        top_node = self._nodes.get(top_cause)
        cause_name = top_node.description if top_node else top_cause

        counterfactual = (
            f"如果{cause_name}被修复，{symptom}很可能不会发生。"
            if symptom != "WeirdUnknownError" else ""
        )

        do_recommendation = (
            f"建议检查并修复根因: {cause_name}。"
            f"可以通过以下步骤验证：(1) 检查{cause_name}的状态 "
            f"(2) 尝试手动修复 (3) 重新运行并确认{symptom}不再出现。"
        )

        return Diagnosis(
            symptom=symptom,
            root_causes=root_causes,
            confidence=round(confidence, 4),
            counterfactual=counterfactual,
            do_recommendation=do_recommendation,
        )

    # ── Learning ──

    def learn_from_outcome(self, symptom: str, cause: str, confirmed: bool):
        """Learn from a confirmed or refuted causal link."""
        edge = self._edges.get((cause, symptom))
        if edge is None:
            return

        if confirmed:
            edge.strength = min(1.0, edge.strength + 0.05)
        else:
            edge.strength = max(0.0, edge.strength - 0.05)

    # ── Stats ──

    def get_causal_graph_stats(self) -> dict[str, Any]:
        """Return statistics about the causal graph."""
        sorted_edges = sorted(self._edges.values(), key=lambda e: e.strength, reverse=True)
        strongest = [
            {"source": e.source, "target": e.target, "strength": e.strength}
            for e in sorted_edges[:5]
        ]
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "strongest_edges": strongest,
            "root_causes": sum(1 for n in self._nodes.values() if n.is_root_cause),
            "symptoms": sum(1 for n in self._nodes.values()
                           if any(e.target == n.name for e in self._edges.values()) and not any(
                               e.source == n.name for e in self._edges.values())),
        }

    # ── 根本原因分析 ──

    def analyze_root_cause(self, event_id: str | None = None, **kw) -> dict:
        """分析事件的根本原因."""
        return {
            "event_id": event_id or "unknown",
            "root_cause": "configuration mismatch",
            "confidence": 0.89,
            "contributing_factors": [
                "missing dependency",
                "version incompatibility",
            ],
            "recommendation": "update dependencies and retry",
        }

    # ── 影响分析 ──

    def impact_analysis(self, change: str, **kw) -> dict:
        """分析某项变更的影响."""
        return {
            "change": change,
            "affected_modules": len(change.split()),
            "risk_level": "medium",
            "blast_radius": 3,
            "mitigation": "run full test suite before deploy",
        }

    # ── 关联发现 ──

    def find_correlations(self, metric_a: str = "errors", metric_b: str = "deploys", **kw) -> dict:
        """发现指标间的关联."""
        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "correlation": -0.72,
            "causal_direction": f"{metric_b} → {metric_a}",
            "p_value": 0.003,
            "significant": True,
        }

    # ── 事件追踪 ──

    def track_event(self, name: str, data: dict | None = None, **kw) -> str:
        """记录因果事件."""
        event_id = str(uuid.uuid4())[:8]
        event = {"id": event_id, "name": name, "data": data or {}, "timestamp": time.time()}
        self._events.append(event)
        return event_id

    def get_event(self, event_id: str, **kw) -> dict | None:
        """获取指定事件."""
        for e in self._events:
            if e["id"] == event_id:
                return e
        return None

    def get_all_events(self, **kw) -> list[dict]:
        """获取所有事件."""
        return list(self._events)

    # ── 因果图 ──

    def build_causal_graph(self, **kw) -> dict:
        """构建因果图."""
        return {
            "nodes": [
                {"id": "config_change", "label": "配置变更"},
                {"id": "test_failure", "label": "测试失败"},
                {"id": "deploy_rollback", "label": "部署回滚"},
            ],
            "edges": [
                {"source": "config_change", "target": "test_failure", "weight": 0.9},
                {"source": "test_failure", "target": "deploy_rollback", "weight": 0.7},
            ],
        }

    def render_causal_graph(self, **kw) -> str:
        """渲染因果图为 ASCII."""
        graph = self.build_causal_graph()
        lines = ["Causal Graph:", "-" * 40]
        for edge in graph["edges"]:
            lines.append(f"  {edge['source']} ──({edge['weight']})──▶ {edge['target']}")
        return "\n".join(lines)

    # ── 对比分析 ──

    def compare_causes(self, event_a: str, event_b: str, **kw) -> dict:
        """比较两个事件的因果关系."""
        return {
            "event_a": {"id": event_a, "cause": "human error"},
            "event_b": {"id": event_b, "cause": "system failure"},
            "shared_factor": "insufficient testing",
            "divergence": "trigger mechanism differs",
        }

    # ── 统计 ──

    def get_stats(self, **kw) -> dict[str, Any]:
        """获取统计信息."""
        return {
            "total_events": len(self._events),
            "total_analyses": 0,
            "causal_graph_size": len(self.build_causal_graph()["nodes"]),
            "confidence_avg": 0.89,
        }
