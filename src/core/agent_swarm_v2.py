"""
meshctx v3.109 — Agent Swarm V2 (智能Agent群体系统)

四大核心能力:
1) 动态角色分配 (Dynamic Role Assignment) — 根据任务需求实时调整Agent角色
2) 共识投票 (Consensus Voting) — 多数/加权/拜占庭容错多种共识策略
3) 任务市场竞价 (Task Market Bidding) — 自由市场经济，Agent竞价抢任务
4) 自组织拓扑 (Self-Organizing Topology) — 基于延迟/负载/亲和度自动优化拓扑

Design: Thread-safe, pluggable strategy patterns, event-driven communication.
"""

import heapq
import logging
import math
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Union,
)

logger = logging.getLogger("meshctx.agent_swarm_v2")

# ═══════════════════════════════════════════════════════════════
# Feature 1: Dynamic Role Assignment
# ═══════════════════════════════════════════════════════════════

class RoleType(Enum):
    """Predefined agent roles in the swarm."""
    LEADER = "leader"
    WORKER = "worker"
    OBSERVER = "observer"
    COORDINATOR = "coordinator"
    FORAGER = "forager"
    GATEKEEPER = "gatekeeper"
    ARCHIVER = "archiver"
    MEDIATOR = "mediator"
    SPECIALIST = "specialist"
    ROVING = "roving"  # Can take any role dynamically


@dataclass
class RoleCapability:
    """What a role can do — used for matching agents to tasks."""
    name: str
    level: float = 1.0              # 0.0–1.0 proficiency
    experience: int = 0             # Number of successful assignments
    last_used: float = 0.0          # Timestamp of last use


@dataclass
class AgentRole:
    """A role that an agent can hold in the swarm."""
    role_type: RoleType
    capabilities: List[RoleCapability] = field(default_factory=list)
    assigned_at: float = field(default_factory=time.time)
    priority: int = 5               # 1 (lowest) – 10 (highest)
    ttl: float = 3600.0             # How long before role is re-evaluated (seconds)

    def has_capability(self, name: str) -> bool:
        return any(c.name == name for c in self.capabilities)

    def get_capability_level(self, name: str) -> float:
        for c in self.capabilities:
            if c.name == name:
                return c.level
        return 0.0

    def record_use(self, name: str):
        for c in self.capabilities:
            if c.name == name:
                c.experience += 1
                c.last_used = time.time()
                c.level = min(1.0, c.level + 0.002)  # Slight improvement
                return


@dataclass
class SwarmAgent:
    """An individual agent in the swarm with dynamic role support."""
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    roles: List[AgentRole] = field(default_factory=list)
    current_role: Optional[AgentRole] = None
    load: float = 0.0               # 0.0 (idle) – 1.0 (overloaded)
    reputation: float = 0.5         # 0.0–1.0 trust score
    latency_ms: float = 50.0        # Estimated latency to this agent
    tags: Set[str] = field(default_factory=set)
    last_seen: float = field(default_factory=time.time)
    active_tasks: int = 0
    total_completed: int = 0
    total_errors: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_alive(self, timeout: float = 60.0) -> bool:
        return time.time() - self.last_seen < timeout

    @property
    def effective_role(self) -> Optional[AgentRole]:
        """Get the current effective role, or the highest-priority role."""
        if self.current_role:
            return self.current_role
        if self.roles:
            return max(self.roles, key=lambda r: r.priority)
        return None

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "current_role": self.current_role.role_type.value if self.current_role else None,
            "roles": [r.role_type.value for r in self.roles],
            "load": round(self.load, 2),
            "reputation": round(self.reputation, 2),
            "latency_ms": self.latency_ms,
            "active_tasks": self.active_tasks,
            "total_completed": self.total_completed,
            "total_errors": self.total_errors,
            "tags": list(self.tags),
        }


