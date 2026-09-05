# MeshCtx 全面优化方案（2026-09 差距收窄计划）

- 方案编号：MCTX-PLAN-2026-0903
- 版本：v1.2（002meshctx 1c6be790 + 002codex ef9e75e3 回执并入）　日期：2026-09-03
- 编制：004meshctx（产品/架构）　依据：调研报告 MCTX-RES-2026-0903（004meshctx，2026-09-03）+ 本地代码实证（HEAD 41eb7d90）
- 目标版本窗口：v3.123.0 – v3.124.0（一个季度内收窄 P0/P1 差距至"可竞争水位"）

---

## 1. 背景与依据

调研报告 MCTX-RES-2026-0903 核心结论：2026 年 AI Agent 竞争已进入"**能办事 + 标准化 + 可治理**"三线并进阶段（AAIF 成立、MCP 安装 9700 万、AISI/NIST 治理监管化提速）。MeshCtx 在**治理基座**（审批流/配额/审计/action_gate）与**脑启发架构**（17 脑区/IIT/JEPA/元认知）上是差异化领先项（🏆），标准化基本跟上（✅），但在四个维度存在 **P0 级差距**：浏览器自动化、记忆产品化、可观测性、评测公信力；另有五项 P1（多 Agent 编排、工具生态、例行值守、常驻运行时、模型覆盖）。

根因判断（报告第八章）：差距多数是"**工程铺量**"型而非"架构代差"型，可通过聚焦补课在一个季度收窄——本方案即该判断的执行设计。

## 2. 基线核实（方案前实测复核，非照单全收）

方案编制前对报告关键论断做了代码级复核，**三处口径修正**：

| # | 报告口径 | 实测（HEAD 41eb7d90 / 2026-09-03） | 处理 |
|---|---|---|---|
| 1 | 全库历史基线 2846 passed / 118 failed / 92 errors（Py3.14 持续修复） | 全量回归实测 **3663 passed / 59 skipped**（0 failed）；hub 套件 51 passed ×3 | 修正：当前基线为 3663/59，报告引用了过旧记录 |
| 2 | MCP server "312 行 13 defs/classes" | `src/mcp_server.py` 实际 **412 行 / 23 defs/classes** | 修正：按 412 行 / 23 定义计（P1-2 目标相应上调） |
| 3 | 可观测性 "print 级日志" | 新 Agent Hub 代码已用 `logging`（`meshctx.task_cards` logger）；缺的是**结构化 span/trace** 与导出 | 修正：缺口 = 无 span 化追踪/无 OTLP 类导出，非字面 print |

其余论断（swarm 模板存在但 0 可用 worker、`/api/memory/human/*` 为内部应用 API 而非对外 Memory-as-a-Service、Docker 沙箱无网络最小化基线、测试无官方榜提交、62 工具含 61% stub）经抽查**确认成立**。

## 3. 方案定位与目标

- **定位**：不做"追平头部所有产品形态"的全面模仿（浏览器 Agent/常驻 VM 等形态代差非本季度目标），而是做**治理基座 × 可观测 × 记忆商品化 × 公信力**的组合拳——把已领先的治理能力产品化、把缺失的工程基座补齐，让"安全可控的全脑 Agent"叙事有公开证据支撑。
- **目标**（季度末可验证）：
  1. 可观测性：核心链路（agent_loop / task_cards / hub / 工具调用 / 审批配额）100% span 化，消灭 print 链路；
  2. 评测公信力：官方 SWE-bench Verified harness 跑通并出可发布成绩页（替代内部启发式口径）；
  3. 记忆产品化：对外 Memory API（HTTP + MCP 双形态）上线，LongMemEval_S 跑分出公开成绩；
  4. swarm 从模板到 ≥2 worker 实测编排；
  5. MCP 定义 23 → ≥40；
  6. Routines（定时/事件触发值守）统一进 task_cards 运行时；
  7. 沙箱硬化基线落地 + 治理白皮书（NIST 对标）发布。

## 4. 总体架构决策（先定边界再动手）

沿用 Agent Hub（Task Cards）已验证的架构模式：**开源核心 + 闭源增强 + 版本门控**，任何新能力不破坏既有 edition 检测与安装器机制。

