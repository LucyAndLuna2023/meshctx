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

## 2. Unified UnifiedTask Schema（v3.130 代码）

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
| plan (订阅层级) | plan (保留原义) | 不迁移, PLAN_LIMITS 独立 |
| status | status | 保持 |
| result | result | 保持 |
| extra.trace_id (v3.128 OTLP) | trace_id | 迁移映射, 复用勿新造 |
| (无) | learning | **新增**：执行后学习记录 |

### 2.2 实现方案

- `src/core/unified_task.py` — UnifiedTask dataclass（向后兼容 TaskCard，双写迁移）
- `UnifiedTask.to_taskcard()` — 与现有 CardWorker 兼容
- `UnifiedTaskSchema.validate()` — JSON Schema 校验
- Lifecycle 常量：`UNDERSTAND → RETRIEVE → PLAN → DECOMPOSE → EXECUTE → VERIFY → APPROVE → COMMIT → LEARN → STORE`
- 每阶段 hook 接口（现有 approval/quota/telemetry 已覆盖 5/10）

### 2.3 交付物

- `src/core/unified_task.py` (新增, ~150 行)
- `tests/test_agent_task.py` (schema/lifecycle/TaskCard 兼容)
- 现有 TaskCard 路径不破坏 (加法式)

## 3. Benchmark 重构（v3.130 文档+数据）

### 3.1 从综合分 → 领域分

| 维度 | 实测值 | 溯源 |
|---|---|---|
| LongMemEval Memory | EM 54.2% (oracle 上限) / 语义 83.3% | docs/reports/…v4.md 2026-08-19 |
| GAIA Task Completion | 75% (6/8, L1 100% L2 67% L3 50%) | benchmarks/results/gaia_report_2026-08-18 |
| Error Recovery | 6 项根因修复 → GAIA 37.5%→75% | 同上 (dc4a371 评分器修复链) |
| SDB Safety | 85.43/100 (A-grade) | src/core/sdb* + brain_benchmark |
| Token Reduction | T2 压缩 -95.5% (单样本) | 同 v4 报告 |

→ 主页 benchmark 区块改表格式（×11 语言），标注口径+日期；综合分不作为首屏指标。
⚠️ 原"94%/86%/91%/98%/42ms/60%" 六项无溯源 (002meshctx b16ac51b/002codex 3d6ffcec 确认) → 全部替换为上表真实数。

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
| v3.130.0 | UnifiedTask Schema + 主页叙事重写 + Benchmark 重构 + 11 语言 | rc → tag |
| v3.131.0 | MeshCtx SDK (`pip install meshctx`) + Task API v1 | rc → tag |
| v3.132.0 | Agent Marketplace MVP + Compute 抽象层预留 | rc → tag |

## 7. 审计送审项

①UnifiedTask Schema 完整性与 TaskCard 兼容性 ②主页叙事 ×11 语言质量 ③Benchmark 数据真实性
④版本 single-source-of-truth 确认 ⑤不破坏现有 3823 测试基线

---

## 8. 三方审计修正 (2026-09-09 首轮)

- 002codex 3d6ffcec: AgentTask 不得与 src/core/agent_tasks.py 冲突 → 改名 UnifiedTask;
  trace_id 迁移映射非新造; tools[] 服务端白名单强校验; budget 接 quota 硬停止;
  Benchmark 须 evidence artifact 否则标 roadmap/internal estimate
- 002meshctx b16ac51b: Memory 94% 疑似竞品 Mem0 自报数字; LongMemEval EM≈50-54% 才是实测;
  10 阶段须映射 CardStatus 6 态; budget 结构化 {max_tokens, max_seconds};
  plan 字段保留原义 (PLAN_LIMITS/worker 使用)
- 004meshctx 10259b9f: src/core/agent_tasks.py (复数) 已存在 = 必须声明 UnifiedTask
  为适配层 (非第三套状态机); budget/plan 解耦; Benchmark 6 数字查无出处 → 阻塞

以上全部纳入本修正版。Benchmark 用真实可溯源数据 (上表)。

— 004deepseek/004meshctx 2026-09-09 · v0.2 修正版 · 待三方复审
