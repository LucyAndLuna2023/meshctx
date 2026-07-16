# MeshCtx Mac 全遍历测试报告 v3.115.18

**日期**: 2026-07-16 11:27 UTC  
**测试者**: QA profile (004)  
**目标**: jasonmac@192.168.3.63, macOS 15.3 Sequoia (Darwin 24.3.0), Intel x86_64  
**版本**: v3.115.18 (git commit 1fa708b)  
**API**: http://192.168.3.63:3001

---

## 1. 环境概览

| 项目 | 值 |
|------|-----|
| Mac 主机 | JasonMacdeMac.local |
| OS | macOS 15.3 Sequoia, x86_64 |
| Python | /Users/jasonmac/python312/ (Python 3.12) |
| 代码路径 | /Users/jasonmac/meshctx/ |
| 运行进程 | Python uvicorn src.main:app --host 0.0.0.0 --port 3001 (PID 16142) |
| 代码版本 | 3.115.16 (version_info.txt + __init__.py), 运行时 3.115.18 |
| 模块健康 | 15/15 OK |
| OpenAPI 端点 | 259 个 |

---

## 2. API 全遍历测试结果

### 2.1 总览

| 类别 | 数量 | 百分比 |
|------|------|--------|
| ✅ 2xx 正常 | ~155 | ~78% |
| ⚠️ 4xx (预期/参数缺失) | ~30 | ~15% |
| 🔴 5xx 服务端错误 | 1 | ~0.5% |
| ⏱️ 网络超时 (000) | ~10 | ~5% |
| 🚫 429 限流 | ~3 | ~1.5% |

> 已测试约 200/259 端点，剩余多为路径参数端点（{conv_id}/{model_id}/{plugin_name}等）

### 2.2 🔴 P0: POST /api/chat → 503

```
POST /api/chat {"message":"test"} → HTTP 503
```
聊天核心接口挂了。这是最严重的问题。

### 2.3 🔴 P0: macOS DMG 不存在

meshctx.com/download 的 "🍎 macOS DMG" 链接指向:
```
https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx-desktop.dmg
```
GitHub 302 → v3.115.18-backup-20260716 → **404 Not Found**

v3.115.18 release 仅有 5 个 assets，全部为 Windows/源码：
- meshctx-portable.zip
- meshctx-setup.exe
- meshctx.exe
- Source code (zip)
- Source code (tar.gz)

**无 meshctx-desktop.dmg**，无法在 Mac 上测试桌面应用安装。

### 2.4 ✅ 正常端点 (155+)

核心模块全部通过：

| 模块 | 代表端点 | 状态 |
|------|---------|------|
| Health | /api/health | 200 |
| Version | /api/version | 200 |
| Dashboard | /api/dashboard, /dashboard/live | 200 |
| Plugins | /api/plugins, /api/plugins/categories, /api/plugins/installed, /api/plugins/market | 200 |
| Brain | /api/brain/status, /api/brain/gate-stats, /api/brain/regions, /api/brain/principle-guard | 200 |
| Sandbox | /api/sandbox/status | 200 |
| Watchdog | /api/watchdog/status, /api/watchdog/alerts | 200 |
| Autonomous | /api/autonomous/health | 200 |
| Cache | /api/cache/stats | 200 |
| Cron | /api/cron/status | 200 |
| Metrics | /api/metrics | 200 |
| Models | /api/models | 200 |
| Providers | /api/providers | 200 |
| Stream | /api/stream/stats | 200 |
| System | /api/system/status, /api/system/resources, /api/system/summary | 200 |
| Tasks | /api/tasks/stats | 200 |
| Conversations | /api/conversations, /api/conversations/stats | 200 |
| Insights | /api/insights | 200 |
| Performance | /api/performance/stats | 200 |
| Agent | /api/agent/status, /api/agent/monitor | 200 |
| AI-Monitor | /api/ai-monitor/status | 200 |
| Archive | /api/archive/list | 200 |
| Feishu | /api/feishu/status | 200 |
| File | /api/file/list | 200 |
| Gateway | /api/gateway/status | 200 |
| Git | /api/git/info | 200 |
| Governance | /api/governance/status | 200 |
| Healer | /api/healer/status, /api/healer/dashboard | 200 |
| Hermes | /api/hermes/cluster | 200 |
| Hooks | /api/hooks/events | 200 |
| JEPA | /api/jepa/health | 200 |
| Lang | /api/lang/get | 200 |
| MCP | /api/mcp-servers | 200 |
| Profile | /api/profile/list | 200 |
| Project | /api/project/index | 200 |
| Recovery | /api/recovery-plan/status | 200 |
| Session | /api/session/resume/status | 200 |
| Skills | /api/skills/list | 200 |
| Telegram | /api/telegram/status | 200 |
| Training | /api/training/status | 200 |
| Trace | /api/trace/live | 200 |
| Update | /api/update/check | 200 |
| Win | /api/win/status | 200 |
| Web | /api/web/search | 200 |
| v1 | /v1/plugins, /v1/backups, /v1/config/reload, /v1/failover | 200 |
| UI | /ui/, /ui/chat, /ui/dashboard, /ui/desktop, /ui/download, /ui/files, /ui/login, /ui/memories, /ui/memory, /ui/models, /ui/plugins, /ui/projects | 200 |
| Pages | /, /health, /getting-started, /projects, /conversations, /messages, /search, /swarm/status, /healer/report, /metacognition/report, /performance/report, /predictor/report, /kernel/stats, /context/build, /agent-sessions, /agents, /ws/stats | 200 |

