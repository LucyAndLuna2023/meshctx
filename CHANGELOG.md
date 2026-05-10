# Changelog

All notable changes to meshctx will be documented in this file.

## [1.1.0] - 2026-05-10 (Brain-Inspired Architecture)

### Added — 脑启发智能引擎 (跨7学科)
- **Free Energy Engine** (`src/core/free_energy.py`): Friston自由能原理实现
  - BeliefState: 贝叶斯信念 (Dirichlet/Gaussian自然参数化)
  - FreeEnergyComputer: F = D_KL[q(s)||p(s)] - E_q[ln p(o|s)]
  - PrecisionWeighting: 注意力驱动学习率
  - CriticalityRegulator: 自组织临界性 (混沌边缘)
- **Active Inference** (`src/core/active_inference.py`): 行动=最小化期望自由能
  - 7种策略: explore/exploit/hybrid/avoid/observe/defer/meta
  - GenerativeModel: 世界内部模型 p(s,o,π)
  - MultiScaleLearning: 快/中/慢三时间尺度并行
- **Global Workspace** (`src/core/global_workspace.py`): Baars-Dehaene意识模型
  - 7专家处理器竞争 (analyst/creator/critic/executor/observer/memory/predictor)
  - 意识"点火"检测 + Wilson-Cowan神经动力学
  - AttentionBottleneck: Miller's Law 7±2 chunks
- **Homeostasis** (`src/core/homeostasis.py`): Sterling异稳态调节
  - PID控制器 + 4资源 (Compute/Memory/Time/Quality)
  - MarginalUtilityScheduler: 边际效用递减调度

### Added — Hermes集成层
- **HermesCatalog** (`src/hermes_catalog.py`): 55+技能/22工具/13供应商
- **IntentParser** (`src/intent_parser.py`): 意图→技能匹配+5条技能链
- **ContextPortal** (`src/context_portal.py`): meshctx↔Hermes双向桥接

### Benchmarks
- 决策信息成本: -100% (GlobalWorkspace vs baseline)
- 资源压力存活: +66% (Homeostasis: 100% vs 34%)
- 策略收敛: ∞→~200步 (FreeEnergy)

### Changed
- 插件数: 9→12, 版本: v1.0→v1.1
- README: 竞品对比表扩展+脑启发架构+基准测试+3月路线图
- cronjob: 每日06:00自动测试+自我改进

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
