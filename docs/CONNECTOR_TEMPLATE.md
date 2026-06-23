# MeshCtx Connector Documentation Template

> 每个连接器的SKILL.md — AI Agent如何使用这个连接器

---

## 模板

```markdown
---
name: connector-name
description: "简短描述 (中英文)"
version: "1.0.0"
author: "MeshCtx Community"
connector: connector-name
type: mcp | api | webhook
---

# 连接器名称 Skill

本 Skill 指导 AI 调用 `connector-name`。

## 调用原则

- [核心规则1]
- [核心规则2]
- 敏感信息不写入公开日志

## 工具说明

| Tool | 用途 | 关键参数 |
| --- | --- | --- |
| tool_name | 功能描述 | param1, param2 |

## 典型流程

1. [步骤1]
2. [步骤2]
3. [步骤3]

## 错误处理

- 参数缺失时向用户说明缺少的字段
- 返回会话过期时重新连接
- 保留服务端 failReason 含义
```

## 已实现的连接器

| 连接器 | 类型 | 状态 |
|--------|------|------|
| sandbox-runner | builtin | ✅ |
| project-indexer | builtin | ✅ |
| feishu-notifier | builtin | ✅ |
| code-reviewer | builtin | ✅ |
| web-search | community | ✅ |
| file-manager | community | ✅ |
| feishu-bot | community | ✅ |
| data-visualizer | community | ✅ |

## 如何提交连接器

1. 复制本模板到 `plugins/{name}/SKILL.md`
2. 填写你的连接器信息
3. 提交到 [meshctx-plugins](https://github.com/LucyAndLuna2023/meshctx-plugins)
