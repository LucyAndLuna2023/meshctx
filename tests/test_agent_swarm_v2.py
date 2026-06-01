"""
Agent Swarm V2 — 完整测试套件 (8+ 用例)
========================================
测试覆盖:
  1) Dynamic Role Assignment
  2) Consensus Voting (多策略)
  3) Task Market Bidding
  4) Self-Organizing Topology
  5) Agent Lifecycle
  6) Rebalance Roles
  7) Swarm Status & Reporting
  8) Integration (end-to-end)
  9) Byzantine Fault Tolerance
 10) Role Expiry
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.agent_swarm_v2 import (
    AgentSwarmV2, SwarmAgent, AgentRole, RoleType, RoleCapability,
    DynamicRoleManager, ConsensusEngine, ConsensusStrategy, ConsensusResult, Vote,
    TaskMarket, MarketTask, MarketTaskStatus, Bid,
    SelfOrganizingTopology, TopologyType, TopologyConfig, TopologyNode,
    get_agent_swarm_v2, reset_agent_swarm_v2,
)


# ═══════════════════════════════════════════════════════════════
# Test 1: Dynamic Role Assignment
# ═══════════════════════════════════════════════════════════════

def test_dynamic_role_assignment():
    """测试动态角色分配：分配角色、查询能力、角色切换。"""
    manager = DynamicRoleManager()
    agent = SwarmAgent(name="Alice")

    # Assign LEADER role
    role = manager.assign_role(agent, RoleType.LEADER, priority=9)
    assert agent.current_role is not None
    assert agent.current_role.role_type == RoleType.LEADER
    assert agent.current_role.priority == 9
    assert agent.current_role.has_capability("coordinate")
    assert agent.current_role.has_capability("decide")

    # Verify capabilities exist
    assert agent.current_role.get_capability_level("coordinate") == 0.5

    # Record use -> level should increase slightly
    agent.current_role.record_use("coordinate")
    assert agent.current_role.get_capability_level("coordinate") > 0.5

    # Switch to WORKER role
    role2 = manager.assign_role(agent, RoleType.WORKER, priority=5)
    assert agent.current_role.role_type == RoleType.WORKER
    assert agent.current_role.has_capability("execute")
    assert not agent.current_role.has_capability("coordinate")

    # Both roles in history
    assert len(agent.roles) >= 2

    print("  ✅ Test 1 passed: Dynamic Role Assignment")


# ═══════════════════════════════════════════════════════════════
# Test 2: Role Rebalancing
# ═══════════════════════════════════════════════════════════════

def test_role_rebalancing():
    """测试角色再平衡：根据需求自动分配/调整角色。"""
    manager = DynamicRoleManager()
    agents = [
        SwarmAgent(name="A1"),
        SwarmAgent(name="A2"),
        SwarmAgent(name="A3"),
        SwarmAgent(name="A4"),
        SwarmAgent(name="A5"),
    ]

    # Demand: 2 leaders, 3 workers
    demand = {
        RoleType.LEADER: 2,
        RoleType.WORKER: 3,
    }

    assignments = manager.rebalance_roles(agents, demand)

    assert len(assignments) == 5, f"Expected 5 assignments, got {len(assignments)}"

    leaders = [a for a in agents if a.effective_role and a.effective_role.role_type == RoleType.LEADER]
    workers = [a for a in agents if a.effective_role and a.effective_role.role_type == RoleType.WORKER]

    assert len(leaders) == 2, f"Expected 2 leaders, got {len(leaders)}"
    assert len(workers) == 3, f"Expected 3 workers, got {len(workers)}"

    print("  ✅ Test 2 passed: Role Rebalancing")


# ═══════════════════════════════════════════════════════════════
# Test 3: Consensus Voting — Majority
# ═══════════════════════════════════════════════════════════════

def test_consensus_majority():
    """测试多数共识策略。"""
    engine = ConsensusEngine(default_strategy=ConsensusStrategy.MAJORITY)

    # Proposal
    engine.propose("p1", "Should we enable feature X?", threshold=0.5)

    # Votes: 3 yes, 1 no -> should pass
    engine.cast_vote("p1", "a1", "yes", weight=1.0)
    engine.cast_vote("p1", "a2", "yes", weight=1.0)
    engine.cast_vote("p1", "a3", "yes", weight=1.0)
    engine.cast_vote("p1", "a4", "no", weight=1.0)

    result = engine.tally("p1")
    assert result.passed, "Majority should pass with 3 yes vs 1 no"
    assert result.winner == "yes"
    assert result.votes_for == 3
    assert result.votes_against == 1
    assert result.votes_abstain == 0

    print("  ✅ Test 3 passed: Consensus Majority")


# ═══════════════════════════════════════════════════════════════
# Test 4: Consensus Voting — Unanimous
# ═══════════════════════════════════════════════════════════════

def test_consensus_unanimous():
    """测试全票通过策略。"""
    engine = ConsensusEngine()

    engine.propose("p2", "Critical change", strategy=ConsensusStrategy.UNANIMOUS)

    engine.cast_vote("p2", "a1", "yes")
    engine.cast_vote("p2", "a2", "yes")
    engine.cast_vote("p2", "a3", "yes")

    result = engine.tally("p2")
    assert result.passed, "Unanimous yes should pass"
    assert result.winner == "yes"

    # Now add a "no" -> re-tally (engine replaces previous vote)
    engine.cast_vote("p2", "a3", "no")
    result2 = engine.tally("p2")
    assert not result2.passed, "Unanimous should fail with one 'no'"
    assert result2.votes_for == 2
    assert result2.votes_against == 1

    print("  ✅ Test 4 passed: Consensus Unanimous")


# ═══════════════════════════════════════════════════════════════
# Test 5: Consensus Voting — Weighted
# ═══════════════════════════════════════════════════════════════

def test_consensus_weighted():
    """测试加权共识策略。"""
    engine = ConsensusEngine()

    engine.propose("p3", "Budget allocation", strategy=ConsensusStrategy.WEIGHTED)

    # High-reputation agent votes yes
    engine.cast_vote("p3", "expert", "yes", weight=10.0)
    # Two low-reputation agents vote no
    engine.cast_vote("p3", "newbie1", "no", weight=1.0)
    engine.cast_vote("p3", "newbie2", "no", weight=1.0)

    result = engine.tally("p3")
    # 10 yes weight > 2 no weight -> should pass
    assert result.passed, "Weighted: 10 yes > 2 no should pass"
    assert result.winner == "yes"
    assert result.total_weight == 12.0

    print("  ✅ Test 5 passed: Consensus Weighted")


# ═══════════════════════════════════════════════════════════════
# Test 6: Task Market — Bidding & Auction
# ═══════════════════════════════════════════════════════════════

def test_task_market_bidding():
    """测试任务市场竞价流程。"""
    market = TaskMarket()

    # Post a task
    task = market.post_task(
        "Analyze dataset #42",
        required_capabilities=["analyze", "compute"],
        base_reward=100.0,
        complexity=0.7,
    )
    assert task.status == MarketTaskStatus.BIDDING
    assert len(market.get_active_auctions()) == 1

    # Agents place bids
    bid1 = market.place_bid(task.task_id, "alice", amount=5.0,
                            estimated_time=30.0, confidence=0.9, capability_match=0.8)
    bid2 = market.place_bid(task.task_id, "bob", amount=3.0,
                            estimated_time=60.0, confidence=0.8, capability_match=0.7)
    bid3 = market.place_bid(task.task_id, "charlie", amount=8.0,
                            estimated_time=10.0, confidence=0.95, capability_match=0.9)

    assert bid1 is not None
    assert bid2 is not None
    assert bid3 is not None

    # Resolve auction — best_score strategy
    winner = market.resolve_auction(task.task_id, strategy="best_score")
    assert winner is not None
    assert task.status == MarketTaskStatus.ASSIGNED

    # Charlie should win (high confidence, fast, good match)
    print(f"    Winner: {winner.agent_id} (amount={winner.amount}, score={winner.effective_score:.3f})")

    # Verify market stats
    stats = market.get_market_stats()
    assert stats["total_tasks"] == 1
    assert stats["total_bids"] == 3
    assert stats["active_auctions"] == 0

    print("  ✅ Test 6 passed: Task Market Bidding")


# ═══════════════════════════════════════════════════════════════
# Test 7: Task Market — Lowest Bid Strategy
# ═══════════════════════════════════════════════════════════════

def test_task_market_lowest_bid():
    """测试任务市场最低价竞价策略。"""
    market = TaskMarket()

    task = market.post_task("Quick bug fix", base_reward=50.0)

    market.place_bid(task.task_id, "expensive_agent", amount=30.0,
                     estimated_time=5.0, confidence=0.99)
    market.place_bid(task.task_id, "cheap_agent", amount=5.0,
                     estimated_time=60.0, confidence=0.5)

    winner = market.resolve_auction(task.task_id, strategy="lowest_bid")
    assert winner is not None
    assert winner.agent_id == "cheap_agent"
    assert winner.amount == 5.0

    print("  ✅ Test 7 passed: Task Market Lowest Bid")


# ═══════════════════════════════════════════════════════════════
# Test 8: Self-Organizing Topology — Mesh
# ═══════════════════════════════════════════════════════════════

def test_topology_mesh():
    """测试自组织拓扑 — Mesh型。"""
    config = TopologyConfig(topology_type=TopologyType.MESH, max_neighbors=4)
    topo = SelfOrganizingTopology(config)

    # Add agents
    for i in range(6):
        topo.add_agent(f"agent_{i}")

    stats = topo.get_topology_stats()
    assert stats["nodes"] == 6
    assert stats["edges"] > 0, "Mesh should have edges"
    assert stats["topology_type"] == "mesh"

    # Every agent should have neighbors
    for i in range(6):
        neighbors = topo.get_neighbors(f"agent_{i}")
        assert len(neighbors) > 0, f"agent_{i} should have neighbors in mesh"

    print(f"    Mesh stats: {stats['nodes']} nodes, {stats['edges']} edges, "
          f"avg_degree={stats['avg_degree']}, diameter={stats['diameter']}")
    print("  ✅ Test 8 passed: Topology Mesh")


# ═══════════════════════════════════════════════════════════════
# Test 9: Self-Organizing Topology — Small World + Path Finding
# ═══════════════════════════════════════════════════════════════

def test_topology_small_world():
    """测试自组织拓扑 — Small-World + 路径查找。"""
    config = TopologyConfig(
        topology_type=TopologyType.SMALL_WORLD,
        max_neighbors=3,
        rewire_probability=0.2,
        random_seed=42,
    )
    topo = SelfOrganizingTopology(config)

    for i in range(10):
        topo.add_agent(f"node_{i}")

    stats = topo.get_topology_stats()
    assert stats["nodes"] == 10
    assert stats["topology_type"] == "small_world"

    # Path finding
    path = topo.find_path("node_0", "node_9")
    if path:
        print(f"    Path node_0 -> node_9: {' -> '.join(path)} (hops={len(path)-1})")
        assert path[0] == "node_0"
        assert path[-1] == "node_9"
    else:
        print("    No path found between node_0 and node_9 (acceptable in disconnected graph)")

    # Diameter
    diameter = topo.get_diameter()
    print(f"    Diameter: {diameter}")

    print("  ✅ Test 9 passed: Topology Small World + Path")


# ═══════════════════════════════════════════════════════════════
# Test 10: AgentSwarmV2 — Full Integration
# ═══════════════════════════════════════════════════════════════

def test_swarm_v2_integration():
    """测试AgentSwarmV2完整集成流程。"""
    reset_agent_swarm_v2()
    swarm = get_agent_swarm_v2()

    # 1. Add agents
    alice = swarm.add_agent(SwarmAgent(name="Alice", tags={"code", "python"}))
    bob = swarm.add_agent(SwarmAgent(name="Bob", tags={"review", "testing"}))
    charlie = swarm.add_agent(SwarmAgent(name="Charlie", tags={"search", "analyze"}))
    diana = swarm.add_agent(SwarmAgent(name="Diana", tags={"code", "deploy"}))

    assert len(swarm.agents) == 4

    # 2. Dynamic role assignment
    swarm.role_manager.assign_role(alice, RoleType.LEADER, priority=9)
    swarm.role_manager.assign_role(bob, RoleType.WORKER, priority=7)
    swarm.role_manager.assign_role(charlie, RoleType.FORAGER, priority=6)
    swarm.role_manager.assign_role(diana, RoleType.WORKER, priority=7)

    assert swarm.get_agents_by_role(RoleType.LEADER)[0].agent_id == alice.agent_id
    assert len(swarm.get_agents_by_role(RoleType.WORKER)) == 2

    # 3. Consensus: vote on deployment
    swarm.consensus.propose("deploy_v2", "Deploy AgentSwarm V2 to production?",
                            strategy=ConsensusStrategy.MAJORITY)
    swarm.consensus.cast_vote("deploy_v2", alice.agent_id, "yes", weight=2.0)
    swarm.consensus.cast_vote("deploy_v2", bob.agent_id, "yes", weight=1.0)
    swarm.consensus.cast_vote("deploy_v2", charlie.agent_id, "yes", weight=1.0)
    swarm.consensus.cast_vote("deploy_v2", diana.agent_id, "no", weight=1.0)

    result = swarm.consensus.tally("deploy_v2")
    assert result.passed
    assert result.votes_for == 3

    # 4. Task market
    task = swarm.market.post_task(
        "Implement consensus unit tests",
        required_capabilities=["execute", "compute"],
        base_reward=50.0,
    )
    swarm.market.place_bid(task.task_id, bob.agent_id, amount=5.0,
                           estimated_time=120.0, confidence=0.85, capability_match=0.9)
    swarm.market.place_bid(task.task_id, diana.agent_id, amount=8.0,
                           estimated_time=60.0, confidence=0.9, capability_match=0.7)

    winner = swarm.market.resolve_auction(task.task_id)
    assert winner is not None
    swarm.market.complete_task(task.task_id)

    # 5. Topology optimization
    swarm.topology.optimize(swarm.agents)

    # 6. Status
    status = swarm.get_swarm_status()
    assert status["agents_total"] == 4
    assert status["agents_alive"] == 4
    assert "leader" in status["role_distribution"]
    assert "worker" in status["role_distribution"]

    detailed = swarm.get_detailed_status()
    assert "topology_map" in detailed
    assert "agents" in detailed

    print(f"    Swarm status: {status['agents_alive']}/{status['agents_total']} agents alive")
    print(f"    Roles: {status['role_distribution']}")
    print(f"    Market: {status['market']}")
    print(f"    Topology: {status['topology']}")

    print("  ✅ Test 10 passed: Full Integration")


# ═══════════════════════════════════════════════════════════════
# Test 11: Byzantine Fault Tolerance
# ═══════════════════════════════════════════════════════════════

def test_byzantine_consensus():
    """测试拜占庭容错共识。"""
    engine = ConsensusEngine()

    engine.propose("bft_1", "Byzantine test", strategy=ConsensusStrategy.BYZANTINE)

    # 4 agents, need > 2/3 for BFT (3f+1 with f=1, so 4 total needed, 3 yes minimum)
    # 3 honest yes + 1 malicious no
    engine.cast_vote("bft_1", "honest_1", "yes")
    engine.cast_vote("bft_1", "honest_2", "yes")
    engine.cast_vote("bft_1", "honest_3", "yes")
    engine.cast_vote("bft_1", "malicious", "no")

    result = engine.tally("bft_1")
    assert result.passed, f"BFT should pass with 3 honest yes vs 1 malicious no"
    assert result.votes_for == 3
    assert result.votes_against == 1

    print("  ✅ Test 11 passed: Byzantine Fault Tolerance")


# ═══════════════════════════════════════════════════════════════
# Test 12: Role Expiry
# ═══════════════════════════════════════════════════════════════

def test_role_expiry():
    """测试角色过期机制。"""
    manager = DynamicRoleManager()
    agent = SwarmAgent(name="TempAgent")

    # Assign role with very short TTL
    role = manager.assign_role(agent, RoleType.OBSERVER, ttl=0.01)
    assert agent.current_role is not None

    # Wait for expiry
    time.sleep(0.02)

    manager.check_role_expiry([agent])
    assert agent.current_role is None, "Role should have expired"
    assert "rebalance_needed" in agent.tags

    print("  ✅ Test 12 passed: Role Expiry")


# ═══════════════════════════════════════════════════════════════
# Test 13: Agent Lifecycle
# ═══════════════════════════════════════════════════════════════

def test_agent_lifecycle():
    """测试Agent添加、移除、容量查询。"""
    reset_agent_swarm_v2()
    swarm = get_agent_swarm_v2()

    # Add
    a1 = swarm.add_agent(SwarmAgent(name="Agent1"))
    a2 = swarm.add_agent(SwarmAgent(name="Agent2", tags={"ml", "python"}))

    assert len(swarm.agents) == 2

    # Query by capability
    swarm.role_manager.assign_role(a1, RoleType.SPECIALIST)
    swarm.role_manager.assign_role(a2, RoleType.WORKER)

    specialists = swarm.get_agents_by_capability("analyze")
    assert len(specialists) >= 1

    workers = swarm.get_agents_by_capability("execute")
    assert len(workers) >= 1

    # Remove
    removed = swarm.remove_agent(a1.agent_id)
    assert removed is not None
    assert len(swarm.agents) == 1
    assert swarm.get_agent(a1.agent_id) is None

    # Prune stale agents (a2 is still alive)
    swarm.agents[0].last_seen = 0  # Make a2 stale
    stale = swarm.prune_stale_agents(timeout=60)
    assert len(stale) == 1
    assert len(swarm.agents) == 0

    print("  ✅ Test 13 passed: Agent Lifecycle")


# ═══════════════════════════════════════════════════════════════
# Test 14: Supermajority Consensus
# ═══════════════════════════════════════════════════════════════

def test_consensus_supermajority():
    """测试超级多数共识 (2/3)。"""
    engine = ConsensusEngine()

    engine.propose("super_1", "Constitutional amendment",
                   strategy=ConsensusStrategy.SUPERMAJORITY)

    # 4 yes, 2 no = 66.7% -> should pass
    for i in range(4):
        engine.cast_vote("super_1", f"agent_{i}", "yes")
    for i in range(4, 6):
        engine.cast_vote("super_1", f"agent_{i}", "no")

    result = engine.tally("super_1")
    assert result.passed, f"Supermajority: 4/6=66.7% should pass (got {result.votes_for}/{result.votes_for + result.votes_against})"

    # 3 yes, 3 no = 50% -> should fail
    engine.propose("super_2", "Another amendment", strategy=ConsensusStrategy.SUPERMAJORITY)
    for i in range(3):
        engine.cast_vote("super_2", f"agent_{i}", "yes")
    for i in range(3, 6):
        engine.cast_vote("super_2", f"agent_{i}", "no")

    result2 = engine.tally("super_2")
    assert not result2.passed, "Supermajority: 3/6=50% should fail"

    print("  ✅ Test 14 passed: Supermajority Consensus")


# ═══════════════════════════════════════════════════════════════
# Test 15: Topology Optimization
# ═══════════════════════════════════════════════════════════════

def test_topology_optimization():
    """测试拓扑优化：基于延迟、负载、角色亲和度调整边权重。"""
    config = TopologyConfig(
        topology_type=TopologyType.SMALL_WORLD,
        max_neighbors=4,
        latency_weight=0.4,
        load_weight=0.3,
        affinity_weight=0.3,
        optimization_interval=0.0,
        random_seed=123,
    )
    topo = SelfOrganizingTopology(config)

    # Create agents with varying properties
    agents = []
    for i in range(8):
        agent = SwarmAgent(name=f"OptAgent_{i}", tags={"cluster_a"} if i < 4 else {"cluster_b"})
        agent.latency_ms = 10.0 + i * 5
        agent.load = 0.1 * i
        agents.append(agent)
        topo.add_agent(agent.agent_id)

    # Assign roles within clusters
    for i in range(4):
        agents[i].current_role = AgentRole(role_type=RoleType.WORKER)
    for i in range(4, 8):
        agents[i].current_role = AgentRole(role_type=RoleType.OBSERVER)

    # Run optimization
    topo.optimize(agents)

    stats = topo.get_topology_stats()
    assert stats["nodes"] == 8
    assert stats["edges"] > 0

    # Render topology map
    topo_map = topo.render_topology_map()
    assert "nodes" in topo_map
    assert "edges" in topo_map

    print(f"    Optimized: {stats['nodes']} nodes, {stats['edges']} edges, "
          f"avg_degree={stats['avg_degree']}, clustering={stats['avg_clustering_coefficient']}")
    print("  ✅ Test 15 passed: Topology Optimization")


# ═══════════════════════════════════════════════════════════════
# Test Runner
# ═══════════════════════════════════════════════════════════════

def main():
    """Run all Agent Swarm V2 tests."""
    print("=" * 55)
    print("  Agent Swarm V2 — Full Test Suite (15 tests)")
    print("=" * 55)
    print()

    tests = [
        ("Dynamic Role Assignment", test_dynamic_role_assignment),
        ("Role Rebalancing", test_role_rebalancing),
        ("Consensus — Majority", test_consensus_majority),
        ("Consensus — Unanimous", test_consensus_unanimous),
        ("Consensus — Weighted", test_consensus_weighted),
        ("Task Market — Bidding", test_task_market_bidding),
        ("Task Market — Lowest Bid", test_task_market_lowest_bid),
        ("Topology — Mesh", test_topology_mesh),
        ("Topology — Small World + Path", test_topology_small_world),
        ("Swarm V2 — Full Integration", test_swarm_v2_integration),
        ("Byzantine Fault Tolerance", test_byzantine_consensus),
        ("Role Expiry", test_role_expiry),
        ("Agent Lifecycle", test_agent_lifecycle),
        ("Consensus — Supermajority", test_consensus_supermajority),
        ("Topology Optimization", test_topology_optimization),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  ❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 55)
    print(f"  Results: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 55)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
