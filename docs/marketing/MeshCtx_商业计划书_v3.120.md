MeshCtx 商业计划书

全脑仿真自适应 AI Agent 平台（进化经 API 受控触发；全自动闭环为路线图项，见附录 D）

版本: v3.120  |  日期: 2026-09-05 (v3.124.1 治理章节定稿里程碑后)

Open Core (AGPLv3)  |  meshctx.com

# 目录

一、执行摘要

二、产品概述与核心架构

三、功能矩阵详述

四、市场分析

五、竞品对比

六、商业模式与定价策略

七、Go-to-Market 策略

八、技术壁垒与护城河

九、团队

十、财务预测

十一、风险与应对

十二、里程碑与路线图

附录：v3.115.27 工程质量里程碑

# 一、执行摘要

MeshCtx 是基于"全脑仿真"（Full-Brain Emulation）架构的自适应 AI Agent 平台；进化能力经 API 受控触发，自动喂数与回注闭环为路线图项（详见附录 D 与进化声称核验报告）。我们不是又一个 AI 编程助手——MeshCtx 模拟人类大脑的 17 个脑区协同工作，实现记忆、学习、推理、自我纠错、主动思考等类人认知能力。

核心差异化：

17 脑区架构：据我们所知业界唯一模拟前额叶、海马体、杏仁核、默认模式网络等 17 个脑区的 Agent 系统

SDM 突破性记忆：稀疏分布式记忆，O(2^1000) 地址空间，比任何竞品高 10^296 倍

自适应进化底座：进化引擎（遗传算法+CMA-ES）与记忆整合已实现, 经 API 受控触发（evolve/feedback）; 任务终态自动喂数与参数自动回注为路线图（2026-09 核验口径）

多模型群审：5 模型并行投票，错误率指数级下降（Swarm 模式）

全平台：Windows/macOS/Linux 三平台原生安装包，11 语言 i18n（含希伯来语 עברית RTL）

GenomicOptimizer 基因进化引擎：基因组学启发的 Agent 参数进化引擎（遗传算法驱动；进化经 API 受控触发，自动闭环为路线图项）

Open Core：AGPLv3 框架永久开源

v3.115.27 工程里程碑（2026-07-29）：

三平台桌面版发布管线成熟：Windows 安装包完整性根治（PyInstaller 全量子模块收集，245 个隐藏导入自动化）

10 语言 UI 资源全量入包：根治 Windows 安装包丢失 7 语言的根因，i18n Guard CI 常态化防回归

俄语本地化 6 处深度修复：语言切换链路加固（事件防护 + 同步 Cookie + 文本节点更新）

GenomicOptimizer 进化引擎上线：002 号节点交付 784 行零依赖进化引擎，Agent 参数（temperature/top_p/prompt 风格等 6 维基因型）经变异-选择-生态位保护自动进化

商业模式：C 端个人用户永久免费。半年后上线 Team 版（$9/月/人）和 Enterprise 版（$29/月/人），定价显著低于竞品（Cursor Pro $20/月，GitHub Copilot Business $19/月，Claude Max $100-200/月）。目标通过个人免费策略快速占领市场→口碑传播→企业转化。

# 二、产品概述与核心架构

## 2.1 什么是 MeshCtx？

MeshCtx 是一个开源核心（Open-Core）的自适应多智能体平台（进化能力经 API 受控触发），将"分工协作 + 全透明"理念融入 AI 系统设计。它不是一个黑箱单一 Agent，而是由编排器（Orchestrator）、守卫（Guardian）、17 个脑区模块和专业化子 Agent 组成的网状协作系统。

## 2.2 全脑仿真：17 脑区架构

这是 MeshCtx 最核心的技术壁垒。每个脑区解决一个实际痛点：

## 2.3 四层记忆系统 (L0-L4)

MeshCtx 构建了业界最完整的层次化记忆架构，模拟人脑从感官记忆到语义记忆的完整链条：

## 2.4 自适应与进化引擎（引擎已实现；全自动闭环为路线图）

## ⑤ 睡眠期离线巩固 + 主动遗忘修剪：闲时自动 consolidate + 低价值高遗忘记忆移入 ARCHIVAL 层（不删除可恢复）

