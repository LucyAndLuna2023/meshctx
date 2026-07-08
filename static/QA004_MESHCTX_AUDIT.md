# 004 QA MeshCtx 产品审计 — 第四轮

> **审计时间**: 2026-07-08 10:30 UTC
> **目标**: meshctx-web v3.115.14 @ localhost:3001

---

## R3→R4 变化

| 端点 | R3 | R4 | 变化 |
|------|:---:|:---:|:---:|
| /ui/projects | 500 | **TIMEOUT(5s)** | 🔴 恶化 |
| /ui/chat | 200 | 200 | ✅ |
| human/recall | 200 | 200 | ✅ |
| /conversations | 200 | 200 | ✅ |
| /messages | 200 | 200 | ✅ |
| /search | 200 | 200 | ✅ |
| agent-loop/stream | 404 | 404 | ❌ |
| trace/live | 404 | 404 | ❌ |

---

## 🔴 P0: /ui/projects 页面死锁

不是500，而是**请求永久挂起**（5秒超时无响应）。
推测：458个project渲染时死循环或DB锁。

## 残余 (2个)
- /api/agent-loop/stream 404
- /api/trace/live 404

## 📊 四轮趋势

| | R1 | R2 | R3 | R4 |
|---|:---:|:---:|:---:|:---:|
| bug总数 | 6 | 9 | 4 | 3 |
| P0 | 1 | 0 | 1 | 1 |

R1和R4各一个P0，R2/R3干净。

---

## ⚠️ 未收到admin回复
hub_inbox/meshctx对话均未找到回复消息。
