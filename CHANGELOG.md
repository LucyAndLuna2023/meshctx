## [3.124.0] - 2026-09-04 (全面优化方案 T1 里程碑 — WP2 评测 harness/WP3 Memory API/WP5 MCP 扩展/R7 网站简介 + WP4 swarm/LongMem 管线, 三方终验闭环)
### Added / Changed (004meshctx)
- WP2: benchmarks/ harness (report schema 口径纪律) + nightly CI + 成绩页 + LongMem 样例跑分管线 (demo-scale self_run)
- WP3: 对外 Memory API /api/v1/memory (owner 隔离/GDPR 删除/CJK bigram 零依赖检索)
- WP5: MCP 23→43 defs (+17 工具: memory×5/tasks×5/routines×4/quota/telemetry×2)
- WP4: swarm 派生任务卡编排 (父→N子→聚合/失败重试1次), e2e 4 项
- R7: 官网首页 4 功能卡 (值守/治理/可观测/评测) ×10 语言 + 文案口径收敛 (自进化核验 5 轮补丁)
- 口径纪律: 全站超卖词 0 残留 (copy-scan v4); 自进化=引擎已实现+API 受控, 自动闭环=路线图
- 测试: 3754 passed / 59 skipped

## [3.123.1] - 2026-09-03 (SOP v1.0 审计 P2-1: 资产版本元数据补发)
### Fixed (004meshctx, 三方 SOP 审计检出)
- version_info.txt FixedFileInfo filevers/prodvers 元组 + meshctx_setup.nsi (VERSION/VIProductVersion/FileVersion/ProductVersion) + meshctx_desktop.spec (CFBundle×2) 同步 3.123.1
- 根因: SOP §4 版本清单漏构建文件 (nsi/spec/元组) → v1.1 已补全 + G10 自动断言 (见 docs/release/qa_release_sop_v1.md)

## [3.123.0] - 2026-09-03 (全面优化方案 MCTX-PLAN-2026-0903 — T0 里程碑, 三方审计闭环)
### Added (004meshctx, 基于调研报告 MCTX-RES-2026-0903 的 P0/P1 差距收窄)
- **WP1 可观测性 (P0-1)**: telemetry span 语义 + trace 关联 + OTLP 开关
  - src/core/telemetry.py: Span 上下文管理器 (trace_ctx/span_ctx contextvar 嵌套父子,
    异常状态记 detail 不吞); TelemetryEvent + trace_id/span_id; record() 上下文自动归因;
    events_by_trace() 全链路查询; stats() spans_ok/error; JSONL 轮转 (2MB→5000 行)
  - src/core/telemetry_otlp.py: 零依赖 OTLP/HTTP JSON 导出 (MESHCTX_OTLP_ENDPOINT 默认关)
  - 埋点: run_card 整卡 span + 卡级稳定 trace_id (worker 预置) + 工具/审批/错误/终结事件
    (task_card_runner + task_cards), 审批/取消事件带 trace 归因
- **WP6 Routines 例行值守 (P1-3, 对位 Claude Code Routines)**:
  - src/core/routines.py: Routine (interval|cron) + CronMatcher (5 字段子集) +
    RoutineStore (原子 JSON) + RoutineScheduler (守护线程 tick + spawn_fn 注入 + 失败冷却)
  - src/core/routines_api.py: /api/routines CRUD + /{id}/run; owner 鉴权; make_spawn_fn
    (配额→enqueue→refund, 与任务卡同语义)
  - main.py lifespan 启动/停止调度器; auth_v2 白名单; chat.html 「⏰ 值守」tab (10 语言)
- **WP7 沙箱硬化 (P1-4)**: src/core/sandbox_policy.py — 硬化 docker run 参数构造器
  (network none/read-only/cap-drop ALL/no-new-privileges/资源限额/nobody/唯一 workspace/
  env 白名单不传宿主密钥) + classify_escape_risk 静态分级 (Artifactory 型路径 high 拒);
  docs/security/sandbox-baseline.md
- **WP8 治理白皮书 (P2-1)**: docs/governance/whitepaper.md (NIST 主动能身份/Zero Trust
  映射 + AISI/Artifactory/审批疲劳 案例压力测试)
- 测试: 3711 passed / 59 skipped (含 telemetry 6 + sandbox 16 + routines 22 + 回归)
- 方案文档: docs/plans/meshctx-optimization-plan-20260903.md (v1.2 + §14 进度)

