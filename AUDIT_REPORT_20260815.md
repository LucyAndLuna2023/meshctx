# MeshCtx 全面审计报告 (48h) — 实时记录

> 审计者: 004-meshctx profile | 开始: 2026-08-15 09:00 CST | 基线 tag: `audit-baseline-20260815`
> 铁律: ①不碰股票 ②禁删代码/禁 _P ③十语言三平台不丢功能 ④先架构后测试 ⑤可回滚

---

## 一、审计范围

| 层 | 位置 | 状态 |
|---|---|---|
| 开源 meshctx-public | `~/meshctx-public` (GitHub LucyAndLuna2023) | v3.115.15+, 305 py 文件 / 119,295 行 |
| 闭源 meshctx-core | `~/meshctx-core` (私有仓库) | v3.48 服务器版, AGENTS.md 已读 |
| 网站 meshctx.com | `~/meshctx-local` | 7语言主页, docker-compose |

## 二、架构全景 (阶段1 完成)

```
Layer 1: meshctx.com 网站 (~/meshctx-local)
Layer 2: 闭源核心 (~/meshctx-core, v3.48, 62工具, deepseek-v4-pro)
Layer 3: 开源组件 (~/meshctx-public, 当前主力开发)
```

**开源侧结构**:
- `src/main.py` — **6969 行 / 270KB 巨型入口** (FastAPI app + lifespan + 全部 API)
- `src/core/` — 278 个 py 文件 / 11MB (插件内核 + stub 代理)
- `src/chat_tools.py`, `src/cli.py`, `src/agent_loop.py`, `src/model_registry.py` — CLI/Agent 核心
- `benchmarks/` — terminal_bench + gaia + swebench_pro 三套 harness (已闭环)
- `tests/` — 197 个测试文件
- `cluster/hub_client.py` — 集群通讯 v5
- **stub 模式**: 开源侧大量模块是 `_StubProxy`/`_MeshCtxStubProxy` 接口, 核心实现闭源 (meshctx-core 未安装时优雅降级)

## 三、十语言 i18n (阶段2 完成)