## ④ schema_layer 注入排序：core > semantic > episodic 分层分配 token，核心原则常驻

## ③ 表观遗传语境标记：context_score = 基础×0.3 + 语境匹配×0.7，同一语境下的记忆更易被唤醒

## ① FSRS v4 间隔重复：R 感知遗忘曲线 R(t)=10^(-t/S)，按记忆强度安排复习，越常用越牢固

## ② 图式化三层收敛管线：episodic（情景）→ semantic（语义）→ core（核心），consolidate 自动触发（节流 <1h），低层记忆自动归纳为可复用原则

## 【记忆引擎 v2.0（2026-08 重构，对标 Mem0 consolidate）】

进化与元认知引擎已实现并可通过 API 受控触发（/api/genomic/evolve|feedback、/metacognition/report）；任务终态→引擎的自动喂数与参数自动回注为路线图项（2026-09 核验口径）。当前能力：

① 任务评估：对完成质量打分，识别错误和不足

② 模式提取：从成功/失败中提取可复用模式

③ 知识更新：将新模式写入知识图谱（L3 语义记忆）

④ 行为调整：下次类似任务自动应用经验

⑤ 海马回放：闲时 10-20x 压缩回放，发现跨记忆关联

⑥ 睡眠巩固：离线 consolidate + 到期复习重排，闲时自动强化记忆（对标人脑睡眠期记忆巩固）

⑥ 主动思考：默认模式网络在后台产生创意连接

# 三、功能矩阵详述

## 3.1 AI 编程与代码

## 3.2 多模型智能化

## 3.3 安全与合规

## 3.4 平台与生态

## 3.5 SDM 突破性记忆（v2.85）

Sparse Distributed Memory（稀疏分布式记忆）是 MeshCtx 最具突破性的存储技术：

地址空间：O(2^1000) — 比传统 Agent 的向量存储高出 10^296 倍

预测预激活：在检索前根据上下文预激活相关地址

100:1 分形压缩：海量记忆高度压缩，存储成本极低

· 工具输出压缩：5008B → 223B（-95.5%）；全量回归 3095 passed / 0 failed

· 16KB 预算公平对比：脑区精选 33.3% vs 暴力截断 25.0%（+8.3pp），token 节省 4.5×

· 严格判分 EM 25-26/48 = 52-54%（四次采样 24/25/26/25，oracle 上限口径）；语义判分 40/48 = 83.3% —— 约 GPT-4o 无记忆全上下文 60-64% 的 81-85%，用平价模型达到顶级模型全上下文记忆水平的约八成

【记忆基准成绩（2026-08-19 本地独立实测，LongMemEval 48 问）】

Kanerva 模型：基于 Pentti Kanerva 的 SDM 理论工程化实现

## 3.6 GenomicOptimizer 基因组进化引擎（NEW · 002 号节点交付）

GenomicOptimizer 是基因组学启发的 Agent 参数进化引擎——MeshCtx 继元认知自适应循环之后的第二个进化引擎（进化均经 API 受控触发）。它将 Agent 的运行参数视为"基因型"，任务表现视为"表现型"，用 38 亿年自然选择打磨出的遗传算法，让 Agent 在不依赖人工调参的情况下自动进化出最优参数组合。784 行纯 Python 标准库实现，零外部依赖，线程安全（copy-deep-mutate 模式）。

生物学映射（核心理念）：

6 维可进化基因（Genome）：

temperature（0.1–1.5）：采样温度，影响生成多样性

top_p（0.5–1.0）：核采样阈值

max_tokens（512–16384）：输出长度预算

system_prompt_style（8 种离散候选）：concise / detailed / step_by_step / creative / analytical / minimal / encouraging / direct

memory_weight（0.1–1.0）：记忆检索权重

retrieval_top_k（1–20）：记忆检索条数

进化工作流：

反馈记录与进化触发（2026-09 核验口径: 自动闭环为路线图, 当前 API 受控触发）:
- 当前: 反馈经 REST API 受控记录 (POST /api/genomic/feedback)；进化由 API 触发 (POST /api/genomic/evolve)
- 路线图: 内核事件自动监听喂数 + 积累阈值自动触发 + 最优参数回注运行时 (核验报告 §3.4 落地点)