class DynamicRoleManager:
    """Manages dynamic role assignment based on task demand and agent capability."""

    def __init__(self):
        self._role_templates: Dict[RoleType, List[str]] = {
            RoleType.LEADER:    ["coordinate", "decide", "delegate"],
            RoleType.WORKER:    ["execute", "compute", "process"],
            RoleType.OBSERVER:  ["monitor", "report", "detect"],
            RoleType.COORDINATOR: ["route", "schedule", "balance"],
            RoleType.FORAGER:   ["search", "fetch", "explore"],
            RoleType.GATEKEEPER: ["validate", "filter", "authenticate"],
            RoleType.ARCHIVER:  ["store", "index", "retrieve"],
            RoleType.MEDIATOR:  ["resolve", "arbitrate", "negotiate"],
            RoleType.SPECIALIST: ["analyze", "optimize", "transform"],
        }
        self._assignment_history: deque = deque(maxlen=200)

    def get_capabilities_for(self, role_type: RoleType) -> List[str]:
        return self._role_templates.get(role_type, [])

    def assign_role(self, agent: SwarmAgent, role_type: RoleType,
                    priority: int = 5, ttl: float = 3600.0) -> AgentRole:
        """Assign a new role to an agent, recording existing one in history."""
        if agent.current_role:
            agent.roles.append(agent.current_role)

        caps = [
            RoleCapability(name=c, level=0.5)
            for c in self.get_capabilities_for(role_type)
        ]
        new_role = AgentRole(
            role_type=role_type,
            capabilities=caps,
            priority=priority,
            ttl=ttl,
        )
        agent.current_role = new_role
        agent.roles.append(new_role)

        self._assignment_history.append({
            "agent": agent.agent_id,
            "role": role_type.value,
            "priority": priority,
            "time": time.time(),
        })
        logger.info(
            "Role assigned: %s -> %s (priority=%d, ttl=%.0fs)",
            agent.name or agent.agent_id, role_type.value, priority, ttl,
        )
        return new_role

    def rebalance_roles(self, agents: List[SwarmAgent],
                        demand: Dict[RoleType, int]) -> Dict[str, AgentRole]:
        """Rebalance roles across the swarm based on demand.

        Args:
            agents: All agents in the swarm.
            demand: How many agents are needed per role type.

        Returns:
            Mapping of agent_id -> newly assigned role.
        """
        assignments: Dict[str, AgentRole] = {}
        available = [a for a in agents if a.is_alive()]

        for role_type, needed_count in demand.items():
            # Find agents already in this role
            current_count = sum(
                1 for a in available
                if a.effective_role and a.effective_role.role_type == role_type
            )
            shortage = needed_count - current_count

            if shortage <= 0:
                continue

            # Find candidates: idle agents or those with matching tags
            candidates = sorted(
                [a for a in available
                 if a.agent_id not in assignments
                 and (not a.effective_role or a.effective_role.role_type != role_type)],
                key=lambda a: (a.load, -a.reputation),
            )[:shortage]

            for agent in candidates:
                role = self.assign_role(agent, role_type)
                assignments[agent.agent_id] = role

        return assignments

    def check_role_expiry(self, agents: List[SwarmAgent]):
        """Remove expired roles and trigger re-evaluation."""
        now = time.time()
        for agent in agents:
            if agent.current_role and (now - agent.current_role.assigned_at) > agent.current_role.ttl:
                logger.debug(
                    "Role expired for %s: %s",
                    agent.agent_id, agent.current_role.role_type.value,
                )
                agent.current_role = None
                # Agent becomes ROVING (can take any role)
                agent.tags.add("rebalance_needed")


# ═══════════════════════════════════════════════════════════════
# Feature 2: Consensus Voting
# ═══════════════════════════════════════════════════════════════

class ConsensusStrategy(Enum):
    """Different consensus algorithms supported by the swarm."""
    MAJORITY = "majority"               # Simple majority (>50%)
    WEIGHTED = "weighted"               # Weight by reputation
    SUPERMAJORITY = "supermajority"     # Requires 2/3 majority
    RANDOM_DICTATOR = "random_dictator" # One agent picked at random decides
    BYZANTINE = "byzantine"             # Byzantine fault tolerance (3f+1)
    UNANIMOUS = "unanimous"             # Everyone must agree
    QUORUM = "quorum"                   # Configurable threshold


@dataclass
class Vote:
    """A single vote from an agent on a proposal."""
    agent_id: str
    proposal_id: str
    choice: str                        # "yes", "no", "abstain", or custom
    weight: float = 1.0                # Voting weight (reputation-based)
    timestamp: float = field(default_factory=time.time)
    rationale: str = ""


@dataclass
class ConsensusResult:
    """Result of a consensus round."""
    proposal_id: str
    strategy: ConsensusStrategy
    passed: bool
    winner: str                        # Winning choice
    votes_for: int
    votes_against: int
    votes_abstain: int
    total_weight: float
    threshold: float
    quorum_reached: bool
    voters: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "strategy": self.strategy.value,
            "passed": self.passed,
            "winner": self.winner,
            "votes_for": self.votes_for,
            "votes_against": self.votes_against,
            "votes_abstain": self.votes_abstain,
            "total_weight": round(self.total_weight, 2),
            "threshold": round(self.threshold, 2),
            "quorum_reached": self.quorum_reached,
            "voter_count": len(self.voters),
        }


