# 🔍 004 QA — MeshCtx 全量审计报告

> **审计日期**: 2026-07-08 | **审计者**: 004 QA (HCQA-YFVOARYRGY)
> **目标版本**: meshctx v3.115.14 @ localhost:3001 | GitHub: LucyAndLuna2023

---

## 总览

| 审计维度 | 结论 |
|----------|------|
| GitHub 仓库总数 | **20**（12公开 + 8私有） |
| 公开代码行数 | ~6,818,325 |
| meshctx/hermes 代码比 | **14.4%**（含完整生态） |
| `_P`黑洞模式占比 | **60%** 模块受影响 |
| 虚假宣称 | SWE-bench 98.7%, IIT意识引擎, 元认知等 |
| 真实实现 | WebUI 274K行 + API 227K行 |
| 架构模式 | 开源外壳 + 私有核心（meshctx-core） |

---

## 一、GitHub 仓库审计

### 公开仓库 (12个)

| 仓库 | 语言 | 行数 | 文件 | 最后提交 |
|------|------|------|------|----------|
| **meshctx** | Python/HTML/TS | **6,565,669** | 691 | 2026-07-08 |
| feishu-evidence | JS/HTML | 180,351 | 17 | 2026-04-30 |
| find_evil | Python | 66,332 | 14 | 2026-06-03 |
| memory-agent | HTML/Python | 53,029 | 9 | 2026-06-05 |
| oobe-agent | Python | 20,730 | 3 | 2026-06-01 |
| memoryagent | Python | 18,414 | 3 | 2026-06-05 |
| keypool | Python | 9,308 | 4 | 2026-06-01 |
| agent_vault | Python | 9,101 | 10 | 2026-06-03 |
| tradeflow-uipath | Python | 9,407 | 8 | 2026-05-27 |
| membase | Python | 4,286 | 2 | 2026-06-01 |
| cryptopulse-slack | Python | 4,182 | 7 | 2026-05-27 |
| studypulse-dsh | Python | 4,180 | 4 | 2026-05-27 |

### 私有仓库 (8个)

| 仓库 | 大小 | 最后提交 |
|------|------|----------|
| **hermes-agent** | 368MB | 2026-06-30 |
| **meshctx-core** | 285MB | 2026-06-20 |
| **hermes-profiles** | 130MB | 2026-07-08 |
| geo-content-engine | ~3M行 | 2026-06-22 |
| lexai + lexai-web + lexai-crypto | JS/Python | 2026-06-19 |

> **关键**: meshctx-core (285MB 私有) 是真实引擎，公开 meshctx 仓库的 core/__init__.py 是 stub 分发器。

---

## 二、代码规模对比 — 用户怀疑成立 ✅

| 指标 | MeshCtx | Hermes-Agent | 比率 |
|------|---------|-------------|------|
| Python 源文件 | 266 | 747 | 35.6% |
| Python 行数 | ~112,560 | ~530,256 | **21.2%** |
| 测试文件 | 203 | 1,548 | 13.1% |
| 测试行数 | ~43,151 | ~567,314 | 7.6% |

含 Hermes 完整生态（skills + profiles + scripts = ~784K行）:

**meshctx / hermes完整生态 = 14.4%** 🔴

---

## 三、水分分析 — `_P` 黑洞代理模式 🔴🔴🔴

63个模块各自定义 `_P` 类 (~40行)，覆盖 Python dunder 方法，让任何调用"成功但无效果"：

```python
class _P:
    def __bool__(self): return True       # 永远 Truthy
    def __eq__(self, o): return True      # 永远相等
    def __getattr__(self, n): return _P() # 无限代理
    def __call__(self, *a, **k): return _P()
```

| Stub 类型 | 文件数 | 行数 | 占比 |
|-----------|--------|------|------|
| 显式"开源版 stub" | 24 | 1,508 | 1.3% |
| 定义 `class _P` | 63 | 13,107 | 11.6% |
| 引用 `_P` (依赖stub) | 87 | 54,345 | 48.3% |
| **总涉及 _P 模式** | **150/266 (56%)** | **~67K** | **~60%** |

---

## 四、虚假宣称清单 🔴

| 宣称 | 实际情况 | 严重度 |
|------|---------|:---:|
| **SWE-bench v8: 296/300=98.7%** | 代码中完全无 SWE-bench 引用 | 🔴 |
| **IIT 意识引擎 (Φ计算)** | `phi = 0.3 + random.random() * 0.4` | 🔴 |
| **元认知引擎** | 99行 stub，显式"开源版(stub)" | 🔴 |
| **Docker 沙箱** | `# Docker状态 stub (v3.115.16)` | 🔴 |
| **28 插件** | plugin_manager 37行 stub | 🟡 |
| **JEPA 世界模型** | 有类结构，无训练/推理 pipeline | 🟡 |

