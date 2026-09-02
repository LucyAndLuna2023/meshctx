# Agent 派活中心 (Agent Hub / Task Cards) 落地计划 — HeyClicky 借鉴大工程

> 起草: 004meshctx 2026-09-02 | 实施: 004meshctx | 审计对象: 002meshctx / 002codex / 004meshctx（实施后三方审计）
> 当前版本: v3.121.7 (HEAD 0398e2aa) → 目标: v3.122.x
> 回滚保障: tag `pre-agent-hub-v20260902-2224` (已推远端) + backup 分支 +
>           `/home/administrator/meshctx-backups/` (git bundle 全历史 + tar 快照, 2026-09-02)
> 勘察来源: 4 份独立只读架构侦察 (edition 门控 / 任务审批额度 / i18n+WebUI / 文档站+安装器)，
>           详档见 /home/administrator/桌面/deepseekHarness/meshctx_agent_hub_plan_notes.md

---

## 0. 决策摘要（先给结论）

1. **做什么**：落地 **"一句话派活 + 后台任务卡片 + 审批 + 配额"**（Agent Hub / Task Cards）——
   HeyClicky 验证过的消费者化 agent 交互（"一句话唤起 → 任务卡可见进度 → 可重试 → 消耗可审批"）。
   覆盖 10 语言 / Win+Mac+Linux（同 3001 Web UI，天然三平台）/ 个人+团队+企业三版本。
2. **开源/闭源边界：开源闭源结合（open-core），与现有架构完全一致。**
   - **开源（个人版免费, AGPL, 写进 meshctx-public）**：TaskCardStore + 后台 CardWorker +
     run_agent_loop 执行链 + 任务级审批 + 配额计量（quota_manager/usage_meter 接线）。
     理由：个人版定位"永久免费全功能"；底层循环/审批/配额器均已开源真实实现，只缺封装层。
   - **闭源（team/enterprise, 私有库 stub→真实现）**：组织级治理 = 团队共享任务队列/看板、
     admin 配额预算与超限策略、Always-approve 域、审批审计(audit_logger)、SSO、跨成员委派。
     即 $9/$29 的付费卖点，延续 business_plans/team_memory/sso 既有 stub→私有模式。
   - **机制提醒（勘察硬事实）**：edition 差异 = 私有安装器物理覆盖 `src/core/*.py`；
     `main.py` 与 shared-full 模块永不覆盖 → "open-but-limited" 逻辑必须写在 main.py /
     shared 模块内（detect_edition() / plan rank 运行时分支），不能靠"开源有/私有无"文件实现。
3. **复用而非重造**（勘察确认的现成部件）：`run_agent_loop` 统一循环（agent_loop.py:98）、
   `work_engine.WorkJob` 原子 JSON 持久化范式、`quota_manager`/`usage_meter`（完整但零接线，
   正好本工程接上）、`_current_user_id`（main.py:7557）、`ResourceManager.pre_task` 前门、
   `_needs_approval`/`_approval_waiter`/`POST /api/approval/decide` 审批链。
4. **不做/注意**：summon 引擎开源版默认是 mock（不真调 LLM），不当作执行路径；
   `/api/tasks/*` 是死壳可安全替换（注意它在认证白名单 auth_v2.py:46）；开源版 34 个
   core 模块是 enterprise stub（调即 501），不可依赖。
5. **meshctx.com**：主页新增 Hub 功能卡 + BP/edition 定价区块（10 语言 landing.json）；
   补子页 (download/getting-started/test-report) it/ar/ru 到 10 语言；修 llms.txt /
   competition.md 冲突标记。产品 UI 补 chat.html LANG ru、base.html LANG it/ar/ru。
6. **交付**：全量 pytest ≥3600 passed + 三方审计 + 三仓推送 + CHANGELOG + 版本 bump。

---

## 1. 背景与动机