| 决策 | 内容 | 理由 |
|---|---|---|
| D1 | 新工作包一律**加法式**：新增模块/路由/表，不改既有 41eb7d90 语义；全部可回滚 | 用户铁律：历史版本保存好、不行就回滚 |
| D2 | **task_cards 作为统一值守运行时**：Routines（P1-3）与 swarm worker 任务（P1-1）都落成任务卡，复用 CardWorker 线程模型/配额/审批/恢复 | 报告 P1-3 建议"统一进 task_cards"，且复用已三审加固的代码 |
| D3 | 观测埋点走**自研轻量 telemetry core**（span 上下文 + JSONL 本地 + 可选 OTLP 导出），不引入重依赖框架 | 报告 P0-1 对位 Langfuse/OTel；个人版免费不能背云成本，闭源版才接托管 |
| D4 | 记忆产品化**复用现有 sdm/memory_v2 内核**，只加"商品化外衣"（对外 API + 鉴权 + 命名空间隔离 + 跑分），不改内核算法 | 报告第五章结论：缺三件外衣，非缺内核 |
| D5 | 评测 harness 独立于主程序（`benchmarks/` 目录 + CI 独立 workflow），不污染运行时 | 官方榜提交需要受控环境与凭据，不进日常 pytest |
| D6 | 治理白皮书 = 既有 审批+配额+审计+action_gate **打包成 Agent Governance 模块**（对外 API + 文档），零新逻辑、纯产品化表达 | 报告 P2-1：把先发优势变话语权 |

## 5. 工作包详设

> 每个 WP 标注：目标 / 落地清单 / 开源闭源边界（edition 策略）/ 验收 / 工作量。工作量按"单人 + 多 Agent 辅助"计。

### WP1 — P0-1 可观测性（Telemetry Core）　预估 1.5 周

- **目标**：全链路结构化追踪，消灭 print 级链路；个人版本地 JSONL 可视，团队/企业版 OTLP 导出。
- **设计**：
  - **扩展现有** `src/core/telemetry.py`（v3.122.0 已有 134 行 TelemetryStore：平铺事件 + JSON 落盘 + `get_telemetry()` 单例 + `/api/telemetry/events|stats|record` 路由，main.py ~L8286+；002codex P2-2 澄清命名冲突，非从零新增）：保留 `record/events/stats` 既有 API **与既有路由** 兼容，新增 `Span`/`Tracer`/`trace_ctx`（contextvar）span 语义 + JSONL **轮转落盘**（大小上限，防长跑磁盘膨胀，002meshctx P3①）+ 可选 OTLP exporter（HTTP，feature flag `MESHCTX_OTLP_ENDPOINT`，默认关）。
  - 埋点接入点（均为既有代码 + 装饰器/上下文管理器，侵入最小）：`run_agent_loop`（span: card_id/agent 轮次/工具调用/耗时）、CardWorker 线程（queue→run→terminal 状态机）、hub 收发（msg 级）、配额 consume/approval decide、62 工具调用。
  - 审计日志（现 audit.log）与 trace 的关联字段：card_id/request_id 贯通。
- **edition 边界**：telemetry core + JSONL 本地查看 = 开源个人版；OTLP 导出与"治理面板"（trace 检索/配额看板 UI）= 团队/企业（走 `_EDITION_ROUTE_MAP` 隐藏）。
- **验收**：核心 4 链路 span 覆盖断言测试（如跑一张卡 → JSONL 含完整 span 树含耗时）；print 扫描清零（lint）；feature flag 关闭时零开销。
- **工作量**：1.5 周（core 0.5 + 埋点 0.5 + 测试/清理 0.5）。

### WP2 — P0-2 评测公信力（Benchmark Harness）　预估 2–3 周

- **目标**：官方口径可发布成绩：SWE-bench Verified + GAIA（+ 顺带 LongMemEval_S runner 供 WP3 复用）。
- **落地清单**：
  - 新增仓库根 `benchmarks/`：`swebench_verified_runner.py`（官方镜像/容器内跑、FAIL_TO_PASS/PASS_TO_PASS 判定）、`gaia_runner.py`（提交协议 + 结果 JSON 规范化）、`longmem_runner.py`（WP3 用）。
  - 独立 CI workflow（`benchmark-nightly.yml`，凭据 gated、仅手动/定时触发，不进日常 pytest）。
  - 结果页：`docs/benchmarks/index.html`（10 语言 i18n 复用现有管线）展示**分口径**成绩（自测 vs 官方提交状态），避免报告第八章"口径警示"的坑。
  - 内部启发式 v8 保留为开发快循环，但对外只讲官方口径。
  - **longmem_runner 前置**（002meshctx P3）：随 SWE harness 第一批交付（T1 前半），供 WP3 T3 跑分直接复用，避免 T3 阻塞。
- **edition 边界**：harness 开源（AGPL，含运行脚本与文档）；**官方榜提交账号/凭据与分数归属**为运营资产不进仓库（同 provider_config 处理）。
- **验收**：SWE-bench Verified 官方容器在本仓库可复现跑通 ≥1 个样本集；结果 JSON 字段齐全；成绩页 i18n 10 语言渲染无缺键（复跑 docs i18n 套件）。
- **工作量**：2–3 周（SWE harness 1 + GAIA/提交 0.5 + 页面/管线 0.5 + 试跑调参 0.5–1）。

