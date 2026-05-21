# MeshCtx Changelog

## [2.50.0] - 2026-05-21 🏆里程碑
### 统一OODA循环 — 全模块集成
- 🔄 **统一Agent循环** (unified_loop.py): LLM→Observe→Orient→Decide→Act→Learn→Verify
- 🛡️ SDB集成: 文件操作自动过安全门控
- 🧠 脑状态验证: 每10轮自动检查13维度
- 🎯 意图分类: 6种意图→自动路由动作
- 📊 综合指标: 迭代/动作/延迟/SDB拒绝/脑评分
- ⌨️ 6个CLI新命令: diff/tasks/sdb/brain/modify/loop
- 📊 测试: 1151 passed

## [2.49.0] - 2026-05-21
### Gateway LLM集成 — 真实模型接入消息平台
- 🤖 **GatewayLLMAdapter** (gateway_llm.py): Gateway路径接入真实LLM
- 📡 流式输出: chat_stream()逐token推送
- ⬇️ 优雅降级: LLM不可用时回退模板
- 💬 对话历史: 多会话隔离+自动截断
- 📊 测试: 1124 passed

## [2.48.0] - 2026-05-21
### 脑状态验证框架 (论文arXiv 2605.20127落地)
- 🧠 **BrainStateValidator** (brain_validator.py): 13个可复现脑响应维度
- 📊 Recovery Profile: 超越pass/fail,量化每个维度恢复程度
- 🔁 测试-重测可复现性验证
- 🤝 brain-to-brain alignment比较
- 📊 测试: 1100 passed

## [2.47.0] - 2026-05-20
### 自修改代码引擎 — 世界首创
- 🔧 **SelfModifyEngine** (self_modify.py): Agent自主优化自身源码
- 🔄 7阶段管道: Analyze→Propose→Test→SDBGate→Apply→Verify→Rollback
- 🔗 整合diff_preview+sdb_framework
- 📊 源码分析: 指标+问题检测(TODO/FIXME/长行/长函数)
- 🛡️ 安全级别: low/medium/high/paranoid
- 📊 测试: 1077 passed

## [2.46.0] - 2026-05-20
### SDB框架 — 论文arXiv 2605.20173直接落地
- 🛡️ **SDBEngine** (sdb_framework.py): 随机-确定性边界管理
- 🔒 4阶段合约: Propose→Verify→Commit→Reject
- 🔍 重放分歧检测: 相同输入不同LLM输出→自动拒绝
- 📊 可量化指标: commit_rate, variance_coefficient, replay_divergence
- 🏅 可靠性评分: 85.43/100 A级
- 📊 测试: 1047 passed

## [2.45.0] - 2026-05-20
### 后台任务进度引擎
- 📊 **TaskProgressEngine** (task_progress.py): 实时进度追踪
- 📡 SSE流式推送 + WebSocket广播 + 心跳
- 🔄 完整生命周期: create→start→update→complete/fail/cancel
- 📝 async上下文管理器: engine.track()
- 📊 测试: 1018 passed

## [2.44.0] - 2026-05-20
### Unified Diff Preview — 对标Claude Code
- 📝 **DiffPreviewEngine** (diff_preview.py): 文件修改前unified diff预览
- 💾 自动备份+一键回滚
- 📦 批量diff操作
- 🌊 SSE流式输出diff
- 📊 测试: 999 passed

## [2.38.0] - 2026-05-20
### 使用洞察分析 — 对标Hermes insights
- 📊 **UsageInsights** (usage_insights.py): 日/周/月分析

## [2.37.0] - 2026-05-19
### 凭证池轮转
- 🔑 **CredentialPool** (credential_pool.py): API Key多策略轮转

## [2.15.7] - 2026-05-16
### New Features — 智能防错系统
- 🧠 **原则提取器** — 8条内置原则(从历史错误学习),支持LLM自动提取+用户自定义
- 🛡️ **行动前检查** — 文件修改前自动语法检查(node --check/ast.parse)+原则匹配
- 🔍 **自动错误诊断** — /api/principles/extract 从错误日志匹配已知原则
- 🔧 **NSIS乱码修复** — LangString $\n换行(49处)+版本同步2.15.7
- 📦 **Windows管理模块完好** — 12端点/560行,构建中已包含
- 📊 测试: 673 passed + 8原则在线

## [2.15.6-hotfix] - 2026-05-16
### Critical Bug Fixes — 全链路测试驱动
- 🔴 **ModelClient.chat() 吞错误修复** — 删除try/except伪装成功,改为抛出真实异常
- 🔴 **模型CRUD×4缺import yaml** — add/update/delete/set_default_model 全部补上
- 🔴 **test_model_connection假成功** — 增加base_url检查+错误响应检测
- 🧪 **E2E全链路测试** — 36条curl测试覆盖6阶段(核心/模型/新特性/UI/竞品/文件)
- 📊 测试结果: 673 pytest passed + 35/36 E2E passed (97%)