HeyClicky（YC S26, $10M+, 25k 用户, 8 周起爆）证明：agent 的杀手级包装不是 CLI/面板，而是
"文本/语音一句话唤起 → 后台任务卡可见进度 → 失败可 Retry → 消耗可审批"。
meshctx 引擎能力已具备（run_agent_loop / approval / work_engine / quota），但**无后台 runner、
无任务卡 UI、无配额账本接线、无任务持久化+用户归属**——服务端所有执行绑定 HTTP/CLI 前台，断连即死。
本工程 = 补"消费者化封装层"，并把组织治理留在付费版（open-core 变现）。

## 2. 现状诊断（勘察事实，全部 file:line 可溯）

### 2.1 可复用（开源真实实现）
| 部件 | 位置 | 用法 |
|---|---|---|
| 统一 agent 循环 | `src/agent_loop.py:98 run_agent_loop`（async gen，事件 dict: round/deliver/reasoning/approval/tool_*/final/done） | 任务执行器直接复用 |
| 审批引擎 | `src/core/approval.py` + main.py:5406/5433/5444 | 危险命令审批；需补持久化+列表 API |
| 作业持久化范式 | `src/work_engine.py` WorkJob 原子 JSON + 心跳 + pid 锁 (WORK_DIR=~/.meshctx/work) | TaskCardStore 照抄 |
| 配额/用量台账 | `src/core/quota_manager.py`（QuotaManager:150, set_quota/check/consume/get_remaining, JSON 持久化）+ `usage_meter.py`（UsageMeter:346, record_usage/check_quota/成本计算）——**均零接线** | 接线即用 |
| 身份归因 | main.py `_current_user_id`:7557（admin/key:{name}/local/""）；auth_v2 | 任务 owner |
| spawn 前门 | main.py:7529 `ResourceManager.pre_task`(:282) | 入队前配额/健康检查 |
| 状态机枚举 | `agent_tasks.TaskStatus`:29（pending/running/completed/failed/cancelled/blocked） | 卡状态复用 |
| 工具执行 | `chat_tools.execute_tool/TOOLS` (chat_tools.py:601/625) | run_card 工具面 |
| 模型客户端 | `model_registry.get_registry().get(model)` | LLM 调用 |
| 前端审批弹窗 | `templates/chat.html` confirm-panel（agree/reject/custom） | 任务审批复用 |
| 加键脚本样板 | `scripts/add_crew_i18n.py`（N 键×10 语言写 JSON） | 产品 i18n 加键 |

### 2.2 关键陷阱
- **服务端无任何后台 LLM runner**；一切执行绑定 HTTP StreamingResponse/CLI 前台 → 需 FastAPI
  lifespan 后台 asyncio worker 队列。
- summon 开源版 mock（summon_engine.py:198-232 sleep 拼串）——不可当执行路径。
- `/api/tasks/*` 死壳（main.py:2185-2249, swarm stub → 空值），可安全替换；`/api/tasks/`
  前缀在认证白名单（auth_v2.py:46）→ 新端点内部自行鉴权。
- 审批 pending 全在进程内存（approval.py _pending + main.py _APPROVAL_FUTURES），SSE 断连
  120s 超时拒绝 → 任务级审批须持久化到任务 JSON。
- 无每用户/每计划用量账本；PLAN_FEATURES 开源为空 → 本地套餐阈值自定（开源常量表）。
- 34 个 core 模块 enterprise stub（agent_swarm*/team/swarm*/business_plans/billing_payments/
  agent_crew_cost_tracker/sso/audit_logger/agent_writing_studio/agent_tuning_skills 等）。

### 2.3 版本门控 / i18n / 文档站 / 安装器
- edition: detect_edition() (src/core/_edition.py:31) sso→enterprise / team_memory→team / personal；
  路由隐藏 _EDITION_ROUTE_MAP (main.py:666) personal 删 36 条 + /ui/crews；501 兜底 (:699)。
- 产品 i18n: src/i18n_translations.json 10 语言×1440 key 全等（validate_keys OK, 基线已测）；
  缺失回退 en→key。**缺口：templates/chat.html LANG 缺 ru（9 语言）；templates/base.html LANG
  缺 it/ar/ru（7 语言）；legal-i18n.json 缺 ru**；web_ui.py 内嵌 _TEMPLATES(7 名字) 默认权威、
  与磁盘 templates/ 双份须同步。