### WP3 — P0-3 记忆产品化（Memory as a Service）　预估 2–3 周

- **目标**：对外 Memory API（HTTP REST + MCP 工具双形态）+ LongMemEval_S 公开跑分；个人版本地自托管、团队/企业版多租户托管。
- **设计**：
  - 新增 `src/core/memory_api.py` 路由组 `/api/v1/memory/*`：`store / recall / search / delete / namespaces`；**API key 鉴权**（复用现有 key 管理 + 审批/审计写入）；命名空间隔离（per-user/per-project 已有 scoping 升级为对外 tenant 语义）。
  - MCP 侧：`mcp_server.py` 增 `memory_store / memory_recall / memory_search` 工具（与 WP5 计数打通）。
  - 复用内核：sdm_memory / memory_v2 / human_memory 只做适配层 + 一致性/冲突策略文档，**不改内核**（D4）。
  - LongMemEval_S：复用 WP2 runner，先出**内部分口径跑分**（oracle/reasoner 分表），对外发布与 Mem0/Zep 对照表并列口径。
- **edition 边界**：HTTP/MCP 对外 API + 本地命名空间 = 开源个人版；多租户托管、跨设备同步、知识图谱（topo_memory 增强）与用量计费 = 团队/企业闭源。
- **验收**：对外 API e2e 测试（key 鉴权 401/403、跨 namespace 隔离、审计落账）；MCP 三工具可用；LongMemEval_S 跑分文档 + 成绩页挂出。
- **工作量**：2–3 周（API+鉴权 1 + MCP/适配 0.5 + 跑分 0.5–1 + 文档/页 0.5）。

### WP4 — P1-1 Swarm Worker 实测落地　预估 1–1.5 周

- **目标**：swarm 从"模板 + 0 worker"到 **≥2 worker 编排实测**（对齐 CrewAI/AutoGen 最低水位）。
- **设计**：
  - 复用 `agent_swarm_v2.py`（WORKER 角色枚举已在）与 hub 队列：leader 通过 `hub:tasks` 派发子任务 → 2 worker 各自独立拉取执行 → 结果聚合回 leader（产物落盘/记忆）。
  - 同机 2 worker e2e + 跨机（hub 通道）冒烟各一。
  - 与 task_cards 打通（D2）：swarm 任务以任务卡形式可见/可配额/可审批。
- **edition 边界**：编排核心（2 worker 内）开源个人版；多 worker 编排、团队共享 swarm、配额池化 = 团队/企业（swarm 路由已在 personal 隐藏的 36 路由清单内，保持）。
- **个人版落地路径**（002codex P3 澄清）：personal 隐藏 `/api/swarm/*`（main.py ~L688），个人版 swarm **不经 swarm HTTP 路由**，而是经 task_cards 接口以**派生 swarm 任务卡**形态落地（D2：leader 创建 swarm 卡 → worker 经 hub 队列拉子任务 → 卡级可见/配额/审批/审计），验收以"个人版可创建 swarm 任务卡并完成 2-worker 编排"为准，避免无个人版入口的验收盲区。
- **验收**：e2e 测试 ≥2 场景（同机聚合 + 失败重试）；hub 冒烟跨机 1 场景；测试进套件。
- **工作量**：1–1.5 周。

### WP5 — P1-2 MCP 扩展（23 → ≥40 定义）　预估 1.5–2 周

- **目标**：MCP 工具/定义从 23 扩到 ≥40，覆盖：记忆（WP3 三工具）、任务卡控制（spawn/list/approve/cancel，复用 `/api/tasks/cards` 语义）、治理（配额查询/审批查询）、浏览器（Web2API 桥接）、观测（trace 查询）。
- **落地**：`mcp_server.py` 增量 + 每工具 schema 测试 + `docs/mcp.md` 更新（i18n 后补）。
- **交付边界**（002meshctx P3，防范围蔓延）：桥接 = 经 MCP 工具调用 Web2API 发起受控网页操作，**≠** 常驻浏览器/Computer Use 产品形态；本 WP 不含浏览器会话管理、视觉定位等；范围蔓延项一律记入 3.125+ 立项评估清单。
- **验收**：≥40 定义；每个新工具 ≥1 测试（schema 校验 + 授权路径）；mcp 测试套件绿。
- **工作量**：1.5–2 周。

### WP6 — P1-3 Routines 例行值守　预估 1–1.5 周