## [2.15.6] - 2026-05-16
### New Features — Chat Core Enhancement
- 🔢 **Token计数器** — POST /api/utils/tokens + 前端实时显示(>4K橙色>8K红色警告)
- ⌨️ **键盘快捷键** — Ctrl+Enter发送 / Esc取消清空 / ↑历史回溯
- 🔵 **流式状态指示** — 思考中→生成中→完成 实时状态+光标平滑闪烁
- ⚙️ **系统提示词** — 每个Chat独立System Prompt,可折叠编辑器,后端/api/chat接受system参数

## [2.15.5] - 2026-05-16
### New Features — Chat Intelligence Upgrade
- 📎 **@文件引用** — 输入@触发文件自动补全,选择后注入文件内容为上下文(活用/api/file/read)
- 🔢 **代码块行号** — 所有代码块自动显示行号,可选中不复制
- ⚡ **快捷操作栏** — 翻译/总结/解释代码/修复Bug/优化性能 一键填充
- ✏️ **会话重命名** — 右键Chat Tab可重命名,持久化存储
- 竞品对标: @文件引用对标Cursor/Copilot,快捷操作对标ChatGPT

## [2.15.4] - 2026-05-16
### New Features — Chat UX Enhancement
- 📋 **提示词模板库** — GET/POST/DELETE /api/prompts 端点 + 前端下拉选择器
- 📥 **对话导出** — 一键导出对话为Markdown文件下载
- ✏️ **消息编辑重发** — 编辑已发送消息,自动截断历史重新提问
- 竞品对标驱动: 补齐Claude Code/ChatGPT/Cursor等对话增强体验
- 测试: 673 passed, 1 failed (UI/WSL), 2 skipped, 5 warnings

## [2.15.3] - 2026-05-16
### Fix & Deploy
- 版本号统一: main.py 2.9.1→2.15.3, core 2.15.2→2.15.3, pyproject.toml 1.6.0→2.15.3
- meshctx_desktop.spec 版本同步 v2.15.1→v2.15.3
- Python 3.10兼容: platform_fs.py f-string反斜杠转义修复
- README/docs/download/docs.html/getting-started.html 全量版本更新
- 远程服务器部署: 47.120.0.239:3000 v1.5.24→v2.15.3 (全量同步)
- 测试: 673 passed, 6 failed (UI/WSL无浏览器), 9 errors (UI), 2 skipped

## [2.15.0] - 2026-05-16
### WorkBuddy & OpenWork Learnings
- SOUL.md/IDENTITY.md/USER.md 三大人格文件系统
- 版本化记忆 (VersionedMemory, 自动递增版本号)
- 连接器SKILL.md文档标准 (学自WorkBuddy)
- 多通道通知: Telegram/Discord/Slack (学自OpenWork Telegram集成)
- 自动更新检查 (/api/update/check)

### Added
- `src/core/versioned_memory.py` — 版本追踪记忆
- `src/core/auto_update.py` — GitHub Release更新检测
- `src/core/multi_notify.py` — Telegram/Discord/Slack通知
- `src/core/realtime_push.py` — WebSocket实时推送
- `src/core/agent_monitor.py` — Agent实时指标

## [2.14.0] - 2026-05-15
### i18n Completion + Build
- JA/KO/ES/FR/DE c9-c18完整翻译
- 竞品表18行全语言覆盖
- Windows/macOS构建触发

## [2.13.0] - 2026-05-15
### Plugin System + Tasks
- 插件自动加载 (plugin_autoload)
- Agent任务持久化 (agent_tasks)
- WebSocket实时推送 (/ws/metrics)

## [2.12.0] - 2026-05-15
### Docker + Code Review
- Dockerfile + docker-compose.yml 一键部署
- .env.example 28供应商配置模板
- 代码审查插件 (12+检测规则)
- 安全加固: XSS防护/输入消毒/Key脱敏
- TTL缓存系统

## [2.11.0] - 2026-05-15
### Multi-Model Compare + Persistence
- 多模型对比Chat (并发问3模型, 并排卡片)
- 对话持久化 (JSON存储, 重启不丢)
- 配置备份恢复
- API限流 (60次/分钟)

## [2.10.0] - 2026-05-15
### Windows Management
- 全方位Windows管理 (win_admin)
- 服务/进程/注册表/PowerShell/浏览器
- 桌面🪟 Windows管理面板
- Chat /win 命令

## [2.7.0 - 2.9.0] - 2026-05-15
### Core Features
- 核心IP保护 (双重许可)
- 代码沙箱 (Docker+SSE流式)
- 项目索引 (15语言符号)
- 飞书通知 (卡片/文本/部署)
- 100模型·28供应商
- Agent自监控+记忆可视化
- 性能基准仪表盘

## [1.8.2] - 2026-05-14
### BrainRouter OODA Integration
- BrainRouterAdapter集成到OODA循环
- Surprise-Gated温度调制
- 超级大脑架构 (13脑区)
- 插件市场上线
- 本地文件直读API
- Web搜索API