- 营销站: docs/i18n/landing.json 10×248（唯一全 10 语言源, 服务 index.html/profile）；
  download/getting-started/test-report 内嵌 7 语言 dict（缺 it/ar/ru）；站上无 pricing/BP 页。
- 安装器: docs/ 与根 5 对逐字节镜像（test_project_integrity:66-70 强制）；install-edition 合并
  白名单 = src/core/*.py + src/web_crews.py → 新开源模块天然随开源仓分发；新私有 stub 需确认覆盖。
- 测试护栏（新增键/页时须过）: test_project_integrity / test_homepage_i18n（10 语言块≥50 keys,
  非中文 8 语言 CJK≤3）/ test_real_i18n_behavior（data-lang-key 全覆盖, f18-f22 硬编码, f23+ 需
  自觉追加）/ test_v16_i18n（恰 10 语言, available_languages=10）/ test_localization_cross_platform。
- 顺手缺陷: docs/competition.md:1 git 冲突标记；llms.txt 过期(13 脑区/v2.9.4)；tools/i18n_guard.py
  与 validate_i18n.js 已空转/硬编码（本工程顺带标注, 不展开修）。

---

## 3. 目标架构

```
┌─ 入口（本地 3001 Web UI, 三平台同一浏览器）────────────────────┐
│ templates/chat.html: 顶部新增「派活中心」入口 (按钮/页签)          │
│   一句话输入 (复用输入框, 支持 "派活: xxx" / /hub 前缀)           │
│   任务卡列表: 状态徽章/进度/结果/耗时/创建者/取消/重试             │
│   审批: 复用 confirm-panel, 任务卡内嵌 pending 动作               │
└──────────────┬─────────────────────────────────────────────────┘
               │ fetch REST + SSE 订阅
┌──────────────▼─────────────────────────────────────────────────┐
│ API 层 (main.py, 永不被覆盖 → open/paid 差异化写这里)             │
│  POST /api/tasks/cards                  创建派活任务卡            │
│  GET  /api/tasks/cards                  我的任务卡列表 (owner 过滤)│
│  GET  /api/tasks/cards/{id}             单卡详情 (含 timeline)    │
│  POST /api/tasks/cards/{id}/cancel|retry 取消/重试                │
│  POST /api/tasks/cards/{id}/approve     pending 审批决定          │
│  GET  /api/tasks/cards/{id}/stream      SSE 事件订阅/回放          │
│  GET  /api/tasks/quota                  配额状态 (开源本地表)      │
└──────────────┬─────────────────────────────────────────────────┘
┌──────────────▼─────────────────────────────────────────────────┐
│ 开源核心 src/core/task_cards.py (AGPL 真实实现, 新文件, 永不 stub)  │
│  TaskCard: id/owner/plan/title/prompt/status/priority/created_at/ │
│            timeline[]/result/error/approval_pending               │
│  TaskCardStore: 原子 JSON 持久化 ~/.meshctx/task_cards/ (0600)     │
│  CardWorker: 全局 asyncio 队列 (FastAPI lifespan 启动)             │
│    run_card = model_registry.get(model) +                         │
│                run_agent_loop(system_prompt+prompt, tools,         │
│                  needs_approval=卡级, approval_waiter=persist)     │
│  HubQuota: 接线 quota_manager.set_quota/check/consume              │
│            + usage_meter.record_usage; 本地套餐表常量 FREE/TEAM/ENT │
└──────────────┬─────────────────────────────────────────────────┘
┌──────────────▼─────────────────────────────────────────────────┐
│ 闭源治理 (team/enterprise 私有库; 本仓只留 stub 占位)               │
│  src/core/team_hub.py (stub→私有): 团队共享任务队列/看板/委派       │
│  admin 配额预算/超限策略/Always-approve 域 → 私有 business_plans    │
│  审批审计 audit_logger + SSO → 已私有 (延续既有)                   │
└─────────────────────────────────────────────────────────────────┘
```

### 执行模型
- 后台 worker：FastAPI lifespan 中启动全局 asyncio 消费者；卡运行 = run_agent_loop 事件流
  逐条写卡 timeline + 更新 status；SSE 端点按卡 id 回放/订阅。
- 持久化：每卡一个 JSON（原子写 tmp+rename），含 owner/status/timeline/result/pending。
- 审批：危险动作 → 卡内 pending + 事件；Web decide → 写回卡 → agent 继续（跨断连存活）。
- 配额：spawn 前 pre_task + quota.check；执行中 usage_meter.record_usage；超限 → 额度确认/
  拒绝（本地软提示；组织硬限在闭源层）。
- 会话不混入：任务卡独立 store，不塞 conversations。

---

## 4. 开源/闭源边界（论证）

| 能力 | 归属 | 理由 |
|---|---|---|
| 一句话派活引擎 + 任务卡 CRUD/进度/取消/重试 | 开源 | 个人版核心体验；run_agent_loop/work_engine 已开源 |
| 任务级审批 (pending persist + decide) | 开源 | approval 引擎已开源 (chat confirm 已有) |
| 本地配额记账 + 软提示 | 开源 | 个人版"永久免费"，透明展示不强收费墙 |
| 团队共享队列/看板/委派 | 闭源 (team) | $9 卖点；business_plans 模式 |
| admin 配额预算/超限策略/Always-approve 域 | 闭源 (team/enterprise) | 组织治理 |
| 审批审计日志 | 闭源 (enterprise) | audit_logger 已 stub→私有 |
| SSO 集成 | 闭源 (enterprise) | sso 已 stub→私有 |

**个人版体验不设硬付费墙**：额度仅提示不阻断；阻断/治理逻辑全在 team/enterprise（闭源）。
**差异化实现位置**：main.py 路由（永不覆盖）+ task_cards.py（开源新文件）。
私有扩展 team_hub.py：开源仓 stub（_IMPLEMENTATION_MOVED），真实现放私有库，install-edition
白名单（src/core/*.py）天然覆盖——沿用既有模式，无需改安装器。

---

## 5. 任务分解 T0..T11（实施顺序 + 验收；单步提交可回滚）

| # | 任务 | 验收 |
|---|---|---|
| T0 | 回滚保险: tag+branch+bundle+tar | ✅ 2026-09-02 完成 |
| T1 | `src/core/task_cards.py`: TaskCard dataclass + TaskCardStore(原子 JSON) + HubQuota(本地表) + CardWorker 队列骨架 | pytest 单测（store 持久化/幂等/并发锁, quota check/consume） |
| T2 | FastAPI lifespan 后台 worker + run_agent_loop 执行链（事件→卡 timeline） | 集成测试：mock 模型驱动跑完卡, status/timeline 正确, 断连后卡可续查 |
| T3 | API: /api/tasks/cards* (create/list/get/cancel/retry/stream/quota), 内部鉴权(owner 归属) | pytest httpx 全端点；/api/tasks/ 旧死壳移除或重定向 |
| T4 | 任务级审批: 卡内 pending + approve 端点 + 持久化恢复 | pytest: 危险动作挂起→decide→agent 继续；重启后仍可 decide |
| T5 | 前端: chat.html 派活中心入口/卡片列表/进度/取消重试/审批 | 冒烟: 派活→跑→结果; (环境允许) playwright |
| T6 | 产品 i18n: src/i18n_translations.json 10 语言加 hub_* 键 (scripts/add_crew_i18n.py 样板) + chat.html LANG 补 ru + base.html LANG 补 it/ar/ru + web_ui 内嵌/磁盘双份同步 | validate_keys OK; 10 语言键全等; test_*i18n* 全绿; ru 切语言实测 |
| T7 | 版本门控三态: personal 全开(不隐藏) / team/enterprise 治理路由前缀登记; team_hub.py stub 占位 | detect_edition 三态实测 (stub 模拟), personal 无 501, team/ent 隐藏正确 |
| T8 | 安装器/镜像: 根与 docs 5 对安装器保持逐字节 (本工程无新私有文件→白名单无需改, 验证) | test_project_integrity 通过; bash -n 通过 |
| T9 | docs 站: landing.json 10 语言 hub fNN_title/fNN_desc + index.html 卡片 + BP/edition 定价区块(10 语言, 含 $9/$29/三版对比) + download/getting-started/test-report 补 it/ar/ru + llms.txt/competition.md 修复 | test_homepage_i18n / test_real_i18n_behavior (f23 追加) / test_localization_cross_platform 全绿; 10 语言渲染实测 |
| T10 | 全量回归 pytest (≥3600 passed) + CHANGELOG + 版本 bump v3.122.0 (tools/release.py + sync_version.py) | 全绿; 版本号 18 处一致 |
| T11 | 三仓推送 + 三方审计 (002meshctx/002codex/004meshctx) + 处理回执 | 审计闭环 |

**提交策略**：T1 独立 commit → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10；每阶段 commit 前
打 `pre-hub-<stage>-<ts>` tag；任一步失败 `git reset --hard <tag>` 回滚，修复后重来。
私有库 (team/enterprise) 在开源稳定后再同步 team_hub stub → 真实现的交付。

---

## 6. 回滚方案
1. 每阶段前: `git tag pre-hub-<stage>-<ts>`; 失败: `git reset --hard <tag>` + 删除坏 commit 分支。
2. 跨仓: 开源库独立演进; 私有库只在开源全绿后同步。
3. 灾难恢复: `/home/administrator/meshctx-backups/` (2026-09-02 git bundle 332MB + tar 快照)；
   远端 tag `pre-agent-hub-v20260902-2224` 永不移除。
4. 数据库/用户数据: 本工程纯本地新 JSON store (~/.meshctx/task_cards/), 不触碰既有
   conversations/memories/state.db → 无数据迁移风险。

---

## 7. 风险清单
| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | 后台 worker 与既有并发/单机模型 key 冲突 | 中 | lifespan 单例 worker; 复用现有 interruptible_runner 语义 |
| R2 | 任务卡无限增长 | 低 | 上限 N 卡/用户, 自动清理完成卡 (同 conversations 清理策略) |
| R3 | run_agent_loop 工具副作用 (写文件/远程) | 中 | 复用 _needs_approval + 卡级审批; 配额前门 |
| R4 | SSE 订阅内存泄漏 | 低 | 断连即清理; 卡事件落盘为主, SSE 仅回放 |
| R5 | i18n 键漏加某语言导致 CI 红 | 低 | scripts/add_crew_i18n.py 模板 + validate_keys + 三测试护栏 |
| R6 | edition stub 误暴露个人版 501 | 低 | personal 全开不隐藏; team_hub stub 仅被治理路由引用且路由按 edition 隐藏 |
| R7 | 版本 bump 漏同步 (18 处) | 低 | tools/sync_version.py 强制 |

---

## 8. 附: 关键 file:line 索引（实施时快速定位）
- run_agent_loop: src/agent_loop.py:98 | approval: src/core/approval.py:114/416 | _needs_approval:
  main.py:5406 | _approval_waiter: main.py:5433 | decide: main.py:5444 | _current_user_id:
  main.py:7557 | _plan_of_user: main.py:7576 | pre_task: main.py:7529 | agent_tasks.TaskStatus:
  src/core/agent_tasks.py:29 | work_engine WorkJob: src/work_engine.py:68 | quota_manager:
  src/core/quota_manager.py:150/895 | usage_meter: src/core/usage_meter.py:346/724 |
  chat_tools: src/chat_tools.py:601/625 | model_registry: src/model_registry.py:522/749 |
  chat.html LANG: templates/chat.html:584 | chat t(): :794 | web_ui chat_page: src/web_ui.py:4124 |
  auth whitelist: src/core/auth_v2.py:40-46 | edition map: src/main.py:666 | detect_edition:
  src/core/_edition.py:31 | i18n json: src/i18n_translations.json | landing: docs/i18n/landing.json |
  install-edition 合并: docs/install-edition.sh:76-86 | i18n 加键模板: scripts/add_crew_i18n.py