- **目标**：定时 + 事件触发值守统一进 task_cards（对位 Claude Code Routines）。
- **设计**：
  - 新增 `src/core/routines.py`：Routine 定义（cron 表达式/间隔/事件钩子 [新消息、hub 事件、文件变化] → 模板化派活参数）→ 到点/触发即 spawn 任务卡（复用 HubQuota/审批）。
  - 存量 `scheduler.py`/`channel_scheduler.py` 迁移为 Routine 实例（保留旧入口兼容，版本内双跑；**删除点定于 3.124.0 里程碑**，002codex P3① 明确版本）。
  - UI：chat.html 派活面板加 "⏰ 值守" tab（10 语言键复用管线新增 ~30 键）。
- **edition 边界**：单机定时值守开源个人版；事件值守（多 hub 事件）与跨机调度 = 团队/企业。
- **验收**：定时触发 e2e（1 分钟粒度 mock 时钟）；事件触发 e2e；旧调度迁移兼容测试。
- **工作量**：1–1.5 周。

### WP7 — P1-4 Docker 沙箱硬化　预估 1 周

- **目标**：回应 Artifactory 型逃逸 / AISI 越权事件类风险：沙箱默认网络隔离 + 最小权限基线。
- **落地清单**：docker-compose/run 基线改：默认 `--network none`（白名单端口才开）、只读 rootfs（仅 /workspace 可写）、内存/CPU 限额、seccomp profile、无宿主密钥 env 直传（改 secret 挂载）、动作级网络授权（action_gate 联动）；`docs/security/sandbox-baseline.md`（中英双语起步）。
- **验收**：逃逸路径测试集（禁网/禁宿主密钥/只读根）通过；既有沙箱用例无回归。
- **工作量**：1 周。

### WP8 — P2-1 Agent Governance 模块 + 白皮书　预估 1–1.5 周（可并行）

- **目标**：把先发优势变成话语权：治理能力打包为对外模块 + NIST/Cisco Zero Trust 对标白皮书。
- **落地清单**：`src/core/governance_api.py`（只读治理 API：审批流查询/配额/审计导出）——**复用既有 `agent_governance.py`**（进程内 identity/quota/policy/audit，002codex P3 澄清：只做对外聚合层，零新逻辑）；`docs/governance/whitepaper.md`（NIST 主动能身份/最小权限/可审计映射表 + AISI 案例对照 + MeshCtx 实现映射）；meshctx.com 治理页（10 语言 i18n）。
- **验收**：治理 API 测试；白皮书章节完整性 checklist；页面 i18n 套件绿。
- **工作量**：1–1.5 周（可与其他 WP 并行）。

### WP9 — P2-2 企业 HA（评估项，本季度不承诺落地）

- 单机→HA/灰度/多租户 仅做**架构评估文档**（`docs/plans/enterprise-ha-eval.md`），记录：状态外置（卡/配额/审计到 Postgres）、多实例互斥（worker leader election）、灰度（edition 版本切换）。不进 3.124.0 排期。

## 6. 依赖与排期（周粒度，单人 + Agent 辅助）

依赖关系：
- WP1（观测 core）无前置，且后续 WP 埋点受益 → **先做**。
- WP6（Routines）依赖 task_cards（已完成）→ 可与 WP1 并行。
- WP7（沙箱）独立 → 可与 WP1 并行。
- WP2（harness）独立；WP3 的跑分复用 WP2 的 LongMem runner → WP2 先行半个身位。
- WP5（MCP 扩展）部分依赖 WP3 的记忆工具 → WP3 API 先行。
- WP8（白皮书）纯文档聚合 → 任意时刻并行。
- WP4（swarm）依赖 hub 与 task_cards（已就绪）→ 中段插入。

```
T0（第 1–1.5 周）: WP1 观测 core（0.5）+ WP6 Routines 起步 + WP7 沙箱硬化
    ← 002meshctx P3: 原 T0 单周 WP1+WP6+WP7 ≈3 人周, 超出单人+agent 单周产出,
       T0 放宽至 1.5 周; WP6/WP7 收尾计入 T1
T1（第 2–2.5 周）: WP1 埋点收尾（0.5）+ WP6/WP7 收尾 + WP2 SWE harness v1
    （含 longmem_runner 前置）+ WP8 白皮书
T2（第 3–3.5 周）: WP2 GAIA/成绩页 → WP3 Memory API（HTTP/MCP）→ WP5 MCP 扩展
    （半周错峰启动, 002codex P3: T2 单周三 WP 偏挤）
T3（第 4 周）: WP3 LongMem 跑分/成绩 + WP4 swarm 2-worker + WP5 收尾(≥40)
T4（第 5–5.5 周）: 全量回归 + 文档/BP/10 语言联动 + 三方审计 round 2 + 发版 3.124.0
```

