<p align="center">
  <img src="docs/assets/logo.png" alt="MeshCtx" width="200">
  <h1 align="center">🧠 MeshCtx v3.116.0</h1>
  <h3 align="center">世界第一全脑仿真自进化AI Agent · SDM突破性记忆 · 自修改代码 · 全量测试 · 17脑区 · 17模块 · GenomicOptimizer 自进化 · 可观测性追踪</h3>
</p>

<p align="center">
  <a href="LEGAL.md"><img src="https://img.shields.io/badge/license-AGPLv3+Commercial-blue"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-3404-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/modules-17-purple"></a>
  <a href="#"><img src="https://img.shields.io/badge/brain_regions-17-orange"></a>
  <a href="#"><img src="https://img.shields.io/badge/languages-10-red"></a>
  <a href="#"><img src="https://img.shields.io/badge/papers-3-blue"></a>
</p>

---

## 🔓 开源 / 🔒 闭源架构

MeshCtx 采用 **开源接口 + 闭源核心** 的双仓库架构：

| 仓库 | 可见性 | 内容 |
|------|--------|------|
| **meshctx** (本仓库) | 🔓 公开 | 开源安全模块（完整实现）+ 核心模块的**接口 stub**（签名+文档保留，供外部对接/扩展） |
| **meshctx-core** | 🔒 私有 | 33 个核心模块的**完整实现**（AgentSwarm · Kernel · SuperBrain · Sandbox · MultiAgent · AutonomousEngine 等） |

**对开发者**：公开仓库的 `src/core/*.py` 是完整接口定义（函数/类签名、docstring、枚举常量），可直接 `from src.core.agent_swarm import AgentIdentity` 进行类型对接与二次开发；调用实现时抛 `NotImplementedError("meshctx-core required")` 提示需商业授权。

**商业授权**：`pip install meshctx-core`（私有仓库，需授权）后自动获得完整实现，公开仓库代码零改动即可无缝切换。

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

### 🧬 GenomicOptimizer 基因进化引擎 (v3.116) 🆕
- 遗传算法自动进化 Agent 自身参数：temperature · top_p · prompt style · memory weights
- 变异(高斯扰动) · 大跳跃变异(模拟转座子) · 交叉 · 精英保留 · 生态位保护防早熟
- 784行零依赖纯Python实现，线程安全，约10代后优于人工调参

### 🔍 可观测性追踪 (v3.116) 🆕
- Span/TraceLogger 结构化追踪：llm · tool · chain 全链路
- 线程安全(RLock) + 可选磁盘 JSONL 导出，零依赖
- 注入 hybrid_reasoning 调度与 tool_orchestrator 执行

### 🔄 RAG 查询改写 + RRF 融合 (v3.116) 🆕
- 多路查询改写(同义/子问题/扩展) + Reciprocal Rank Fusion 重排序
- 检索召回率与相关性显著提升

### 🛡️ 会话式终端安全沙箱 (v3.116) 🆕
- 会话上下文连续 + 三级危险分级(普通/危险/高危)
- 危险命令拦截确认，高危命令强制审批

### 🗳️ SelfFeedback 任务后自评 + GroupChat 群辩 (v3.116) 🆕
- 任务规划后自动反馈迭代，多角色动态发言选择

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
| v3.116 | **开源Agent框架挖掘** (RAG+RRF · 终端沙箱 · SelfFeedback · GroupChat · GenomicOptimizer · 可观测性) | **3404** |

---

## 🏗️ 技术架构

```
meshctx/
├── src/
│   ├── main.py              # FastAPI 主应用
│   ├── web_ui.py            # Web UI 模板
│   ├── cli.py               # CLI 命令行
│   ├── i18n.py              # 10语言国际化
│   └── core/                # 核心模块
│       ├── hybrid_reasoning.py  # 混合推理调度 (注入追踪)
│       ├── observability.py     # Span/TraceLogger 可观测性
│       ├── tool_orchestrator.py # 工具编排 (注入追踪)
│       ├── rag_orchestrator.py  # RAG查询改写+RRF融合
│       ├── terminal_sandbox.py  # 会话式终端安全沙箱
│       ├── task_planner.py      # 任务规划+SelfFeedback
│       ├── agent_debate.py      # Agent辩论+GroupChat
│       ├── genomic_optimizer.py # 基因进化引擎
│       ├── dual_session.py      # Planner/Executor 双session引擎
│       ├── prompt_registry.py   # YAML模板注册表 + 版本化
│       ├── subagent_isolated.py # 子进程真隔离 subagent
│       ├── cost_router.py       # flash/pro 成本分级路由
│       ├── config_chain.py      # 4级TOML配置链覆盖
│       ├── identity_guard.py    # System prompt身份固化
│       ├── tui_format.py        # 6种TUI输出格式注入
│       ├── tool_repair.py       # 7策略JSON修复层
│       └── memory_v5.py         # 4级分级内存注入
├── tests/                   # 3404个测试
├── docs/                    # 文档站点
├── install.sh               # Linux一键安装
├── install.bat              # Windows安装脚本
└── index.html               # 10语言主页 (gh-pages)
```
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
| Windows | NSIS安装包 (10语言) | ✅ |
| Linux | curl\|bash 一键脚本 | ✅ |
| macOS | DMG + Homebrew | ✅ |
| WSL | 同Linux | ✅ |
| Docker | docker-compose | ⚠️ 待更新 |

## 📄 许可证

框架层: AGPLv3 开源
核心大脑层: 源码可见 · 非商业免费 · 商业需授权
联系: license@meshctx.com