| 语言文件 | 语言数 | 结论 |
|---|---|---|
| `docs/i18n/landing.json` | 10 (en/zh/fr/de/ja/ko/es/it/ar/ru) | ✅ 完整 |
| `src/i18n_translations.json` | 10 (zh/en/ja/ko/fr/de/es/it/ar/ru) | ⚠️ 键不一致 (见 bug #2) |

## 四、三平台构建 (阶段3 完成)

| 平台 | 构建脚本 | CI |
|---|---|---|
| Linux | install.sh (35KB) | build-linux.yml ✅ |
| macOS | install-mac.sh (42KB) + build-mac.sh + build-dmg.sh | build-macos.yml ✅ |
| Windows | install.bat + build.bat + meshctx.spec + meshctx_setup.nsi | build-windows.yml ✅ |

## 五、bug 清单 (持续更新)

| # | 优先级 | 类别 | 描述 | 状态 |
|---|---|---|---|---|
| 1 | **P0** | 内存 | `src/main.py:602` 模块顶层执行 `_setup_memory_limit()` → import 时 RLIMIT_AS 限 2GB → Python 3.14 import main MemoryError (pytest 污染) | ✅ 已修复 (见下) |
| 2 | P1 | i18n | `src/i18n_translations.json` ru 多 133 键 (132 chat_text_xxx + __available_langs__), 其他 9 语言缺 chat 界面翻译键 | 待修 |
| 3 | P2 | 架构 | `src/main.py` 6969 行巨型文件, 顶层大量副作用 (MetricsCollector/APIKeyFailover 实例化) | 记录 |
| 4 | P2 | 文档 | ARCHITECTURE.md 过时 (说拆分未执行, 实际已 stub 化) | 记录 |
| 5 | P3 | 文档 | meshctx-core/AGENTS.md 引用的服务器 47.120.0.239 已停用 (2026-06-20 UAT 关闭) | 记录 |
| 6 | **P1** | 产品描述 | meshctx.com 跨语言宣称不一致: 英文版诚实 "SWE-bench Lite target >30% (runner in development)", 中文/日文/韩文等 9 语言夸大 "超越 Claude Code" | 待修 |
| 7 | **P1** | 产品描述 | "17-Brain-Region" 宣称 vs 代码实际: brain_architecture.py 文档称 13 脑区, 实际导入 14 个脑区模块, 共 22 个 brain_*.py 文件 | 待修 |
| 8 | P2 | i18n | `templates/chat.html` 内联 i18n 仅 9 语言 (缺 ru), 且 de 用键名 `chat_text` 与其他语言 `chat_direct` 不一致 | 待修 |
| 9 | P2 | i18n | `src/i18n_translations.json` ru 多 132 个 chat_text_xxx 死键 (旧版 chat 界面翻译, 现 chat.html 内联, 无代码引用) | 记录 |
| 10 | **P1** | stub | `memory_hierarchy.py` 等 stub 构造器直接 raise NotImplementedError (非优雅降级), 导致 44 个内存测试 error — 与 conftest "优雅降级" 声明矛盾 | 待修 |
| 11 | **P0** | 基准 | SWE-bench 跑分不可信: harness `resolved = syntax_valid AND file_f1>0` (纯文本重叠启发式), **未跑 FAIL_TO_PASS/PASS_TO_PASS 测试**, 自报 98.7-100% resolve rate 与官方口径不可比 | 待修 |
| 12 | P1 | 基准 | file_f1_mean 从 v7c 0.347 跳到 v8_auto 0.967 (评分算法变动未记录), 跑分纵向不可比 | 记录 |

## 六、修复记录 (每轮可回滚)

### 修复 1 (已执行, tag: audit-fix-1-memory-rlimit)
- **bug #1**: `_setup_memory_limit()` 从模块顶层移至 lifespan startup, 修复 Python 3.14 import MemoryError
- **根因**: `_setup_memory_limit()` 在 import 时执行, RLIMIT_AS=2GB 限制虚拟地址空间 (非 RSS), Python 3.14 解释器+共享库 mmap 超限
- **验证**: 默认环境 import src.main 成功 (RSS 70.6MB, 1.2s); MESHCTX_MEMORY_SOFT_MB=8192 → RSS 71MB; 默认 2048 → MemoryError
- **功能保留**: `_setup_memory_limit` 函数与 SIGSEGV 处理保留, 由 lifespan startup 调用
- commit: `fix(P0-内存): 内存限制从模块顶层移至 lifespan startup`

### 回滚点
- `audit-baseline-20260815` — 审计开始前基线 (HEAD `251c3a0`)
- `audit-fix-1-memory-rlimit` — 修复 1 前快照
- 每轮修复前打 tag: `audit-fix-N-<desc>`, 回滚: `git reset --hard <tag>`

## 七、SWE-bench 对比 (2026-02 官方数据)

**官方 % Resolved 判定** = 通过 FAIL_TO_PASS 测试 + 不破坏 PASS_TO_PASS 测试 (真实跑测试)

| 排行榜 | 顶级模型 | % Resolved | 数据日期 |
|---|---|---|---|
| Verified (500) | Claude 4.5 Opus (high) | **76.8** | 2026-02-17 |
| Verified (500) | Gemini 3 Flash (high) | 75.8 | 2026-02-17 |
| Verified (500) | Claude 4.6 Opus | 75.6 | 2026-02-17 |
| Verified (500) | GPT 5.2 Codex | 72.8 | 2026-02-19 |
| Verified (500) | GLM 5 (high, 开源) | 72.8 | 2026-02-17 |
| Lite (300) | Claude 4 Sonnet (ExpeRepair) | **60.3** | 2025-06-25 |
| Lite (300) | Refact.ai Agent | 60.0 | 2025-04-25 |
| Lite (300) | Qwen3-Coder-30B (开源) | 49.7 | 2025-09-01 |

**MeshCtx 声称 vs 实际**:
- 闭源仓库自报: SWE-bench Lite resolve_rate **98.7-100%** (swebench_score_v6/v7c/v8_auto.json)
- 实际判定逻辑: `resolved = syntax_valid AND file_f1>0` — **未跑 FAIL_TO_PASS/PASS_TO_PASS 测试**, 与官方口径不可比 (伪跑分)
- meshctx.com 英文版诚实: "SWE-bench Lite target >30% (runner in development)"
- meshctx.com 中文/日文/韩文版夸大: "超越 Claude Code" — 与官方数据 (Claude 76.8%) 矛盾

**结论**: MeshCtx 无经过官方 SWE-bench 验证的真实跑分; 其 98.7% 自报分数比顶级 agent 还高 22 个百分点, 但判定逻辑完全不同, **不可用于对外对比**。

## 八、GitHub 最新 AI agent 测试方法 (2026)

1. **SWE-bench** (官方 swebench.com) — 代码修复基准, % Resolved = FAIL_TO_PASS + PASS_TO_PASS 真实测试; Verified 500 / Lite 300 / Multilingual / Multimodal
2. **Terminal-Bench** (github.com/laude-institute/terminal-bench) — CLI/终端任务基准, 32 类任务
3. **AgentBench** (github.com/THUDM/AgentBench) — 首个 LLM-as-Agent 多环境基准 (操作系统/数据库/知识图谱等 8 环境)
4. **OSWorld** — GUI/桌面操作系统操作基准
5. **Anthropic "Demystifying Evals for AI Agents"** (2026) — 评估方法论: 测什么/如何建 harness/为何单元测试式 eval 对 agent 失效
6. **awesome-harness-engineering** (github.com/ai-boost/awesome-harness-engineering) — harness 工程最佳实践清单
7. **awesome-ai-agent-papers** (github.com/VoltAgent) — 2026 arXiv 论文集合 (多智能体/记忆/RAG/工具/评估)

**对 MeshCtx 的建议**: 当前 harness 的 `resolved` 判定必须改为真实执行 FAIL_TO_PASS/PASS_TO_PASS 测试 (可用 SWE-bench CLI 官方验证器), 否则跑分不可对外使用。
