# MeshCtx 全面优化方案（2026-09 差距收窄计划）

- 方案编号：MCTX-PLAN-2026-0903
- 版本：v1.0（待三方审计）　日期：2026-09-03
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
  - 新增 `src/core/telemetry.py`：`Span`/`Tracer`/`trace_ctx`（contextvar）+ JSONL 落盘（沿用 `_atomic_write` 模式防并发）+ 可选 OTLP exporter（HTTP，feature flag `MESHCTX_OTLP_ENDPOINT`）。
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
- **验收**：e2e 测试 ≥2 场景（同机聚合 + 失败重试）；hub 冒烟跨机 1 场景；测试进套件。
- **工作量**：1–1.5 周。

### WP5 — P1-2 MCP 扩展（23 → ≥40 定义）　预估 1.5–2 周

- **目标**：MCP 工具/定义从 23 扩到 ≥40，覆盖：记忆（WP3 三工具）、任务卡控制（spawn/list/approve/cancel，复用 `/api/tasks/cards` 语义）、治理（配额查询/审批查询）、浏览器（Web2API 桥接）、观测（trace 查询）。
- **落地**：`mcp_server.py` 增量 + 每工具 schema 测试 + `docs/mcp.md` 更新（i18n 后补）。
- **验收**：≥40 定义；每个新工具 ≥1 测试（schema 校验 + 授权路径）；mcp 测试套件绿。
- **工作量**：1.5–2 周。

### WP6 — P1-3 Routines 例行值守　预估 1–1.5 周

- **目标**：定时 + 事件触发值守统一进 task_cards（对位 Claude Code Routines）。
- **设计**：
  - 新增 `src/core/routines.py`：Routine 定义（cron 表达式/间隔/事件钩子 [新消息、hub 事件、文件变化] → 模板化派活参数）→ 到点/触发即 spawn 任务卡（复用 HubQuota/审批）。
  - 存量 `scheduler.py`/`channel_scheduler.py` 迁移为 Routine 实例（保留旧入口兼容，版本内双跑，下一版本删旧）。
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
- **落地清单**：`src/core/governance_api.py`（只读治理 API：审批流查询/配额/审计导出——零新逻辑，仅聚合现有数据）；`docs/governance/whitepaper.md`（NIST 主动能身份/最小权限/可审计映射表 + AISI 案例对照 + MeshCtx 实现映射）；meshctx.com 治理页（10 语言 i18n）。
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
T0（第 1 周）: WP1 观测 core（0.5）+ WP6 Routines + WP7 沙箱硬化     ← 三线并行
T1（第 2 周）: WP1 埋点收尾（0.5）+ WP2 SWE harness v1 + WP8 白皮书
T2（第 3 周）: WP2 GAIA/成绩页 + WP3 Memory API（HTTP/MCP）+ WP5 MCP 扩展启动
T3（第 4 周）: WP3 LongMem 跑分/成绩 + WP4 swarm 2-worker + WP5 收尾(≥40)
T4（第 5 周）: 全量回归 + 文档/BP/10 语言联动 + 三方审计 round 2 + 发版 3.124.0
```

里程碑版本：**3.123.0**（T0–T1 产物：telemetry/routines/沙箱/白皮书）→ **3.124.0**（T2–T3 产物：harness/memory API/MCP/swarm）。每里程碑打 tag + `~/meshctx-backups/` 快照（沿既有回滚机制）。

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
3. `test_project_integrity` 34 passed（安装器 md5 对一致——新增模块不破坏 edition 物理覆盖清单，`src/core/*.py` 白名单需同步 install-edition.sh）；
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
