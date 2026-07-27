<p align="center">
  <img src="docs/assets/logo.png" alt="MeshCtx" width="200">
  <h1 align="center">🧠 MeshCtx v3.115.31</h1>
  <h3 align="center">世界第一全脑仿真自进化AI Agent · SDM突破性记忆 · 自修改代码 · 全量测试 · 17脑区 · 17模块 · Swarm代码生成 · 11工具链</h3>
</p>

<p align="center">
  <a href="LEGAL.md"><img src="https://img.shields.io/badge/license-MIT+Commercial-blue"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-3320-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/modules-276-purple"></a>
  <a href="#"><img src="https://img.shields.io/badge/brain_regions-17-orange"></a>
  <a href="#"><img src="https://img.shields.io/badge/languages-9-red"></a>
  <a href="#"><img src="https://img.shields.io/badge/papers-3-blue"></a>
</p>

---

## 🚀 快速安装

### Windows
```powershell
# 下载安装程序 (推荐)
# 访问 https://github.com/LucyAndLuna2023/meshctx/releases/latest
# 下载 meshctx-setup.exe — NSIS安装向导，7语言，一键安装

# 或便携版
# 下载 meshctx-portable.zip 解压即用
```

### Linux / WSL
```bash
curl -fsSL https://cdn.jsdelivr.net/gh/LucyAndLuna2023/meshctx@main/install.sh | bash
# 安装完成后配置API密钥
meshctx setup
```

### macOS
```bash
# 下载 DMG 安装包
# https://github.com/LucyAndLuna2023/meshctx/releases/latest
# 下载 meshctx-macos.dmg

# 或 Homebrew
brew install meshctx
```

### 启动
```bash
meshctx start          # 启动Web服务 (默认 http://localhost:3001)
meshctx chat           # 命令行对话
meshctx setup          # 配置API密钥和模型
meshctx desktop        # Windows桌面客户端
```

---

## 🧠 核心特性

### 多模型自由切换 (v3.115.25) 🆕
- **每会话独立模型**: 每个对话窗口可选择不同AI模型，切换会话自动恢复
- **Web UI 下拉菜单**: 聊天页顶部一键切换，实时生效
- **CLI 斜杠命令**: `/model deepseek:v4-pro` 切换，`/model` 查看当前，`/models` 列出可用
- **跨平台统一**: Linux / Windows / macOS 浏览器访问同一套 Web UI

### 脑启发AI引擎
- **17脑区全脑仿真**: 自由能原理 · 主动推理 · 全局工作空间 · 稳态调节
- **混合推理调度**: 自由能驱动的探索vs直出决策
- **超级大脑**: 海马回放 · 杏仁核情绪标记 · 默认模式网络 · 丘脑门控
- **元认知**: 自我评估 · 错误分类 · 行为调整

### 类人记忆系统 (v2.40)
```
传统AI记忆: 存数据 → 关键词匹配
类人记忆:   模式组块 → 情绪加权 → 海马回放 → 联想扩散
```
- **模式组块**: 像围棋手识别"中国流布局"，压缩原始数据为意义模式
- **情绪加权**: 重要信息(CRITICAL)几乎永不遗忘(衰减200倍慢于日常)
- **海马回放**: 后台5分钟周期重放记忆，自动巩固+发现关联
- **再巩固**: 每次回忆都会更新记忆（人类学习的核心机制）
- **联想扩散**: 记忆通过加权链接传播激活（气味→场景→人→对话）
- **有效遗忘**: 忘掉细节保留模式，遗忘是特征不是bug

### 自主运维引擎 (v2.41)
- 15+指标实时监控（CPU/内存/磁盘/网络/FD/记忆块）
- Z-score异常检测（5σ触发CRITICAL）
- 症状模式匹配 → 根因诊断 → 自动修复
- 修复数据库自学习（成功率追踪）
- 进化日志记录所有事件

### Hooks引擎 (v2.42) — 对标Claude Code
- 8种事件: PreTool · PostTool · Stop · SessionStart · PreCompact · Notification · SubagentStop · UserPrompt
- 通配符匹配: `Bash(git *)` · `Write(*.py)` · 子串匹配
- 安全规则: 默认拦截 `rm -rf` / `git push --force` / `curl|bash`

