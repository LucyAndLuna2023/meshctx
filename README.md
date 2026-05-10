# MeshCtx — AI Continuous Context Memory Platform

智能助手连续上下文记忆平台。集成 Hermes Agent 全部能力（80+ 技能 / 30+ 工具），
为 AI 助手提供跨会话持久化记忆、动态技能编排和多智能体协作。

## Architecture

```
meshctx/
├── src/                     # Core: 记忆引擎 + Hermes 集成层
│   ├── __init__.py
│   ├── memory_engine.py     # MemoryEngine + CrossPlatformEngine + VectorStore + LLMExtractor
│   ├── capabilities.py      # Hermes 能力目录（80+ skills / 30+ tools 注册表）
│   ├── orchestrator.py      # 技能编排引擎：意图→技能匹配→执行
│   └── adapter.py           # 上下文适配器：对接 Hermes memory / session_search
├── server/                  # FastAPI REST 服务
│   ├── __init__.py
│   └── main.py
├── frontend/                # React + TypeScript UI
│   ├── src/ (App.tsx, api.ts, main.tsx)
│   ├── index.html / package.json / vite.config.ts
├── tests/                   # 测试套件
│   ├── unit/                # 单元测试
│   └── integration/         # 集成测试
├── data/                    # SQLite 持久化（自动创建）
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Quick Start

### 1. Backend
```bash
pip install -r requirements.txt
python server/main.py
# → http://localhost:8412
# → Swagger: http://localhost:8412/docs
```

### 2. Frontend
```bash
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

### 3. Tests
```bash
pytest tests/ -v
```

## API Endpoints

| Method | Path | 说明 |
|--------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/stats` | 引擎统计 |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 创建项目 |
| DELETE | `/api/projects/{id}` | 删除项目 |
| POST | `/api/projects/{id}/messages` | 添加消息 → 自动存储+向量化+抽取 |
| GET | `/api/projects/{id}/context` | 获取完整上下文 |
| GET | `/api/projects/{id}/search?q=` | 语义+关键词搜索 |
| GET | `/api/projects/{id}/facts` | 已抽取事实 |

## Hermes 集成能力

meshctx 深度集成 Hermes Agent，提供：

| 能力层 | 说明 |
|--------|------|
| **能力目录** | 80+ 技能 / 30+ 工具的完整注册表，支持语义搜索 |
| **技能编排** | 基于意图自动发现+匹配+调用技能 |
| **上下文桥接** | 对接 Hermes memory / session_search，跨会话上下文打通 |
| **多智能体** | 利用 delegate_task 实现并行任务分解 |
| **MCP 连接** | 通过 native-mcp 接入外部工具生态 |
| **定时任务** | cronjob 驱动的上下文维护 |

## Core Components

### MemoryEngine
统一编排层，管理消息的存储、向量化和信息抽取。

### CrossPlatformEngine
基于 SQLite 的跨平台持久化存储，支持 Linux/Windows/macOS。

### VectorStore
轻量级向量存储，支持余弦相似度搜索。可选集成 sentence-transformers。

### LLMExtractor
使用 LLM 从对话中抽取结构化关键信息（OpenAI 兼容 API）。

## Environment Variables

| Variable | Default | 说明 |
|----------|---------|------|
| `MESHCTX_DATA_DIR` | `./data` | 数据存储目录 |
| `LLM_API_KEY` | — | LLM API key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM 地址 |
| `LLM_MODEL` | `gpt-3.5-turbo` | 模型名 |

## License

MIT
