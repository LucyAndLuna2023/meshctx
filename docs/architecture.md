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
- Kubernetes: Horizontal pod autoscaling

## Security

- Plugin sandboxing (optional subprocess isolation)
- Resource quotas per plugin
- Circuit breaker on failure storms
- Audit logging of all events
