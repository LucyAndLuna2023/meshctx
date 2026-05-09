# meshctx v1.0.0 发布说明

> 发布日期: 2026-05-10  
> 代号: "World's First Self-Evolving Agent"

---

## 🎯 概述

meshctx v1.0 是世界第一个自进化AI Agent系统。相比 Hermes、OpenClaw、Claude Cowork 等竞品，meshctx 有三个世界首创能力。

## ⭐ 三大世界首创

| 能力 | 说明 | 竞品状态 |
|------|------|---------|
| **预测引擎** | 学习用户时间模式，提前预加载上下文 | Hermes ❌ OpenClaw ❌ Copaw ❌ |
| **自主OODA循环** | 观察→判断→决策→执行→学习 全自动 | 所有竞品 ❌ |
| **自愈引擎** | 插件故障自动检测、重启、恢复 | 所有竞品 ❌ |

## 🧩 9核心插件

```
memory        — L0-L4层次记忆 + 艾宾浩斯遗忘曲线
metacognition — 元认知: 自评→模式提取→行为调整  
orchestrator  — 多Agent DAG编排 (Coder/Researcher/DevOps/Reviewer)
predictor     — ★预测引擎 (世界首创)
agent_loop    — ★自主OODA循环 (世界首创)
performance   — L1/L2缓存+流式响应
healer        — ★自愈引擎: 监控+恢复+熔断+记忆压缩
gateway       — 企业微信/飞书/Telegram等9平台接入
websocket     — 实时事件推送+双向通信
```

## 🆚 竞品对比

| 能力 | Hermes | OpenClaw | Copaw | Cowork | **meshctx** |
|------|--------|----------|-------|--------|-------------|
| 层次记忆 L0-L4 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 元认知自进化 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 多Agent编排 | ❌ | ❌ | ❌ | ⚠️ | ✅ |
| 预测引擎 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自主OODA循环 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自愈引擎 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 企业微信接入 | ✅ | ❌ | ❌ | ❌ | ✅ |
| 遗忘曲线 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 知识图谱 | ❌ | ❌ | ❌ | ❌ | ✅ |
| MCP协议 | ✅ | ❌ | ❌ | ❌ | ✅ |
| 开源 | ✅ MIT | ✅ | ⚠️ | ❌ | ✅ AGPLv3 |

## 📦 安装

```bash
git clone https://github.com/meshctx/meshctx.git
cd meshctx && pip install -e . && pip install pycryptodome
meshctx start
```

## 🚀 30秒上手

```bash
export DEEPSEEK_API_KEY=sk-你的key
meshctx model scan
meshctx chat
# 聊天中: /models 看模型列表, /gateway 配企业微信
```

## 📚 文档

- [完整用户手册](docs/USER_GUIDE.md) — 安装/模型配置/企业微信接入/排错
- [架构设计](docs/architecture.md)
- [API参考](docs/api.md)
- [竞品分析](docs/DESIGN_v1.0.md)

## 🔧 技术栈

- Python 3.10+, FastAPI, asyncio
- 9插件微内核架构, 事件总线
- 70个自动化测试
- systemd生产部署, Docker支持

## 🛣️ 路线图

- v1.1: 飞书/Telegram webhook完善
- v1.2: WebSocket聊天前端
- v1.3: 插件市场 + MCP工具生态
- v2.0: 多语言SDK + K8s部署
