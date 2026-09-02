# meshctx vs Competition — Honest Comparison v3.0

> Last updated: 2026-07-04
> Methodology: Public docs + GitHub repos + announced benchmarks
> "Unverified" = claim exists but no third-party reproduction

---

## Core vs Adjacent Competitors

### Tier 1: Direct Coding Agent Competitors

| Capability | meshctx | Claude Code | Cursor Agent | GitHub Copilot |
|------------|---------|-------------|--------------|----------------|
| **MCP Protocol** | ✅ Native (mcp_integrator.py 133L) | ✅ Native (announced 2024.11) | ✅ Agent mode | ❌ |
| **Multi-Agent** | ✅ Manager-Worker swarm (agent_swarm.py 346L) | ❌ Single agent | ❌ | ❌ |
| **Hierarchical Memory** | ✅ memory_v5.py (512L) + forgetting curve | ❌ CLAUDE.md only | ❌ .cursorrules only | ❌ |
| **Self-Modifying Code** | ✅ self_modify.py (1347L, 7-stage pipeline) | ✅ Limited (file edits) | ❌ | ❌ |
| **Plugin Marketplace** | ✅ plugin_market.py (329L) | ❌ (uses MCP servers) | ✅ Extension market | ✅ Extension market |
| **Knowledge Graph** | 🚧 v2 stub | ❌ | ❌ | ❌ |
| **Code Sandbox** | ✅ sandbox.py (1033L) | ✅ Execution | ✅ Terminal | ❌ |
| **SWE-bench Lite** | 🚧 Target: >30% (harness exists, not yet run) | ~49%* (Claude 3.5) | Unverified | Unverified |
| **Brain Architecture** | ✅ 9-region model (brain_router.py 102L) | ❌ | ❌ | ❌ |
| **Offline Dreaming/Memory Consolidation** | ✅ dreaming_agent.py (727L) | ❌ | ❌ | ❌ |
| **Workflow Engine** | ✅ workflow_engine.py (649L) + workflow.py (863L) | ❌ | ❌ | ❌ |
| **Distributed Lock / Circuit Breaker** | ✅ distributed_lock.py (897L) + circuit_breaker.py (858L) | ❌ | ❌ | ❌ |
| **Open Source** | ✅ AGPLv3 | ❌ Proprietary | ❌ Proprietary | ❌ Proprietary |

*Claude Code SWE-bench score from Anthropic's own published benchmark results.

### Tier 2: Infrastructure / Bridge Tools

| Tool | Relationship to meshctx | Overlap |
|------|------------------------|---------|
| **OpenClaw** | Communication bridge (matrix→telegram→discord) | Minimal — meshctx uses hub protocol |
| **Hermes Agent** | Upstream framework (meshctx is a fork) | High — shares core but meshctx adds brain arch + benchmarking |
| **FreeEnergy Chat** | Spiritual predecessor | Concept only — meshctx is full reimplementation |

---

## STUB Modules (Planned, Not Yet Real)

These features appear in the comparison table but are currently auto-generated stubs:

| Feature | Module | Status | Target |
|---------|--------|--------|--------|
| Desktop Agent | desktop_agent.py (54L) | 🚧 STUB (desktop_tool.py is REAL) | v3.40 |
| Smart Permissions | smart_permissions.py (44L) | 🚧 STUB | v3.41 |
| JEPA Router | jepa_router.py (121L) | 🚧 STUB（基础路由已实现；预测式模型选择待完整版） | v3.41 |
| Knowledge Graph | knowledge_graph.py/v2 (50L each) | 🚧 STUB | v3.42 |
| SDB Framework | sdb_framework.py (50L) | 🚧 STUB | v3.42 |
| Attractor Reasoner | attractor_reasoner.py (48L) | 🚧 STUB | v3.43 |
| Meta-Cognition | metacognition.py (94L) | 🚧 STUB | v3.43 |

> **JEPA World Model（jepa_world_model.py 696L）已实测 ✅（不再 STUB）**——真实用途：**非生成式记忆预筛**。
> query 到达时**不开 LLM**，用 JEPA 潜空间（char-trigram 余弦）先捞 top-k 候选记忆，只对候选开 LLM。
> 实测（benchmarks/jepa/results/，LongMemEval oracle 数据）：
> - **30 条大池**（1 正 + 29 干扰）：recall@1 **18.3%** / recall@5 **56.7%** / MRR 0.36，**5.5× 于随机基线**（3.3%）
> - 含义：LLM 调用量可从 30 条降到 top-5（≈17%），仍保住 56.7% 召回——「决策 token≈0、省 30~35%」的量化机制
> - 完整 VICReg 训练权重在 meshctx-core 私有核心（开源版为 QR 正交投影 + char-ngram 基础模式）
| Predictive Pre-Compute | predictive_precompute.py (44L) | 🚧 STUB | v3.44 |
| Evolution Tracker | evolution_tracker.py (46L) | 🚧 STUB | v3.44 |

---

## Benchmark Data

### SWE-bench Lite

- **Harness**: swebench_harness_v2.py (RepoManager + real code injection)
- **Runner**: benchmarks/SWE-bench/run.py (calls official SWE-bench evaluation)
- **Status**: Infrastructure ready; dataset needs ~80GB disk, to be run on dedicated server
- **Target**: >30% resolve rate (conservative, verifiable)
- **Note**: 98.7% claim on homepage is aspirational. Real score will be published when harness completes.

### Self-Modification Benchmark

- **self_modify.py**: 1347 lines, 7-stage pipeline (Propose→Validate→Backup→Apply→Verify→Rollback→Audit)
- **Risk Levels**: 5 tiers (SAFE→CRITICAL), auto-approval for SAFE/LOW
- **Status**: ✅ Verified (QA audit passed, commit b9781ceb)

### Production Resilience

- **distributed_lock.py** (897L): Redis/etcd-backed distributed coordination
- **circuit_breaker.py** (858L): Fault isolation with half-open recovery
- **config_hot_reload.py** (928L): Zero-downtime config updates
- **feature_flags.py** (790L): Runtime feature gating
- **api_versioning.py** (786L): Multi-version API support

---

## Summary

| Category | REAL | STUB | % Complete |
|----------|------|------|------------|
| Core Engine (agent_loop, sandbox, approval) | 12 | 0 | 100% |
| Memory System | 3 | 2 | 60% |
| Multi-Agent | 5 | 0 | 100% |
| Brain Architecture | 2 | 4 | 33% |
| Advanced Inference | 4 | 6 | 40% |
| Production Ops | 8 | 0 | 100% |
| **TOTAL** | **34** | **12** | **74%** |