里程碑版本：**3.123.0**（T0–T1 产物：telemetry/routines/沙箱/白皮书）→ **3.124.0**（T2–T3 产物：harness/memory API/MCP/swarm）。总日历 **5.5 周**（T0 放宽后）。里程碑内保留 **WP 级缓冲**（002codex P3: 9 WP/5.5 周单人+agent 排期紧，防单 WP 超期拖垮整里程碑）。每里程碑打 tag + `~/meshctx-backups/` 快照（沿既有回滚机制）。

## 7. 版本 / edition / 商业化映射

| 能力 | 个人版（开源 AGPL） | 团队版 $9 | 企业版 $29 |
|---|---|---|---|
| Telemetry 本地 JSONL / 查看 | ✅ | ✅（含导出） | ✅（含治理面板） |
| 对外 Memory API（本地命名空间） | ✅ | ✅（多设备同步） | ✅（多租户托管 + 计费） |
| Routines 定时值守 | ✅ | ✅（事件值守） | ✅（全部） |
| Swarm | ≤2 worker 实测 | 小规模编排 | 大规模 + 配额池化 |
| Benchmark harness | ✅ 开源 | — | 官方榜资产（运营） |
| 沙箱硬化 / 治理白皮书 | ✅ / ✅ | ✅ | ✅ + SOC2 类导出 |
| MCP ≥40 工具 | ✅ | ✅ | ✅ |

个人版永远是能力演示底座（open-core 定位不变）；卖点在**托管/多租户/治理导出**，全部复用 WP 已建模块，无新内核。

## 8. 多语言、文档与 BP 联动

- 新增页（benchmarks / governance / memory api）文案走既有 i18n 管线：`docs/i18n/landing.json` 增量键（估 +80–120 键 ×10 语言）→ docs 子页重建 → docs i18n 套件（24 passed 基线）复跑。
- `docs/llms.txt`、`docs/api.md`、`docs/architecture.md` 按 WP 落地增量追加。
- BP（`docs/marketing/MeshCtx_商业计划书_v3.116.md`）：新增章节——治理白皮书摘要、记忆商品化路线、评测公信力计划；三版本定价理由补"托管/导出"价值锚点。
- 报告建议的 OpenClaw 对标叙事（Mesh 化个人 Agent 集群）与中文生态位（10 语言 i18n）写入市场段。

## 9. 测试与质量门（每个 WP 合入前）

1. 新增测试 ≥ 覆盖面断言（不降既有：hub 51 / 全量 3663 基线为准）；
2. docs i18n 套件 24 passed 不回归；
3. `test_project_integrity` 34 passed（安装器 md5 对一致）；**新增即登记**（002meshctx P3 补强 + 002codex 澄清）：install-edition.sh 按 `src/core/*.py` glob 物理拷贝（新模块自动随版，无需改拷贝白名单，002codex 已核验），故新增核心模块的硬性登记点 = personal 路由隐藏清单（含 /api 路由时）+ project_integrity 覆盖清单 + CHANGELOG；36 路由隐藏清单不漂移；
4. edition 门控测试（personal 隐藏 36 路由清单不漂移）；
5. lint：print 清零 / GC 严格模式无 unraisable 警告（沿用 43 passed 标准）。

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 官方榜提交环境不可得/凭据缺失 | harness 与成绩页解耦：先出"本地复现 + 方法学"页，提交为第二步 |
| Memory API 对外开放引入隐私面 | 默认本地命名空间 + API key + 审批/审计全覆盖；对外前安全评审（WP7 基线复用） |
| OTLP/重观测引入性能开销 | feature flag 默认关；埋点采样率可配；个人版 JSONL 轻量 |
| swarm/值守改变既有调度行为 | 旧 scheduler 兼容双跑一个版本再删；任务卡审批兜底 |
| 10 语言新增键量过大 | 分两批：先 en/zh 全量 + 其余 8 语言键值对齐脚本（既有工具） |
| 任一 WP 翻车 | 每里程碑 tag + backups 快照 + 加法式提交（可单 WP revert）——沿用 agent-hub 回滚机制 |
| telemetry JSONL 长跑磁盘膨胀（002meshctx P3①） | JSONL 轮转 + 大小上限 + 采样率可配（WP1 已并入设计） |
| WP7 沙箱基线变更破坏既有用户 compose（002meshctx P3②） | 兼容模式 + 迁移说明文档 + 版本升级提示（breaking change 显式标注） |
| 记忆对外 API 隐私合规（GDPR 删除请求，002meshctx P3③ 低优） | 删除端点 + 数据留存策略文档（进 WP3 收尾清单） |
| 个人版 Memory API 开源被 fork 白嫖托管形态（002codex P3②） | open-core 固有风险; 商业化条款显式声明（托管/多租户/企业治理为增值层，与开源本地版区分; 品牌/文档/基准分数沉淀于官方渠道） |

