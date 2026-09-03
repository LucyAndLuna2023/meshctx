# MeshCtx "自进化"声称核验报告 — 代码事实 vs 文案口径

- 编号: MCTX-VER-2026-0903　日期: 2026-09-03　方法: BP/主页声称逐条对照 `src/` 代码、运行接线、API、测试（只读未改码）
- 触发: 用户要求核验"BP 和主页里描述的自进化是否真的实现了"

## 1. 结论摘要

**部分真实，需口径修正**：MeshCtx 确有**两套真实的"进化/自适应"工程引擎**（GenomicOptimizer 参数进化 + CMA-ES 自调优 + 记忆整合/元认知模块），有实现、API、持久化与测试，非纯文案。但：
- **"每次任务后自动评估→自动进化→自动应用回运行时"的闭环**：证据不足——进化与反馈主要为 **API/手动触发**（/api/genomic/evolve|feedback），未见 agent 主循环自动喂结果并自动把最优参数回注到聊天/任务的**运行时路径**（best_genome 的 get_active_genome 存在，但应用到请求参数链未闭合）；
- 元认知/记忆整合以**独立模块 + 报告 API** 存在，**未接入统一 agent 主循环**（agent_loop 无接线）；
- 因此"世界首个自进化智能体系统 / continuously self-evolves / 越用越聪明（自动闭环）"等**超卖措辞**超出当前可验证边界，建议口径修订为"进化引擎已实现（API/受控触发）+ 全自动闭环为路线图项"。

## 2. 声称 vs 证据矩阵

| # | 声称（BP/主页） | 代码证据 | 运行态 | 判定 |
|---|---|---|---|---|
| 1 | GenomicOptimizer 基因进化引擎（遗传算法参数自进化, 784 行零依赖） | src/core/genomic_optimizer.py（>800 行: Genome/mutation/fitness/selection + copy-deep-mutate）| ✅ 存在 | ✅ **真实现** |
| 2 | 进化引擎接线: lifespan 初始化 / /api/genomic/stats\|best\|evolve\|feedback / get_active_genome / best_genome.json 持久化 | src/main.py:349-355, 5843-5893；~/.meshctx/genomes/best_genome.json | ✅ 可用（受控/API 触发） | ✅ **真实现（受控触发）** |
| 3 | 引擎有测试 | tests/test_v59_evolution.py, test_cmaes_optimizer.py, test_v40_evolution_tracker.py | ✅ | ✅ |
| 4 | "每次任务后自动评估→提取模式→更新图谱→优化行为"（BP §2.4 闭环） | 无自动喂入点：agent_loop/run_card 未调用 optimize/feedback；evolve 仅在 API 触发 | ❌ 自动闭环缺失 | 🟡 **半实现**: 反馈 API 可喂（manual），自动闭环未接线 |
| 5 | "CMA-ES + PID 双环实时调温…continuously self-evolves"（主页 f17） | CMA-ES 在 cmaes_optimizer.py（genomic 内部调用）；PID/自适应在 brain_* 模块 | 调优引擎存在；**实时逐请求应用链未证实** | 🟡 **部分**: 引擎真、持续自动应用措辞超卖 |
| 6 | 元认知自进化循环（BP 2.4/海外文案） | src/core/metacognition.py + /metacognition/report 等报告端点（main 1710+） | 独立模块+报告 | 🟡 **独立实现**, 未入 agent 主循环闭环 |
| 7 | 6 维成长跟踪 + weekly evolution reports（主页 f22） | src/core/evolution_tracker.py + tests | 报告 API 存在；"weekly" 为口径非定时器 | 🟡 **部分**: 手动/API 生成，非自动周报 |
| 8 | "世界首个…自进化智能体系统 / 越用越聪明"（hero/一句） | — | 超卖形容词 | ❌ **文案**: 建议降级为可验证表述 |

## 3. 建议口径修订（落地清单）

1. 主页 hero（zh/en）+ f17/f22 描述：把 "continuously self-evolves / 世界首个自进化" 改为可验证表述：
   例: "内置进化引擎（遗传算法+CMA-ES）与 6 维成长跟踪 —— 引擎可 API 受控进化，全自动闭环路线图中"。
2. BP 附录本报告；§2.4/GenomicOptimizer 段补一行口径注（自动闭环为路线图，当前受控触发可验证）。
3. 海外发布文案（HN/Reddit 等）同步避免 "self-evolving hyperparameters" 无修饰——改为 "evolution engine with API-triggered tuning"。
4. 未来闭环落地点（可立项）: run_card 终态结果 → genomic.feedback 自动喂 + best_genome 回注 chat/卡参数解析点 + evolution_tracker 自动周报定时器 —— 落地后升格回"全自动自进化"口径。

## 4. 文件

- 代码: src/core/genomic_optimizer.py, cmaes_optimizer.py, evolution_tracker.py, metacognition.py
- API: /api/genomic/*（main.py ~5843）, /api/status metrics.genomic, /metacognition/report
- 持久化: ~/.meshctx/genomes/best_genome.json