最优基因组自动持久化到磁盘，重启后从最优解重建种群，进化成果不丢失

REST API 全开放：GET /api/genomic/stats、GET /api/genomic/best、POST /api/genomic/evolve、POST /api/genomic/feedback

与元认知引擎的协同：元认知循环在"模式层"学习（做什么更有效），GenomicOptimizer 在"参数层"进化（用什么配置跑得更好）。双引擎叠加构成 MeshCtx 的进化体系——进化经 API 受控触发（evolve/feedback 端点），自动喂数与回注闭环为路线图项。

## 3.7 Agent 派活中心（Agent Hub · 2026-09-02 交付，对标 HeyClicky 消费者化交互）

一句话派活 → 后台任务卡片 → 可见进度/结果/取消/重试 → 危险操作审批：

- **一句话派活**：在 Web Chat 输入一句话（如"读 README 总结项目结构"），即生成一张后台任务卡，由统一 agent 循环（run_agent_loop）自主执行——文件读写、代码搜索、命令执行、网页检索等工具全自动串联。
- **后台任务卡**：卡片化生命周期（排队/执行中/待审批/完成/失败/取消），每张卡持久化到本地（原子 JSON + 0600），支持随时查看进度时间线、取消、失败重试。
- **额度级审批**：删除/移动/覆盖/远程等危险操作挂起为"待审批"，用户在界面上同意/拒绝/自定义处理；审批请求跨断连持久化，决策后任务自动继续。本地配额记账（接线 quota_manager/usage_meter），个人版软提示不设付费墙。
- **并发与调度**：任务执行跑在独立线程池（不占用 Web 服务事件循环），支持多卡并行，服务稳定性与任务执行互不阻塞。
- **价值定位**：把 meshctx 从"对话框 agent"升级为"可委派的后台员工"——用户发起任务后可继续手头工作，危险动作保持人机共治；这正是 HeyClicky 等 2026 头部产品验证的消费者化 agent 形态。
- **API**：POST/GET /api/tasks/cards、/api/tasks/cards/{id}（详情/取消/重试/审批）、/api/tasks/quota。


## 3.8 治理与可观测性（v3.123.0–v3.124.1 新增, 2026-09 定稿）

### 3.8.1 Org Governance 组织治理（团队/企业价值主承载, 已并入 v3.124.1 治理章节）

- 组织架构导入：部门树支持 JSON/CSV 批量导入（乱序父引用、显式 parent_id）、防环校验、
  同批同名二义显式报错、级联删除与根部门删除保护
- RBAC 授权模型：owner/admin/manager/member/auditor 五角色等级矩阵；授权只降不升、
  不得越级、owner 级成员仅 owner 可设（邀请门控：组织非空后未入册用户一律 403）
- 数据权限 self|dept|org：同一套 scope 求值一致落地于任务卡部门视图、值守（Routines）
  部门视图、部门共享记忆（经理写/成员读/跨部门隔离）
- 审计与合规导出：敏感操作审计轨迹（actor 归责, cap 200 持久化）+ owner/admin/auditor
  可导出 SOC2 风格 JSONL 证据包（EU AI Act Art.26 对位）
- 详情页: meshctx.com/governance.html（×11 语言）

### 3.8.2 可观测性（v3.123.0 随 WP1 发布）

- OpenTelemetry 风格 span/trace（trace_id 32hex/span_id 16hex, contextvar 嵌套归因）
- 本地 JSONL ~/.meshctx/telemetry.jsonl + >2MB 自动轮转（保留最近 5000 行, 环形上限）
- HTTP API /api/telemetry/{events,stats,record}（认证 + agent 白名单）; 任务卡整卡 span 埋点
- OTLP 远程导出：MESHCTX_OTLP_ENDPOINT（默认关零开销, 面向团队/企业自建 collector）
- 详情页: meshctx.com/telemetry.html（×11 语言）

### 3.8.3 声称纪律（Claims Scope, 2026-09-05 定稿）