## 11. 三方审计范围与节奏

- **本方案即送审对象**：审计方核对——目标合理性 / WP 拆分与 edtion 边界 / 排期依赖 / 风险覆盖 / 与 41eb7d90 既有代码兼容性。
- 审计节奏沿用既有协议：方案 v1.0 送审 → 三方回执（P2/P3 意见）→ 方案修订 v1.1 → 按 T0 开工；每里程碑（3.123.0 / 3.124.0）合入前再送审一轮。
- 审计回执通道：meshctx profile 收件箱（002meshctx / 002codex / 004meshctx），项目路由 meshctx。

## 12. 附录

### A. 工作量汇总

| WP | 项 | 预估 | 里程碑 |
|---|---|---|---|
| WP1 | P0-1 可观测性 | 1.5 周 | 3.123.0 |
| WP2 | P0-2 评测公信力 | 2–3 周 | 3.124.0 |
| WP3 | P0-3 记忆产品化 | 2–3 周 | 3.124.0 |
| WP4 | P1-1 swarm | 1–1.5 周 | 3.124.0 |
| WP5 | P1-2 MCP 扩展 | 1.5–2 周 | 3.124.0 |
| WP6 | P1-3 Routines | 1–1.5 周 | 3.123.0 |
| WP7 | P1-4 沙箱硬化 | 1 周 | 3.123.0 |
| WP8 | P2-1 治理白皮书 | 1–1.5 周（并行） | 3.123.0 |
| WP9 | P2-2 企业 HA | 评估文档 0.5 周 | 3.124.0 后 |

合计：约 5 周串行当量（多线并行下 5 周日历）。

### B. 决策记录（本方案 vs 报告路线图的取舍）

1. 报告路线图 P0-1→P0-3 逐项照做，但**排序调整**：观测（WP1）前提化，Routines（WP6）前移——因 task_cards 已就绪、见效最快且为 swarm/值守共用底座。
2. 报告路线图 P1-3 建议"统一进 task_cards"采纳为 D2 硬约束。
3. 报告 P0-3 记忆"托管/自托管双形态"按 edition 拆分（个人自托管开源 / 团队企业托管闭源），维持 open-core 定位。
4. 浏览器自动化（报告 P0 第 1 维）**明确不在本季度**：产品形态代差（常驻 VM/浏览器 Agent）需要产品定位决策而非工程补课，列为 3.125+ 立项评估（可选项：Web2API 强化 + MCP Browser 桥接作为低成本中间形态，放 WP5 内）。

### C. 术语

- AAIF：Agentic AI Foundation（OpenAI/Anthropic/Google/Block 共建）
- OTLP：OpenTelemetry 协议导出
- LongMemEval_S：500 题长程记忆基准（每题≈115k tokens）
- SWE-bench Verified：GitHub 真实 issue 编码基准（官方 FAIL_TO_PASS/PASS_TO_PASS）

## 13. 审计修订记录（v1.0 → v1.1）

### 13.1 三方回执并入（002meshctx 1c6be790，2026-09-03）
- ✅ 目标/取舍/兼容性/风险总评: 同意方案架构与 open-core 取舍, 可进入实施; 主要阻塞项 = P2-2（随首个代码 WP 落地前闭环——已修复, 见 13.2）
- P3 意见并入: ① WP5 桥接交付边界写明（§5 WP5 已加"桥接≠常驻浏览器"）; ② 排期放宽 T0→1.5 周、WP6/WP7 收尾进 T1（§6 已改）; ③ WP2 longmem_runner 前置（§5 WP2 已加）; ④ "新增即加清单"硬性门禁（§9.3 已改）; ⑤ 风险表补 telemetry JSONL 轮转 / 沙箱 compose 兼容 / GDPR 删除（§10 已加 3 行）
- 002codex / 004meshctx 回执: 尚未到达本收件箱（截至 v1.1 提交时; 到达后并入 v1.2 或作为代码 WP 落地意见）

### 13.2 前置勘察并入（存 /tmp/opt_prep_notes_v11.md）
- WP1 从"新增 telemetry"改为"扩展现有 src/core/telemetry.py（134 行 TelemetryStore）+ span 语义/OTLP"（§5 WP1 已改）
- WP6 scheduler.py 接口映射表（schedule_periodic/delayed/cancel_all/list_tasks）; WP4 swarm stub 确认