---

## 五、真正扎实的实现 (~40%)

| 模块 | 行数 | 评价 |
|------|------|------|
| web_ui.py | 274K | ✅ 完整 SPA，252 API routes |
| main.py | 227K | ✅ API 服务器 |
| doc_generator.py | 51K | ✅ |
| test_generator.py | 66K | ✅ |
| notification_hub.py | 47K | ✅ |
| load_balancer.py | 45K | ✅ |
| task_queue_v2.py | 43K | ✅ |
| refactor_agent.py | 41K | ✅ |
| pr_agent.py | 38K | ✅ |
| error_recovery.py | 38K | ✅ |

---

## 六、功能覆盖对比

| 功能域 | MeshCtx 实际 | Hermes 实际 |
|------|-------------|------------|
| Agent Loop | 286行+_P | 249K行 |
| Gateway 平台 | 3 stub | 32 完整适配器 |
| 浏览器自动化 | 8.8K | 164K+ |
| 插件系统 | 37行 stub | 58K/137文件 |
| MCP | 11K | 203K |
| TUI | 无 | 10K |
| Web UI | 274K ✅ | TUI+Desktop |
| 定时任务 | 9K ✅ | 42K |

---

## 七、本机测试结果

### API 端点 (13项)

| 端点 | 状态 | 备注 |
|------|:---:|------|
| Projects CRUD | ✅ | 5/5 通过 |
| Conversations | ✅ | 正常 |
| /messages GET | ✅ 200 | |
| /messages POST | 🔴 404 | 回归 |
| /search | ✅ 200 | |
| /api/memory/human/recall | ✅ 200 | |
| /api/agent-loop/stream | 404 | 未实现 |
| /api/trace/live | 404 | 未实现 |
| /api/sandbox/stream | ✅ 200 | |
| /ui/projects | 🔴 500 | 白页 |

### UI 页面 (7个)

| 页面 | 渲染 | JS错误 |
|------|:---:|:---:|
| Dashboard | ✅ | 0 |
| Setup | ✅ | 0 |
| Desktop | ✅ | 0 |
| API Docs | ✅ | 0 |
| Files | ⚠️ Loading卡死 | 4 |
| Chat | 🔴 空白 | 5 |
| Projects | 🔴 500 | 1 |

---

## 八、架构图

```
LucyAndLuna2023 GitHub
├── meshctx (公开, 6.5M行) ─── 开源外壳
│   ├── core/__init__.py ── _P 黑洞代理 ──→ meshctx-core (私有, 285MB)
│   ├── web_ui.py 274K ✅ ─── 真实 SPA
│   ├── main.py 227K ✅ ─── 真实 API
│   └── 150/266 模块 ── _P stub (~60%)
│
├── meshctx-core (私有, 285MB) ── 🔒 真实引擎
├── hermes-agent (私有, 368MB) ── 🔒 Hermes本体
├── hermes-profiles (私有, 130MB) ── 🔒 配置文件
│
└── 辅助仓库 ×16 (公开+私有)
    ├── memory-agent, oobe-agent ── 概念验证
    ├── find_evil ── 安全工具
    ├── geo-content-engine ── 私有内容引擎
    └── lexai* ×4 ── 交易信号
```

---

## 九、结论

### 🔴 水分确认
- **代码量只有 Hermes 的 14.4%**，用户怀疑完全成立
- **60% 模块含 `_P` 黑洞代理** — 开源版本质是外壳
- **SWE-bench 98.7%、IIT意识引擎、元认知均为虚假宣称**
- 真实引擎在 meshctx-core (私有)，不开源

### 🟢 非完全空壳
- Web UI (274K行) + API (227K行) 是真实实现
- 代码生成、任务队列、通知等模块真实可用
- API 端大部分正常（除了几个已知404/500）

### 📊 最终评分

| 维度 | 评分 |
|------|:---:|
| 代码真实性 | 🔴 D (60% stub) |
| 功能宣称诚实度 | 🔴 F (多项虚假) |
| Web UI 质量 | 🟢 B+ |
| API 完整性 | 🟡 C (有回归) |
| 开源透明度 | 🔴 F (核心私有) |
| **综合** | **🔴 D+** |

---

> *审计依据: GitHub API全量仓库扫描 + 本机meshctx全功能测试 + 源码级模块对比 + `_P`模式静态分析*
> *报告路径: http://localhost:3001/static/QA004_FULL_AUDIT.md*