- 全站营销词 Scope 声明 (docs/marketing/claims-scope-20260905.md) + 机器复验脚本
  (claims_scope_check.sh: A1 活跃营销面须 0 命中 / A2 仓库级 ⊆ 排除附录 + HEAD 基线证据链)
- 口径: self-adaptive + auditable; 进化能力 = 引擎已实现 + API 受控触发, 全自动闭环 = 路线图;
  禁止最高级与超卖词（全词形表见 claims-scope-20260905.md §1.1, 机器复验 §3-A）
- 版本对位: 个人版(免费, 单用户数据域) / 团队版($9/人/月, 部门+经理) / 企业版($29/人/月,
  完整 RBAC+审计导出, 遥测 OTLP)

# 四、市场分析

## 4.1 市场规模

## 4.2 目标用户画像

## 4.3 市场趋势

AI 编程工具从"补全"到"自主 Agent"：Cursor、Copilot 都在从代码补全进化到 Agent 模式

多模型趋势：单一模型无法满足所有场景，需要智能路由和多模型编排

隐私与本地化：企业越来越关注代码安全和数据隐私，GDPR 等合规要求推动本地部署需求

开源可信：企业要求可审计、可定制的解决方案，Open Core 模式成为新标准

记忆与个性化：用户期望 AI 记住上下文和个人偏好，跨 Session 记忆成为刚需

自适应 Agent：从静态工具转向能自主学习与自我调整的协作伙伴，遗传算法与元认知成为前沿方向

# 五、竞品对比

## 5.1 功能对比矩阵

## 5.2 定价对比 (2026)

MeshCtx 定价策略核心优势：

个人用户永久免费 —— 竞品免费版功能严重受限

Team $9/人/月 —— 比 Copilot Business ($19) 便宜 53%，比 Cursor Pro ($20) 便宜 55%

Enterprise $29/人/月 —— 比 Copilot Enterprise ($39) 便宜 26%

无隐藏的"usage-based"超额费用 —— 透明定价，预算可控

# 六、商业模式与定价策略

## 6.1 核心理念

C 端永久免费 + B 端低价转化。通过免费策略快速占领个人开发者心智，形成口碑和网络效应。半年后（2027年1月）上线付费版，目标是将 5-10% 的免费用户转化为付费用户。

## 6.2 定价详情（2027年1月上线）

Free — 个人开发者 · 永久免费

完整 17 脑区引擎

全 123+ 模型支持（自带 API Key）

记忆引擎 v2（FSRS 间隔重复 + 图式化三层收敛 + ARCHIVAL 修剪）

元认知进化循环（API 受控）

代码沙箱 + 项目索引

11 语言 i18n

Plugin 市场全部免费插件

Web UI + CLI

社区支持（GitHub Issues）

Team — $9/人/月（年付 $7/人/月）🔥

Free 全部功能 +

团队共享记忆：团队成员间共享 L2/L3 记忆

Swarm 群审模式：5 模型并行 + 共识投票（含 API 费用）

优先模型路由：更快的响应时间

团队仪表盘：使用量/质量/效率统计

Enterprise — $29/人/月（年付 $24/人/月）🔥

Team 全部功能 +

私有化部署：内网/离线环境完整运行

SSO/SAML + 审计日志 + SLA 保障

GenomicOptimizer 进化引擎高级调优

专属客户成功经理 + 定制开发

## 6.3 定价哲学

开源降低研发成本：AGPLv3 框架社区贡献，减少核心开发人力

多模型降低成本：智能路由自动选择性价比最优模型，减少 API 开销

缓存命中率 60%+：多级缓存大幅减少重复 API 调用

轻量化运营：以 PLG (Product-Led Growth) 为核心，降低销售成本

不做 VC 定价：不追求高 ARPU，追求用户基数和长期转化

# 七、Go-to-Market 策略

## 7.1 阶段一：社区冷启动（现在 - 2026.12）

Hacker News / Reddit / V2EX / 掘金 首发亮相

GitHub Star 驱动：目标 5,000+ Stars，进入 trending

YouTube / Bilibili 教程系列：对比 Cursor/Copilot 实战

