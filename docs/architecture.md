# Architecture

## Overview

meshctx uses an **event-driven microkernel architecture** where every capability is a plugin communicating through a priority event bus.

```
┌─────────────────────────────────────────────────────────┐
│                    meshctx Kernel                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Event Bus   │  │   Plugin     │  │  Resource    │  │
│  │  (Priority   │  │   Manager    │  │  Governor    │  │
│  │   Queues)    │  │  (Hot-swap)  │  │  (Anti-OOM)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
│  ┌──────┴─────────────────┴──────────────────┴───────┐  │
│  │                  Plugin Registry                   │  │
│  │                                                    │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐          │  │
│  │  │  Memory  │ │  Meta-   │ │Orchestra-│  ...     │  │
│  │  │  Plugin  │ │Cognition │ │   tor    │          │  │
│  │  └──────────┘ └──────────┘ └──────────┘          │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Core Modules

### 0. 智能闭环集成层 (v1.6 新增)

三大闭环将独立脑启发模块融合为统一智能引擎:

```
OODA循环(agent_loop.py) — 主干
   │
   ├─ Orient阶段 → WorkspaceAwareAdapter → GlobalWorkspace.cycle()
   │     ├─ 7处理器竞争(analyst/creator/critic/executor/observer/memory/predictor)
   │     ├─ 意识点火检测(>0.75 activation → "aha moment")
   │     ├─ 认知状态注入 → observation.context["workspace"]
   │     └─ learn_from_outcome → processor_belief 更新
   │
   ├─ Orient阶段 → FreeEnergyPredictorAdapter
   │     ├─ TemporalPatternLearner → Dirichlet BeliefState
   │     ├─ 预测置信度 = expected_probability × precision_gate
   │     └─ → 发布 predictor.free_energy_prediction + context.preloaded
   │
   └─ Learn阶段 → MetaActiveInferenceAdapter
         ├─ TaskEvaluation → (success:bool, strength:float)
         ├─ → ActiveInferenceEngine.learn_from_outcome()
         ├─ BehaviorAdjuster → AI温度调节
         └─ → 发布 metacognition.ai_feedback
```

**关键类文件:**
- `FreeEnergyPredictorAdapter` in `predictor.py` — 预测×自由能桥接
- `MetaActiveInferenceAdapter` in `metacognition.py` — 元认知×主动推理桥接
- `WorkspaceAwareAdapter` in `agent_loop.py` — 工作空间×OODA桥接

### 1. Kernel (`src/core/kernel.py`)

The microkernel. Manages the event bus, plugin lifecycle, and resource allocation.

**Key components**:
- `EventBus`: Async priority-based publish/subscribe
- `PluginManager`: Plugin discovery, dependency resolution, hot-swap
- `ResourceGovernor`: Memory/CPU limits, circuit breaker pattern

### 2. Memory Hierarchy (`src/core/memory_hierarchy.py`)

4-tier memory system with Ebbinghaus Forgetting Curve.

```
Level │ Name        │ Capacity      │ Retention
──────┼─────────────┼───────────────┼──────────────
  L0  │ Sensory     │ ~100 messages │ Session only
  L1  │ Working     │ ~50 items     │ Task duration
  L2  │ Short-term  │ ~500 items    │ 7 days (decaying)
  L3  │ Long-term   │ Unlimited     │ Permanent (vector)
  L4  │ Archival    │ Compressed    │ Cross-project
```

**Retrieval**: Hybrid scoring:
```
FinalScore = 0.4*VectorSim + 0.3*Importance + 0.2*Recency + 0.1*AccessFreq
```

### 3. Meta-Cognition (`src/core/metacognition.py`)

Self-learning loop that runs after every task:

1. **Self-Evaluate**: Quality score (0-1), error categorization
2. **Pattern Extract**: Cluster similar tasks → create Skills
3. **Knowledge Update**: Update entity graph
4. **Behavior Adjust**: Tune strategy weights

### 4. Orchestrator (`src/core/orchestrator.py`)

Multi-agent coordination:

- **TaskDecomposer**: Intent → Task DAG
- **AgentPool**: Specialized agents (Coder/Researcher/DevOps/Reviewer)
- **MemoryHub**: Shared context for inter-agent communication
- **TaskDAG**: Dependency graph with parallel scheduling

## Event System

All communication is through typed events on the priority bus:

| Priority | Use Case |
|----------|----------|
| CRITICAL | System events (shutdown, health) |
| HIGH | User interactions |
| NORMAL | Business events |
| LOW | Background (logging, stats) |
| LAZY | Deferred (compaction, archival) |

### Key Events

| Event Type | Publisher | Subscribers |
|-----------|-----------|-------------|
| `message.added` | Gateway | Memory |
| `task.completed` | Orchestrator | MetaCognition |
| `orchestrator.execute` | API | Orchestrator |
| `memory.search` | Any | Memory |
| `plugin.loaded` | PluginManager | All |

## Data Flow

```
User Intent
    │
    ▼
Orchestrator.decompose()
    │
    ▼
TaskDAG ──► AgentPool.acquire()
    │             │
    ▼             ▼
Agent.execute()  MemoryHub.read()
    │
    ▼
Event: task.completed
    │
    ▼
MetaCognition.evaluate()
    │
    ▼
PatternEngine.extract()
    │
    ▼
BehaviorAdjuster.update()
```

## Performance

- **Context assembly**: < 50ms (L1 cache hit)
- **Memory retrieval**: < 10ms (vector index)
- **Event delivery**: < 1ms (in-process)
- **Plugin hot-swap**: < 100ms

## Scalability

- Single process: up to 100 concurrent agent sessions
- Multi-process: Redis event bus + shared memory
- Horizontal scaling: Multi-process with shared memory

## Security

- Plugin sandboxing (optional subprocess isolation)
- Resource quotas per plugin
- Circuit breaker on failure storms
- Audit logging of all events
