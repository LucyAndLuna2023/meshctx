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