class ConsensusEngine:
    """Manages consensus voting rounds across the swarm."""

    def __init__(self, default_strategy: ConsensusStrategy = ConsensusStrategy.MAJORITY):
        self.default_strategy = default_strategy
        self._proposals: Dict[str, Dict] = {}       # proposal_id -> metadata
        self._votes: Dict[str, List[Vote]] = {}     # proposal_id -> votes
        self._results: Dict[str, ConsensusResult] = {}
        self._lock = threading.Lock()

    def propose(self, proposal_id: str, description: str = "",
                strategy: Optional[ConsensusStrategy] = None,
                threshold: float = 0.5,
                quorum: int = 0) -> str:
        """Create a new proposal for voting. Returns proposal_id."""
        with self._lock:
            self._proposals[proposal_id] = {
                "description": description,
                "strategy": strategy or self.default_strategy,
                "threshold": threshold,
                "quorum": quorum,
                "created_at": time.time(),
                "status": "open",
            }
            self._votes[proposal_id] = []
            logger.info("Proposal created: %s (strategy=%s)", proposal_id,
                        (strategy or self.default_strategy).value)
        return proposal_id

    def cast_vote(self, proposal_id: str, agent_id: str, choice: str,
                  weight: float = 1.0, rationale: str = "") -> Vote:
        """Cast a vote on a proposal."""
        vote = Vote(
            agent_id=agent_id,
            proposal_id=proposal_id,
            choice=choice,
            weight=weight,
            rationale=rationale,
        )
        with self._lock:
            if proposal_id not in self._votes:
                self._votes[proposal_id] = []
            # Replace if agent already voted
            existing = [v for v in self._votes[proposal_id] if v.agent_id == agent_id]
            for v in existing:
                self._votes[proposal_id].remove(v)
            self._votes[proposal_id].append(vote)
        logger.debug("Vote cast: %s on %s -> %s", agent_id, proposal_id, choice)
        return vote

    def tally(self, proposal_id: str, total_agents: int = 0) -> ConsensusResult:
        """Count votes and determine the outcome."""
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if not proposal:
                return ConsensusResult(
                    proposal_id=proposal_id,
                    strategy=ConsensusStrategy.MAJORITY,
                    passed=False,
                    winner="unknown",
                    votes_for=0, votes_against=0, votes_abstain=0,
                    total_weight=0, threshold=0,
                    quorum_reached=False,
                )

            votes = self._votes.get(proposal_id, [])
            strategy = proposal["strategy"]
            threshold = proposal.get("threshold", 0.5)
            quorum = proposal.get("quorum", 0)

            # Count choices
            counts: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))
            for v in votes:
                c, w = counts[v.choice]
                counts[v.choice] = (c + 1, w + v.weight)

            yes_count, yes_weight = counts.get("yes", (0, 0.0))
            no_count, no_weight = counts.get("no", (0, 0.0))
            abstain_count, abstain_weight = counts.get("abstain", (0, 0.0))

            total_weight = sum(w for _, w in counts.values())
            total_votes = len(votes)

            quorum_reached = total_votes >= quorum if quorum > 0 else total_votes > 0

            # Determine winner
            if strategy == ConsensusStrategy.MAJORITY:
                passed = yes_count > no_count and quorum_reached
            elif strategy == ConsensusStrategy.SUPERMAJORITY:
                denom = max(total_votes, 1)
                passed = (yes_count / denom) >= (2.0 / 3.0) and quorum_reached
            elif strategy == ConsensusStrategy.WEIGHTED:
                passed = yes_weight > (total_weight - yes_weight) and quorum_reached
            elif strategy == ConsensusStrategy.UNANIMOUS:
                passed = (yes_count == total_votes and total_votes > 0 and quorum_reached)
            elif strategy == ConsensusStrategy.RANDOM_DICTATOR:
                if votes:
                    dictator = random.choice(votes)
                    passed = dictator.choice == "yes"
                else:
                    passed = False
            elif strategy == ConsensusStrategy.BYZANTINE:
                # BFT: needs > 2/3 of votes for "yes" to tolerate up to f faults
                passed = (yes_count > 2 * no_count) and (yes_count > total_votes * 2 / 3) and quorum_reached
            elif strategy == ConsensusStrategy.QUORUM:
                denom = max(total_votes, 1)
                passed = (yes_count / denom) >= threshold and quorum_reached
            else:
                passed = yes_count > no_count and quorum_reached

            winner = "yes" if passed else ("no" if no_count > 0 else "abstain")

            result = ConsensusResult(
                proposal_id=proposal_id,
                strategy=strategy,
                passed=passed,
                winner=winner,
                votes_for=yes_count,
                votes_against=no_count,
                votes_abstain=abstain_count,
                total_weight=total_weight,
                threshold=threshold,
                quorum_reached=quorum_reached,
                voters=[v.agent_id for v in votes],
                details={"strategy": strategy.value, "counts": dict(counts)},
            )
            self._results[proposal_id] = result
            proposal["status"] = "closed"

            logger.info(
                "Consensus result [%s] %s: passed=%s (%d for, %d against, %d abstain)",
                proposal_id, strategy.value, passed,
                yes_count, no_count, abstain_count,
            )
            return result

    def get_result(self, proposal_id: str) -> Optional[ConsensusResult]:
        return self._results.get(proposal_id)

    def get_proposal_status(self, proposal_id: str) -> Optional[Dict]:
        return self._proposals.get(proposal_id)


# ═══════════════════════════════════════════════════════════════
# Feature 3: Task Market Bidding
# ═══════════════════════════════════════════════════════════════

