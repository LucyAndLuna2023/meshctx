# MeshCtx Changelog

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