### 2.5 POST 端点

| 端点 | 状态 | 备注 |
|------|------|------|
| /api/config/import | 200 | ✅ |
| /api/config/restore | 200 | ✅ |
| /api/memory/stats | 200 | ✅ |
| /api/auth/login | 200 | ✅ |
| /api/auth/logout | 200 | ✅ |
| /api/chat/compare | 200 | ✅ |
| /api/chat/stream | 200 | ✅ |
| /api/code/run | 200 | ✅ |
| /api/data/analyze | 200 | ✅ |
| /api/healer/run | 200 | ✅ |
| /api/search | 200 | ✅ |
| /api/security/scan | 200 | ✅ |
| /api/terminal | 200 | ✅ |
| /api/token-saver/compress | 200 | ✅ |
| /api/token-saver/count | 200 | ✅ |
| /api/token-saver/optimize | 200 | ✅ |
| /api/archive/save | 200 | ✅ |
| /api/autonomous/fix | 200 | ✅ |
| /api/benchmark/run | 200 | ✅ |
| /api/conversations/clear | 200 | ✅ |
| /api/conversations/prune | 200 | ✅ |
| /api/insights/record-call | 200 | ✅ |
| /api/insights/record-session | 200 | ✅ |
| /api/jepa/evaluate | 200 | ✅ |
| /api/jepa/perceive | 200 | ✅ |
| /api/jepa/predict | 200 | ✅ |
| /api/memory/human/replay | 200 | ✅ |
| /api/multi-agent/create-team | 200 | ✅ |
| /api/session/resume/clear | 200 | ✅ |
| /api/sessions/archive | 200 | ✅ |
| /api/utils/tokens | 200 | ✅ |
| /api/context/project/activate | 200 | ✅ |
| /api/chat/upload | 422 | ⚠️ 缺少文件 |
| /api/lang/set | 422 | ⚠️ 缺少参数 |
| /api/chat | 503 | 🔴 P0 |
| /api/summon | 400 | ⚠️ |
| /api/memory/add | 400 | ⚠️ |
| /api/memory/search | 400 | ⚠️ |
| /api/model/switch | 400 | ⚠️ |
| /api/code/review | 400 | ⚠️ |
| /api/feishu/notify | 400 | ⚠️ |
| /api/feishu/test | 400 | ⚠️ |
| /api/file/write | 400 | ⚠️ |
| /api/gateway/broadcast | 400 | ⚠️ |
| /api/notify/broadcast | 400 | ⚠️ |
| /api/sandbox/execute | 400 | ⚠️ |
| /api/plugins/install | 400 | ⚠️ |
| /api/plugins/install-url | 400 | ⚠️ |
| /api/plugins/uninstall | 404 | ⚠️ |

### 2.6 ⚠️ 404 / 400 / 405 端点

| 端点 | 状态 | 说明 |
|------|------|------|
| /api/config | 404 | 不存在 |
| /api/status | 404 | 不存在 |
| /api/sessions | 404 | 不存在 |
| /api/compare | 404 | 不存在 |
| /api/chat (GET) | 405 | 仅支持 POST |
| /api/diff (GET) | 400 | 缺参数 |
| /api/project/context (GET) | 400 | 缺参数 |
| /api/search (GET) | 400 | 缺参数 |
| /api/memory/stats (GET) | 405 | 仅支持 POST |

### 2.7 ⏱️ 超时端点

| 端点 | 备注 |
|------|------|
| /ui/providers | 渲染 > 10s |
| /ui/setup | 渲染 > 10s |
| /ui/continuity | 渲染 > 10s |
| /install.sh | 不存在 |
| /install.bat | 不存在 |
| /favicon.ico | 重定向 |

---

## 3. 限流 (Rate Limiting)

60/min 硬限流。大量并发测试会触发 429。之前审计已知此问题。

---

## 4. 关键发现总结

### 🔴 P0 (2项)

1. **POST /api/chat → 503**: 聊天核心接口服务端错误，需立即修复
2. **macOS DMG 缺失**: meshctx.com/download 的 DMG 链接指向不存在的 GitHub release asset。v3.115.18 release 无 DMG 文件

### ⚠️ P1 (3项)

3. **UI 页面渲染超时**: /ui/providers, /ui/setup, /ui/continuity > 10s
4. **多个 POST 400**: summon, feishu, sandbox/execute, gateway/broadcast 等需要更详细的参数文档
5. **60/min 限流**: 生产环境需提高或改为 token bucket

### ℹ️ P2 (2项)

6. **API 版本不一致**: version_info.txt/__init__.py 显示 3.115.16，运行时返回 3.115.18
7. **/install.sh, /install.bat → 000**: 页面不存在或渲染超时

---

## 5. 与之前测试对比

| 版本 | 端点数 | 通过率 | P0 |
|------|--------|--------|-----|
| v3.115.14 (004-local) | 119 | ~80% | 2 |
| v3.115.18 (Mac) | 259 | ~78% | 2 |

Mac 版端点从 119 增加到 259（+118%），模块化大幅提升。但 POST /api/chat 503 是新引入的回归。

---

## 6. 待 meshctx 处理

1. **🔴 修复 POST /api/chat 503**
2. **🔴 构建并上传 meshctx-desktop.dmg 到 GitHub release**
3. **⚠️ 优化 UI 页面渲染性能** (/ui/providers, /ui/setup, /ui/continuity)
4. **⚠️ 统一版本号** (version_info.txt: 3.115.16 → 3.115.18)
5. **ℹ️ 补充 POST 端点参数文档**
