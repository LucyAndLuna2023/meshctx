# Changelog

## [1.6.2] - 2026-05-14 (v1.6.2 Release)

### Changed
- 版本号更新: v1.6.0→v1.6.2
- 测试数: 473→555
- benchmark数据更新: free energy 15.2%
- build构件: 4个 (exe/setup/zip/dmg), ~848MB
- 同步官网和文档到meshctx.com

### Tests
- 全量: 555 passed (排除UI)，17 skipped

## [1.6.0] - 2026-05-14 (三大智能闭环集成)

### Added — 预测引擎 × 自由能集成 (世界首创)

- **FreeEnergyPredictorAdapter** (`src/core/predictor.py`)
  - TemporalPatternLearner 包装为 Dirichlet BeliefState
  - 预测置信度 = expected_probability × precision_gate (精密加权)
  - 每次用户活动同时更新时间模式 + 信念状态
  - 动态类别扩展: 新任务类型自动扩展Dirichlet维度
  - 事件驱动注入: `predictor.free_energy_prediction` + `context.preloaded` 事件
  - get_free_energy_state(): 返回信念熵、精度、概率分布、波动性

### Added — 元认知 × 主动推理闭环 (世界首创)

- **MetaActiveInferenceAdapter** (`src/core/metacognition.py`)
  - TaskEvaluation → (success:bool, strength:float) 映射
  - → ActiveInferenceEngine.learn_from_outcome() 策略信念更新
  - BehaviorAdjuster 策略权重 → AI 温度调节
  - 6种评估状态映射: SUCCESS/质量→exploit_best, knowledge_gap→explore_random, tool_error→safe_path, timeout→defer_decision
  - 事件: `metacognition.ai_feedback` 全局广播

### Added — 全局工作空间 × OODA 循环集成

- **WorkspaceAwareAdapter** (`src/core/agent_loop.py`)
  - Orient阶段调用 GlobalWorkspace.cycle() — 7处理器竞争
  - 智能刺激信号构造: intent+urgency+content → 6处理器(analyst/creator/observer/memory/predictor/critic)
  - 意识点火检测 (>0.75 activation) → "aha moment"
  - 认知状态注入 observation.context
  - learn_from_outcome: action_type→processor→processor_belief 更新
  - 新事件: `agent.orient` (在observe和decide之间)

### Added — 36个集成测试

- **test_v15_integration.py** (新文件, 463行, 36测试)
  - FreeEnergyPredictorAdapter: 初始化/学习/预测/置信度/事件集成 (17测试)
  - MetaActiveInferenceAdapter: 初始化/反馈循环/策略映射/集成验证 (7测试)
  - WorkspaceAwareAdapter: 初始化/Orient/点火/反馈/OODA集成 (12测试)

### Changed
- src/core/__init__.py: 新增 FreeEnergyPredictorAdapter, MetaActiveInferenceAdapter, WorkspaceAwareAdapter 导出
- 测试数: 188→224 (+36), 脑启发测试: 46→82 (+36)
- 总测试数: 555

### Benchmarks (vs v1.3)
- 预测置信度: 启发式→自由能量化 (FreeEnergyPredictorAdapter)
- 学习反馈: 单向记录→闭环强化 (MetaActiveInferenceAdapter)
- OODA循环: 3阶段→4阶段(新增Orient/工作空间) (WorkspaceAwareAdapter)

---

## [1.5.25] - 2026-05-13 (7语言 + FastAPI迁移)

### Added
- 7语言全覆盖: EN/ZH/JA/KO/FR/DE/ES
- MUI_LANGDLL替代自定义语言页解决乱码
- FastAPI lifespan迁移消除deprecation
- 下载页 meshctx.com + NSIS安装程序

### Changed
- 主题localStorage key统一 (meshctx_theme)
- CSS重复修复
- exe自动同步到自有服务器
- Tag v1.5.25 已推送触发GitHub Actions构建
- 测试数: 116→188

---

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