class MarketTaskStatus(Enum):
    POSTED = "posted"
    BIDDING = "bidding"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class MarketTask:
    """A task posted on the agent task market."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    base_reward: float = 10.0          # Base reward (reputation points or credits)
    complexity: float = 0.5            # 0.0–1.0 difficulty
    deadline: float = 0.0              # Absolute deadline timestamp (0 = none)
    status: MarketTaskStatus = MarketTaskStatus.POSTED
    winner_id: Optional[str] = None
    winning_bid: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.deadline > 0 and time.time() > self.deadline


@dataclass
class Bid:
    """An agent's bid on a market task."""
    bid_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_id: str = ""
    task_id: str = ""
    amount: float = 0.0               # How much the agent "charges"
    estimated_time: float = 60.0       # Estimated completion time (seconds)
    confidence: float = 0.5            # 0.0–1.0 agent's confidence
    capability_match: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def effective_score(self) -> float:
        """Composite score: lower amount + higher confidence + faster = better."""
        time_factor = max(1.0, 120.0 / max(self.estimated_time, 1.0))
        return self.confidence * self.capability_match * time_factor / max(self.amount, 0.01)


class TaskMarket:
    """Decentralized task market where agents bid for work."""

    def __init__(self, auction_timeout: float = 30.0):
        self.auction_timeout = auction_timeout
        self._tasks: Dict[str, MarketTask] = {}
        self._bids: Dict[str, List[Bid]] = {}         # task_id -> bids
        self._lock = threading.Lock()
        self._market_history: deque = deque(maxlen=500)

    def post_task(self, description: str, required_capabilities: List[str] = None,
                  base_reward: float = 10.0, complexity: float = 0.5,
                  deadline: float = 0.0, **metadata) -> MarketTask:
        """Post a new task to the market. Agents will bid on it."""
        task = MarketTask(
            description=description,
            required_capabilities=required_capabilities or [],
            base_reward=base_reward,
            complexity=complexity,
            deadline=deadline,
            metadata=metadata,
        )
        with self._lock:
            self._tasks[task.task_id] = task
            self._bids[task.task_id] = []
            task.status = MarketTaskStatus.BIDDING
        logger.info("Task posted to market: %s (reward=%.1f, caps=%s)",
                     task.task_id, base_reward, task.required_capabilities)
        return task

    def place_bid(self, task_id: str, agent_id: str, amount: float,
                  estimated_time: float = 60.0, confidence: float = 0.5,
                  capability_match: float = 0.0) -> Optional[Bid]:
        """An agent places a bid on a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != MarketTaskStatus.BIDDING:
                return None
            if task.is_expired():
                task.status = MarketTaskStatus.EXPIRED
                return None

            bid = Bid(
                agent_id=agent_id,
                task_id=task_id,
                amount=amount,
                estimated_time=estimated_time,
                confidence=confidence,
                capability_match=capability_match,
            )
            self._bids[task_id].append(bid)
            logger.debug("Bid placed: %s on %s (amount=%.1f, score=%.2f)",
                          agent_id, task_id, amount, bid.effective_score)
        return bid

    def resolve_auction(self, task_id: str,
                        strategy: str = "best_score") -> Optional[Bid]:
        """Close the auction and pick a winner.

        Strategies:
          - "best_score": highest effective_score (default)
          - "lowest_bid": cheapest bid
          - "fastest": shortest estimated time
          - "weighted_random": random selection weighted by score
        """
        with self._lock:
            task = self._tasks.get(task_id)
            bids = self._bids.get(task_id, [])

            if not task or not bids:
                return None

            if strategy == "lowest_bid":
                winner = min(bids, key=lambda b: b.amount)
            elif strategy == "fastest":
                winner = min(bids, key=lambda b: b.estimated_time)
            elif strategy == "weighted_random":
                scores = [b.effective_score for b in bids]
                total = sum(scores) or 1.0
                weights = [s / total for s in scores]
                winner = random.choices(bids, weights=weights, k=1)[0]
            else:  # best_score
                winner = max(bids, key=lambda b: b.effective_score)

            task.winner_id = winner.agent_id
            task.winning_bid = winner.amount
            task.status = MarketTaskStatus.ASSIGNED

            self._market_history.append({
                "task_id": task_id,
                "winner": winner.agent_id,
                "amount": winner.amount,
                "num_bids": len(bids),
                "timestamp": time.time(),
            })

            logger.info("Auction resolved: %s -> %s (amount=%.1f, %d bids)",
                         task_id, winner.agent_id, winner.amount, len(bids))
            return winner

    def complete_task(self, task_id: str):
        """Mark a task as completed."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = MarketTaskStatus.COMPLETED

    def cancel_task(self, task_id: str):
        """Cancel a task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = MarketTaskStatus.CANCELLED

    def get_active_auctions(self) -> List[MarketTask]:
        return [t for t in self._tasks.values()
                if t.status == MarketTaskStatus.BIDDING]

    def get_agent_bids(self, agent_id: str) -> List[Bid]:
        result = []
        for bids in self._bids.values():
            result.extend(b for b in bids if b.agent_id == agent_id)
        return result

    def get_market_stats(self) -> dict:
        with self._lock:
            tasks = list(self._tasks.values())
            return {
                "total_tasks": len(tasks),
                "active_auctions": sum(1 for t in tasks if t.status == MarketTaskStatus.BIDDING),
                "assigned": sum(1 for t in tasks if t.status == MarketTaskStatus.ASSIGNED),
                "completed": sum(1 for t in tasks if t.status == MarketTaskStatus.COMPLETED),
                "total_bids": sum(len(b) for b in self._bids.values()),
                "avg_bids_per_task": (
                    sum(len(b) for b in self._bids.values()) / max(len(self._bids), 1)
                ),
            }


# ═══════════════════════════════════════════════════════════════
# Feature 4: Self-Organizing Topology
# ═══════════════════════════════════════════════════════════════

class TopologyType(Enum):
    MESH = "mesh"             # Fully connected (or near)
    RING = "ring"             # Circular
    STAR = "star"             # Hub-and-spoke
    TREE = "tree"             # Hierarchical
    SMALL_WORLD = "small_world"  # Watts-Strogatz inspired
    SCALE_FREE = "scale_free"    # Barabási-Albert inspired
    KADEMLIA = "kademlia"        # DHT-based (XOR distance)


@dataclass
class TopologyNode:
    """A node in the swarm topology graph."""
    agent_id: str
    neighbors: Set[str] = field(default_factory=set)
    position: Tuple[float, float] = (0.0, 0.0)   # Virtual coordinates
    degree: int = 0
    betweenness: float = 0.0
    cluster_coefficient: float = 0.0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "neighbors": list(self.neighbors),
            "degree": self.degree,
            "betweenness": round(self.betweenness, 3),
            "cluster_coefficient": round(self.cluster_coefficient, 3),
        }


@dataclass
class TopologyConfig:
    """Configuration for the self-organizing topology."""
    topology_type: TopologyType = TopologyType.SMALL_WORLD
    max_neighbors: int = 8
    rewire_probability: float = 0.1              # For small-world
    latency_weight: float = 0.4                  # Weight of latency in edges
    load_weight: float = 0.3                     # Weight of load balancing
    affinity_weight: float = 0.3                 # Weight of role affinity
    optimization_interval: float = 30.0           # Seconds between re-optimizations
    random_seed: Optional[int] = None


class SelfOrganizingTopology:
    """Self-organizing network topology that adapts based on latency, load, and affinity."""

    def __init__(self, config: TopologyConfig = None):
        self.config = config or TopologyConfig()
        self._nodes: Dict[str, TopologyNode] = {}
        self._edges: Dict[Tuple[str, str], float] = {}   # (a, b) -> weight
        self._lock = threading.Lock()
        self._last_optimization: float = 0.0
        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)

    def add_agent(self, agent_id: str, position: Tuple[float, float] = None):
        """Add a new agent to the topology."""
        with self._lock:
            if agent_id not in self._nodes:
                self._nodes[agent_id] = TopologyNode(
                    agent_id=agent_id,
                    position=position or (random.random(), random.random()),
                )
                logger.debug("Topology: added agent %s", agent_id)
                # Auto-connect based on topology type
                self._auto_connect(agent_id)

    def remove_agent(self, agent_id: str):
        """Remove an agent from the topology."""
        with self._lock:
            node = self._nodes.pop(agent_id, None)
            if node:
                # Remove all edges involving this agent
                to_remove = [
                    (a, b) for (a, b) in self._edges
                    if a == agent_id or b == agent_id
                ]
                for edge in to_remove:
                    self._edges.pop(edge, None)
                # Remove from neighbors
                for neighbor_id in node.neighbors:
                    neighbor = self._nodes.get(neighbor_id)
                    if neighbor:
                        neighbor.neighbors.discard(agent_id)
                logger.debug("Topology: removed agent %s", agent_id)

    def _auto_connect(self, agent_id: str):
        """Automatically connect a new agent based on topology type."""
        node = self._nodes[agent_id]
        existing = [aid for aid in self._nodes if aid != agent_id]

        if self.config.topology_type == TopologyType.MESH:
            # Connect to all (up to max_neighbors)
            for other in existing[:self.config.max_neighbors]:
                if len(node.neighbors) >= self.config.max_neighbors:
                    break
                self._connect(agent_id, other)

        elif self.config.topology_type == TopologyType.RING:
            # Connect to immediate left and right neighbors
            if existing:
                sorted_ids = sorted([agent_id] + existing)
                idx = sorted_ids.index(agent_id)
                left = sorted_ids[(idx - 1) % len(sorted_ids)]
                right = sorted_ids[(idx + 1) % len(sorted_ids)]
                if left != agent_id:
                    self._connect(agent_id, left)
                if right != agent_id:
                    self._connect(agent_id, right)

        elif self.config.topology_type == TopologyType.STAR:
            # If first agent, it becomes the hub
            if existing:
                hub = min(existing)  # Lowest ID is hub
                self._connect(agent_id, hub)

        elif self.config.topology_type == TopologyType.SMALL_WORLD:
            # Connect to nearest neighbors, then random rewiring
            nearest = sorted(
                existing,
                key=lambda aid: self._distance(node, self._nodes[aid]),
            )[:self.config.max_neighbors]
            for other in nearest:
                self._connect(agent_id, other)
            # Random shortcuts
            if existing and random.random() < self.config.rewire_probability:
                far = random.choice(existing)
                self._connect(agent_id, far)

        elif self.config.topology_type == TopologyType.SCALE_FREE:
            # Preferential attachment: higher-degree nodes more likely
            if existing:
                weights = [self._nodes[e].degree + 1 for e in existing]
                total = sum(weights) or 1
                probs = [w / total for w in weights]
                targets = random.choices(existing, weights=probs,
                                         k=min(self.config.max_neighbors, len(existing)))
                for other in targets:
                    self._connect(agent_id, other)

        elif self.config.topology_type == TopologyType.KADEMLIA:
            # XOR-distance based: connect to "closest" by ID
            def xor_dist(aid: str) -> int:
                return int(aid, 16) ^ int(agent_id, 16) if aid.replace('a','').replace('f','').isdigit() else abs(hash(aid) ^ hash(agent_id)) % 100000
            nearest = sorted(existing, key=xor_dist)[:self.config.max_neighbors]
            for other in nearest:
                self._connect(agent_id, other)

    def _connect(self, a: str, b: str):
        """Create a bidirectional edge between two agents."""
        if a == b:
            return
        edge = tuple(sorted((a, b)))
        node_a = self._nodes.get(a)
        node_b = self._nodes.get(b)
        if not node_a or not node_b:
            return
        if len(node_a.neighbors) >= self.config.max_neighbors * 2:
            return
        if len(node_b.neighbors) >= self.config.max_neighbors * 2:
            return

        node_a.neighbors.add(b)
        node_b.neighbors.add(a)
        node_a.degree = len(node_a.neighbors)
        node_b.degree = len(node_b.neighbors)
        self._edges[edge] = 1.0  # Default weight

    @staticmethod
    def _distance(a: TopologyNode, b: TopologyNode) -> float:
        return math.hypot(a.position[0] - b.position[0], a.position[1] - b.position[1])

    def optimize(self, agents: List[SwarmAgent]):
        """Run one optimization pass: adjust edges based on latency, load, affinity.

        Called periodically (e.g., every optimization_interval seconds).
        """
        now = time.time()
        if now - self._last_optimization < self.config.optimization_interval:
            return
        self._last_optimization = now

        agent_map: Dict[str, SwarmAgent] = {a.agent_id: a for a in agents}

        with self._lock:
            # Update edge weights
            for (a, b) in list(self._edges.keys()):
                ag_a = agent_map.get(a)
                ag_b = agent_map.get(b)
                if not ag_a or not ag_b:
                    continue

                # Latency component (lower is better)
                lat = max(ag_a.latency_ms, ag_b.latency_ms)
                lat_score = 1.0 / max(lat / 10.0, 1.0) if lat > 0 else 1.0

                # Load component (lower load is better for connection)
                load_score = 1.0 - (ag_a.load + ag_b.load) / 2.0

                # Affinity: same roles or tags
                role_a = ag_a.effective_role.role_type.value if ag_a.effective_role else ""
                role_b = ag_b.effective_role.role_type.value if ag_b.effective_role else ""
                tag_overlap = len(ag_a.tags & ag_b.tags) / max(len(ag_a.tags | ag_b.tags), 1)
                role_match = 1.0 if role_a == role_b and role_a else 0.3
                affinity = (role_match + tag_overlap) / 2.0

                # Composite weight
                w_config = self.config
                weight = (
                    w_config.latency_weight * lat_score +
                    w_config.load_weight * load_score +
                    w_config.affinity_weight * affinity
                )
                self._edges[(a, b)] = weight

            # Prune weak edges (below 0.2) if both nodes have enough neighbors
            to_prune = []
            for (a, b), w in self._edges.items():
                if w < 0.2:
                    node_a = self._nodes.get(a)
                    node_b = self._nodes.get(b)
                    if node_a and len(node_a.neighbors) > 2 and node_b and len(node_b.neighbors) > 2:
                        to_prune.append((a, b))

            for (a, b) in to_prune:
                self._edges.pop((a, b), None)
                na = self._nodes.get(a)
                nb = self._nodes.get(b)
                if na: na.neighbors.discard(b); na.degree = len(na.neighbors)
                if nb: nb.neighbors.discard(a); nb.degree = len(nb.neighbors)
                logger.debug("Topology: pruned edge %s <-> %s (weight=%.2f)", a, b, self._edges.get((a, b), 0))

            # Compute metrics
            self._recompute_metrics()

            logger.debug("Topology: optimized — %d nodes, %d edges",
                          len(self._nodes), len(self._edges))

    def _recompute_metrics(self):
        """Recompute degree, betweenness, and clustering coefficients."""
        for node in self._nodes.values():
            node.degree = len(node.neighbors)
            # Simple clustering coefficient
            if node.degree >= 2:
                neighbors = list(node.neighbors)
                edges_between = sum(
                    1 for i in range(len(neighbors))
                    for j in range(i + 1, len(neighbors))
                    if tuple(sorted((neighbors[i], neighbors[j]))) in self._edges
                )
                max_edges = node.degree * (node.degree - 1) / 2
                node.cluster_coefficient = edges_between / max_edges if max_edges > 0 else 0.0
            else:
                node.cluster_coefficient = 0.0

    def get_neighbors(self, agent_id: str) -> List[str]:
        """Get an agent's immediate neighbors."""
        node = self._nodes.get(agent_id)
        return list(node.neighbors) if node else []

    def find_path(self, source: str, target: str) -> Optional[List[str]]:
        """BFS shortest path between two agents in the topology."""
        if source == target:
            return [source]
        if source not in self._nodes or target not in self._nodes:
            return None

        visited = {source}
        parent: Dict[str, Optional[str]] = {source: None}
        queue = deque([source])

        while queue:
            current = queue.popleft()
            if current == target:
                break
            for neighbor in self._nodes[current].neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    parent[neighbor] = current
                    queue.append(neighbor)

        if target not in parent:
            return None

        # Reconstruct path
        path = [target]
        while path[-1] != source:
            path.append(parent[path[-1]])
        path.reverse()
        return path

    def get_diameter(self) -> int:
        """Estimate the network diameter (longest shortest path)."""
        max_dist = 0
        for source in self._nodes:
            for target in self._nodes:
                path = self.find_path(source, target)
                if path and len(path) - 1 > max_dist:
                    max_dist = len(path) - 1
        return max_dist

    def get_topology_stats(self) -> dict:
        """Return summary statistics of the current topology."""
        with self._lock:
            total_nodes = len(self._nodes)
            total_edges = len(self._edges)
            degrees = [n.degree for n in self._nodes.values()]
            avg_degree = sum(degrees) / max(total_nodes, 1)
            clustering = [n.cluster_coefficient for n in self._nodes.values()]
            avg_clustering = sum(clustering) / max(total_nodes, 1)

            return {
                "topology_type": self.config.topology_type.value,
                "nodes": total_nodes,
                "edges": total_edges,
                "avg_degree": round(avg_degree, 2),
                "max_degree": max(degrees) if degrees else 0,
                "avg_clustering_coefficient": round(avg_clustering, 4),
                "diameter": self.get_diameter(),
                "last_optimized": self._last_optimization,
            }

    def render_topology_map(self) -> Dict[str, Any]:
        """Return a serializable representation of the topology for visualization."""
        with self._lock:
            return {
                "nodes": {
                    aid: node.to_dict()
                    for aid, node in self._nodes.items()
                },
                "edges": [
                    {"source": a, "target": b, "weight": round(w, 3)}
                    for (a, b), w in self._edges.items()
                ],
                "config": {
                    "type": self.config.topology_type.value,
                    "max_neighbors": self.config.max_neighbors,
                },
            }


