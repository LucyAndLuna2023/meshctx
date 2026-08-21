<p align="center">
  <img src="docs/assets/logo.png" alt="MeshCtx" width="200">
  <h1 align="center">🧠 MeshCtx v3.116.0</h1>
  <h3 align="center">全脑仿真自进化AI Agent · SDM突破性记忆 · 自修改代码 · 17脑区 · 14模块</h3>
  <h3 align="center">Brain-Inspired Self-Evolving AI Agent Platform</h3>
</p>

<p align="center">
  <a href="LEGAL.md"><img src="https://img.shields.io/badge/license-AGPLv3+Commercial-blue"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-3404-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/modules-14-purple"></a>
  <a href="#"><img src="https://img.shields.io/badge/brain_regions-17-orange"></a>
  <a href="#"><img src="https://img.shields.io/badge/papers-3-blue"></a>
  <a href="https://github.com/LucyAndLuna2023/meshctx/stargazers"><img src="https://img.shields.io/github/stars/LucyAndLuna2023/meshctx?style=social"></a>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-why-meshctx">Why MeshCtx</a> ·
  <a href="#-core-features">Features</a> ·
  <a href="#-api">API</a> ·
  <a href="#-contributing">Contributing</a>
</p>

---

## 🌍 Why MeshCtx?

**Most AI agents are stateless tools. MeshCtx is a cognitive architecture.**

| Feature | Typical Agent | MeshCtx |
|---------|--------------|---------|
| Memory | Vector store lookup | Hippocampal replay + emotional weighting + pattern chunking |
| Planning | Single-pass chain | Free energy principle + active inference + thalamic gating |
| Self-improvement | None | Genomic optimizer (genetic algorithm on own parameters) |
| Code modification | Static | Neural plasticity-inspired self-modifying code at runtime |
| Architecture | Flat modules | 17 brain regions simulating cortical-subcortical loops |

MeshCtx treats AI agent design as a **neuroscience problem**, not just an engineering problem.

---

## 🔓 Open Source / Closed Core Architecture

| Repo | Visibility | Content |
|------|-----------|---------|
| **meshctx** (this repo) | 🔓 Public | Security modules (full impl) + core module **interface stubs** (signatures + docs) |
| **meshctx-core** | 🔒 Private | 33 core modules **full implementation** (AgentSwarm · Kernel · SuperBrain · Sandbox · MultiAgent · AutonomousEngine) |

**For developers**: `src/core/*.py` contains complete interface definitions. Use `from src.core.agent_swarm import AgentIdentity` for type-safe integration.

**Commercial**: `pip install meshctx-core` (private repo, license required) — zero code changes needed.

---

## 🚀 Quick Start

### Windows
```powershell
# Download installer (recommended)
# https://github.com/LucyAndLuna2023/meshctx/releases/latest
# meshctx-setup.exe — NSIS wizard, 7 languages, one-click install
```

### Linux / WSL / macOS
```bash
curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
meshctx setup    # Configure API keys
meshctx start    # Start web service (http://localhost:3001)
```

### From Source
```bash
git clone https://github.com/LucyAndLuna2023/meshctx.git
cd meshctx && pip install -e .
meshctx chat     # CLI mode
```

### Commands
```bash
meshctx start          # Web service (default http://localhost:3001)
meshctx chat           # CLI conversation
meshctx setup          # Configure API keys and models
meshctx desktop        # Windows desktop client
meshctx agent          # Multi-step autonomous agent
```

---

## 🧠 Core Features

### 🧬 GenomicOptimizer (v3.116) 🆕
Genetic algorithm that evolves agent's own parameters: temperature, top_p, prompt style, memory weights.
- Gaussian mutation · transposon-style jumps · crossover · elitist selection · niche protection
- ~784 lines, zero dependencies, thread-safe, outperforms manual tuning in ~10 generations

### 🔍 Observability Tracing (v3.116) 🆕
- Span/TraceLogger: llm · tool · chain full pipeline tracing
- Thread-safe (RLock) + optional JSONL disk export

### 🔄 RAG Query Rewriting + RRF Fusion (v3.116) 🆕
- Multi-path rewriting (synonym/sub-question/expansion) + Reciprocal Rank Fusion reranking

### 🛡️ Terminal Security Sandbox (v3.116) 🆕
- Session continuity + 3-tier danger classification (normal/dangerous/critical)
- Dangerous command interception, critical commands require approval

### 🧠 Brain-Inspired Cognitive Architecture
- **17 brain regions**: Free energy principle · active inference · global workspace · homeostasis
- **Hybrid reasoning**: Free energy-driven exploration vs fast-path decisions
- **SuperBrain**: Hippocampal replay · amygdala emotional tagging · default mode network · thalamic gating
- **Metacognition**: Self-evaluation · error classification · behavior adjustment

### 🧩 Human-Like Memory System (v2.40)
```
Traditional AI: Store → Keyword match
MeshCtx:       Pattern chunking → Emotional weighting → Hippocampal replay → Associative spread
```
- **Pattern chunking**: Compress raw data into meaning patterns (like a chess player recognizing formations)
- **Emotional weighting**: CRITICAL memories decay 200x slower than routine
- **Hippocampal replay**: Background 5-min cycle consolidates memories + discovers associations
- **Reconsolidation**: Each recall updates the memory (core human learning mechanism)
- **Associative spread**: Weighted link propagation (smell → scene → person → conversation)
- **Adaptive forgetting**: Forget details, keep patterns — forgetting is a feature, not a bug
- **FSRS spaced repetition** (phase-1): Per-memory stability/difficulty (D/S/R) state machine schedules every recall at the edge of forgetting — reviews land exactly when retrieval is about to fail, cutting injection tokens while maximizing retention
- **Active recall write-back**: Every hit + confirmation rewrites stability and re-schedules the next review (test-effect / retrieval practice theory); forgetful lapses are punished with a stability halving
- **CMA-ES self-tuning** (phase-1): Continuous parameters (temperature / top_p / memory weights / FSRS weights) optimized via covariance-matrix-adaptation evolution — replaces blind GA mutation with gradient-free global optimization

