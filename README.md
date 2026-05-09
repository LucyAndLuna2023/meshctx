<p align="center">
  <h1 align="center">🕸 meshctx</h1>
  <h3 align="center">World's First Self-Evolving Agent System</h3>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue.svg"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10%2B-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-70%2F70-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/plugins-9-blue"></a>
</p>

---

> **meshctx 是一个能自我进化的AI Agent平台。** 它会记住所有对话，越用越聪明，能同时派多个AI干活。支持企业微信/飞书/Telegram接入。

## ⚡ 30秒开始

```bash
git clone https://github.com/meshctx/meshctx.git
cd meshctx && pip install -e . && pip install pycryptodome

export DEEPSEEK_API_KEY=sk-你的key
meshctx model scan
meshctx chat
```

## ⭐ 为什么选 meshctx？

| 能力 | Hermes | OpenClaw | Copaw | Cowork | **meshctx** |
|------|--------|----------|-------|--------|-------------|
| 层次记忆 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 元认知自进化 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 预测引擎 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自主Agent循环 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自愈恢复 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 企业微信 | ✅ | ❌ | ❌ | ❌ | ✅ |
| 开源 | ✅ | ✅ | ⚠️ | ❌ | ✅ |

## 🧩 架构

```
9插件微内核 → 事件总线 → 30+ API端点
 L0-L4记忆 元认知 多Agent编排 预测 自愈 Gateway WebSocket
```

## 📖 文档

| 文档 | 说明 |
|------|------|
| [📘 用户手册](docs/USER_GUIDE.md) | 安装/配模型/企业微信/排错 |
| [📗 发布说明](RELEASE_NOTES.md) | v1.0.0 完整功能列表 |
| [📙 API文档](http://localhost:3000/docs) | 30+端点交互文档 |
| [📕 架构设计](docs/DESIGN_v1.0.md) | 六维碾压竞品分析 |

## 🔌 聊天命令

```
/models           查看可选模型
/model v4-pro     切换最强模型
/gateway          配置企业微信/飞书/Telegram
/quit             退出
```

## 📡 Web控制台

```
http://localhost:3000/ui/    仪表板
http://localhost:3000/docs   API文档
ws://localhost:3000/ws       实时WebSocket
```