### 🐝 Agent Swarm — Manager-Worker多Agent协同 (v3.34) 🆕
```bash
# 启动Manager节点
meshctx start --port 3001

# 启动Worker节点 (另一台机器)
curl -X POST http://manager:3001/swarm/register \
  -d '{"worker_id":"bot1","name":"Coder","capabilities":["code"]}'

# 提交复杂任务 — 自动分解→派发→并行执行
curl -X POST http://manager:3001/swarm/execute \
  -d '{"task":"搜索最佳实践+写代码+审查","type":"research"}'
```
- **Manager-Worker架构**: 1个Manager管理N个Worker，通过网络+密钥协同
- **自动任务分解**: research/code/analysis/report 5种模板
- **智能调度**: 能力匹配+最少任务优先+60s心跳超时
- **身份认证**: ed25519密钥对+HMAC签名+5分钟防重放
- **协作协议**: 委托(Delegate) · 投票(Vote) · 共识(Consensus) · 集成(Ensemble)
- 冷却机制: 防重复触发

### Agent团队 (v2.43) — 对标Claude Code @agent
- 6内置角色: Coder · Reviewer · Architect · Tester · Researcher · DevOps
- 4协作模式: Review · Brainstorm · Divide&Conquer · Pipeline
- 并行调度 + 结果聚合

### 多平台Gateway (v2.39)
- 微信企业 · 飞书 · Telegram · Slack · Discord · WhatsApp
- Socket Mode · Webhook · Cloud API
- 统一消息格式 + 多平台广播

### 凭证池轮转 (v2.37)
- 多API Key轮转: round_robin · least_used · random
- 自动标记耗尽Key + 冷却恢复
- 持久化 + 统计

### 使用洞察 (v2.38)
- 按日/周/月追踪: 会话 · 消息 · Token · 延迟 · 错误率
- Provider/Model性能排行
- 峰值时段热力图

---

## 📊 版本演进

| 版本 | 核心交付 | 测试 |
|------|---------|------|
| v2.37 | 凭证池轮转 + 会话管理增强 | 825 |
| v2.38 | 使用洞察分析 | 846 |
| v2.39 | Gateway (Slack/Discord/WhatsApp) | 894 |
| v2.40 | **类人记忆系统** (6机制) | 916 |
| v2.41 | **自主运维引擎** (自愈+进化) | 935 |
| v2.42 | **Hooks引擎** (8事件) | 956 |
| v2.43 | **Agent团队** (6角色+4模式) | 975 |
| v3.115 | **DeepSeek TUI竞品对标** (17模块·4200行) | **130** |

---

## 🏗️ 技术架构

```
meshctx/
├── src/
│   ├── main.py              # FastAPI 主应用
│   ├── web_ui.py            # Web UI 模板
│   ├── cli.py               # CLI 命令行
│   ├── i18n.py              # 7语言国际化
│   └── core/                # 9个核心模块
│       ├── dual_session.py      # Planner/Executor 双session引擎
│       ├── prompt_registry.py   # YAML模板注册表 + 版本化
│       ├── subagent_isolated.py # 子进程真隔离 subagent
│       ├── cost_router.py       # flash/pro 成本分级路由
│       ├── config_chain.py      # 4级TOML配置链覆盖
│       ├── identity_guard.py    # System prompt身份固化
│       ├── tui_format.py        # 6种TUI输出格式注入
│       ├── tool_repair.py       # 7策略JSON修复层
│       └── memory_v5.py         # 4级分级内存注入
├── tests/                   # 130个测试
├── docs/                    # 文档站点
├── install.sh               # Linux一键安装
├── install.bat              # Windows安装脚本
└── index.html               # 7语言主页 (gh-pages)
```
## 📦 核心模块清单（273 模块）