### 13.3 代码修复（随 v1.1 提交）
- **P2-2 decide_approval 跨卡污染**（002meshctx 实测复现, src/core/task_cards.py L649）: 原实现对无关卡 `discard` 后 `not in reqs` 恒真 → decided_card 被覆盖为迭代末尾无关卡; 双卡并发审批时目标卡漏登记（P3 防抖失效）+ 无辜卡被强制清 pending 且 WAITING_APPROVAL→RUNNING 失真
  - 修复: 只登记真正包含 request_id 的卡（`if request_id in reqs: discard; decided_card=card_id; if not reqs: pop; break`）
  - 回归测试: `test_approve_multi_card_no_cross_contamination`（双卡并发 decide, 断言无辜卡不被污染 + 映射清空）
  - hub 套件 52 passed（51 + 1 新）

### 13.4 002codex 回执并入（ef9e75e3，2026-09-03；方案 v1.1 → v1.2）
- ✅ 目标/取舍/依赖/风险: 条件通过; 结论 = 修订 P2-1(decide owner)+P2-2(telemetry 命名) 后可按 T0 开工
- 🔴 P2-1 [41eb7d90 代码]: decide_approval owner 判定跨卡污染 — 与 002meshctx P2-2 同根因, 已在 ffb56186 修复; 002codex 建议的修复形态 (discard 前判 in reqs) 与实现一致
- 🔴 P2-2 [方案]: WP1 telemetry.py 命名冲突 — v1.1 已改"扩展现有"+ 既有 /api/telemetry 路由兼容注记 (本版 §5 WP1 补全, main.py ~L8286+)
- P3 代码项: cancel WAITING_APPROVAL 卡仍受 120s 审批超时 — 已修复 (见下) + 回归测试
- P3 方案项并入: T2 半周错峰 (§6) / 里程碑 WP 级缓冲 (§6) / scheduler 删除点定 3.124.0 (§5 WP6) / Memory API fork 商业化条款 (§10) / WP4 个人版派生 swarm 卡落地路径 (§5 WP4) / WP8 复用 agent_governance.py (§5 WP8) / §9.3 登记点澄清 (install-edition glob 自动拷贝)

### 13.5 代码修复（随 v1.2 提交）
- **P3 cancel WAITING_APPROVAL 即时收尾**（002codex ef9e75e3 P3[41eb7d90]）:
  - cancel() 对 WAITING_APPROVAL 卡调用新 helper `_reject_card_approvals(card_id)`: 对卡内全部挂起审批 future 投
    {"action":"reject"} (经 fut.get_loop().call_soon_threadsafe), 即时解除卡线程 wait_for(fut,120s) 阻塞
  - task_card_runner._waiter 增加 is_cancelled 双检查 (await 前 + 拿到 future 后), 防取消后 agent 再请求审批重新阻塞
  - 回归测试: test_cancel_waiting_approval_resolves_pending (断言 future 立即 done + action=reject + 映射清空)
  - hub 套件 53 passed (52 + 1 新)

## 14. 实施进度 (里程碑 3.123.0, T0 进行中)

| WP | 状态 | 提交 |
|---|---|---|
| WP1 P0-1 可观测性 | ✅ 阶段1-3 | dd815b2a / 4755c14e / 9fa5f7a7 (span core+卡级 trace+runner 事件遥测, 含 OTLP 开关/JSONL 轮转) |
| WP6 P1-3 Routines | ✅ 核心+API+接线 | 98b96aa2 / a87abf96 (routines.py + routines_api.py + lifespan) |
| WP7 P1-4 沙箱硬化 | ✅ 基线落地 | 32b6b64e (sandbox_policy.py + 16 tests + baseline doc) |
| WP8 P2-1 治理白皮书 | ✅ 文档 v1.0 | (docs/governance/whitepaper.md, 本批) |
| SOP QA/发布流程 | ✅ v1.1 | docs/release/qa_release_sop_v1.md (三方审计 P2/P3 并入, v3.124.0 起强制) |
| WP2 P0-2 评测 harness | ✅ 阶段1+2 | benchmarks/ 全套 + nightly CI + 成绩页; LongMem 样例跑分 (demo-scale self_run em=0.8, 检索基线管线验证); 真实官方榜提交=运营凭据项 |
  + benchmark-nightly.yml + docs/benchmarks 页; 真实榜提交待凭据 runner |
| WP3 P0-3 Memory API | ✅ + LongMem 管线 | memory_api.py + LongMem 样例跑分 (10QA 检索基线, demo 标注, 守护测试) — 官方提交待凭据 |
  owner 隔离, CJK bigram 检索零依赖) + tests 7 |
| WP5 P1-2 MCP 扩展 | ✅ 23→43 defs | mcp_server +17 工具 (memory×5/tasks×5/routines×4/quota/telemetry×2) + tests 9 |
| WP6 UI 值守 tab | ✅ | 176c654a (chat.html ⏰ Routines 折叠区 + 10 语言 10 键) |
| 里程碑 3.123.0/3.123.1 / 3.124.0 | ✅ 已发版 | v3.123.0/3.123.1 + v3.124.0 (2977caf6, tag v3.124.0 资产构建全绿); checksum .sha256 回填+workflow 内嵌=3.124.1 |