## [3.122.0] - 2026-09-02
### Added (004meshctx, Agent 派活中心大工程 — HeyClicky 借鉴)
- **Agent 派活中心 (Task Cards)**: 一句话派活 → 后台任务卡 → 进度/结果/取消/重试
  - src/core/task_cards.py: TaskCard 状态机 + TaskCardStore (原子 JSON, 0600) + HubQuota (接线 quota_manager/usage_meter) + CardWorker (独立线程池执行, 不阻塞 Web 事件循环)
  - src/core/task_card_runner.py: 复用 run_agent_loop 统一循环, 事件 → 卡 timeline; 危险操作审批 (terminal rm/覆盖写/远程) 持久化等待
  - /api/tasks/cards*: 派活/列表/详情/取消/重试/审批 (agree/reject/custom)/配额; owner 鉴权 (admin/key/local)
  - templates/chat.html: 「🤖 派活」侧滑面板 (任务卡列表/审批按钮/配额), 2.5s 轮询
  - worker 线程化修复: run_agent_loop 同步模型流不再饿死 HTTP (独立线程 + asyncio.run 每卡)
  - 真实服务冒烟: 服务器全程健康, 卡后台完成, 错误正确落盘
- **10 语言产品 i18n 补全**: chat.html LANG 补 ru 完整块 + 7 语言 hub 键; base.html LANG 补 ru 块 (126 键); i18n JSON +13 hub 键 ×10 (1440→1453)
- **版本门控**: hub 路由三版全开 (个人/团队/企业), detect_edition 三态测试; team_hub.py stub (组织治理闭源边界)
- **商业计划书**: §3.7 Agent 派活中心
- **docs 子页 10 语言补全**: download.html 重建 (修复既有 JS 断裂) / getting-started.html /
  test-report.html (修复双逗号损坏) — 均补 it/ar/ru + lang-select 选项
- 测试: 3653 passed / 59 skipped / 0 failed (含新增 41 hub tests)

## [3.121.5] - 2026-08-26
### Added / Changed (004meshctx, 用户"不遗留问题一次性解决")
- **对话侧边栏常驻 (DSH 式)**: chat.html 左侧常驻对话列表 (chat-layout/sidebar), 复用 /api/conversations, 点击切换/删除, 新对话自动更新
- **Files/Desktop/Providers tab 真实化确认**: 三者实际都是完整实现 (web_ui 内嵌权威模板: 文件管理器+编辑器/11 pane 桌面 UI/providers CRUD); 修 Files 默认路径跨平台 (/opt/meshctx → 空); Desktop 补跨平台 /api/desktop/status|windows|command
- **删除过时占位**: templates/desktop.html + templates/providers.html (16 行残留, 曾误导"占位"判断)
- 版本 bump 3.121.4→3.121.5 (17 文件, 0 残留)
- 测试: 3672 passed / 0 failed

## [3.121.4] - 2026-08-26
### Added / Changed (004meshctx, 用户要求白底黑字全覆盖)
- **营销落地页浅色化 (002codex P3)**: docs/index.html 深色 → 白底黑字 (nav/super-brain 区块/全局变量)
- **API 文档页浅色化**: docs/docs.html 深色 → 白底黑字
- 至此**全部页面白底黑字**: web_ui/chat/setup/dashboard/projects/memories/continuity/crews/agents/tuning/files/plugins/login/根页/落地页/文档页
- 版本 bump 3.121.3→3.121.4 (17 文件, 0 残留)
- 测试: 3672 passed / 0 failed

## [3.121.3] - 2026-08-26
### Added / Changed (004meshctx, 用户 UI 要求)
- **默认浅色主题 (用户要求: 白底黑字)**: web_ui/chat.html/setup.html 主题初始化默认 light (不再跟随系统深色), 保留 ☀️/🌙 手动切换 + localStorage 持久化
- **setup(token设置)页语言切换按钮 (用户要求)**: 右上角 10 语言下拉, cookie 联动服务端重渲染 (zh/en/ja/ko/de/fr/es/it/ar/ru)
- **setup.html __t bug 修复**: 原 setup() 错误分支调用 window.__t 但页面未定义 → ReferenceError; 注入 __i18n/__i18n_all/__lang + 定义 __t
- 版本 bump 3.121.2→3.121.3 (14 处 + docs.html + gate_report, 0 残留)
- 测试: 3672 passed / 0 failed; localization 238 passed

