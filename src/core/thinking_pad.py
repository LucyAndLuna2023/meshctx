"""
meshctx thinking_pad — Agent thought chain visualization and replay engine.

Claude Code parity feature: structured agent thinking log with visual replay.
Captures the agent's reasoning process at each step, enabling:
  - Decision audit trail (what was considered, why, and outcome)
  - Chain-of-thought visualization (tree/graph of reasoning paths)
  - Session replay for debugging and improvement
  - Thought quality metrics (depth, branching, confidence)

Zero pip dependencies — pure Python stdlib.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════════

class ThoughtCategory(Enum):
    """Category of a thought entry (Claude Code parity)."""
    OBSERVATION = "observation"       # Reading/interpreting output
    REASONING = "reasoning"           # Logical deduction
    DECISION = "decision"             # Final choice among options
    EXPLORATION = "exploration"       # Exploring an alternative path
    CORRECTION = "correction"         # Self-correcting a mistake
    PLAN = "plan"                     # High-level strategy
    EXECUTION = "execution"           # Performing an action
    EVALUATION = "evaluation"         # Judging quality of result
    BRANCH = "branch"                 # Starting a parallel thought branch
    MERGE = "merge"                   # Merging parallel branches


class ThoughtStatus(Enum):
    """Status of the thought."""
    DRAFT = "draft"              # Still being formulated
    COMPLETE = "complete"        # Fully reasoned
    ABANDONED = "abandoned"      # Dead end — discarded path
    PENDING = "pending"          # Awaiting external input


class Confidence(Enum):
    """Confidence level of a decision/thought."""
    HIGH = "high"         # >80% sure
    MEDIUM = "medium"     # 50-80%
    LOW = "low"           # 20-50%
    SPECULATIVE = "speculative"  # <20% — just an idea


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ThoughtNode:
    """A single thought in the agent's reasoning chain.

    Attributes:
        id: Unique identifier for this thought.
        parent_id: Parent thought (None for root).
        category: Type of thought.
        content: The actual thought text.
        confidence: How sure the agent is about this thought.
        status: Current status of this thought.
        timestamp: When this thought was recorded.
        metadata: Arbitrary key-value data (file refs, tool results, etc.).
        children: List of child thought IDs.
        depth: Depth in the thought tree (root=0).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_id: Optional[str] = None
    category: ThoughtCategory = ThoughtCategory.OBSERVATION
    content: str = ""
    confidence: Confidence = Confidence.MEDIUM
    status: ThoughtStatus = ThoughtStatus.DRAFT
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)
    depth: int = 0

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "category": self.category.value,
            "content": self.content[:500],
            "confidence": self.confidence.value,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "depth": self.depth,
            "children": self.children,
            "metadata_keys": list(self.metadata.keys()),
        }