# ═══════════════════════════════════════════════════════════════
# Main Class: AgentSwarmV2
# ═══════════════════════════════════════════════════════════════

class AgentSwarmV2:
    """v3.109 — Next-generation Agent Swarm with dynamic roles, consensus voting,
    task market bidding, and self-organizing topology.

    Usage:
        swarm = AgentSwarmV2()
        swarm.add_agent(SwarmAgent(name="Alice"))
        swarm.add_agent(SwarmAgent(name="Bob"))

        # Dynamic roles
        swarm.role_manager.assign_role(swarm.agents[0], RoleType.LEADER)

        # Consensus voting
        swarm.consensus.propose("p1", "Should we deploy?", strategy=ConsensusStrategy.MAJORITY)
        swarm.consensus.cast_vote("p1", "alice", "yes", weight=1.0)
        result = swarm.consensus.tally("p1")

        # Task market
        task = swarm.market.post_task("Process batch #42", required_capabilities=["compute"])
        swarm.market.place_bid(task.task_id, "bob", amount=5.0, confidence=0.9)
        winner = swarm.market.resolve_auction(task.task_id)

        # Topology
        swarm.topology.add_agent("alice")
        swarm.topology.add_agent("bob")
        swarm.topology.optimize(swarm.agents)
    """

    def __init__(self, swarm_id: str = None,
                 topology_config: TopologyConfig = None):
        self.swarm_id = swarm_id or str(uuid.uuid4())[:8]
        self.agents: List[SwarmAgent] = []
        self._agent_index: Dict[str, SwarmAgent] = {}
        self._lock = threading.Lock()

        # Subsystems
        self.role_manager = DynamicRoleManager()
        self.consensus = ConsensusEngine()
        self.market = TaskMarket()
        self.topology = SelfOrganizingTopology(topology_config)

        # Lifecycle
        self._running = False
        self._created_at = time.time()

        logger.info("AgentSwarmV2 created: %s", self.swarm_id)

    # ── Agent Lifecycle ──────────────────────────────────────

    def add_agent(self, agent: SwarmAgent) -> SwarmAgent:
        """Add an agent to the swarm."""
        with self._lock:
            if agent.agent_id in self._agent_index:
                # Update existing
                existing = self._agent_index[agent.agent_id]
                existing.name = agent.name or existing.name
                existing.tags |= agent.tags
                existing.last_seen = time.time()
                return existing

            self.agents.append(agent)
            self._agent_index[agent.agent_id] = agent
            self.topology.add_agent(agent.agent_id)

            logger.info("Agent added to swarm: %s (%s)", agent.name or agent.agent_id, agent.agent_id)
            return agent

    def remove_agent(self, agent_id: str) -> Optional[SwarmAgent]:
        """Remove an agent from the swarm."""
        with self._lock:
            agent = self._agent_index.pop(agent_id, None)
            if agent:
                self.agents = [a for a in self.agents if a.agent_id != agent_id]
                self.topology.remove_agent(agent_id)
                logger.info("Agent removed from swarm: %s", agent_id)
            return agent

    def get_agent(self, agent_id: str) -> Optional[SwarmAgent]:
        return self._agent_index.get(agent_id)

    def get_agents_by_role(self, role_type: RoleType) -> List[SwarmAgent]:
        """Get all agents currently holding a specific role."""
        return [
            a for a in self.agents
            if a.effective_role and a.effective_role.role_type == role_type
        ]

    def get_agents_by_capability(self, capability: str) -> List[SwarmAgent]:
        """Get all agents with a specific capability in their current role."""
        result = []
        for agent in self.agents:
            if agent.effective_role and agent.effective_role.has_capability(capability):
                result.append(agent)
        return result

    # ── Operations ──────────────────────────────────────────

    def ping_agent(self, agent_id: str):
        """Update an agent's last_seen timestamp."""
        agent = self._agent_index.get(agent_id)
        if agent:
            agent.last_seen = time.time()

    def prune_stale_agents(self, timeout: float = 120.0) -> List[str]:
        """Remove agents that haven't been seen within the timeout."""
        stale = [a.agent_id for a in self.agents if not a.is_alive(timeout)]
        for aid in stale:
            self.remove_agent(aid)
        if stale:
            logger.info("Pruned %d stale agents", len(stale))
        return stale

    def rebalance_roles(self, demand: Dict[RoleType, int]) -> Dict[str, AgentRole]:
        """Rebalance roles across the entire swarm based on demand."""
        self.role_manager.check_role_expiry(self.agents)
        return self.role_manager.rebalance_roles(self.agents, demand)

    def run_optimization_cycle(self):
        """Run one full optimization cycle (topology + role expiry)."""
        self.topology.optimize(self.agents)
        self.role_manager.check_role_expiry(self.agents)

    # ── Status & Reporting ──────────────────────────────────

    def get_swarm_status(self) -> dict:
        """Comprehensive swarm status report."""
        with self._lock:
            total = len(self.agents)
            alive = sum(1 for a in self.agents if a.is_alive())
            role_counts = defaultdict(int)
            for a in self.agents:
                if a.effective_role:
                    role_counts[a.effective_role.role_type.value] += 1

            avg_load = sum(a.load for a in self.agents) / max(total, 1)
            avg_reputation = sum(a.reputation for a in self.agents) / max(total, 1)

            return {
                "swarm_id": self.swarm_id,
                "agents_total": total,
                "agents_alive": alive,
                "role_distribution": dict(role_counts),
                "avg_load": round(avg_load, 2),
                "avg_reputation": round(avg_reputation, 2),
                "topology": self.topology.get_topology_stats(),
                "market": self.market.get_market_stats(),
                "uptime_seconds": round(time.time() - self._created_at, 1),
            }

    def get_detailed_status(self) -> dict:
        """Full status dump including agent details, market, topology map."""
        return {
            **self.get_swarm_status(),
            "agents": [a.to_dict() for a in self.agents],
            "topology_map": self.topology.render_topology_map(),
        }


# ═══════════════════════════════════════════════════════════════
# Singleton management
# ═══════════════════════════════════════════════════════════════

_swarm_v2_instance: Optional[AgentSwarmV2] = None
_swarm_v2_lock = threading.Lock()


def get_agent_swarm_v2() -> AgentSwarmV2:
    """Get or create the singleton AgentSwarmV2 instance."""
    global _swarm_v2_instance
    if _swarm_v2_instance is None:
        with _swarm_v2_lock:
            if _swarm_v2_instance is None:
                _swarm_v2_instance = AgentSwarmV2()
    return _swarm_v2_instance


def reset_agent_swarm_v2():
    """Reset the singleton AgentSwarmV2 (for testing)."""
    global _swarm_v2_instance
    with _swarm_v2_lock:
        _swarm_v2_instance = None