### 🧠 脑区 (22 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `brain` | 1292 | 全脑仿真主控 — 17脑区调度 |
| `brain_acc` | 685 | 前扣带皮层 — 冲突监测与认知控制 |
| `brain_amygdala` | 845 | 杏仁核 — 情绪标记与恐惧学习 |
| `brain_basal_ganglia` | 676 | 基底节 — 动作选择与强化学习 |
| `brain_brainstem` | 191 | 脑干 — 唤醒度与生命维持 |
| `brain_cerebellar` | 679 | 小脑 — 时序预测与运动协调 |
| `brain_dmn` | 695 | 默认模式网络 — 自传体记忆与心智漫游 |
| `brain_hippocampal` | 294 | 海马体 — 情景记忆编码与回放 |
| `brain_iit` | 542 | 整合信息理论 — 意识度量 Φ |
| `brain_insula` | 766 | 岛叶 — 内感受与自我意识 |
| `brain_mirror` | 759 | 镜像神经元 — 共情与意图理解 |
| `brain_pfc` | 181 | 前额叶 — 执行功能与工作记忆 |
| `brain_stdp` | 571 | 脉冲时序可塑性 — 突触学习规则 |
| `brain_thalamic` | 513 | 丘脑 — 感觉门控与注意定向 |
| `brain_visual` | 166 | 视觉皮层 — 层级特征提取 |
| `active_inference` | 46 | 主动推理引擎 — 自由能最小化 |
| `attractor_reasoner` | 319 | 吸引子推理 — Hopfield网络决策 |
| `global_workspace` | 38 | 全局工作空间 — 意识广播 |
| `brain_router` | 59 | 脑启发路由 — 模块选择 |
| `brain_validator` | 275 | 脑状态校验 — 一致性验证 |
| `brain_emotional` | 495 | 情绪系统 — 情感计算 |
| `brain_nacc` | 137 | 伏隔核 — 奖赏预测误差 |

### 💾 记忆 (13 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `breakthrough_memory` | 810 | 突破性记忆 — SDM模式组块引擎 |
| `sdm_memory` | 520 | 稀疏分布记忆 — Kanerva SDM实现 |
| `human_memory` | 637 | 类人记忆 — 6机制(组块/情绪/回放/再巩固/联想/遗忘) |
| `memory_v5` | 346 | 4级分级内存注入 |
| `memory_compactor` | 431 | 记忆压缩 — 摘要与合并 |
| `memory_cleanup` | 159 | 记忆清理 — 过期与淘汰 |
| `memory_export` | 181 | 记忆导出 — 跨会话迁移 |
| `memory_formation` | 456 | 记忆形成 — 编码与索引 |
| `memory_forgetting` | 212 | 遗忘曲线 — Ebbinghaus模型 |
| `memory_graph` | 378 | 记忆图 — 实体关系网络 |
| `recall_engine` | 294 | 回忆引擎 — 联想扩散检索 |
| `forget_curve` | 124 | 遗忘曲线 — 自适应衰减率 |
| `hippocampus_engine` | 403 | 海马引擎 — 模式分离与完成 |

### 🤖 自主引擎 (8 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `autonomous_engine` | 916 | 自主引擎 — OODA循环调度 |
| `autonomous_agent` | 416 | 自主Agent — 感知-决策-执行 |
| `autonomous_action` | 512 | 自主行动 — 工具选择与执行 |
| `autonomous_bugfix` | 156 | 自主修复 — 错误诊断与修补 |
| `autonomous_health` | 111 | 自主健康 — 进程监控与恢复 |
| `agent_swarm` | 299 | Agent蜂群 — Manager-Worker协同 |
| `agent_swarm_v2` | 425 | Agent蜂群v2 — 投票/共识/集成 |
| `swarm_codegen` | 651 | 蜂群代码生成 — 并行代码合成 |