### 🐝 Agent Swarm — Manager-Worker Multi-Agent (v3.34)
```bash
meshctx start --port 3001  # Manager node

# Register worker on another machine
curl -X POST http://manager:3001/swarm/register \
  -d '{"worker_id":"bot1","name":"Coder","capabilities":["code"]}'

# Submit complex task — auto-decompose → dispatch → parallel execute
curl -X POST http://manager:3001/swarm/execute \
  -d '{"task":"Research best practices + write code + review","type":"research"}'
```
- Manager-Worker architecture with network + key-based coordination
- Auto task decomposition: research/code/analysis/report templates
- Identity auth: ed25519 + HMAC + 5-min anti-replay
- Collaboration: Delegate · Vote · Consensus · Ensemble

### 🌐 Multi-Platform Gateway (v2.39)
WeChat Enterprise · Feishu · Telegram · Slack · Discord · WhatsApp

### 📊 Usage Insights (v2.38)
Per day/week/month tracking: sessions · messages · tokens · latency · error rate

### 🔄 Credential Pool Rotation (v2.37)
Multi-API key rotation: round_robin · least_used · random · auto-exhaustion detection

---

## 📊 Version History

| Version | Highlights | Tests |
|---------|-----------|-------|
| v2.37 | Credential pool rotation | 825 |
| v2.40 | **Human-like memory** (6 mechanisms) | 916 |
| v2.41 | **Self-healing ops engine** | 935 |
| v2.42 | **Hooks engine** (8 events, Claude Code parity) | 956 |
| v3.115 | **DeepSeek TUI competitor** (14 modules, 4200 lines) | 130 |
| v3.116 | **Open-source agent framework** (RAG+RRF, Sandbox, GenomicOptimizer, Observability) | **3404** |

---

## 🏗️ Architecture

```
meshctx/
├── src/
│   ├── main.py              # FastAPI main app
│   ├── web_ui.py            # Web UI templates
│   ├── cli.py               # CLI commands
│   ├── i18n.py              # 10-language i18n
│   └── core/                # Core modules
│       ├── hybrid_reasoning.py  # Free energy reasoning
│       ├── observability.py     # Span/TraceLogger
│       ├── rag_orchestrator.py  # RAG + RRF fusion
│       ├── terminal_sandbox.py  # Security sandbox
│       ├── genomic_optimizer.py # Genetic algorithm engine
│       ├── memory_v5.py         # 4-tier memory injection
│       └── ...                  # 14 modules total
├── tests/                   # 3404 tests
├── docs/                    # Documentation site
└── install.sh               # One-click install
```

---

## 🔌 API

### Chat
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Conversation (JSON) |
| `/api/chat/stream` | POST | Streaming (SSE) |

### Dual Session (Planner-Executor)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dual/plan` | POST | Planner planning |
| `/api/dual/execute` | POST | Executor execution |
| `/api/dual/stats` | GET | Session stats |

### Memory
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/memory/stats` | GET | Memory diagnostics |
| `/api/memory/add` | POST | Add memory |
| `/api/memory/search` | POST | Search memories |

### Agent Swarm
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/swarm/register` | POST | Register worker |
| `/swarm/execute` | POST | Submit swarm task |
| `/swarm/status` | GET | Swarm status |

### Subagent
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/subagent/run` | POST | Launch isolated subagent |
| `/api/subagent/{id}/status` | GET | Query status |

---

## 🔒 Security

- **Secret scanning**: Auto-detect and redact API keys/tokens/PII
- **Hooks interception**: Block dangerous commands by default
- **Credential pool**: Key rotation prevents exhaustion
- **Approval modes**: YOLO / smart / manual three-tier

---

## 🌐 Platform Support

| Platform | Install | Status |
|----------|---------|--------|
| Windows | NSIS installer (10 languages) | ✅ |
| Linux | curl\|bash script | ✅ |
| macOS | DMG + Homebrew | ✅ |
| WSL | Same as Linux | ✅ |
| Docker | docker-compose | ⚠️ WIP |

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. **Fork** this repo
2. **Create** a feature branch: `git checkout -b feature/amazing-thing`
3. **Commit** with conventional commits: `feat: add thalamic gating filter`
4. **Test**: `python -m pytest tests/ -x`
5. **Push** and open a **Pull Request**

### Good First Issues
- 🧠 Add new brain region simulations
- 🔌 New platform gateway connectors
- 📊 Dashboard visualizations
- 🐛 Bug fixes and test coverage

### Development Setup
```bash
git clone https://github.com/LucyAndLuna2023/meshctx.git
cd meshctx
pip install -e ".[dev]"
python -m pytest tests/ -x
```

---

## 📄 License

- **Framework layer**: AGPLv3 Open Source
- **Core brain layer**: Source visible · Non-commercial free · Commercial license required
- Contact: license@meshctx.com

---

<p align="center">
  <b>⭐ Star this repo if you find it useful!</b><br>
  <sub>Built with 🧠 by <a href="https://github.com/LucyAndLuna2023">LucyAndLuna2023</a></sub>
</p>
