# MeshCtx v3.130+ 产品战略收敛方案

> 文档: MCTX-STRATEGY-v3.130-20260909 · 状态: 草案送审
> 来源: 外部战略分析 (ChatGPT/用户转述) + 004deepseek 代码级判断
> 基线: v3.129.0 (3823 passed / 59 skipped)

---

## 0. 对外部分析的批判性评估

| 建议 | 判断 | 理由 |
|---|---|---|
| 停止加脑区 | ⚠️ 部分同意 | 脑区系统是核心 IP 不应删；但**营销叙事**应从"17 脑区"转向 Agent Runtime 价值 |
| 统一 Task Object | ✅ 同意 | TaskCard 已有 80% 字段，缺 `intent`/`learning`/`budget` 形式化 |
| Agent Lifecycle 固化 | ✅ 同意 | agent_loop.py 已实现 90%，缺文档化 schema + SDK 包装 |
| MeshCtx SDK 30 天优先 | ⚠️ 缓行 | API 稳定性来自 runtime 先收敛；SDK 应在 Task Object 统一后做 |
| Quantum Plugin | ⚠️ 缓行 | 缺 Compute 抽象层；先做 Tool API 接口预留 |
| Enterprise $29 太低 | ✅ 同意 | 但定价变更不在本轮代码范围 |
| Benchmark 重构 | ✅ 同意 | 综合分 63.5% 对企业不友好；拆领域分更好 |
| 90 天全做 | ❌ 不同意 | 每阶段需独立审计+发版周期；建议 3 个 sprint 而非 6 个 |

## 1. 价值叙事转向（v3.130 文档+主页）

**旧**: "17 脑区仿生自进化 AI"
**新**: "持久自主 Agent 运行时 — 记忆 · 执行 · 治理"

改 docs/ 主页 hero/about/features 排序 ×11 语言 + llms.txt + BP v3.121。
技术架构不变（脑区=实现层），变的是**对外故事**。

## 2. Unified AgentTask Schema（v3.130 代码）

### 2.1 现有 TaskCard vs 目标 AgentTask

| 现有 TaskCard 字段 | 目标 AgentTask 字段 | 差异 |
|---|---|---|
| id | task_id | 改名 |
| prompt | intent | 语义明确化 |
| extra.context | context[] | 结构化 |
| (无) | memory[] | **新增**：关联记忆引用 |
| extra.swarm_plan | plan[] | 结构化子任务 |
| (无) | tools[] | **新增**：工具白名单 |
| (无) | risk | **新增**：风险等级 |
| plan(免费配额) | budget | **新增**：token/cost 预算 |
| status | status | 保持 |
| result | result | 保持 |
| (无, 走 telemetry) | trace_id | **新增**：链路关联 |
| (无) | learning | **新增**：执行后学习记录 |

### 2.2 实现方案

- `src/core/agent_task.py` — AgentTask dataclass（向后兼容 TaskCard，双写迁移）
- `AgentTask.to_taskcard()` — 与现有 CardWorker 兼容
- `AgentTaskSchema.validate()` — JSON Schema 校验
- Lifecycle 常量：`UNDERSTAND → RETRIEVE → PLAN → DECOMPOSE → EXECUTE → VERIFY → APPROVE → COMMIT → LEARN → STORE`
- 每阶段 hook 接口（现有 approval/quota/telemetry 已覆盖 5/10）

### 2.3 交付物

- `src/core/agent_task.py` (新增, ~150 行)
- `tests/test_agent_task.py` (schema/lifecycle/TaskCard 兼容)
- 现有 TaskCard 路径不破坏 (加法式)

## 3. Benchmark 重构（v3.130 文档+数据）

### 3.1 从综合分 → 领域分

| 维度 | 当前值 | 展示方式 |
|---|---|---|
| Memory Recall | 94% | 独立展示 (SDM 优势) |
| Task Completion | 86% | 独立展示 |
| Error Recovery | 91% | 独立展示 |
| Safety | 98% | 独立展示 (SDB/治理优势) |
| Latency | 42ms | 性能指标 |
| Token Reduction | 60% | 成本优势 |

→ 主页 benchmark 区块改表格式（×11 语言）；综合分不再作为首屏指标。

### 3.2 交付物

- docs/index.html benchmark 区块重写
- landing.json bench_* 键 ×11 更新
- 成绩页 benchmarks/index.html 同步

## 4. 营销叙事重写（v3.130 文档）

### 4.1 hero_desc 更换 ×11

旧: "17-brain-region emulated self-adaptive agent platform"
新: "Persistent AI Agent Runtime — remembers your work, executes autonomously, and stays auditable."

### 4.2 about 区块重排

按 Memory / Agent Runtime / Governance 三支柱重写 ×11
脑区降为 Technology 实现细节（about_li 或折叠区）

### 4.3 交付物

- landing.json hero_desc/about_*/f*_desc 关键键 ×11 更新
- docs/index.html 排序调整（治理/遥测/记忆 提前）
- llms.txt 核心定位行更新
- BP v3.121 同步

## 5. 3.130.0 范围外（排后续）

- MeshCtx SDK (v3.131)
- Agent Marketplace (v3.132)
- Quantum Plugin (v3.133)
- 定价变更 (商业化阶段)
- 脑区代码删除/冻结 (不删, 只是营销降权)

## 6. 执行计划

| Sprint | 内容 | 发版 |
|---|---|---|
| v3.130.0 | AgentTask Schema + 主页叙事重写 + Benchmark 重构 + 11 语言 | rc → tag |
| v3.131.0 | MeshCtx SDK (`pip install meshctx`) + Task API v1 | rc → tag |
| v3.132.0 | Agent Marketplace MVP + Compute 抽象层预留 | rc → tag |

## 7. 审计送审项

①AgentTask Schema 完整性与 TaskCard 兼容性 ②主页叙事 ×11 语言质量 ③Benchmark 数据真实性
④版本 single-source-of-truth 确认 ⑤不破坏现有 3823 测试基线

---

— 004deepseek/004meshctx 2026-09-09 · 待三方审计