### 🔒 安全 (12 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `auth_v2` | 324 | 认证v2 — 密码+API Key+Session |
| `code_sandbox_v3` | 482 | 代码沙箱v3 — Docker隔离执行 |
| `prompt_shield` | 337 | 提示词盾 — 7类注入检测 |
| `approval` | 169 | 审批引擎 — YOLO/smart/manual三级 |
| `credential_pool` | 287 | 凭证池 — Key轮转与脱敏 |
| `crypto` | 198 | 加密模块 — AES+HMAC+ed25519 |
| `secret_scanner` | 145 | 密钥扫描 — 自动脱敏检测 |
| `permission_manager` | 213 | 权限管理 — RBAC角色控制 |
| `identity_guard` | 178 | 身份保护 — System Prompt固化 |
| `audit_logger` | 670 | 审计日志 — 操作追溯 |
| `behavior_compliance` | 568 | 行为合规 — 策略执行 |
| `behavior_monitor` | 124 | 行为监控 — 异常检测 |

### 📋 任务/工作流 (12 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `workflow_engine` | 723 | 工作流引擎 — DAG编排 |
| `task_queue_v2` | 1110 | 任务队列v2 — 优先级+依赖 |
| `agent_tasks` | 540 | Agent任务 — 重试+超时 |
| `pipeline_engine` | 389 | 管道引擎 — 阶段流水线 |
| `schedule_wakeup` | 82 | 定时唤醒 — Cron调度 |
| `auto_deploy` | 45 | 自动部署 — CI/CD集成 |
| `backup_manager` | 311 | 备份管理 — 快照+恢复 |
| `backup_vault` | 669 | 备份仓库 — 版本化管理 |
| `distributed_lock` | 875 | 分布式锁 — Redlock+Redis |
| `load_balancer` | 456 | 负载均衡 — 最少连接 |
| `retry` | 82 | 重试机制 — 指数退避 |
| `cron` | 453 | Cron调度 — 持久化任务 |

### 💻 代码引擎 (14 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `llm_code_engine` | 972 | LLM代码引擎 — AI写代码 |
| `code_reviewer` | 234 | 代码审查 — 静态分析 |
| `code_generator` | 312 | 代码生成 — 模板合成 |
| `tool_repair` | 378 | 工具修复 — 7策略JSON修复 |
| `llm_extractor` | 127 | LLM提取 — 结构化信息抽取 |
| `model_adapter` | 386 | 模型适配 — 多Provider统一接口 |
| `model_registry` | 553 | 模型注册 — 动态模型发现 |
| `cost_router` | 289 | 成本路由 — flash/pro分级 |
| `prompt_registry` | 312 | 提示词注册 — YAML模板版本化 |
| `principle_extractor` | 42 | 原则提取 — 规则归纳 |
| `advanced_inference` | 1028 | 高级推理 — 链式思维 |
| `hybrid_reasoning` | 6 | 混合推理调度器 (stub) |
| `image_gen` | 6 | 图像生成 (stub) |
| `knowledge_transfer` | 48 | 知识迁移 — 跨域蒸馏 |

### 🌐 网关/通知 (9 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `api_gateway` | 364 | API网关 — 路由+限流 |
| `notification_hub` | 1138 | 通知中心 — 多渠道分发 |
| `feishu_notify` | 171 | 飞书通知 — HMAC签名+卡片 |
| `telegram_router` | 35 | Telegram路由 — Bot集成 |
| `push_notify` | 234 | 推送通知 — Webhook广播 |
| `message_bus` | 456 | 消息总线 — Pub-Sub |
| `email_notify` | 189 | 邮件通知 — SMTP发送 |
| `websocket_plugin` | 30 | WebSocket插件 — 实时推送 |
| `platform_fs` | 10 | 平台文件系统 (stub) |

### 🖥️ Web/UI (19 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `web_ui` | 456 | Web界面 — FastAPI模板 |
| `context_portal` | 567 | 上下文门户 — 会话历史浏览 |
| `browser_tool` | 423 | 浏览器工具 — Playwright集成 |
| `web_crawler` | 412 | 网页爬虫 — 递归抓取 |
| `chat_tools` | 345 | 聊天工具 — 文件/图片/代码 |
| `dashboard` | 15 | 仪表盘 — 实时监控面板 |
| `api_docs` | 90 | API文档 — 自动发现 |
| `api_versioning` | 761 | API版本化 — 兼容管理 |
| `dual_session` | 289 | 双Session — Planner/Executor |
| `subagent_isolated` | 457 | 子Agent隔离 — 子进程沙箱 |
| `tui_format` | 234 | TUI格式 — 6种输出样式 |
| `config_chain` | 198 | 配置链 — 4级TOML覆盖 |
| `i18n` | 567 | 国际化 — 9语言翻译 |
| `soul` | 33 | 灵魂模块 — Agent人格 |
| `action_gate` | 33 | 行动门控 — 危险操作拦截 |

