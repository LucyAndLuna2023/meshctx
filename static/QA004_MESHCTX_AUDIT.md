# 004 QA MeshCtx 产品审计报告

> **审计时间**: 2026-07-07 06:50-07:05 UTC
> **目标**: meshctx-web v3.115.14 @ localhost:3001
> **方法**: 逐端点黑盒测试 + 代码审查

---

## 测试范围

| 模块 | 端点 | 通过 | 失败 |
|------|:---:|:---:|:---:|
| Projects CRUD | 6 | 6 | 0 |
| Conversations+Messages | 3 | 3 | 0 |
| Agents+Sessions | 4 | 4 | 0 |
| Search | 1 | 1 | 0 |
| Context/Kernel | 4 | 3 | 1* |
| Token Saver | 3 | 3 | 0 |
| Hermes Cluster | 1 | 1 | 0 |
| Memory API | 5 | 4 | 1 |
| Human Memory | 3 | 2 | 1 |
| Brain API | 2 | 2 | 0 |
| File API | 1 | 1 | 0 |
| UI Pages | 8 | 1 | 7 |
| SSE Streams | 3 | 0 | 3 |
| **总计** | **44** | **31** | **13** |

> *Context POST 422 — 缺少必填字段，非bug

---

## 🔴 P0 Bug: 7/8 UI页面500 Internal Server Error

**根因**: `src/web_ui.py` 使用 `DictLoader` 加载模板，_TEMPLATES 只注册了7个模板，但有14个 `_render()` 调用。缺失模板列表:

| 缺失模板 | 路由 | 影响 |
|----------|------|------|
| chat.html | /ui/chat | 聊天主页崩溃 |
| projects.html | /ui/projects | 项目管理页崩溃 |
| project_detail.html | /ui/project/{id} | 项目详情崩溃 |
| conversation.html | /ui/conversation/{id} | 对话页崩溃 |
| memories.html | /ui/project/{id}/memories | 记忆页崩溃 |
| memory.html | /ui/project/{id}/memory | 单记忆崩溃 |
| continuity.html | /ui/project/{id}/continuity | 连续性页崩溃 |

**仅 /ui/dashboard 正常** — 因为使用硬编码HTML而非 _render()。

**代码位置**: `web_ui.py:3595` — `_jinja_env = Environment(loader=DictLoader(_TEMPLATES))`

_TEMPLATES 已注册: base.html, setup.html, desktop.html, download.html, models.html, providers.html, files.html

_TEMPLATES 缺失: **chat.html**, **projects.html**, **project_detail.html**, **conversation.html**, **memories.html**, **memory.html**, **continuity.html**, **dashboard.html**

---

## 🔴 P1 Bug: /api/memory/human/recall 500

**现象**: POST {"query":"测试"} → 500 Internal Server Error
**代码**: `main.py:4555-4568`, 调用 `hm.recall(query, context_tags, top_k)` 崩溃
**影响**: 人类记忆回忆功能完全不可用

---

## 🟡 P2 Bugs

### 3. SSE流端点全部404

| 端点 | 状态 |
|------|:---:|
| /api/agent-loop/stream | 404 |
| /api/sandbox/stream | 404 |
| /api/trace/live | 404 |

### 4. Memories REST路径不一致

- 创建: `/api/memory/add` (POST) ✅
- 读取: `/projects/{id}/memories` (GET) ✅
- 删除: `/memories/{id}` (DELETE) ✅
- 创建2: `/projects/{id}/memories` (POST) → **405** ❌

### 5. 认证未启用

`MESHCTX_PASSWORD` 未设 → auth_middleware_v2 全局放行。所有受保护API无需认证。

---

## ✅ 通过的功能（31项）

Projects/Conversations/Messages/Agents/Sessions 完整CRUD, Search, Context build, Kernel stats, Token saver (stats/count/optimize), Hermes cluster, Memory add/search/graph/stats, Human memory encode/stats, Brain gate-stats/status, File list, Health, Getting started.

---

## 📋 建议修复优先级

1. **[P0]** 将7个缺失模板嵌入 `_TEMPLATES` dict
2. **[P1]** 修复 `human_memory.recall()` 崩溃
3. **[P2]** 实现或移除3个SSE端点
4. **[P2]** 统一memories REST路径
