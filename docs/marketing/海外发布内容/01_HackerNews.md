# Hacker News — Show HN 发布内容

> **发布方式**: https://news.ycombinator.com/submit (标题以 `Show HN:` 开头)
> **最佳时间**: 美东周二/周三上午 9-11 点（= 北京 21:00-23:00）
> **目标**: 300+ upvote 上首页，开发者认知冷启动

---

## 标题（三选一，A 为推荐）

- **A**: `Show HN: MeshCtx – An AI agent with 17 simulated brain regions that evolves its own parameters`
- **B**: `Show HN: I built an AI agent that rewrites its own code and evolves its own settings via genetic algorithms`
- **C**: `Show HN: Full-brain-emulation AI agent – 17 brain regions, sparse distributed memory, free & open core`

> 建议用 A：具体、有技术好奇心钩子，避免夸大。

---

## 正文（Show HN 评论 #1，即说明文字）

```
Hi HN,

I've been building MeshCtx solo for years (250k+ lines of Python) and it just hit a milestone I want to share: a desktop AI agent whose architecture literally simulates 17 brain regions — prefrontal cortex for working memory, hippocampus for memory replay, amygdala for salience detection, default mode network for divergent thinking, and so on. Each region maps to a concrete engineering component.

What makes it different from Cursor/Copilot/Claude Code:

1. 17-region full-brain architecture (not a single black-box LLM call)
2. Sparse Distributed Memory (Kanerva SDM) — O(2^1000) address space for long-term memory
- **Memory Engine v2 (2026-08)**: FSRS spaced repetition + schema consolidation (episodic→semantic→core, auto-triggered) + context markers + sleep-phase offline consolidation & ARCHIVAL pruning (recoverable). LongMemEval: EM 54.2% / semantic judge 83.3% (vs GPT-4o no-memory baseline 60–64%); 16KB curated 33.3% vs truncation 25.0% (+8.3pp, 4.5× fewer tokens); tool output 5008B→223B (−95.5%).
3. Self-evolution loop: after every task it evaluates itself, extracts patterns, updates its knowledge graph
4. GenomicOptimizer: a 784-line genetic algorithm engine that evolves its own hyperparameters (temperature, top_p, prompt style, memory weights) using mutation → crossover → elitism → niche preservation. It literally gets smarter at tuning itself.
5. 5-model swarm consensus voting for code review/generation
6. 3-platform desktop apps (Windows/macOS/Linux), 10-language i18n including RTL Arabic

Pricing: individual users are permanently free. Team/Enterprise tiers are in active development — join the waitlist. Open Core under AGPLv3 — the framework is fully open source.

GitHub: https://github.com/LucyAndLuna2023/meshctx
Site: https://meshctx.com

I'd love brutal feedback on the architecture, the SDM implementation, or the genetic optimizer. What would you steal, what would you scrap?

[If applicable: attach a screenshot of the desktop UI or the evolution benchmark chart.]
```

---

## 评论区运营预案

**可能被问 → 预设回答**:

| 问题 | 回答要点 |
|:---|:---|
| "17 brain regions is just marketing" | 承认部分区域是概念映射，但点出 3 个工程化的：SDM(海马体)、元认知循环(前额叶)、GenomicOptimizer(基底节习惯强化)。邀请看源码 |
| "How is SDM different from a vector DB?" | Kanerva SDM 地址空间 O(2^1000)，预测预激活 + 100:1 分形压缩，非 ANN 近似检索 |
| "Self-modifying code is dangerous" | 7 阶段安全流水线：分析→优化→测试→验证→应用，4 阶段操作合约需用户审批 |
| "Another AI wrapper?" | 展示 123+ 模型支持 + 智能路由 + 自进化引擎，强调 6 年跨学科积累 |
| "Why AGPLv3 not MIT?" | Open Core 策略：框架开源，核心 Brain 算法工程实现可见但不完全开放，防巨头白嫖 |

**加分动作**:
- 发布后 30 分钟内回复前 5 条评论（HN 算法看早期互动）
- 若冲上首页，准备好服务器扛住流量（Cloudcone 记得扩容）
- 给质疑者贴源码链接，用代码说话

---

## 避坑清单

- ❌ 不要用"revolutionary / world's first"等营销词 —— HN 反感
- ❌ 不要放太多链接（1-2 个足够）
- ✅ 承认是 solo project + 6 年迭代，真实故事最打动人
- ✅ 主动求批评，比炫耀更容易上首页
- ✅ 回复要有实质内容，别用"thanks for the feedback"糊弄
