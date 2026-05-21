"""
Cross-Agent Knowledge Transfer — v2.53
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
多Agent之间的知识共享引擎。当一个Agent学到东西,
所有Agent都能受益。

机制:
1. 知识图谱 — 共享语义图，所有Agent读写
2. 课程广播 — Agent解决问题后广播解决方案
3. 冲突解决 — Agent分歧时投票/置信度仲裁
4. 知识衰减 — 旧知识随时间消退
5. 来源追踪 — 每条知识记录来源Agent
"""
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import numpy as np

logger = logging.getLogger(__name__)


class KnowledgeSource(Enum):
    AGENT_EXPERIENCE = "agent_experience"  # Agent自身经验
    USER_CORRECTION = "user_correction"    # 用户纠正
    CROSS_AGENT = "cross_agent"            # 跨Agent迁移
    DERIVED = "derived"                    # 推理推导
    EXTERNAL = "external"                  # 外部知识源


@dataclass
class KnowledgeNode:
    """知识图谱节点"""
    node_id: str = ""
    content: str = ""
    category: str = "general"
    source: KnowledgeSource = KnowledgeSource.AGENT_EXPERIENCE
    source_agent: str = ""
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    decay_rate: float = 0.01  # 每次访问衰减率
    strength: float = 1.0     # 当前强度(0-1)
    tags: List[str] = field(default_factory=list)
    related_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "content": self.content[:200],
            "category": self.category,
            "source": self.source.value,
            "source_agent": self.source_agent,
            "confidence": self.confidence,
            "strength": self.strength,
            "tags": self.tags,
        }