实测基线: 全量 3695 passed/59 skipped @ a87abf96; T0 套件 83 passed;
sandbox 16 passed; 每提交均推送 meshctx main, 加法式可回滚。

## 14b. 实施进度权威小结（2026-09-04 修订, 取代被覆盖的旧 §14 表格）

| WP / 里程碑 | 状态 | 说明 |
|---|---|---|
| WP1 可观测性 (P0-1) | ✅ | telemetry span/trace/OTLP + 卡级 trace + runner 事件埋点 (dd815b2a/4755c14e/9fa5f7a7) |
| WP6 Routines (P1-3) | ✅ | routines 核心+API+UI+e2e (98b96aa2/a87abf96/176c654a/21e22359) |
| WP7 沙箱硬化 (P1-4) | ✅ | sandbox_policy + 逃逸分级 + 基线文档 (32b6b64e) |
| WP8 治理白皮书 (P2-1) | ✅ | docs/governance/whitepaper.md + 全站口径收敛 (5 轮补丁, 留证 v4) |
| WP2 评测 harness (P0-2) | ✅ 阶段1+2 | benchmarks 全套 + nightly CI + 成绩页 + LongMem 样例跑分 (demo-scale) |
| WP3 Memory API (P0-3) | ✅ | /api/v1/memory (owner 隔离/GDPR/CJK bigram) + LongMem 管线 |
| WP4 swarm (P1-1) | ✅ | 派生任务卡编排 + e2e 4 (90d987d6) |
| WP5 MCP 扩展 (P1-2) | ✅ | 23→43 defs +17 工具 |
| R7 网站/口径 | ✅ | 首页 4 卡 ×10 语言 + 自进化核验与文案收敛 |
| **里程碑 v3.123.0 / v3.123.1 / v3.124.0** | ✅ 发版 | tag 已推, 三方审计全程闭环, Release 12+12 (sha256 sidecars) |
| **Org 组织治理 (2026-09 用户新需求)** | ✅ **并入 3.124.1 治理章节定稿** | 阶段1-4 (beb11ca8→959edad4) + 审计补丁链三方闭环 (f1eef868→7ff303f0) + R7.1 详情页 ×10 语言 (9fb30f89) + claims-scope 定稿 (ebb8ee97); 002meshctx 4208f9fe 判定 ✅; 002codex 补丁轮4 回执待达 |
| QA/Release SOP | ✅ v1.1 | docs/release/qa_release_sop_v1.md (G1-G10 + R0-R7, 自 v3.124.0 强制) |
| Org 审计补丁链 三方闭环 (f1eef868 → 7e2be84b → 7ff303f0) | ✅ 2026-09-05 | P2-1 邀请门控 + P2-2 RBAC 闭包 + P3×8 全修 + P3-B 服务端词表 (7e2be84b) + P3-5 upsert 校验先于变异原子性 (7ff303f0); org 套件 27 passed, 全量 3784 passed/59 skipped; 复验: 002meshctx 3a5e7cac ✅ + 002codex f28777d8 ✅ final + 004meshctx 3610f357 round19 闭环 — **Org Governance 可并入 3.124.1 治理章节** |
| R7.1 治理/遥测详情页 ×10 语言 | ✅ 2026-09-05 | docs/governance.html (Org Governance: 导入/部门树/RBAC/数据权限/审计导出/版本范围, 44 keys ×10) + docs/telemetry.html (结构化追踪/JSONL 轮转/API/卡级 trace/OTLP, 38 keys ×10); 键位/运行时自检 node 通过, 无超卖词 |
| 营销词 Scope 声明 (002codex 6c70eaf8) | ✅ 定稿 2026-09-05 | docs/marketing/claims-scope-20260905.md + claims_scope_check.sh (A1 活跃面须 0 / A2 ⊆ §3-A0 排除附录 + HEAD 基线) — 5 轮补丁 (RTL 六页/词表全词形/BP 9 处收敛/证据闭环); 002meshctx 4208f9fe ✅ 通过四项全满足 → **claims-scope 定稿**; 004meshctx round21 ✅; 002codex 补丁轮4 回执待达; 证据 copy-scan-20260905-claims.txt HEAD=ebb8ee97 |
| 进行中/backlog | 🔄 | workflow checksum 内嵌 (4a7d02a9 已含) · WP2 真实榜提交(运营) · WP4 跨机冒烟(运维) · P4 观察余项 (manager 权限冗余/审计签名/记忆 key 前缀/scope 单一 enforce 层/读操作写副作用/org-plan 联动 — CSV 转义与成员最小暴露已修/内建) |
