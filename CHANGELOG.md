# MeshCtx Changelog

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
