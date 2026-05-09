# Changelog

All notable changes to meshctx will be documented in this file.

## [1.0.0] - 2026-05-09

### Added
- **Microkernel Architecture**: Event-driven plugin system with priority event bus
- **Hierarchical Memory (L0-L4)**: 4-tier memory with Ebbinghaus Forgetting Curve
- **Meta-Cognition Engine**: Self-evaluation, pattern extraction, behavior adjustment
- **Multi-Agent Orchestrator**: Task DAG decomposition, specialized agent pool, Memory Hub
- **★ Predictive Engine**: Temporal pattern learning + context preloading (world's first)
- **★ Autonomous Agent Loop**: OODA cycle (Observe→Orient→Decide→Act→Learn) (world's first)
- **★ Performance Layer**: L1/L2 tiered cache, streaming response, latency monitoring
- **Hybrid Retrieval**: Vector + Knowledge Graph + Recency combined scoring
- **Resource Governor**: Per-plugin quotas, circuit breaker pattern
- **MCP Protocol**: Native Model Context Protocol support
- **RESTful API**: 30+ endpoints across 6 plugin domains
- **Web Dashboard**: Jinja2 templates for memory/project/continuity management (6 pages)
- **CLI Tool**: 13 commands (model/chat/skill/start/stop/status/evolve/web/cron/search/browser/tts/mcp)
- **62 Test Cases**: All passing with pytest-asyncio auto mode (48 old + 14 new)

### Changed
- Complete rewrite from v0.2.0 monolithic architecture to v1.0.0 microkernel
- Unified startup: Kernel auto-boots 6 core plugins (memory/meta/orch/predictor/agent/perf)
- FastAPI app integrated with v1.0 Kernel via on_event lifecycle

### Fixed
- pytest-asyncio integration (was missing, causing 39 async test failures)
- Test decorator collision (`test()` → `_test()`) preventing pytest collection
- Kernel not auto-starting in uvicorn (now uses @app.on_event lifecycle)
- Remote deployment: systemd service + Python-based file upload

---

## [0.2.0] - 2026-05-08

### Added
- FastAPI backend with project/conversation/message CRUD
- Basic memory management with LLM extraction
- Web UI dashboard with Jinja2 templates
- Cross-platform storage (Windows/Linux/macOS)
- Vector store with ChromaDB/numpy fallback
- Plugin system framework
- Docker and deployment scripts
- 8 pytest test cases

### Changed
- Renamed from openForge to meshctx
- Flat memory → key-value with importance scoring

---

## [0.1.0] - 2026-05-07

### Added
- Initial project structure
- Basic data models (Project, Conversation, Message, Memory)
- JSON file-based persistence
- Project README and planning documents

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