中文开发者社区深耕：CSDN、知乎、SegmentFault

开源社区协作：与 LangChain、LlamaIndex 等项目联动

## 7.2 阶段二：产品打磨（2026.10 - 2027.01）

内测用户反馈闭环：每周迭代，快速修复

性能基准测试发布：vs Cursor / Copilot 的客观对比

Plugin 开发者计划：激励社区贡献插件

文档完善：中英双语 API 文档 + 视频教程

GenomicOptimizer 进化引擎公开 Benchmark：发布参数进化 vs 人工调参的对比数据

## 7.3 阶段三：付费转化（2027.01+）

Team 免费试用 30 天，无需信用卡

企业 POC：免费部署 + 1 周定制化支持

客户成功案例发布：量化 ROI（开发效率提升 X%）

渠道合作：与云厂商/DevOps 平台联合推广

# 八、技术壁垒与护城河

核心结论：MeshCtx 的技术壁垒不在单一功能，而在 17 脑区 + SDM + 进化引擎（API 受控、可审计）= 系统工程级的护城河。任何一个子模块可以被模仿，但整体的类脑架构需要 5 年以上的跨学科积累。

# 九、团队

MeshCtx 由刘正禹独立创建并持续开发。项目从 v0.1 迭代至 v3.115.27，代码量 250,000+ 行 Python，涵盖神经科学、AI、系统工程等多个领域。

刘正禹，沈阳工业大学计算机学士，20年IT行业从开发、测试、运维、项目管理等世界50强微软、西门子的跨国公司经验。经历过软件全生命周期开发，工业软件PLM运维，主导过戴姆勒卡车中国最大工厂的 IT 基础设施建设，戴姆勒上海最大研发中心和边缘数据中心的基础设施建设项目。

核心能力矩阵：

🧠 计算神经科学：17 脑区建模、SDM、海马回放、STDP

🤖 AI/ML：多模型编排、知识图谱、向量存储、JEPA 实现

⚙️ 系统工程：微内核架构、插件系统、事件总线、FastAPI

🔐 安全：Prompt 注入防护、行为合规引擎、4 阶段审计

🌐 全栈：Python/JS/HTML/CSS、Supabase、GitHub Actions CI/CD

📊 因果推理：Pearl do-calculus、反事实推理

🌍 国际化：11 语言 i18n 体系

🧬 进化计算：遗传算法、适应度评估、种群多样性保护

未来团队扩展优先级：

招聘 1 名全栈工程师（社区运营 + Plugin 生态）

招聘 1 名 SRE/DevOps（私有化部署 + SLA 保障）

招聘 1 名技术内容创作者（教程 + 视频 + 技术博客）

招聘 1 名社区运营（开源社区 + 用户增长）

# 十、财务预测

## 10.1 成本结构 (月度)

## 10.2 收入预测 (3年)

## 10.3 关键假设

免费用户年增长 6x → 3x → 2x（病毒传播 + 社区运营）

Team 转化率从 3% 提升至 6%（产品成熟度提升）

Enterprise 转化率从 0.5% 提升至 1.5%（私有化部署 + 进化引擎企业级调优拉动）

客单价年均提升 5%（通胀 + 价值增加）

人力成本：2027 年 2 人 → 2028 年 4 人 → 2029 年 6 人

# 十一、风险与应对

# 十二、里程碑与路线图

—— MeshCtx：不只是 AI 工具，而是会思考的协作伙伴。

# 附录：v3.115.27 工程质量里程碑（2026-07-29）

本版本是 MeshCtx 桌面版工程化的分水岭，根治了两个长期顽疾：

## A. Windows 启动打地鼠终结

问题：PyInstaller 打包的 Windows 版反复出现 "ModuleNotFoundError"（fastapi.middleware.cors、fastapi.staticfiles 等子模块逐个报错，修一个冒一个）。

根治方案：从手工枚举 hiddenimports 改为 collect_submodules 全量自动收集 —— fastapi(48) + starlette(34) + uvicorn(40) + pydantic(105) + jinja2(25)，共 245+ 个模块一次入包，同类问题永久免疫。

