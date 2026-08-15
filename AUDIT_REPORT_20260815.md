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

## 六、修复记录 (每轮可回滚)

### 修复 1 — bug #1 内存 RLIMIT (P0)
- **根因**: `_setup_memory_limit()` 在 import 时执行, RLIMIT_AS=2GB 限制虚拟地址空间, Python 3.14 解释器+共享库超限
- **验证**: MESHCTX_MEMORY_SOFT_MB=8192 → import 成功 (RSS 71MB); 默认 2048 → MemoryError
- **方案**: 调用从模块顶层移到 lifespan startup (服务启动时仍设置, 功能不丢)
- **回滚**: `git revert` 或 `git reset --hard audit-baseline-20260815`

## 七、回滚点

- `audit-baseline-20260815` — 审计开始前基线 (HEAD)
- 每轮修复前打 tag: `audit-fix-N-<desc>`
