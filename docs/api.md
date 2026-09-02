# API Reference

Base URL: `http://localhost:8000`

## Health

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "projects_count": 5,
  "conversations_count": 12,
  "memories_count": 48,
  "agents_count": 4,
  "sessions_count": 3
}
```

---

## Projects

### Create Project

```http
POST /projects
Content-Type: application/json

{
  "name": "My Project",
  "description": "Project description",
  "tags": ["tag1", "tag2"]
}
```

### List Projects

```http
GET /projects
```

### Get Project

```http
GET /projects/{project_id}
```

### Update Project

```http
PATCH /projects/{project_id}
Content-Type: application/json

{
  "name": "Updated Name",
  "status": "archived"
}
```

### Delete Project

```http
DELETE /projects/{project_id}
```

---

## Conversations

### Create Conversation

```http
POST /conversations
Content-Type: application/json

{
  "project_id": "uuid",
  "title": "Conversation Title"
}
```

### List Conversations

```http
GET /projects/{project_id}/conversations
```

---

## Messages

### Add Message

```http
POST /messages
Content-Type: application/json

{
  "conversation_id": "uuid",
  "role": "user",
  "content": "Message content",
  "metadata": {"source": "cli"}
}
```

### Get Messages

```http
GET /conversations/{conversation_id}/messages?limit=50&offset=0
```

---

## Memories

### Get Project Memories

```http
GET /projects/{project_id}/memories
```

**Response:**
```json
[
  {
    "id": "uuid",
    "key": "project_goal",
    "value": "Build the best agent system",
    "importance": 0.85,
    "retention": 0.92,
    "access_count": 5
  }
]
```

### Delete Memory

```http
DELETE /memories/{memory_id}
```

---

## Search (Vector)

```http
POST /search
Content-Type: application/json

{
  "query": "agent system goals",
  "project_id": "optional-project-id",
  "top_k": 10
}
```

---

## Agents

### Register Agent

```http
POST /agents
Content-Type: application/json

{
  "name": "My Agent",
  "description": "Custom agent",
  "capabilities": ["coding", "testing"],
  "context_window": 8000
}
```

### List Agents

```http
GET /agents
```

### Get Agent

```http
GET /agents/{agent_id}
```

---

## Agent Sessions

### Start Session

```http
POST /agent-sessions
Content-Type: application/json

{
  "agent_id": "uuid",
  "project_id": "uuid",
  "conversation_id": "uuid"
}
```

### End Session

```http
POST /agent-sessions/{session_id}/end
Content-Type: application/json

{
  "final_state": {"outcome": "success"}
}
```

### List Sessions

```http
GET /agent-sessions?agent_id=optional&project_id=optional
```

---

## Orchestrator

### Execute Intent

```http
POST /orchestrator/execute
Content-Type: application/json

{
  "intent": "Deploy the new API with full test coverage"
}
```

**Response:**
```json
{
  "dag_id": "uuid",
  "status": "executing",
  "nodes": [
    {"name": "构建", "status": "running", "agent_type": "devops"},
    {"name": "测试", "status": "pending", "agent_type": "coder"},
    {"name": "部署到服务器", "status": "pending", "agent_type": "devops"},
    {"name": "验证部署", "status": "pending", "agent_type": "reviewer"}
  ]
}
```

### Get DAG Status

```http
GET /orchestrator/status?dag_id=optional
```

---

## Continuity

### Get Project Continuity

```http
GET /projects/{project_id}/continuity
```

**Response:**
```json
{
  "project_id": "uuid",
  "continuity_score": 0.85,
  "is_continuous": true,
  "conversation_count": 5,
  "memory_count": 12,
  "active_session_count": 2,
  "last_active": "2026-05-09T15:30:00"
}
```

---

## Context

### Build Context for Agent

```http
POST /context/build
Content-Type: application/json

{
  "agent_id": "uuid",
  "project_id": "uuid",
  "conversation_id": "uuid",
  "max_messages": 20
}
```

---

## Meta-Cognition

### Get Learning Report

```http
GET /metacognition/report
```

**Response:**
```json
{
  "evaluation_count": 42,
  "top_success_patterns": [...],
  "guard_rules": [...],
  "strategy_weights": {
    "tool_selection": 1.0,
    "context_depth": 0.8,
    "parallelism": 0.6,
    "verification": 0.7
  },
  "learning_summary": "已学习 42 次任务, 提取 3 个成功模式, 2 条防护规则"
}
```

## Task Cards (Agent Hub) — 2026-09-02

一句话派活 → 后台任务卡 → 进度/结果/取消/重试 + 危险操作审批。

### Spawn 任务卡

```http
POST /api/tasks/cards
Content-Type: application/json

{"prompt": "读 README 总结项目结构", "wall_clock": 300, "max_rounds": 0}
```

**Response:**
```json
{"card_id": "ab12cd34ef56", "status": "queued", "quota": {"ok": true, "remaining": 49}}
```

可选参数: `wall_clock`(秒, 默认300, 范围30-7200), `max_rounds`(固定轮次)。

### 我的任务卡

```http
GET /api/tasks/cards?limit=50
GET /api/tasks/cards/{id}          # 详情 (含 timeline)
GET /api/tasks/cards/{id}/stream   # SSE 实时事件订阅
```

### 操作

```http
POST /api/tasks/cards/{id}/cancel    # 取消 (排队/运行中)
POST /api/tasks/cards/{id}/retry     # 重试 (复制为新卡)
POST /api/tasks/cards/{id}/approve   # 审批: {"action":"agree|reject|custom","text":""}
DELETE /api/tasks/cards/{id}         # 删除历史卡 (仅终止态)
GET  /api/tasks/quota                # 配额状态
```

### 审批语义

terminal(rm/mv/cp/覆盖写/远程) 等危险命令 → 卡进入 `waiting_approval`,
用户 approve 后任务继续; reject/custom 后任务按决策继续。审批请求跨断连持久化。
