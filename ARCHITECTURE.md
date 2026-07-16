# meshctx 架构全景图 v3.115.15

> 整理时间：2026-07-07 | 整理者：meshctx agent
> 基于：GitHub 仓库 / 本地代码 / 历史 session / AGENTS.md / repo_split_plan.md

---

## 一、三层架构

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1: meshctx.com 网站                                │
│  ~/meshctx-local/                                        │
│  index.html · docs/ · docker-compose.yml · config.yaml   │
│  7语言主页 (zh/en/ja/ko/de/fr/es)                         │
└──────────────────────┬───────────────────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       │                               │
       ▼                               ▼
┌──────────────────┐          ┌──────────────────────────┐
│ Layer 2: 闭源核心  │          │ Layer 3: 开源组件          │
│ meshctx-core      │          │ meshctx-public            │
│ 私有 GitHub        │          │ GitHub LucyAndLuna2023    │
│ ~80 模块           │          │ ~200+ 模块                 │
│ v3.47 服务器版     │          │ v3.115.15 本地开发版       │
│                   │          │                            │
│ 部署: Docker       │          │ 开发: 纯本地+GitHub         │
│ 目标: 47.120.0.239 │          │ 测试: pytest tests/        │
│ 端口: 3001         │          │                            │
│ (UAT已关闭 6/20)   │          │                            │
└──────────────────┘          └──────────────────────────┘
```

### 1.1 meshctx-public (开源) — 当前主力开发

| 指标 | 值 |
|------|-----|
| 版本 | v3.115.15 |
| 核心模块 | 200+ 个 Python 文件 |
| 测试 | ~1059 (含 152 已修复模块) |
| README 定位 | "世界第一全脑仿真自进化AI Agent" |
| 关键能力 | SDM突破性记忆 · 自修改代码 · 17脑区 · 17模块 · DeepSeek TUI竞品对标 |

**9 个核心公开模块** (README 列出的):
- `dual_session.py` — Planner/Executor 双 session 引擎
- `prompt_registry.py` — YAML 模板注册表 + 版本化
- `subagent_isolated.py` — 子进程真隔离 subagent
- `cost_router.py` — flash/pro 成本分级路由
- `config_chain.py` — 4 级 TOML 配置链覆盖
- `identity_guard.py` — System prompt 身份固化
- `tui_format.py` — 6 种 TUI 输出格式注入
- `tool_repair.py` — 7 策略 JSON 修复层
- `memory_v5.py` — 4 级分级内存注入

### 1.2 meshctx-core (闭源) — 服务器部署版

| 指标 | 值 |
|------|-----|
| 版本 | v3.47 (AGENTS.md) / v3.115.2 (README.md) |
| 部署方式 | Docker Compose |
| API | REST + GraphQL (FastAPI) |
| 入口 | app.py |
| 关键模块 | event_system, task_planner, graphql_gateway, observability, circuit_breaker, semantic_index, knowledge_graph |

**33 个私有敏感模块** (应仅存于 core):

| 类别 | 模块 |
|------|------|
| Agent 核心 | agent_swarm, agent_loop, autonomous_engine, unified_loop, multi_agent, team |
| 认知/意识 | metacognition, brain_validator, cognitive_health, learn_loop, super_brain |
| 记忆 | memory_v2, memory_hierarchy, session_resume, session_archiver |
| 安全 | crypto, credential_pool, secret_scanner, approval, action_gate, kernel, sandbox |
| 运维 | auto_healer, healer, health_monitor, watchdog, heartbeat, backup_vault |
| 其他 | summon_engine, self_modify, gateway_connectors, sdb_framework |

### 1.3 meshctx-local (网站)

静态网站 + 部署中转。包含 index.html(7语言主页)、docs/、install.sh、docker-compose.yml。同时也是 repo_split_plan.md 和相关配置的存放地。

---

## 二、集群架构

| ID | Label | Host | 角色 | 状态 |
|----|-------|------|------|------|
| 001 | WSL-Admin | 192.168.3.47 | Windows 本地化测试 | listener 死 |
| 002 | Laptop-E470 | 192.168.3.60 | **主开发机** (当前) | ✅ |
| 003 | Cloudcone-S6 | 66.154.101.18 | 飞书 Gateway + Redis | ✅ |
| 004 | WSL-New | 192.168.3.45 | 辅助节点 | ✅ |

通信：Redis Pub/Sub (66.154.101.18:6379) → Hub 协议 (DM/Task/Feishu/Broadcast 四通道)

---

## 三、竞争态势 (2026-Q3)

| 维度 | meshctx | 竞品 | 差距 |
|------|---------|------|------|
| SWE-bench | **98.7%** (296/300, F1=0.967) | Claude Opus 88.6% | ✅ 领先 |
| 意识引擎 | IIT Φ计算 + JEPA 世界模型 | 无 | ✅ 唯一护城河 |
| 元认知 | 自评估 + 错误分类 + 行为调整 | 有限 | ✅ |
| 多Agent | Swarm 架构 | CrewAI/AutoGen 成熟 | ❌ 追赶中 |
| MCP 协议 | 未集成 | 全部主流框架已集成 | 🔴 P0 |
| Docker 沙箱 | 无 | 标准配置 | 🔴 P0 |
| 工具生态 | 61% stub | 完整 | 🟡 P1 |
| 可观测性 | print 日志 | Langfuse 全链路 | 🟡 P2 |
| 生产 | 单机 | 企业 HA+灰度 | 🟡 P2 |

**追赶优先级**: P0=MCP(2天)+Docker(3天) → P1=消stub+训练JEPA → P2=观测+HA

---

## 四、版本演进

| 版本 | 核心交付 | 测试数 |
|------|---------|--------|
| v2.37 | 凭证池轮转 | 825 |
| v2.38 | 使用洞察 | 846 |
| v2.39 | Gateway (Slack/Discord/WhatsApp) | 894 |
| v2.40 | **类人记忆系统** (6机制) | 916 |
| v2.41 | **自主运维引擎** (自愈+进化) | 935 |
| v2.42 | **Hooks引擎** (8事件) | 956 |
| v2.43 | **Agent团队** (6角色+4模式) | 975 |
| v3.115 | **DeepSeek TUI竞品对标** (17模块·4200行) | 130→1059+ |

---

## 五、开发铁律

### meshctx-public (当前)
- ✅ 纯本地+GitHub 开发模式
- ✅ 测试在本地执行: `pytest tests/ -v`
- ✅ 改完验证才算完成
- ✅ 不问/不等/自己做/只汇报结果

### meshctx-core (服务器，已过时)
- ⚠️ 所有测试在 47.120.0.239 (UAT 已关闭 2026-06-20)
- ⚠️ 本机只写代码不测试

---

## 六、已知问题: 拆分计划未执行

**repo_split_plan.md (2026-06-19)** 计划从 public 仓库删除 33 个私有模块，但至今未执行：

- 计划: public 80→47 模块 / core 保持 80 模块
- 实际: public ~200+ 模块 (远超计划，且包含全部 33 个私有模块)
- 风险: 核心自主/安全代码在公开仓库暴露
- 建议: 择机执行拆分

---

## 七、当前 bug 状态 (2026-07-07)

| 模块 | 通过/总数 | 状态 |
|------|----------|------|
| notification_hub | 49/49 | ✅ 已修复 |
| api_gateway | 36/36 | ✅ |
| goal_checker | 34/34 | ✅ |
| diff_preview | 24/24 | ✅ |
| memory_engine | 9/9 | ✅ |
| **approval (v31)** | **0/10** | 🔴 全部失败 |
| **profiles (v31)** | **4/9** | 🔴 5个失败 |
| **user_scenarios (v34)** | **?/N** | 🟡 3个失败 |
| brain_modules (v35) | ?/N | ⚠️ 太慢跳过 |

---

## 八、模块全量清单

### 脑启发 AI
free_energy, active_inference, global_workspace, homeostasis, hybrid_reasoning, attractor_reasoner, attention_decay, brain_router, brain_validator, brain_monitor, cognitive_health, super_brain, metacognition, subconscious, jepa_world_model, jepa_router, predictor

### 记忆系统
memory_v2, memory_v5, memory_compactor, memory_health, memory_hierarchy, human_memory, breakthrough_memory, topo_memory, embeddings, semantic_index, hybrid_search, vector_store, vector_db

### Agent 框架
agent_loop, agent_swarm, agent_swarm_v2, agent_teams, agent_factory, agent_governance, agent_benchmark, agent_tasks, multi_agent, swarm_engine, orchestator, unified_loop, team, summon_engine, autonomous_engine

### 安全
crypto, approval, action_gate, secret_scanner, security_audit, security_scanner, permission_intel, smart_permissions, sandbox, code_sandbox_v3, prompt_shield, regression_shield, identity_guard, version_guard

### 运维
auto_healer, healer, health_monitor, heartbeat, watchdog, monitor, alert_engine, dashboard, error_recovery, circuit_breaker, resilience_loop, self_healing2, error_learner, evolution_tracker

### 工具/集成
notification_hub, api_gateway, goal_checker, diff_preview, hooks_engine, tool_repair, tool_curator, tool_search, lsp_tool, desktop_tool, win_admin, platform_fs, message_tool, send_file, notebook_tool, spreadsheet_tool, ppt_generator

### 通信/平台
feishu_notify, push_notify, realtime_push, telegram_router, gateway_connectors, gateway_llm, ha_bridge, websocket_plugin, web2api, web_crawler, web_scraper

### 测试/基准
agent_benchmark, claude_bench, pipeline_bench, benchmark_engine, cross_validator, model_compare, llm_quality, test_generator

### 基础设施
config_chain, config_hot_reload, dual_session, prompt_registry, subagent_isolated, cost_router, tui_format, token_budget, context_window, context_compression, context_compressor, context_restorer, progressive_context, session_identity, session_archiver, session_resume, conversation_store, knowledge_base, knowledge_graph, knowledge_graph_v2, knowledge_sync, knowledge_synth, knowledge_transfer, rag_orchestrator, chain_engine, prompt_engine, prompt_optimizer, workflow, workflow_engine, task_planner, task_progress, task_queue_v2, goal, goal_decomposer, schedule_wakeup, project_indexer, dependency_scanner, plugin_manager, plugin_market, plugin_adapter, plugin_autoload, plugin_hotreload, profile_manager, credential_pool, quota_manager, rate_limiter, load_balancer, distributed_lock, distributed_mesh, info_geo_router, smart_router, self_opt_router, self_modify, self_updater, self_debug, auto_tuner, auto_deploy, deploy_engine, backup_manager, backup_vault, checkpoint, feature_flags, api_versioning, api_docs, event_system, data_pipeline, experiment_engine, federated, online_learning, learn_loop, deep_research, deep_research_v2, thinking_depth, thinking_pad, cookbook, hermes_catalog, hermes_connector, acp_bridge, acp_server, mcp_integrator, mcp_standardizer, sdb_framework, kernel, usage_insights, usage_meter, roi_analytics, thermo_cost, performance, performance_optimizer, predictive_precompute, pwa_builder, voice_chat, image_gen, multi_modal, calendar_engine, email_engine, git_ops, worktree_tool, hotreload, desktop_agent, interactive_console, x_search, proxy, pr_agent, refactor_agent, code_reviewer, causal_analyzer, principle_extractor, intent_predict_v2, category_composer, wasserstein_bridge, feedback_loop, observer, behavior_monitor, autonomous_action, autonomous_bugfix, autonomous_health, schedule_wakeup, agents_list, agents_md, docs_generator, lsp_tool