class CrossAgentKnowledgeEngine:
    """跨Agent知识迁移引擎"""

    def __init__(self, max_nodes: int = 1000,
                 default_decay: float = 0.005,
                 consolidation_threshold: float = 0.3):
        self.max_nodes = max_nodes
        self.default_decay = default_decay
        self.consolidation_threshold = consolidation_threshold

        # 知识图谱
        self._graph: Dict[str, KnowledgeNode] = {}
        self._edges: Dict[str, Set[str]] = {}  # node_id → related node_ids

        # Agent注册
        self._agents: Dict[str, Dict] = {}
        self._broadcast_log: List[Dict] = []

        # 统计
        self._stats = {
            "total_nodes": 0,
            "total_broadcasts": 0,
            "total_queries": 0,
            "consolidations": 0,
            "pruned_nodes": 0,
        }

    # ── Agent Management ───────────────────────────────

    def register_agent(self, agent_id: str, capabilities: List[str] = None) -> Dict:
        """注册Agent到知识共享网络"""
        self._agents[agent_id] = {
            "registered_at": time.time(),
            "capabilities": capabilities or [],
            "contributions": 0,
            "queries": 0,
        }
        return {"agent_id": agent_id, "status": "registered"}

    def unregister_agent(self, agent_id: str):
        """Agent离开网络"""
        self._agents.pop(agent_id, None)

    # ── Knowledge CRUD ────────────────────────────────

    def add_knowledge(self, content: str, category: str = "general",
                      source: KnowledgeSource = KnowledgeSource.AGENT_EXPERIENCE,
                      source_agent: str = "", confidence: float = 0.5,
                      tags: List[str] = None) -> KnowledgeNode:
        """添加知识到图谱"""
        import hashlib
        node_id = hashlib.md5(
            f"{content[:100]}{time.time()}".encode()
        ).hexdigest()[:12]

        node = KnowledgeNode(
            node_id=node_id,
            content=content,
            category=category,
            source=source,
            source_agent=source_agent,
            confidence=confidence,
            tags=tags or [],
        )

        self._graph[node_id] = node
        self._edges[node_id] = set()
        self._stats["total_nodes"] = len(self._graph)

        return node

    def get_knowledge(self, node_id: str) -> Optional[KnowledgeNode]:
        """获取知识节点并更新访问"""
        node = self._graph.get(node_id)
        if node:
            node.last_accessed = time.time()
            node.access_count += 1
            # 衰减: 每次访问轻微衰减
            node.strength = max(0.1, node.strength - node.decay_rate)
        return node

    def query_knowledge(self, query: str, category: str = "",
                        min_confidence: float = 0.3,
                        limit: int = 10) -> List[KnowledgeNode]:
        """查询知识图谱

        Args:
            query: 搜索关键词
            category: 分类过滤
            min_confidence: 最低置信度
            limit: 返回数量
        """
        self._stats["total_queries"] += 1
        results = []

        query_lower = query.lower()
        for node in self._graph.values():
            # 强度太低跳过
            if node.strength < 0.1:
                continue
            # 置信度太低跳过
            if node.confidence < min_confidence:
                continue
            # 分类过滤
            if category and node.category != category:
                continue

            # 匹配评分
            score = self._match_score(node, query_lower)
            if score > 0:
                results.append((score, node))

        results.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in results[:limit]]

    # ── Knowledge Decay & Consolidation ────────────────

    def decay_knowledge(self):
        """对所有知识应用时间衰减"""
        now = time.time()
        for node in list(self._graph.values()):
            # 未访问的时间越长，衰减越快
            idle_hours = (now - node.last_accessed) / 3600
            decay = self.default_decay * max(1, idle_hours)
            node.strength = max(0.02, node.strength - decay)

            # 移除极弱的知识
            if node.strength <= 0.02:
                self._graph.pop(node.node_id, None)
                self._edges.pop(node.node_id, None)
                self._stats["pruned_nodes"] += 1

    def consolidate_knowledge(self):
        """知识巩固: 加强高频访问的知识，关联相似节点"""
        self._stats["consolidations"] += 1

        for node in self._graph.values():
            if node.access_count >= 5 and node.strength > self.consolidation_threshold:
                # 高频访问 → 巩固（增加强度）
                boost = min(0.1, node.access_count * 0.01)
                node.strength = min(1.0, node.strength + boost)
                # 降低衰减率（巩固的知识更持久）
                node.decay_rate = max(0.001, node.decay_rate * 0.5)

        # 关联相似节点
        self._link_similar_nodes()

    # ── Broadcast (课程广播) ───────────────────────────

    def broadcast_lesson(self, source_agent: str, lesson: str,
                         category: str = "general",
                         confidence: float = 0.5) -> Dict:
        """广播一条课程到所有Agent"""
        node = self.add_knowledge(
            content=lesson,
            category=category,
            source=KnowledgeSource.CROSS_AGENT,
            source_agent=source_agent,
            confidence=confidence,
        )

        self._stats["total_broadcasts"] += 1
        self._broadcast_log.append({
            "time": time.time(),
            "source_agent": source_agent,
            "lesson": lesson[:200],
            "node_id": node.node_id,
        })

        # 更新Agent贡献
        if source_agent in self._agents:
            self._agents[source_agent]["contributions"] += 1

        logger.info(f"📡 Agent {source_agent} 广播知识: {lesson[:80]}...")
        return {"broadcast_id": node.node_id, "lesson": lesson[:200]}

    # ── Conflict Resolution ────────────────────────────

    def resolve_conflict(self, node_a_id: str, node_b_id: str) -> Dict:
        """解决两个知识节点的冲突

        策略: 高置信度 + 多Agent支持 + 新近性 决定胜负
        """
        node_a = self._graph.get(node_a_id)
        node_b = self._graph.get(node_b_id)

        if not node_a or not node_b:
            return {"error": "节点未找到"}

        # 综合评分
        def score(n: KnowledgeNode) -> float:
            return (
                n.confidence * 0.4 +
                n.strength * 0.3 +
                (1.0 / (1 + (time.time() - n.created_at) / 86400)) * 0.3
            )

        score_a = score(node_a)
        score_b = score(node_b)

        winner = node_a if score_a >= score_b else node_b
        loser = node_b if score_a >= score_b else node_a

        # 合并: 保留winner, loser降权
        loser.strength *= 0.3
        loser.confidence *= 0.5

        return {
            "winner_id": winner.node_id,
            "loser_id": loser.node_id,
            "winner_score": round(max(score_a, score_b), 4),
            "resolution": "winner_kept_loser_deprecated",
        }

    # ── Agent Insights ──────────────────────────────────

    def get_agent_insights(self, agent_id: str) -> Dict:
        """获取给特定Agent的个性化知识"""
        agent = self._agents.get(agent_id)

        # 获取该Agent相关的高价值知识
        nodes = []
        for node in self._graph.values():
            if node.strength < 0.3:
                continue
            # 优先返回该Agent贡献的或高置信度的
            if node.source_agent == agent_id or node.confidence >= 0.7:
                nodes.append(node)

        nodes.sort(key=lambda n: n.confidence * n.strength, reverse=True)

        self._stats["total_queries"] += 1
        return {
            "agent_id": agent_id,
            "insights": [n.to_dict() for n in nodes[:10]],
            "total_available": len(self._graph),
        }

    # ── Graph Operations ───────────────────────────────

    def _link_similar_nodes(self):
        """基于内容相似度连接节点"""
        nodes_list = list(self._graph.values())
        for i, node_a in enumerate(nodes_list):
            if node_a.strength < 0.3:
                continue
            for node_b in nodes_list[i + 1:]:
                if node_b.strength < 0.3:
                    continue
                sim = self._content_similarity(node_a.content, node_b.content)
                if sim > 0.5:
                    self._edges[node_a.node_id].add(node_b.node_id)
                    self._edges[node_b.node_id].add(node_a.node_id)

    def _match_score(self, node: KnowledgeNode, query: str) -> float:
        """计算节点与查询的匹配分数"""
        content_lower = node.content.lower()
        # 精确匹配
        if query in content_lower:
            return 0.9
        # 部分匹配
        words = query.split()
        matches = sum(1 for w in words if w in content_lower)
        if matches > 0:
            return 0.5 * matches / len(words)
        # 标签匹配
        for tag in node.tags:
            if query in tag.lower():
                return 0.7
        return 0.0

    def _content_similarity(self, a: str, b: str) -> float:
        """内容相似度"""
        if not a or not b:
            return 0.0
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_nodes": len(self._graph),
            "agent_count": len(self._agents),
            "graph_density": sum(len(e) for e in self._edges.values()) / max(1, len(self._graph)),
            "avg_strength": round(np.mean([n.strength for n in self._graph.values()]), 4) if self._graph else 0,
            "top_categories": self._top_categories(),
        }

    def _top_categories(self, n: int = 5) -> List[tuple]:
        cats: Dict[str, int] = {}
        for node in self._graph.values():
            cats[node.category] = cats.get(node.category, 0) + 1
        return sorted(cats.items(), key=lambda x: x[1], reverse=True)[:n]


# 单例
_engine: Optional[CrossAgentKnowledgeEngine] = None


def get_knowledge_engine() -> CrossAgentKnowledgeEngine:
    global _engine
    if _engine is None:
        _engine = CrossAgentKnowledgeEngine()
    return _engine