### ⚙️ 基础设施 (11 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `hotreload` | 114 | 热重载 — 配置变更检测 |
| `config_hot_reload` | 512 | 配置热重载 — Watch+Apply |
| `watchdog` | 40 | 看门狗 — 进程守护 |
| `auto_healer` | 135 | 自动修复 — 症状→诊断→修复 |
| `healer` | 16 | 修复器 — 自愈策略 |
| `auto_tuner` | 232 | 自动调优 — PID参数自适应 |
| `alert_engine` | 536 | 告警引擎 — Z-score异常检测 |
| `retry` | 82 | 重试策略 — 指数退避+抖动 |
| `plugin_autoload` | 6 | 插件自动加载 (stub) |
| `federated` | 44 | 联邦学习 — 隐私保护聚合 |
| `performance` | 49 | 性能分析 — Profiling报告 |

### 📊 分析/指标 (15 模块)
| 模块 | 行数 | 说明 |
|------|------|------|
| `benchmark_engine` | 104 | 基准测试引擎 |
| `agent_benchmark` | 81 | Agent基准 — 任务完成率 |
| `audit_logger` | 670 | 审计日志 — 操作追溯 |
| `behavior_monitor` | 124 | 行为监控 — 异常检测 |
| `brain_monitor` | 52 | 脑监控 — 脑区状态追踪 |
| `quota_manager` | 912 | 配额管理 — Token预算控制 |
| `insight_engine` | 345 | 洞察引擎 — 使用趋势分析 |
| `metric_collector` | 234 | 指标采集 — 时序数据 |
| `performance` | 49 | 性能分析 — Profiling |
| `cost_router` | 289 | 成本路由 — 消耗追踪 |

---

## 🔌 API 端点

### 聊天
- `POST /api/chat` — 对话 (非流式JSON)
- `POST /api/chat/stream` — 流式对话 (SSE)

### 双Session
- `POST /api/dual/plan` — Planner规划
- `POST /api/dual/execute` — Executor执行
- `GET /api/dual/stats` — Session统计

### Prompt注册表
- `GET /api/prompts` — 列出模板
- `POST /api/prompts` — 创建模板
- `POST /api/prompts/{id}/publish` — 发布版本
- `POST /api/prompts/render` — 渲染模板

### Subagent隔离
- `POST /api/subagent/run` — 启动隔离subagent
- `GET /api/subagent/{id}/status` — 查询状态
- `POST /api/subagent/{id}/storm_break` — 强制终止

### 记忆
- `GET /api/memory/stats` — 记忆诊断
- `POST /api/memory/add` — 添加记忆
- `POST /api/memory/search` — 搜索记忆
- `POST /api/memory/set_level` — 设置注入级别

### 成本路由
- `POST /api/cost/select` — 选择路由
- `GET /api/cost/metrics` — 成本度量
- `POST /api/cost/report_error` — 上报错误

---

## 🔒 安全

- **Secret扫描**: 自动检测并脱敏API Key/Token/PII
- **Hooks拦截**: 默认阻止危险命令
- **凭证池**: Key轮转防耗尽
- **审批模式**: YOLO/smart/manual 三级

## 🌐 平台支持

| 平台 | 安装方式 | 状态 |
|------|---------|------|
| Windows | NSIS安装包 (7语言) | ✅ |
| Linux | curl\|bash 一键脚本 | ✅ |
| macOS | DMG + Homebrew | ✅ |
| WSL | 同Linux | ✅ |
| Docker | docker-compose | ⚠️ 待更新 |

## 📄 许可证

框架层: MIT 开源
核心大脑层: 源码可见 · 非商业免费 · 商业需授权
联系: license@meshctx.com