@dataclass
class DecisionPoint:
    """A point where the agent chose among multiple options.

    Captures the alternatives considered and why the chosen one won.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    thought_id: str = ""
    question: str = ""               # The question being decided
    options: List[str] = field(default_factory=list)  # Alternatives considered
    chosen: str = ""                 # The selected option
    reasoning: str = ""              # Why this option was chosen
    rejected_reasons: Dict[str, str] = field(default_factory=dict)  # Why others were rejected
    timestamp: float = field(default_factory=time.time)

    @property
    def option_count(self) -> int:
        return len(self.options)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "thought_id": self.thought_id,
            "question": self.question,
            "options": self.options,
            "chosen": self.chosen,
            "reasoning": self.reasoning[:300],
            "rejected_count": len(self.rejected_reasons),
        }


@dataclass
class ThinkingSession:
    """A complete thinking session with thought tree and decision log.

    Represents one agent invocation from start to finish.
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    node_count: int = 0
    decision_count: int = 0
    max_depth: int = 0
    abandoned_branches: int = 0
    tags: List[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        end = self.finished_at if self.finished_at else time.time()
        return (end - self.started_at) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "node_count": self.node_count,
            "decision_count": self.decision_count,
            "max_depth": self.max_depth,
            "abandoned_branches": self.abandoned_branches,
            "tags": self.tags,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ThinkingPad — main engine
# ═══════════════════════════════════════════════════════════════════════════════

class ThinkingPad:
    """Agent thought chain recorder and visualizer.

    Records every reasoning step as a ThoughtNode, building a tree of
    how the agent arrived at each decision. Supports:
      - Real-time thought recording
      - Decision point capture with alternatives
      - Branch abandonment tracking
      - Session replay (timeline reconstruction)
      - Quality metrics (depth, branching factor, confidence distribution)

    Usage::

        pad = ThinkingPad(session_id="bugfix-42")
        root = pad.think("Read error traceback", ThoughtCategory.OBSERVATION)
        decision = pad.think("Should I check the DB connection?", ThoughtCategory.REASONING)
        pad.decide(decision.id, "Fix approach", ["Restart DB", "Add retry", "Check logs"],
                   chosen="Add retry", reasoning="Simplest fix, low risk")
        pad.complete(decision.id)
        print(pad.render_text_tree())
    """

    def __init__(self, session_id: str = ""):
        self.session = ThinkingSession(
            session_id=session_id or str(uuid.uuid4())[:12],
        )
        self._nodes: Dict[str, ThoughtNode] = {}
        self._decisions: Dict[str, DecisionPoint] = {}
        self._root_id: Optional[str] = None
        self._current_id: Optional[str] = None
        self._category_counts: Dict[str, int] = defaultdict(int)

    # ── Thought recording ───────────────────────────────────────────────

    def think(
        self,
        content: str,
        category: ThoughtCategory = ThoughtCategory.OBSERVATION,
        confidence: Confidence = Confidence.MEDIUM,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ThoughtNode:
        """Record a new thought in the chain.

        Args:
            content: The thought text.
            category: Type of thought.
            confidence: Confidence level.
            parent_id: If None, uses the current cursor (last thought).
            metadata: Arbitrary context data.

        Returns:
            The created ThoughtNode.
        """
        # Determine parent
        if parent_id is None:
            parent_id = self._current_id

        # Determine depth
        depth = 0
        if parent_id and parent_id in self._nodes:
            depth = self._nodes[parent_id].depth + 1

        node = ThoughtNode(
            parent_id=parent_id,
            category=category,
            content=content,
            confidence=confidence,
            status=ThoughtStatus.DRAFT,
            metadata=metadata or {},
            depth=depth,
        )
        self._nodes[node.id] = node

        # Link parent
        if parent_id and parent_id in self._nodes:
            self._nodes[parent_id].children.append(node.id)

        # Track root
        if self._root_id is None:
            self._root_id = node.id

        # Update cursor
        self._current_id = node.id

        # Update session stats
        self.session.node_count = len(self._nodes)
        self.session.max_depth = max(self.session.max_depth, depth)
        self._category_counts[category.value] += 1

        return node

    def think_observation(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> ThoughtNode:
        """Shortcut for recording an observation."""
        return self.think(content, ThoughtCategory.OBSERVATION, metadata=metadata)

    def think_reasoning(self, content: str, confidence: Confidence = Confidence.MEDIUM) -> ThoughtNode:
        """Shortcut for recording a reasoning step."""
        return self.think(content, ThoughtCategory.REASONING, confidence=confidence)

    def think_decision(self, content: str, confidence: Confidence = Confidence.HIGH) -> ThoughtNode:
        """Shortcut for recording a decision."""
        return self.think(content, ThoughtCategory.DECISION, confidence=confidence)

    # ── Decision points ─────────────────────────────────────────────────

    def decide(
        self,
        thought_id: str,
        question: str,
        options: List[str],
        chosen: str = "",
        reasoning: str = "",
        rejected_reasons: Optional[Dict[str, str]] = None,
    ) -> DecisionPoint:
        """Record a decision point — choosing among alternatives.

        This is the heart of Claude Code's "thinking block" — showing
        users WHY the agent chose one path over others.

        Args:
            thought_id: The thought node this decision belongs to.
            question: The question being decided.
            options: All alternatives considered.
            chosen: Which option was selected.
            reasoning: Why this option won.
            rejected_reasons: Why each rejected option was dismissed.

        Returns:
            The DecisionPoint record.
        """
        dp = DecisionPoint(
            thought_id=thought_id,
            question=question,
            options=options,
            chosen=chosen or (options[0] if options else ""),
            reasoning=reasoning,
            rejected_reasons=rejected_reasons or {},
            timestamp=time.time(),
        )
        self._decisions[dp.id] = dp
        self.session.decision_count = len(self._decisions)

        # Update the thought node's metadata
        if thought_id in self._nodes:
            self._nodes[thought_id].metadata["decision_id"] = dp.id
            self._nodes[thought_id].metadata["options"] = options
            self._nodes[thought_id].metadata["chosen"] = dp.chosen

        return dp

    # ── Thought lifecycle ───────────────────────────────────────────────

    def complete(self, thought_id: str) -> Optional[ThoughtNode]:
        """Mark a thought as complete."""
        node = self._nodes.get(thought_id)
        if node:
            node.status = ThoughtStatus.COMPLETE
        return node

    def abandon(self, thought_id: str) -> Optional[ThoughtNode]:
        """Mark a thought as abandoned (dead end)."""
        node = self._nodes.get(thought_id)
        if node:
            node.status = ThoughtStatus.ABANDONED
            self.session.abandoned_branches += 1
        return node

    def finish_session(self) -> ThinkingSession:
        """Close the session with final stats."""
        self.session.finished_at = time.time()
        return self.session

    # ── Navigation ──────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[ThoughtNode]:
        """Get a thought node by ID."""
        return self._nodes.get(node_id)

    def get_children(self, node_id: str) -> List[ThoughtNode]:
        """Get all direct children of a thought."""
        node = self._nodes.get(node_id)
        if not node:
            return []
        return [self._nodes[cid] for cid in node.children if cid in self._nodes]

    def get_path(self, node_id: str) -> List[ThoughtNode]:
        """Get the full path from root to this node."""
        path = []
        current = node_id
        while current:
            node = self._nodes.get(current)
            if not node:
                break
            path.append(node)
            current = node.parent_id or ""
        path.reverse()
        return path

    def get_leaves(self) -> List[ThoughtNode]:
        """Get all leaf nodes (no children)."""
        return [n for n in self._nodes.values() if n.is_leaf]

    def get_branches(self) -> List[List[ThoughtNode]]:
        """Get all distinct reasoning paths (root to leaf)."""
        branches = []
        for leaf in self.get_leaves():
            branches.append(self.get_path(leaf.id))
        return branches

    # ── Visualization ───────────────────────────────────────────────────

    def render_text_tree(self, max_depth: int = 20) -> str:
        """Render the thought tree as ASCII text (like `tree` command).

        Returns:
            Multiline string with tree structure.
        """
        if not self._root_id:
            return "(empty)"

        lines = []

        def _render(node_id: str, prefix: str, is_last: bool):
            node = self._nodes.get(node_id)
            if not node:
                return
            if node.depth > max_depth:
                return

            connector = "└── " if is_last else "├── "
            cat_icon = self._category_icon(node.category)
            status_mark = ""
            if node.status == ThoughtStatus.ABANDONED:
                status_mark = " ✗"
            elif node.status == ThoughtStatus.COMPLETE:
                status_mark = " ✓"

            content_preview = node.content[:80].replace("\n", " ")
            lines.append(
                f"{prefix}{connector}{cat_icon} [{node.id}] {content_preview}{status_mark}"
            )

            # Render children
            children = [c for c in node.children if c in self._nodes]
            for i, child_id in enumerate(children):
                child_prefix = prefix + ("    " if is_last else "│   ")
                _render(child_id, child_prefix, i == len(children) - 1)

        lines.append(f"🧠 {self.session.session_id}")
        _render(self._root_id, "", True)
        return "\n".join(lines)

    def render_timeline(self) -> str:
        """Render thoughts as a chronological timeline."""
        sorted_nodes = sorted(self._nodes.values(), key=lambda n: n.timestamp)
        lines = ["## Thinking Timeline", ""]

        for node in sorted_nodes:
            ts = time.strftime("%H:%M:%S", time.localtime(node.timestamp))
            cat = node.category.value
            icon = self._category_icon(node.category)
            indent = "  " * min(node.depth, 5)
            content = node.content[:100].replace("\n", " ")
            conf = node.confidence.value[:3]
            status = node.status.value[:4]
            lines.append(f"{ts} {icon} [{conf}/{status}] {indent}{content}")

        return "\n".join(lines)

    @staticmethod
    def _category_icon(cat: ThoughtCategory) -> str:
        icons = {
            ThoughtCategory.OBSERVATION: "👁",
            ThoughtCategory.REASONING: "💭",
            ThoughtCategory.DECISION: "⚡",
            ThoughtCategory.EXPLORATION: "🔍",
            ThoughtCategory.CORRECTION: "🔧",
            ThoughtCategory.PLAN: "📋",
            ThoughtCategory.EXECUTION: "▶️",
            ThoughtCategory.EVALUATION: "📊",
            ThoughtCategory.BRANCH: "🌿",
            ThoughtCategory.MERGE: "🔗",
        }
        return icons.get(cat, "•")

    # ── HTML Rendering ──────────────────────────────────────────────────

    def render_html_tree(self) -> str:
        """Render the thought tree as interactive HTML."""
        import html as html_mod

        if not self._root_id:
            return '<div style="color:#94a3b8">(empty)</div>'

        def _render_node(node: ThoughtNode) -> str:
            children_html = ""
            for cid in node.children:
                if cid in self._nodes:
                    children_html += _render_node(self._nodes[cid])

            cat_color = {
                "observation": "#06b6d4",
                "reasoning": "#8b5cf6",
                "decision": "#fbbf24",
                "exploration": "#22c55e",
                "correction": "#dc2626",
                "plan": "#3b82f6",
                "execution": "#f59e0b",
                "evaluation": "#ec4899",
                "branch": "#10b981",
                "merge": "#6366f1",
            }.get(node.category.value, "#94a3b8")

            status_badge = ""
            if node.status == ThoughtStatus.ABANDONED:
                status_badge = '<span style="color:#dc2626;font-size:10px">✗</span>'
            elif node.status == ThoughtStatus.COMPLETE:
                status_badge = '<span style="color:#22c55e;font-size:10px">✓</span>'

            conf_bars = {"high": "●●●", "medium": "●●○", "low": "●○○", "speculative": "○○○"}
            conf = conf_bars.get(node.confidence.value, "●○○")

            return (
                f'<div style="margin-left:{node.depth * 24}px;margin-bottom:6px;'
                f'border-left:2px solid {cat_color};padding:4px 12px">'
                f'<div style="font-size:11px;color:{cat_color};margin-bottom:2px">'
                f'[{node.category.value}] {status_badge} '
                f'<span style="color:#64748b">{conf} #{node.id}</span>'
                f'</div>'
                f'<div style="font-size:13px;color:#e2e8f0">'
                f'{html_mod.escape(node.content[:200])}'
                f'</div>'
                f'{children_html}'
                f'</div>'
            )

        return (
            f'<div style="font-family:system-ui,sans-serif;background:#0f172a;'
            f'color:#e2e8f0;padding:16px;border-radius:8px">'
            f'<div style="font-weight:bold;color:#8b5cf6;margin-bottom:12px">'
            f'🧠 {html_mod.escape(self.session.session_id)} '
            f'({self.session.node_count} thoughts, depth {self.session.max_depth})'
            f'</div>'
            f'{_render_node(self._nodes[self._root_id])}'
            f'</div>'
        )

    # ── Quality metrics ─────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        """Compute quality metrics about the thinking process.

        Returns:
            Dict with: avg_depth, branching_factor, confidence_distribution,
            category_distribution, abandonment_rate, decision_density.
        """
        if not self._nodes:
            return {"nodes": 0}

        depths = [n.depth for n in self._nodes.values()]
        avg_depth = sum(depths) / len(depths) if depths else 0

        non_leaves = [n for n in self._nodes.values() if n.children]
        branching = (
            sum(len(n.children) for n in non_leaves) / len(non_leaves)
            if non_leaves else 0
        )

        conf_dist: Dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            conf_dist[n.confidence.value] += 1

        abandoned = sum(1 for n in self._nodes.values()
                        if n.status == ThoughtStatus.ABANDONED)
        abandonment_rate = abandoned / len(self._nodes) if self._nodes else 0

        return {
            "nodes": len(self._nodes),
            "decisions": len(self._decisions),
            "avg_depth": round(avg_depth, 2),
            "max_depth": self.session.max_depth,
            "branching_factor": round(branching, 2),
            "confidence_distribution": dict(conf_dist),
            "category_distribution": dict(self._category_counts),
            "abandonment_rate": round(abandonment_rate, 3),
            "decision_density": round(len(self._decisions) / max(len(self._nodes), 1), 3),
            "duration_ms": self.session.duration_ms,
        }

    # ── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full thinking session to a dict."""
        return {
            "session": self.session.to_dict(),
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "decisions": [d.to_dict() for d in self._decisions.values()],
            "metrics": self.metrics(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    # ── Replay ──────────────────────────────────────────────────────────

    def replay(self) -> List[ThoughtNode]:
        """Return all thoughts in chronological order for replay."""
        return sorted(self._nodes.values(), key=lambda n: n.timestamp)


# ═══════════════════════════════════════════════════════════════════════════════
# ThinkingPadManager — manages multiple sessions
# ═══════════════════════════════════════════════════════════════════════════════

class ThinkingPadManager:
    """Manage multiple ThinkingPad sessions across agent invocations.

    Useful for tracking thinking patterns over time — which reasoning
    strategies work, where the agent tends to get stuck, etc.
    """

    def __init__(self, max_sessions: int = 100):
        self._sessions: Dict[str, ThinkingPad] = {}
        self._completed: List[ThinkingSession] = []
        self._max_sessions = max_sessions

    def create(self, session_id: str = "") -> ThinkingPad:
        """Create a new thinking session."""
        pad = ThinkingPad(session_id)
        self._sessions[pad.session.session_id] = pad
        self._evict_old()
        return pad

    def get(self, session_id: str) -> Optional[ThinkingPad]:
        return self._sessions.get(session_id)

    def finish(self, session_id: str) -> Optional[ThinkingSession]:
        """Finish a session and move it to completed."""
        pad = self._sessions.pop(session_id, None)
        if pad:
            session = pad.finish_session()
            self._completed.append(session)
            return session
        return None

    def _evict_old(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest = min(self._sessions.keys(),
                        key=lambda k: self._sessions[k].session.started_at)
            self.finish(oldest)

    def aggregate_metrics(self) -> Dict[str, Any]:
        """Aggregate metrics across all completed sessions."""
        all_metrics = []
        for pad in self._sessions.values():
            all_metrics.append(pad.metrics())
        for session in self._completed:
            all_metrics.append({
                "nodes": session.node_count,
                "decisions": session.decision_count,
                "max_depth": session.max_depth,
                "abandonment_rate": session.abandoned_branches / max(session.node_count, 1),
            })

        if not all_metrics:
            return {"sessions": 0}

        avg_nodes = sum(m.get("nodes", 0) for m in all_metrics) / len(all_metrics)
        avg_depth = sum(m.get("max_depth", 0) for m in all_metrics) / len(all_metrics)

        return {
            "sessions": len(all_metrics),
            "avg_nodes_per_session": round(avg_nodes, 1),
            "avg_max_depth": round(avg_depth, 1),
            "total_nodes": sum(m.get("nodes", 0) for m in all_metrics),
        }

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def completed_count(self) -> int:
        return len(self._completed)
