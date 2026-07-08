# 🔍 004 QA MeshCtx 功能审计报告

> 审计时间: 2026-07-08 | 版本: v3.115.14

## API端点 (核心功能)

| 类别 | 通过 | 失败 |
|------|:---:|:---:|
| Projects CRUD | 5/5 | 0 |
| Conversations+Messages | 4/4 | 0 |
| Agent Sessions | ⚠️ | 1 |
| Memory/Recall | ✅ | 0 |
| Sandbox | ✅ | 0 |
| SSE Stream | ⚠️ 2 | 2 |
| 合计 | 10 | 3 |

⚠️ Agent sessions: conversation_id required
⚠️ SSE /agent-loop/stream 404, /trace/live 404

## UI页面 (7个)

| 页面 | 状态 | 说明 |
|------|:---:|------|
| Dashboard | ✅ | Watchdog/Healer/API表正常 |
| Setup | ✅ | 32模型/多语言/暗色 |
| Desktop | ✅ | 11标签正常 |
| API Docs | ✅ | Swagger正常 |
| **Files** | 🔴 | Loading卡死, 4 JS errors |
| **Chat** | 🔴 | 完全空白, 5 JS errors |
| **Projects** | 🔴 | 500白页 |

## Windows安装

install.bat存在(v3.115.4), 8889端口未启动无exe, 无法测试

## 汇总

P0: Chat空白 / Projects 500 / Files卡死
P1: agent-loop SSE 404 / trace SSE 404
P2: Desktop Windows tab JS error / Agent sessions校验
