# Changelog

## [1.7.0] - 2026-05-14 (v1.7.0 BrainRouter OODA Integration)

### Added — BrainRouter OODA集成 + 跨模块闭环

- **BrainRouterAdapter** (`src/core/agent_loop.py`)
  - 将BrainInspiredRouter完整集成到OODA循环的Orient→Decide阶段
  - 工作空间7处理器激活→稀疏路由→神经符号投影→ψ容量调节
  - 自由能门控: surprise动态调制路由温度 (high surprise → more exploration)
  - 动态活跃专家数调节 (高惊讶度时激活更多专家)
  - AgentLoopPlugin自动初始化brain_router实例

- **Surprise-Gated Temperature Modulation**
  - 低惊讶度(surprise=0.1) → 温度T=1.15 → 保守路由
  - 高惊讶度(surprise=0.9) → 温度T=2.35 → 探索路由
  - n_active动态范围: 3(默认) → 5(高surprise)

### Fixed
- brain_router `_gumbel_topk` 线性归一化数值不稳定 → 改用softmax归一化
- test_gumbel_vs_softmax 边界值溢出修复
- PEP 668 外部管理环境: 网站安装指令添加venv创建步骤

### Changed
- **网站重构**: 快速开始分平台展示 (🐧 Linux / 🍎 macOS / 🪟 Windows)
  - 每个平台独立代码块, tab切换
  - Linux明确标注PEP 668 venv解决方案
  - Windows一键安装+开发者模式双选项
  - 英文版i18n全覆盖 (quick_start/windows/install区域)
  - 修复英文站"30秒快速开始"/"一键安装"等中文残留
  
- agent_loop.py: 新增 `import numpy as np`
- version_info.txt: 1.6.3 → 1.7.0

### Tests
- 新增: 19个BrainRouter集成测试 (test_v17_brain_router_integration.py)
- 脑模块: 46 passed (test_v11_brain)
- 脑路由: 29 passed (test_v16_brain_router, 修复1个)
- 集成: 57 passed (test_v15_integration)
- 新集成: 19 passed (test_v17)
- 全量: 648 passed (排除UI)

### Module Stats
| 模块 | 行数 | 类 | 方法 | 测试 |
|------|------|-----|------|------|
| free_energy | 771 | 7 | 30 | 18 ✅ |
| active_inference | 510 | 7 | 22 | 10 ✅ |
| global_workspace | 573 | 6 | 20 | 10 ✅ |
| homeostasis | 819 | 7 | 30 | 6 ✅ |
| metacognition | 812 | 7 | 35 | - |
| brain_router | 692 | 4 | 19 | 29 ✅ |
| **agent_loop** | **1104** | **+1** | **+3** | **+19 ✅** |
| **总计** | **~5300** | **~42** | **~163** | **648** |

## [1.6.3] - 2026-05-14 (v1.6.3 Brain Router Integration)

### Added — 脑启发路由器模块 (基于Global Workspace Theory 2.0论文 2026.04.30)

- **SymbolicProjector** (`src/core/brain_router.py`)
  - Gumbel-Softmax神经符号转换，支持可微分离散化
  - 自适应维度处理，任意输入维度均可投影
  - 自动温度调度（高熵→降温，低熵→升温）
  - 符号空间投影、置信度、分布熵计算

- **SparseAttentionRouter** (`src/core/brain_router.py`)
  - 动态路由系数α_i，可学习注意力机制
  - Gumbel-TopK稀疏化，避免所有专家同时激活
  - 自适应上下文投影（任意维度→key_dim）
  - 路由历史跟踪、专家使用率统计

- **PsiParameterizedComplexity** (`src/core/brain_router.py`)
  - ψ-参数化动态复杂度调节（基于Active Inference+Free Energy论文 2026.05.12）
  - 自适应容量扩展/收缩（利用率驱动）
  - λ惩罚系数随惊讶度动态调整
  - Token预算分配（30%-80%动态范围）

- **BrainInspiredRouter** (`src/core/brain_router.py`)
  - 统一接口整合符号投影+稀疏路由+ψ参数化
  - 全链路统计（router/symbolizer/psi_adjuster）
  - 支持空专家、变维度、连续操作压力测试

### Tests
- 新增: 30个脑启发路由器测试全过
- 全量: 629 passed (排除UI), 2 skipped

### Changed
- 版本: v1.6.2 → v1.6.3
- src/core/__init__.py: 导出新增4个类
- 测试数: 599 → 629

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