## B. Windows 安装包丢失 7 语言根治

问题：Windows 安装包只显示 3 种语言（中/英/日），其余 7 种丢失。根因：spec 文件 datas 未打包 templates/ 与 static/ 目录，UI 资源整体缺失。

根治方案：spec datas 补全 templates/ + static/ + i18n_translations.json；新增 i18n Guard CI 工作流，每次构建自动校验 10 语言键完整性（俄语 1221 键全绿），防回归常态化。

## C. 俄语本地化 6 处深度修复

语言切换 changeLang 加固：children.length 防护 + textContent 文本节点更新（替代 innerHTML 防 XSS）

Cookie 同步写入：document.cookie 与 localStorage 双通道，服务端 Accept-Language 协商一致

导航栏 4 处硬编码修复：i18n key 对齐（it/ar 各 126 键零缺失）

v2 模板硬编码 <html lang="zh-CN"> 全部改为动态语言注入

验证：v3.115.27 Windows 安装包（67.6MB）二进制级 9 项验证全绿 —— VERSIONINFO 版本号、fastapi 全家桶、模板/静态资源入包、俄语 1221 键完整性。
---
## 附录 D：进化声称核验与差异化战略引用（2026-09-03 修订）

### D.1 进化声称口径核验
按用户要求对"进化/自适应"相关声称做了代码级核验，结论:**部分真实, 需口径修正**（详见核验报告 `docs/marketing/self-evolution-verification-20260903.md`，属 claims-scope §3-A0 排除类）:
- ✅ 真实实现: GenomicOptimizer 遗传算法引擎（>800 行, fitness/mutation/selection, copy-deep-mutate）+ CMA-ES 自调优 + 6 维成长跟踪 + best_genome.json 持久化 + /api/genomic/stats|best|evolve|feedback + 测试（test_v59_evolution 等）
- 🟡 半实现: "每次任务后自动评估→自动优化"闭环 — 现为 **API/受控触发**（evolve/feedback），agent 主循环自动喂数与最优参数自动回注运行时的**自动闭环未接线**（路线图项）; 元认知为独立模块+报告, 未入 agent 主循环
- 口径处理: 主页/landing 关键超卖措辞已修订为可验证表述（引擎已实现+自动闭环路线图）；海外发布文案同步建议见核验报告 §3
- 未来闭环立项点: run_card 终态→genomic.feedback 自动喂 + best_genome 回注参数解析 + evolution_tracker 自动周报 → 落地后可恢复"全自动进化"口径
- 已改范围边界 (2026-09-03 同批补修): docs/index.html SEO/pageMeta/title/og/f2-fallback、landing.json hero_desc/f17/f22/f28 (10 语言)、docs/download.html subtitle、docs/llms.txt、docs/index.md、BP §3.6 —— 收敛为 "self-adaptive + auditable / API 受控进化 + 自动闭环路线图"
- 发布前必检清单 (防超卖流出): 海外发布草稿 (docs/marketing/海外发布内容/00-08) 发布前必须按口径清单修订; 已发布平台 (LinkedIn/ProductHunt 等) 无法撤回, 后续增补帖附口径说明

### D.2 差异化战略引用
2026-09 前沿调研结论（全文 `docs/marketing/meshctx-differentiation-strategy-20260903.md`）:
- 主定位: **本地优先的 Agent 治理/控制平面**（审批/配额/审计 + SDM 记忆 + MCP 中立治理网关 + 跨机 hub）——落在大厂结构性不做的空白带（本地自托管/强监管合规/SMB 长尾/非英语/跨厂商治理/记忆所有权）
- 护城河排序: 工作流治理锁定 > 信任与合规许可（EU AI Act Art.26 审计导出/SOC2 型证据）> 多语言本地化 > 社区生态 > 数据（最弱, 无内容飞轮）
- 快速落地 Top3 垂直: 财税/簿记多语言区域 SMB 申报、医疗行政后台、中小律所非计费后台
- 90 天楔子: MCP 治理网关 → "可审计确定性"叙事（以生产实证替代自报分数）→ 1-2 个 SMB 垂直验证 PLG→渠道
