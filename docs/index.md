# meshctx — Auditable Self-Adaptive Agent System

## Overview

meshctx is an open-source, self-adaptive agent platform designed to be a capable, auditable AI agent system.

### What Makes meshctx Different?

**1. It Remembers Everything (Intelligently)**

Unlike other agents that forget everything after each session, meshctx uses a 4-tier hierarchical memory system modeled after human cognition. It applies the Ebbinghaus Forgetting Curve — important information persists, trivial information naturally decays.

**2. Adaptive Memory That Compounds**

meshctx ships an evolution engine (genetic-algorithm parameter tuning + meta-cognition reports) with API-controlled endpoints (evolve/feedback). Memory consolidation runs automatically between sessions; auto-feeding task outcomes into the optimizer and applying tuned parameters back to the runtime are on the roadmap. Successful patterns can be promoted into reusable Skills with user confirmation.

**3. It Orchestrates Multiple Agents**

One command. meshctx decomposes your intent into a task DAG, assigns specialized agents (Coder, Researcher, DevOps, Reviewer), and executes in parallel with full dependency resolution.

### Key Features

#### 🧠 Hierarchical Memory (L0-L4)
- **L0 Sensory**: Current conversation stream
- **L1 Working**: Active task context (~10K tokens)
- **L2 Short-term**: Last 7 days with natural decay
- **L3 Long-term**: All history, vector + graph retrieval
- **L4 Archival**: Cross-project knowledge, auto-dedup

#### 🔄 Meta-Cognition & Evolution Engine
- Metacognition module with self-evaluation reports (API: /metacognition/report)
- Evolution engine: genetic-algorithm parameter tuning via API (evolve/feedback)
- Memory consolidation runs automatically between sessions
- Auto-feeding task outcomes and parameter write-back: on the roadmap

#### 🎭 Multi-Agent Orchestra
- Intent decomposition into task DAGs
- Specialized agents: Coder, Researcher, DevOps, Reviewer
- Parallel execution with dependency resolution
- Shared Memory Hub for inter-agent communication

#### ⚡ Event-Driven Microkernel
- Plugin architecture with hot-swap support
- Priority event bus
- Resource governor (anti-OOM)
- Async throughout

#### 🔌 Extensible
- MCP protocol native
- pip/npm plugin marketplace
- Python/TypeScript/Rust SDKs
- Webhook ecosystem

### Architecture

```
                    User Intent
                         │
                         ▼
              ┌──────────────────┐
              │   Orchestrator    │  ← Decomposes into task DAG
              └────────┬─────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌─────────┐  ┌──────────┐  ┌──────────┐
    │  Coder  │  │Researcher│  │  DevOps  │
    │  Agent  │  │  Agent   │  │  Agent   │
    └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │
         └─────────────┼─────────────┘
                       ▼
              ┌──────────────────┐
              │   Memory Hub      │  ← Shared context
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ Meta-Cognition    │  ← Evaluates & learns
              └──────────────────┘
```

### Quick Start

```bash
# Install
pip install meshctx

# Start
meshctx start
```

### API (Port 8000)

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `POST /projects` | Create project |
| `POST /conversations` | Start conversation |
| `POST /messages` | Add message |
| `GET /projects/{id}/memories` | Get memories |
| `POST /search` | Vector search |
| `POST /orchestrator/execute` | Execute intent |

### Comparison

| Capability | meshctx | Hermes | OpenClaw | Cowork |
|-----------|---------|--------|----------|--------|
| Hierarchical Memory | ✅ L0-L4 | ❌ | ❌ | ❌ |
| Ebbinghaus Forgetting | ✅ | ❌ | ❌ | ❌ |
| Self-Learning | ✅ | ❌ | ❌ | ❌ |
| Multi-Agent | ✅ DAG | ❌ | ❌ | ⚠️ |
| Knowledge Graph | ✅ | ❌ | ❌ | ❌ |
| Plugin Market | ✅ | ❌ | ❌ | ❌ |
| MCP Protocol | ✅ | ✅ | ❌ | ❌ |
| Open Source | ✅ MIT | ✅ MIT | ✅ | ❌ |

### License

MIT — Free forever.