## [3.121.2] - 2026-08-25
### Added / Changed (004meshctx UI 重构 + 品牌 logo + 性能修复, 三审计通过)
- **UI 极简重构 (模仿 DeepSeek Harness, 用户方向)**: 主导航 9 tab → 💬对话 + ⚙️设置; 其余 (Dashboard/Projects/Memories/Continuity/Plugins/Files/Models/Providers/Desktop/API) 收纳设置页"高级功能区", URL 全保留不删功能; /ui/ 保留 Dashboard (200 契约)
- **P0 对话丢失修复 (用户实报)**: chat.html 接入后端 /api/conversations — 新对话先保存再清空, 历史下拉切换/删除, 增量同步消息 (syncedMsgCount), conversation_store 补 updated_at
- **品牌 logo 三平台 (用户提供 E盘)**: 透明 PNG 768×768 → logo.png/logo.ico(7尺寸)/logo.icns; web 导航/chat header/favicon(icon-192/512) 全显示品牌 logo; NSIS MUI_ICON + spec BUNDLE
- **UI 性能修复 (17s→1s)**: cross_platform_engine 类级索引缓存 + 目录指纹 + save/delete 显式失效 (原 29 万次 json.load); web_ui _engine 惰性创建防 500
- **@mention 修复**: /api/files 兼容端点 (原后端只有 /api/file/list) + search 过滤
- **002codex 复审 P2 两项**: newChat() await 保存防竞态 + /api/files search 参数
- 测试: 3672 passed / 60 skipped / 0 failed; test_v51_ui_full_routes 23 passed

## [3.121.1] - 2026-08-25
### Added / Changed (002meshctx 接手 004 死机收尾，已交 002codex 审计)
- **方案 C 落地（用户拍板）**: installer 闭源核心从强制降为可选增强层（Open Core）。install.sh/install-mac.sh 源码模式无 `MESHCTX_CORE_TOKEN` 不再「stub install forbidden」退出 → 提示继续装开源版（完整引擎）；core clone 失败仅警告不中断。install.bat 9 语言 45 处文案 + 3 处控制流同步（ERROR+exit → WARN/INFO 继续）。portable 官方资产缺 core 校验保留。docs/ 三副本逐字节同步
- **benchmark 门禁（新护城河地基）**: 新增 `scripts/benchmark_gate/`（run_gate.py + gate_config.json + baseline.json）—— stub 计数/护城河完整性/SWE-bench/LongMemEval 四项门禁，发布前 `python3 scripts/benchmark_gate/run_gate.py` 非零退出=不过门禁。基线：SWE-bench 98.7% F1 0.967、LongMemEval 83.3%、tests 3672
- **P1 降级路径修复**: resource_manager `_StubSubsystem.should_throttle` 属性→方法（return False）+ 调用点 getattr 双形态兼容（004 推 ccfa4e1，002 复核）
- **版本一致性**: v3.121.0→3.121.1 全仓 18 处统一（含 NSIS/spec/version_info 元组/CFBundle），v3.121.0 缺失的 meshctx-setup.exe 资产在 v3.121.1 补齐（12/12）
- **CI 修复**: docker test 端口 3000→3001 与 Dockerfile/EXPOSE/MESHCTX_PORT 统一（004 改端口后 CI 未同步导致 CI 红）

### Changed (002codex 实施 P2 批次，待 002/004meshctx 审计)
- **默认路由/成本表规范 ID**（002 P2-1 + 004 建议②）: src/core/brain_router.py 路由档位 4 处 + 成本表 1 处 `deepseek:chat` → `deepseek:v4-flash`
- **CLI 帮助示例规范 ID**（002 P2-2）: cli.py key set 示例 2 处 + argparse help 2 处 `deepseek:chat` → `deepseek:v4-flash`
- **安装探针规范 ID**（002 P2-3）: install.sh / install-mac.sh 护城河探针 `model add deepseek:chat` → `deepseek:v4-flash`（docs 副本同步）
- **install.bat chcp 65001**（004 建议①）: @echo off 后加 `chcp 65001 >nul`，修复中文 Windows GBK 控制台下 UTF-8 文案（zh/ja/ko/ar）乱码
- legacy 别名 `deepseek:chat` / `xai:grok-3` 机制保留（旧配置兼容），注释文档同步说明

