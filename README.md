<p align="center">
  <img src="docs/assets/logo.png" alt="MeshCtx" width="200">
  <h1 align="center">🧠 MeshCtx v2.60</h1>
  <h3 align="center">世界第一全脑仿真自进化AI Agent · SDM突破性记忆 · 自修改代码 · 1279测试 · 123模型 · 37供应商 · 13脑区 · 1177测试</h3>
</p>

<p align="center">
  <a href="LEGAL.md"><img src="https://img.shields.io/badge/license-AGPLv3+Commercial-blue"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-1279-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/models-123-purple"></a>
  <a href="#"><img src="https://img.shields.io/badge/providers-37-orange"></a>
  <a href="#"><img src="https://img.shields.io/badge/languages-7-red"></a>
  <a href="#"><img src="https://img.shields.io/badge/modules-83-yellow"></a>
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
curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
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
meshctx start          # 启动Web服务 (默认 http://localhost:3000)
meshctx chat           # 命令行对话
meshctx setup          # 配置API密钥和模型
meshctx desktop        # Windows桌面客户端
```

---

## 🧠 核心特性

### 脑启发AI引擎
- **13脑区全脑仿真**: 自由能原理 · 主动推理 · 全局工作空间 · 稳态调节
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
| v2.43 | **Agent团队** (6角色+4模式) | **975** |

---

## 🏗️ 技术架构

```
meshctx/
├── src/
│   ├── main.py              # FastAPI 主应用 (5600行)
│   ├── web_ui.py            # Web UI 模板 (6200行)
│   ├── cli.py               # CLI 命令行 (1100行)
│   ├── model_registry.py    # 123模型/37供应商
│   └── core/                # 72个核心模块
│       ├── human_memory.py  # 类人记忆 (650行)
│       ├── autonomous_engine.py # 自主运维 (600行)
│       ├── hooks_engine.py  # Hooks系统 (350行)
│       ├── agent_teams.py   # Agent团队 (320行)
│       ├── gateway_connectors.py # 多平台Gateway (525行)
│       ├── credential_pool.py   # 凭证池 (300行)
│       ├── usage_insights.py    # 使用洞察 (350行)
│       ├── super_brain.py       # 13脑区超级大脑
│       ├── free_energy.py       # 自由能原理
│       ├── active_inference.py  # 主动推理
│       └── ... (60+ 更多)
├── tests/                   # 975个测试 (55个文件)
├── docs/                    # 文档站点
├── install.sh               # Linux一键安装
├── install.bat              # Windows安装脚本
├── meshctx_setup.nsi        # NSIS安装程序 (7语言)
└── meshctx_desktop.spec     # PyInstaller打包配置
```

## 🔌 API 端点 (100+)

### 聊天
- `POST /api/chat` — 对话
- `POST /api/chat/stream` — 流式对话 (SSE)

### 记忆
- `GET /api/memory/human/stats` — 类人记忆诊断
- `POST /api/memory/human/encode` — 编码记忆
- `POST /api/memory/human/recall` — 联想回忆
- `POST /api/memory/human/replay` — 海马回放

### 自主运维
- `GET /api/autonomous/health` — 健康报告
- `GET /api/autonomous/metrics` — 实时指标

### Hooks
- `GET /api/hooks/rules` — 查看规则
- `POST /api/hooks/fire` — 触发事件

### Agent团队
- `GET /api/teams/agents` — 所有Agent
- `POST /api/teams/dispatch` — 分配任务
- `POST /api/teams/patterns/review` — Review模式
- `POST /api/teams/patterns/brainstorm` — Brainstorm模式

### Gateway
- `GET /api/gateway/connectors` — 连接器状态
- `POST /api/gateway/connectors/{platform}/send` — 发送消息
- `POST /api/gateway/broadcast` — 多平台广播

### 凭证池
- `GET /api/auth/pool` — 查看Key池
- `POST /api/auth/pool` — 添加Key
- `POST /api/auth/pool/test-rotate` — 测试轮转

### 洞察
- `GET /api/insights?period=today` — 今日统计
- `GET /api/insights/providers` — Provider排行

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

框架层: AGPLv3 开源
核心大脑层: 源码可见 · 非商业免费 · 商业需授权
联系: license@meshctx.com
