# Reddit — 多 Sub 发布内容

> **核心原则**: Reddit 反硬广。必须先融入社区、以"分享/请教"姿态发帖，**self-promotion 比例控制在 10% 以内**（每发 10 条有益回复/内容，才发 1 条推广）。
> **建议账号**: 使用运营账号提前 2 周在目标 sub 活跃（评论、点赞、发干货）。

---

## Sub 1: r/artificial — 概念讨论向（P0，最大流量池）

**标题**: `I simulated 17 brain regions in an AI agent — here's what actually works and what's just metaphor`

**正文**:
```
I've spent years building an AI agent whose architecture maps to 17 brain regions (PFC for working memory, hippocampus for memory consolidation/replay, amygdala for salience, DMN for divergent thinking, etc.).

After shipping it I want to be honest about what's real engineering vs. what's metaphor:

WORKS:
- Sparse Distributed Memory (Kanerva) — genuinely different from vector DBs, O(2^1000) address space, handles long-term memory without RAG pipelines
- **Memory Engine v2 (2026-08)**: FSRS spaced repetition + schema consolidation (episodic→semantic→core, auto-triggered) + context markers + sleep-phase offline consolidation & ARCHIVAL pruning (recoverable). LongMemEval: EM 52-54% (48Q oracle subset) / semantic judge 83.3% (~81-85% of GPT-4o no-memory full-context 60–64%); 16KB curated 33.3% vs truncation 25.0% (+8.3pp, 4.5× fewer tokens); tool output 5008B→223B (−95.5%).
- Hippocampal replay — compressing + replaying past sessions 10-20x during idle, real "gets smarter over time" effect
- Salience detection — prioritizing messages/context by urgency, actually useful for task management

METAPHOR SO FAR:
- "Default mode network" — I map it to background idea generation, but it's early
- "Consciousness/Φ" — more of a philosophical framing than engineering

Also shipping a genetic-algorithm tuning engine for runtime parameters (temperature, top_p, prompt style) — mutation, crossover, elitism, niche preservation, triggered via API endpoints (evolve/feedback). It converged noticeably better settings within ~10 generations.

Repo: [GitHub link] (open core, AGPLv3, 250k lines)
Free for individuals. 

Curious what this community thinks is genuinely interesting vs. gimmicky. Brutal honesty welcome.
```

---

## Sub 2: r/LocalLLaMA — 本地模型/自托管向（P0）

**标题**: `MeshCtx: open-core AI agent with local model support (Ollama), 123+ providers, API-tuned hyperparameters (adaptive)`

**正文**:
```
Sharing something I've been building: an agent platform that runs fully local models via Ollama alongside 123+ cloud providers, with smart routing between them based on task type/cost/latency.

Highlights for this community:
- Local models first-class: Ollama fully supported, no account needed
- Intelligent router picks local vs cloud per task (privacy-sensitive → local, heavy reasoning → cloud)
- 5-model swarm consensus: parallel generation + voting, error rate drops dramatically
- Genetic optimizer tunes runtime config (temperature/top_p/max_tokens/prompt style) via API — generation quality improvements are visible across generations

Desktop apps for Win/macOS/Linux, 10 languages, AGPLv3 open core. Personal use free forever.

[GitHub link]

If you're running local models, I'd love feedback on the routing heuristics and the genetic tuning approach.
```

---

## Sub 3: r/selfhosted — 自托管向（P0）

**标题**: `Self-hosted AI agent with SDM memory and genetic self-tuning — open core, no telemetry`

**正文**:
```
For those who want AI that stays on your machines:

- Runs entirely on your own hardware (local models via Ollama)
- No cloud dependency, no data leaving your network
- Sparse Distributed Memory instead of sending context to external vector DBs
- Genetic algorithm tunes its own parameters on-device
- Linux .deb + AppImage, Windows installer, macOS dmg

Open Core AGPLv3 — framework source fully on GitHub. [link]

Personal use is free forever. Team/Enterprise tiers are in active development — join the waitlist if you need SSO or private deployment.

AMA about the architecture or the self-hosting setup.
```

---

## Sub 4: r/OpenSource — 开源向（P1）

**标题**: `Open-core AI agent (AGPLv3) — 250k lines, 17 brain regions, looking for contributors`

**正文**:
```
MeshCtx is an open-core AI agent platform. The framework is AGPLv3 on GitHub [link], 250k+ lines of Python.

Architecture highlights: 17 brain-region modules, sparse distributed memory, API-controlled evolution engine, genetic-parameter-optimizer, 5-model swarm review, MCP protocol native.

Looking for contributors in: plugin ecosystem, VSCode extension, benchmarking (we claim to beat Cursor on code tasks — want public numbers), and localization.

The business model: individuals free forever, teams/enterprises pay for hosted/managed features. Open source isn't a marketing gimmick here — the whole framework is on GitHub.
```

---

## Sub 5: r/Python — 技术实现向（P1）

**标题**: `[Project] Genetic algorithm that tunes an LLM agent's hyperparameters — 784 lines, stdlib only`

**正文**:
```
I wrote a zero-dependency genetic optimizer for LLM agent parameters. Each "genome" = 6 evolvable params (temperature, top_p, max_tokens, prompt style, memory weight, retrieval top_k). Fitness = task success rate (40%) + latency (20%) + token efficiency (20%) + user acceptance (20%).

Engine: mutation (Gaussian perturbation) + large-jump mutation (simulated transposons) + crossover + top-K elitism + tournament selection + niche preservation to avoid premature convergence.

It's embedded in my agent platform (MeshCtx, open core) — after ~10 generations it finds configs that beat my manual tuning. The optimizer is 784 lines of pure Python stdlib, thread-safe.

Source: [GitHub link to the module]

Happy to explain the fitness landscape design or the niche preservation approach.
```

---

## ⏰ Reddit 发布时间

| Sub | 最佳时间 (美东) | 对应北京时间 |
|:---|:---|:---|
| r/artificial | 周二/三 上午 9-11 | 21:00-23:00 |
| r/LocalLLaMA | 上午 8-10 | 20:00-22:00 |
| r/selfhosted | 上午 9-11 | 21:00-23:00 |
| r/OpenSource | 周中下午 1-3 | 次日凌晨 1-3 |
| r/Python | 上午 10-12 | 22:00-24:00 |

---

## ⚠️ Reddit 避坑

- ❌ 不要在标题写 "Show HN" / "Check out my startup" 这类
- ❌ 不要同一天在多个 sub 发同一内容（会被判定 spam）
- ✅ 每天最多 1-2 个 sub，错开 24h
- ✅ 每个 sub 用不同标题/角度（上面已写好）
- ✅ 发帖后 2 小时内回复所有评论