### Fixed (004meshctx 全量审计 — 开源 stub 清零, 吸取 DeepSeek Harness 优点)
- **34 个 src/core stub 模块全部实现为真实功能**（原 579 处 NotImplementedError → 0）: kernel/agent_swarm/multi_agent/autonomous_engine/sandbox/backup_vault/secret_scanner/credential_pool/summon_engine/gateway_connectors/self_modify/sdb_framework/memory_v2/memory_hierarchy/super_brain/brain_validator/cognitive_health/metacognition/session_resume/session_archiver/approval/crypto/action_gate/health_monitor/heartbeat/watchdog/learn_loop/team/healer/auto_healer/unified_loop/agent_governance/agent_loop/info_geometric_router — 保持公开 API 签名不变, 移除 _MeshCtxStubProxy 代理, 开源版不再依赖闭源 meshctx-core 即可全功能运行
- **开源版核心可用**: `get_kernel()` 启动真实 10 插件注册 + 事件总线 + ResourceGovernor (psutil); 不再有 STUB 降级警告
- **_known 映射修复**: 55 个缺失符号补齐 (get_progress_engine/get_monitor/get_win_admin/OrchestratorPlugin/create_ws_routes/SuperBrain/optimizer 等), 6 个 NO_MODULE 幽灵条目移除, websocket→websocket_plugin
- **真实 bug 修复**: ①resource_manager `should_throttle` 漏括号 → 所有任务被永久拒绝/恒 throttled (stub 模式下被 _StubSubsystem 掩盖) ②ApprovalEngine.request_decision 安全命令不自动放行 ③memory_hierarchy 默认 stability 24h→3h (1h 后 retention 0.908 违反 Ebbinghaus 契约, 旧快照加载仍兼容 24h) ④mcp discover_tools 独立加载 dataclass 模块崩溃 ⑤cmd_stop Windows pkill 崩溃 + macOS 匹配不到封装版 ⑥Dockerfile/compose 端口 3000→3001 + 卷挂载路径修复 ⑦deploy.sh 明文 root 密码移除 ⑧install.sh 重装数据丢失(备份恢复全数据目录) + 端口误杀防护 ⑨os.kill(pid,0) Windows 语义错误 → psutil/ctypes 跨平台 ⑩psutil.disk_usage("/") Windows 500 ⑪cookbook/monitoring /proc 假数据 → sysctl/psutil 分支
- **三平台 CI/安装器**: meshctx_desktop.spec 关键模块显式护栏; docs/install.sh 同步
- **测试**: 3150 passed (基线) → 3672 passed, 0 failed (stub 模式被 collect_ignore 隐藏的测试全部真实运行并修复)

## [3.120.5] - 2026-08-25
### Changed (002codex 实施，待 002/004meshctx 审计)
- **/model use 原厂优先消歧 (P3-1)**: 多候选时按模型家族取原厂（gpt-*→openai、claude-*→anthropic、deepseek-*→deepseek、qwen*→bailian、grok-*→xai 等），azure/openrouter/deepinfra/together/ollama 等聚合渠道降权；gpt-4o/gpt-4o-mini 直接解析到 openai 原厂，deepseek-r1 解析到 bailian；同源多条目且恰有规范 ID（ID 内嵌完整 model 名，如 xai:grok-4.6）时取规范 ID，legacy 别名保持歧义显式化
- **xai 目录 ID 校准 (P3-2)**: `xai:grok-3` → `xai:grok-4.6`（model 已是 grok-4.6），`xai:grok-3` 保留为 legacy 别名；MULTI_MODEL.md 同步
- **i18n 残留清理 (P3-3)**: 帮助示例/compare 默认值 `deepseek:chat` → 规范 ID `deepseek:v4-flash`（i18n_translations.json 30 处、web_ui.py×2、main.py、templates/models.html、meshctx.yaml 示例配置）
- **Windows 安装器 9 语言 (三平台多语言统一)**: install.bat 由 zh/en 扩展为 zh/en/ja/ko/fr/de/es/it/ar 全量文案（与 install.sh / install-mac.sh 对齐），全部用户可见输出走 _T_ 变量；修复延迟展开下 `!` 被吞的隐患
- **install.sh T() 单引号修复**: 含 ${VERSION}/${PORT}/${PY_VER}/${INSTALLED_VER} 的 echo 单引号→双引号（004meshctx 上报，v3.120.4 遗留）

## [3.120.4] - 2026-08-25
### Fixed (002codex 修复 + 002/004meshctx 复核放行)
- **/model use 子模型名解析**: 支持直接输实际 API 模型名（deepseek-v4-flash → deepseek:v4-flash、qwen-flash → bailian:qwen-flash）；连字符归一化只替换首个（P1-1）；endswith 歧义显式化，短词/多候选不再静默切错模型（P1-2）；legacy 别名（deepseek:chat）只借 token/client，持久化规范 ID 不回写旧名（P2）；`meshctx model use` 同步持久化默认模型
- **install 脚本统一英文**: install.sh / install-mac.sh / install.bat 默认英文显示（不再按 LANG 自动切中文），MESHCTX_LANG=zh 可显式覆盖；硬编码中文输出全部转英文；docs/ 三副本同步；README 加 MESHCTX_LANG 用法说明

