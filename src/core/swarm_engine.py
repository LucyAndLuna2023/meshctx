"""Agent Swarm Intelligence — v2.84
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
群体智能: 多Agent自组织协作

机制:
- 发现: Agent自动发现局域网/网络中的其他meshctx实例
- 投票: 多数决策+加权信任
- 分工: 任务自动分配给最擅长Agent
- 共识: Raft-like共识协议简化版
"""
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    LEADER = "leader"
    WORKER = "worker"
    OBSERVER = "observer"
    CANDIDATE = "candidate"


@dataclass
class SwarmMember:
    """群体成员"""
    agent_id: str
    host: str = ""
    port: int = 3001
    role: AgentRole = AgentRole.WORKER
    capabilities: List[str] = field(default_factory=list)
    trust_score: float = 0.5
    last_heartbeat: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0


@dataclass
class Vote:
    """投票"""
    proposal: str
    votes_yes: int = 0
    votes_no: int = 0
    voters: Set[str] = field(default_factory=set)
    threshold: float = 0.51
    decided: bool = False
    result: bool = False


class SwarmEngine:
    """群体智能引擎"""

    def __init__(self, agent_id: str = "meshctx-0",
                host: str = "localhost", port: int = 3001):
        self.agent_id = agent_id
        self.host = host
        self.port = port
        self._members: Dict[str, SwarmMember] = {}
        self._votes: Dict[str, Vote] = {}
        self._task_queue: List[Dict] = []
        self._knowledge_pool: Dict[str, Any] = {}

        # 注册自己
        self._members[agent_id] = SwarmMember(
            agent_id=agent_id, host=host, port=port,
            capabilities=["safety", "memory", "code", "deploy", "monitor"],
            trust_score=1.0,
        )

    # ── Discovery ──────────────────────────────────────

    def discover(self, hosts: List[str]) -> List[SwarmMember]:
        """发现网络中的其他Agent"""
        discovered = []
        for host in hosts:
            try:
                # 尝试连接 /api/version
                parts = host.split(":")
                h = parts[0]
                p = int(parts[1]) if len(parts) > 1 else 3001

                # 模拟发现
                agent_id = f"meshctx-{hash(host) % 1000}"
                if agent_id not in self._members:
                    member = SwarmMember(
                        agent_id=agent_id, host=h, port=p,
                        capabilities=["code", "memory"],
                    )
                    self._members[agent_id] = member
                    discovered.append(member)
                    logger.info(f"🔍 发现Agent: {agent_id} @ {host}")
            except Exception:
                pass

        return discovered

    def register(self, member: SwarmMember):
        """注册新成员"""
        if member.agent_id not in self._members:
            self._members[member.agent_id] = member

    def heartbeat(self) -> Dict:
        """心跳检查"""
        now = time.time()
        alive = 0
        dead = 0
        for mid, member in self._members.items():
            if now - member.last_heartbeat < 30:
                alive += 1
            else:
                dead += 1
        return {"alive": alive, "dead": dead, "total": len(self._members)}

    # ── Voting ─────────────────────────────────────────

    def propose(self, proposal: str,
               threshold: float = 0.51) -> Vote:
        """发起投票"""
        vote = Vote(proposal=proposal, threshold=threshold)
        self._votes[proposal] = vote
        return vote

    def cast_vote(self, proposal: str, agent_id: str,
                 vote_yes: bool, weight: float = 1.0) -> bool:
        """投票"""
        vote = self._votes.get(proposal)
        if not vote or vote.decided:
            return False

        if agent_id in vote.voters:
            return False

        vote.voters.add(agent_id)
        member = self._members.get(agent_id)
        w = weight * (member.trust_score if member else 0.5)

        if vote_yes:
            vote.votes_yes += w
        else:
            vote.votes_no += w

        # 检查是否达到阈值
        total = len(self._members)
        ratio = vote.votes_yes / max(1, total)

        if ratio >= vote.threshold:
            vote.decided = True
            vote.result = True
        elif (1 - ratio) >= vote.threshold:
            vote.decided = True
            vote.result = False

        return True

    def get_consensus(self, proposal: str) -> Dict:
        """获取共识结果"""
        vote = self._votes.get(proposal)
        if not vote:
            return {"error": "proposal not found"}

        return {
            "proposal": proposal,
            "yes": vote.votes_yes,
            "no": vote.votes_no,
            "ratio": round(vote.votes_yes / max(1, vote.votes_yes + vote.votes_no), 2),
            "decided": vote.decided,
            "result": vote.result,
            "voter_count": len(vote.voters),
        }

    # ── Task Distribution ──────────────────────────────

    def assign_task(self, task: Dict) -> Optional[str]:
        """分配给最合适的Agent"""
        task_type = task.get("type", "general")
        best_agent = None
        best_score = -1

        for mid, member in self._members.items():
            if task_type in member.capabilities:
                # 计算胜任分数: 能力匹配 + 信任度 + 负载
                load_penalty = (
                    member.tasks_completed / max(1, member.tasks_completed + member.tasks_failed)
                )
                score = 1.0 * member.trust_score * (0.5 + 0.5 * load_penalty)

                if score > best_score:
                    best_score = score
                    best_agent = mid

        if best_agent:
            task["assigned_to"] = best_agent
            task["assigned_at"] = time.time()
            self._task_queue.append(task)
            return best_agent

        return None

    def report_result(self, agent_id: str, task_id: str,
                     success: bool, output: str = ""):
        """报告任务结果"""
        member = self._members.get(agent_id)
        if member:
            if success:
                member.tasks_completed += 1
                member.trust_score = min(1.0, member.trust_score + 0.05)
            else:
                member.tasks_failed += 1
                member.trust_score = max(0.1, member.trust_score - 0.1)

    # ── Knowledge Sharing ──────────────────────────────

    def share_knowledge(self, key: str, value: Any):
        """分享知识到群体池"""
        self._knowledge_pool[key] = {
            "value": value,
            "shared_by": self.agent_id,
            "timestamp": time.time(),
        }

    def query_knowledge(self, key: str) -> Optional[Any]:
        """从群体池查询知识"""
        entry = self._knowledge_pool.get(key)
        return entry["value"] if entry else None

    # ── Leader Election ────────────────────────────────

    def elect_leader(self) -> str:
        """选举Leader (简化Raft)"""
        # Leader = 最高信任度+经验
        best = max(
            self._members.values(),
            key=lambda m: m.trust_score * 0.6 + min(1.0, m.tasks_completed / 10) * 0.4,
        )
        best.role = AgentRole.LEADER
        for m in self._members.values():
            if m.agent_id != best.agent_id:
                m.role = AgentRole.WORKER
        return best.agent_id

    # ── Stats ──────────────────────────────────────────

    def get_swarm_stats(self) -> Dict:
        leader = self.elect_leader()
        return {
            "members": len(self._members),
            "leader": leader,
            "roles": {
                r.value: sum(1 for m in self._members.values() if m.role == r)
                for r in AgentRole
            },
            "knowledge_pool_size": len(self._knowledge_pool),
            "active_votes": sum(1 for v in self._votes.values() if not v.decided),
            "pending_tasks": len([t for t in self._task_queue if "assigned_to" not in str(t)]),
            "avg_trust": round(
                sum(m.trust_score for m in self._members.values()) / max(1, len(self._members)), 3
            ),
        }

    def get_stats(self) -> Dict:
        return self.get_swarm_stats()


# 单例
_swarm: Optional[SwarmEngine] = None


def get_swarm_engine() -> SwarmEngine:
    global _swarm
    if _swarm is None:
        _swarm = SwarmEngine()
    return _swarm
