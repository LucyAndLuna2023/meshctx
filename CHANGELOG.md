# Changelog

All notable changes to meshctx will be documented in this file.

## [1.0.0] - 2026-05-09

### Added
- **Microkernel Architecture**: Event-driven plugin system with priority event bus
- **Hierarchical Memory (L0-L4)**: 4-tier memory with Ebbinghaus Forgetting Curve
- **Meta-Cognition Engine**: Self-evaluation, pattern extraction, behavior adjustment
- **Multi-Agent Orchestrator**: Task DAG decomposition, specialized agent pool, Memory Hub
- **Hybrid Retrieval**: Vector + Knowledge Graph + Recency combined scoring
- **Resource Governor**: Per-plugin quotas, circuit breaker pattern
- **Plugin Marketplace**: pip/npm publish support
- **MCP Protocol**: Native Model Context Protocol support
- **RESTful API**: 20+ endpoints for all core functionality
- **Web Dashboard**: Jinja2 templates for memory/project/continuity management
- **Docker Support**: Dockerfile + docker-compose.yml
- **Deploy Script**: Automated deploy to remote servers
- **CLI Tool**: Command-line interface for all operations

### Changed
- Complete rewrite from v0.2.0 monolithic architecture to v1.0.0 microkernel

### Fixed
- N/A (first major release)

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