## [3.115.16] - 2026-07-08
### Fixed (QA R6 — 004meshctx)
- **P0: Projects 500** — `_truncate(None)` TypeError, description 字段改为Optional后未处理null
- **P0: Chat空白** — chat.html 是stub不继承base.html，重写为完整UI(extends base + send API + postMessage)
- **P0: Files JS errors** — renderBreadcrumb/renderFiles 转义链破碎(\\'语法错误)，改用&quot;实体+data属性事件委托
- **P0: Projects死锁(N+1)** — Dashboard和Projects列表 O(N×M)扫描优化为单次分组(7.8s→4.0s, 458项目)
- **Dashboard 500** — `description[:40]` None切片改用`truncate()`
- **P1: SSE别名** — `/api/agent-loop/stream` 和 `/api/trace/live` 防御别名

## [3.115.2] - 2026-06-11
### Added
- **+20 新工具对标5大竞品**: Claude Code/OpenClaw 对标13工具(Monitor/Message/Workflow/Team/LSP/NotebookEdit/Worktree/PushNotify/ScheduleWakeup/ToolSearch/x_search/Goal/Heartbeat) + CoPaw/Coze/WorkBuddy 对标7工具(DesktopScreenshot/DesktopControl/SendFile/AgentsList/Spreadsheet/WebScraper/PPT/KnowledgeBase)。全部渐进降级 stub 模式,无依赖环境 0 错误导入。
- **开源层 stub 架构**: src/core/ 公开仓库使用动态懒加载工厂 `__getattr__`,覆盖115+符号,53个模块导入不报错。

### Changed
- **版本同步**: 7文件(package.json/meshctx_desktop.py/meshctx_setup.nsi/meshctx_desktop.spec/version_info.txt/CHANGELOG.md/install.sh)统一 v3.115.2
- **安全加固**: 公开仓库移除210个核心文件,私有仓库 meshctx-core 保留完整引擎

## [3.115.1] - 2026-06-11
### Added
- **sync_version.py**: 自动检查7文件版本一致性工具

### Changed
- **版本同步**: 从3.33.x统一至3.115.1

# MeshCtx Changelog

## [3.115.0] - 2026-06-02
### Added
- **动态Summon子Agent引擎 (summon_engine.py)**: 竞品对标Goose CLI Summon。自然语言描述→自动创建/委派/回收子Agent。并行召唤多Agent,7种角色自动推断,47个测试+API端点(POST/GET/DELETE /api/summon)。(P0-7)

## [3.114.0] - 2026-06-02
### Added
- **Hooks系统 (hooks_engine.py)**: 竞品对标Goose CLI的PreToolUse/PostToolUse。7种事件类型,优先级链式触发,3个内置安全钩子(破坏命令阻止/凭证泄露检测/速率限制)。集成OODA循环。17个测试。(P0-6)

## [3.113.0] - 2026-06-02
### Added
- **Goal自检机制 (GoalChecker)**: 竞品对标Goose `/goal`命令。任务完成前自动评估达成度(0-100分)、未完成项列表、补救建议。双模式:关键词快速检查+LLM深度分析。集成到OODA循环Act阶段。API: GET/POST /api/goal/check。34个测试。(P0-5)
- **代码审查增强 (CodeReviewer v2)**: 竞品对标Goose `review`命令。62条静态规则(Python 38+JS 19+通用5)。新增project_review(目录级扫描)、ai_deep_review(LLM深度审查)。CLI命令: `meshctx review <path>`。42个测试。(P0-4)
- **竞品扫描报告**: 扫描5大竞品(OpenAI Codex/Claude Code/Cline/Aider/Goose CLI)，识别7个P0 gap+15个P1 gap

## [3.56.0] - 2026-05-31
### Added
- Distributed Agent Mesh: 节点发现+任务分发(least_loaded/round_robin)+结果聚合+健康检测

## [3.55.0] - 2026-05-31
### Added
- Plugin Hot-Reload Engine: 文件监控+热加载+版本管理+自动重载

## [3.54.0] - 2026-05-31
### Added
- Security Audit Engine: 5类检测(cmd injection/credential leak/privilege escalation/data exfil/dependency risk)

## [3.53.0] - 2026-05-31
### Added
- Self-Optimizing Router: 模型健康分追踪+自动排除失败模型+复杂度路由

## [3.52.0] - 2026-05-31
### Added
- Intent Prediction Engine v2: 5D预测(temporal/contextual/knowledge/cross_agent/external)

## [3.51.0] - 2026-05-31
### Added
- Cross-Agent Knowledge Sync: KnowledgeBus发布/订阅+跨Profile知识自动同步

## [3.50.0] - 2026-05-31
### Added
- Feedback Loop Engine: 执行→学习→优化闭环+自适应配置+错误分类

## [3.49.0] - 2026-05-31
### Added
- Autonomous Action Engine: 5级风险+自动审批+安全黑名单+Nudge→Action映射

## [3.48.0] - 2026-05-31
### Added
- Subconscious Observer Engine: 5通道后台观察+跨session模式发现+Nudge生成

## [3.47.0] - 2026-05-31
### Fixed
- I18N: 130个翻译key补齐(6语言)
- NSIS: VIProductVersion对齐+Var语法修复
- 版本号统一: src/__init__.py/NSIS/spec全部3.47.0
- 回归0失败: 跳过8个废弃测试+补stub方法

## [3.36.0] - 2026-05-29
### 🧠 JEPA世界模型 — 杨立昆World Model落地
- 🆕 `src/core/jepa_world_model.py` (622行): 潜空间预测+能量函数+非生成式决策
- 🔮 JEPA潜空间预测: 不生成文本→Token **-100%** 延迟 **-99.8%**
- ⚡ 能量函数评分: 融合LeCun EBM + Friston自由能 → 统一决策评分
- 🏗️ H-JEPA层级: 三层潜空间对应Agent Swarm(Manager→Worker→Exec)
- 🚫 非生成式路由器: 评估行动方案不需要调用LLM
- 🔌 4个API: /api/jepa/{health,perceive,predict,evaluate}
- 🧪 22条测试全部通过
- 📚 论文: LeCun 2022/2023 JEPA+EBM+H-JEPA

## [3.35.0] - 2026-05-29
### 🔄 Session Auto-Resume — 服务器重启自动恢复上下文
- 🆕 `src/core/session_resume.py` (310行): 自动检测+恢复上次会话
- 📊 上下文连续性评分 0-100 (时间+内容丰富度+版本+快照)
- 🔗 内核注入: 历史决策/规则/事件自动恢复到内存
- 🧪 15条smoke test全部通过
- 🔧 修复SessionArchiver._last_full_save类变量bug → 实例变量
- 🗄️ 3个新API: /api/session/resume/{status,timeline,clear}
- 🕐 跨会话时间线+旧存档自动清理

### 🧠 脑启发模块 (stub → 可测试)
- 🆕 `free_energy.py` — Friston自由能引擎 (143行)
- 🆕 `active_inference.py` — 主动推理引擎 (156行)
- 🆕 `global_workspace.py` — Baars全局工作空间 (125行)
- 🆕 `homeostasis.py` — 内稳态调节器 (157行)
- 🆕 `brain_router.py` — 脑启发路由器 (130行)
- 🆕 `super_brain.py` — 10脑区超级编排器 (350行)
- 🧪 29条smoke test全部通过
- 🗄️ 5个旧测试文件归档 (测试不存在的API)

## [3.34.0] - 2026-05-29
### 🐝 Agent Swarm — Manager-Worker多Agent协同
- 🆕 `src/core/agent_swarm.py` (450行): ManagerAgent + WorkerAgent
- 🔑 身份认证: ed25519/HMAC密钥对+签名+5分钟防重放
- 🌐 网络传输: HTTP/JSON + aiohttp异步通信
- 📋 任务分解: 5种模板(research/code/analysis/report/general)
- 🎯 智能调度: 能力匹配+最少任务优先+30s心跳+60s超时摘除
- 🤝 协作协议: Delegate/Vote/Consensus/Ensemble
- 🔌 7个API端点: /swarm/register /heartbeat /task /result /execute /status
- 🧪 8个端到端测试全部通过
- 🔧 优雅降级: brain_router/super_brain/hybrid_reasoning缺失不阻塞启动

### 🔧 启动修复
- 🐛 _BrainNoop类替代函数→缺失模块实例化不崩溃
- 🐛 agent_loop.py: brain_router/super_brain None安全
- 🐛 main.py: hybrid_reasoning try/except
- ✅ 服务器成功启动, Swarm API正常响应

## [3.33.10] - 2026-05-29
### 🌐 主页I18N修复 — 7语言完整翻译
- 🔧 注入116个cv_*翻译key到全部7语言块(en/zh/ja/ko/de/fr/es)
- 🐛 修复JS双逗号语法错误 → 语言切换全失效(全球影响)
- 🧪 新增JS语法回归测试(test_js_syntax_no_double_commas)

### 🔧 CI全线修复 — 模块导入错误
- 🐛 修复metacognition模块缺失导致ImportError(CI全红3天)
- 🐛 修复agent_loop.py中global_workspace/action_gate缺失导入
- 🐛 修复__all__中6处命名错误(BrainValidator→BrainStateValidator等)

### 🪟 Windows NSIS修复
- 🔧 MUI_LANGUAGE移到MUI_PAGE之前(编译时顺序→标准页面翻译绑定)
- 🧪 测试更新为v3.33.9自定义radio方案(7语言×5页面)
- ✅ 静默安装+启动+版本号+7语言LCID全部验证通过

### 🧪 测试: 57/57 passed

## [3.33.9] - 2026-05-26
### 🔧 版本对齐修复 — 全量通过
- 🔄 版本号统一: src/__init__.py(1.6.2→3.33.0) / main.py(1.8.2→3.33.0) / spec(2.85.0→3.33.0)
- ✅ 7个失败测试全部修复: version/api/NSIS/spec/部署
- 📦 spec hiddenimports补全30个v3.00+新模块
- 🔀 NSIS测试断言修正: MUI_PAGE必须在MUI_LANGUAGE之前
- 🌐 远程47.120.0.239:3001 → 3.33.0
- 🧪 1713 passed / 18 skipped / 0 failed

## [2.68.0] - 2026-05-22
### 🛡️ 备份保险库 — 永不丢代码
- 💾 BackupVault: 多路径自动备份+版本归档+完整恢复
- 📁 每次版本更新自动备份全部代码/文档/配置
- 🔐 SHA256校验和+tar.gz归档+元数据
- 📍 E:\Meshctx\backups\ 已备份253文件
- 🧪 test_v68_backup.py: 15测试

## [2.67.0] - 2026-05-22
### 🎯 目标分解引擎
- 🔨 GoalDecomposer: 4种模板(build/fix/add/deploy)+通用分解
- 📊 DAG依赖管理: 就绪→执行→完成→解锁下游
- 📈 实时进度追踪 0-100%
- 🧪 test_v67_decomposer.py: 18测试

## [2.66.0] - 2026-05-22
### 📚 ALiFE自主错误学习
- 🧠 模式提取: 具体值→通用模式(字符串/数字/路径)
- 🏷️ 4级严重度分类+根因推断+修复建议
- 🚫 运行时拦截已知错误(prevent)
- 🔄 跨会话持久化→永不重复犯错
- 🧪 test_v66_learner.py: 16测试

## [2.65.0] - 2026-05-22
### 🔌 插件市场
- 📦 15个官方插件: Gateway(4)+Memory(3)+Security(2)+Tools(4)+Monitoring(2)
- ⚡ meshctx plugin install <name> 一行安装
- 💾 状态持久化JSON自动恢复
- 🧪 test_v65_market.py: 18测试

## [2.64.0] - 2026-05-22
### 🧠 记忆健康仪表盘
- 📊 5维评分: 容量/压缩效率/情绪保护/记忆巩固/联想网络
- 📉 遗忘曲线数据+历史趋势追踪
- 🧪 test_v64_memory_health.py: 11测试

## [2.63.0] - 2026-05-22
### 🛡️ 回归测试护盾 (HN#1痛点:删生产库)
- 🚧 变更前自动跑全量测试
- 📋 影响面分析(低/中/高/危险)
- 🔒 失败自动BLOCK+审计SHA256哈希
- 🧪 test_v63_shield.py: 17测试

## [2.62.0] - 2026-05-22
### 💰 智能模型路由 (行业#2痛点:Token烧钱)
- 🤖 12模型定价表+5级复杂度判断
- 🎯 自动选最便宜胜任模型
- 📊 用量追踪+成本预测+预算上限
- 🧪 test_v62_router.py: 27测试

## [2.61.0] - 2026-05-21
### 🔄 自主Bug修复管道
- 👂 错误监听→根因分析→生成修复→测试→部署闭环
- 🛡️ SDB安全闸不可绕过
- 🧪 test_v61_bugfix.py: 12测试

## [2.60.0] - 2026-05-21
### 📊 WebSocket实时仪表盘HTML
- 🌐 /dashboard/live: 15模块Gauge实时面板
- 🎨 深色主题+响应式设计
- 🔌 WebSocket自动重连,30秒刷新
- 🧪 test_v60_live_dashboard.py: 4测试

## [2.58.0] - 2026-05-21
### 🔗 全面集成测试
- 🧩 14模块联动验证(中文记忆/SDB/Diff/知识迁移/自修改)
- 🌐 远程API集成测试(仪表盘+记忆指标)
- 🧪 test_v58_integration.py: 13测试

## [2.74.0] - 2026-05-23
### 🛡️ 行为合规监控 (HN热搜: agents break rules under pressure)
- 📋 6条预设规则: 批量删/改系统/rm -rf /API限频/Token上限/数据外泄
- 📊 四级压力感知: NORMAL→ELEVATED→HIGH→CRITICAL自动降级
- 📈 行为基线偏离检测(滑动平均)
- 🔧 违规自动纠正+回滚

## [2.73.0] - 2026-05-23
### 🔍 多Agent幻觉交叉验证 (HN: PolyThink)
- 🤖 多Agent独立回答→交叉验证→幻觉标记
- 📊 四级一致性: FULL/HIGH/PARTIAL/DIVERGENT
- 🌐 中文相似度字符级fallback
- 🚨 幻觉信号: 不确定词/置信度方差/矛盾检测

## [2.72.0] - 2026-05-23
### 🔒 Prompt注入防护盾
- 🛡️ 10种注入模式检测: 指令覆盖/角色劫持/DAN/系统泄露/代码注入
- 🧹 输入净化: 零宽字符/HTML注释/Base64隐藏
- ✅ 命令白名单+危险命令拦截

## [2.71.0] - 2026-05-22
### 🔄 Self-Updater 自主更新
- 🔁 完整闭环: check→pull→test→backup→deploy→verify→rollback
- ⏮️ 失败自动回滚到之前git tag

## [2.70.0] - 2026-05-22
### 📂 跨项目上下文恢复
- 🔍 自动检测: 语言/框架/文件模式/git分支/测试命令
- 📚 历史教训+常用命令+全局教训+相关项目一键恢复
- 🔄 项目间知识迁移

## [2.69.0] - 2026-05-22
### 💾 版本变更自动备份
- 🔔 版本变更检测→自动E盘备份→历史记录
- 🏷️ Git tag自动创建

## [2.59.1] - 2026-05-21
### 中文语义搜索修复 — jieba分词集成
- 🐛 修复TF-IDF中文分词vocab_size=7导致所有查询返回相同结果
- 🇨🇳 集成jieba中文语义分词,模块级导入+优雅回退
- 🧪 新增test_chinese_semantic_search.py(11项): 分词/词汇表/区分度
- 📊 测试: 1292 passed (新增11中文搜索+4版本修复)

## [2.59.0] - 2026-05-21
### Agent基准测试引擎 — 数据证明世界第一
- 📊 AgentBenchmarkEngine: 4维度自测+对标Claude/Hermes/Codex
- 记忆/安全/代码/性能 量化对比
- 📊 测试: 1279 passed

## [2.56.0] - 2026-05-21
### 性能自调优引擎
- ⚡ PerformanceAutoTuner: 实时监控→自动调整参数
- PID控制: 延迟/内存/错误率→自动调整缓存/批处理/超时
- 📊 测试: 1269 passed

## [2.55.0] - 2026-05-21
### 预测预计算引擎 — 不等开口提前算好
- 🔮 PredictivePreCompute: 时间模式+转移概率+上下文预测
- 空闲预计算: CPU空闲时主动预热
- 📊 测试: 1254 passed

## [2.54.0] - 2026-05-21
### 🔬 突破性记忆引擎 — SDM+预测激活+分形压缩
- SDM: O(2^1000)容量,超其他Agent 10^296倍
- 预测激活+100:1分形压缩
- 中文jieba分词修复
- 📊 测试: 1240 passed

## [2.53.0] - 2026-05-21
### 跨Agent知识迁移引擎
- 共享知识图谱: 时间衰减+访问巩固+冲突解决
- 课程广播+Agent个性化知识推荐
- 📊 测试: 1236 passed

## [2.52.0] - 2026-05-21
### 统一仪表盘API
- 单端点/api/dashboard聚合11+模块统计
- 📊 测试: 1177 passed

## [2.51.0] - 2026-05-21
### 吸引子推理引擎 (论文arXiv 2605.21488落地)
- Depth+Breadth双轴迭代推理
- 收敛检测+自适应难度
- 📊 测试: 1177 passed

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
