<p align="center">
  <img src="https://raw.githubusercontent.com/meshctx/meshctx/main/docs/assets/logo.svg" alt="meshctx" width="180">
</p>

<h1 align="center">meshctx</h1>
<h3 align="center">World's First Self-Evolving Agent System</h3>

<p align="center">
  <a href="https://github.com/meshctx/meshctx/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://pypi.org/project/meshctx/"><img src="https://img.shields.io/badge/python-3.12%2B-green" alt="Python"></a>
  <a href="https://github.com/meshctx/meshctx/actions"><img src="https://img.shields.io/badge/build-passing-brightgreen" alt="Build"></a>
  <a href="https://discord.gg/meshctx"><img src="https://img.shields.io/badge/discord-join-7289da" alt="Discord"></a>
  <a href="https://github.com/meshctx/meshctx/stargazers"><img src="https://img.shields.io/github/stars/meshctx/meshctx?style=social" alt="Stars"></a>
</p>

---

> **meshctx** is an **open-source, self-evolving agent platform** that remembers everything, learns from every task, and orchestrates multiple AI agents in parallel — all with zero manual configuration.

## ⚖️ License — AGPL v3 · Free for Everyone

> MeshCtx is and always will be free — for individuals, startups, and enterprises. The core engine is open-source under AGPL v3. We make money from optional cloud services and enterprise support, never from the software itself.
>
> 📋 [Business Model](docs/BUSINESS.md) · 📄 [Legal](docs/LEGAL.md)

> **MeshCtx is and always will be free — for everyone. Individuals, startups, enterprises.**
>
> We compete on technology, not on price. Our revenue comes from [optional paid services](docs/BUSINESS.md) — cloud hosting, enterprise support, and premium plugins — never from charging for the software itself.

---

### Why meshctx?

| Feature | meshctx | Hermes | OpenClaw | Claude Cowork |
|---------|---------|--------|----------|---------------|
| **Hierarchical Memory (L0-L4)** | ✅ | ❌ | ❌ | ❌ |
| **Ebbinghaus Forgetting Curve** | ✅ | ❌ | ❌ | ❌ |
| **Meta-Cognition (Self-Learning)** | ✅ | ❌ | ❌ | ❌ |
| **Multi-Agent Orchestration** | ✅ | ❌ | ❌ | ⚠️ |
| **Predictive Context Preloading** | ✅ | ❌ | ❌ | ❌ |
| **Knowledge Graph** | ✅ | ❌ | ❌ | ❌ |
| **Plugin Marketplace** | ✅ | ❌ | ❌ | ❌ |
| **MCP Native** | ✅ | ✅ | ❌ | ❌ |
| **Open Source (MIT)** | ✅ | ✅ | ✅ | ❌ |

### 🧠 Hierarchical Memory That Thinks Like a Brain

meshctx uses a **4-tier memory system** modeled after human cognition, complete with the **Ebbinghaus Forgetting Curve** — information naturally decays over time unless reinforced.

```
L0: Sensory Memory    → Current conversation stream
L1: Working Memory    → Active task context (~10K tokens)
L2: Short-Term Memory → Last 7 days, natural decay
L3: Long-Term Memory  → All history, vector + graph retrieval
L4: Archival Memory   → Cross-project knowledge, auto-dedup
```

### 🔄 Self-Evolving via Meta-Cognition

After every task, meshctx automatically:

1. **Evaluates** — Success? Quality? What went wrong?
2. **Extracts Patterns** — Successful patterns become reusable Skills
3. **Updates Knowledge Graph** — New entities and relationships learned
4. **Adjusts Behavior** — Tool selection, parallelism, verification strategy

> *"The agent that gets better every time you use it."*

### 🎭 Multi-Agent Orchestra

One command. meshctx decomposes your intent into a **task DAG**, assigns specialized agents (Coder / Researcher / DevOps / Reviewer), and executes in parallel:

```python
# One intent, automatically decomposed and executed by 4 agents:
await orchestrator.execute("Deploy the new API with full test coverage")
```

### ⚡ Quick Start

```bash
# Install
pip install meshctx

# Start the kernel
meshctx start

# Or via Docker
docker run -d -p 8000:8000 meshctx/meshctx
```

### 📦 Architecture

```
┌──────────────────────────────────────────┐
│              meshctx Kernel               │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Event   │ │ Plugin   │ │ Resource  │  │
│  │ Bus     │ │ Manager  │ │ Governor  │  │
│  └────┬────┘ └────┬─────┘ └─────┬─────┘  │
│       │            │              │        │
│  ┌────┴────────────┴──────────────┴─────┐  │
│  │           Plugin Slots               │  │
│  │ [Memory] [Meta] [Orch] [Tools] ...  │  │
│  └──────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### 📚 Documentation

- [Getting Started](https://meshctx.dev/docs/getting-started)
- [Architecture Deep Dive](https://meshctx.dev/docs/architecture)
- [API Reference](https://meshctx.dev/docs/api)
- [Plugin Development](https://meshctx.dev/docs/plugins)
- [Competitive Analysis](https://meshctx.dev/docs/competition)

### 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### 📄 License

MIT © 2026 meshctx — Free forever, open forever.

---

<p align="center">
  <sub>Built with ❤️ by the meshctx community</sub>
</p>
