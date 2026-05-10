<p align="center">
  <h1 align="center">🕸 meshctx</h1>
  <h3 align="center">World's First Self-Evolving Agent System — v1.1 Brain-Inspired</h3>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue.svg"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10%2B-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-70%2F70-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/plugins-12-purple"></a>
</p>

---

> **meshctx 是一个能自我进化的AI Agent平台。** v1.1 引入脑启发智能架构：自由能原理驱动的预测加工、主动推理、全局工作空间和异稳态调节。跨7学科融合，目前没有任何开源框架实现过。

## ⚡ 30秒开始

```bash
git clone https://github.com/LucyAndLuna2023/meshctx.git
cd meshctx && pip install -e . && pip install pycryptodome

export DEEPSEEK_API_KEY=sk-你的key
meshctx model scan
meshctx chat
```

## ⭐ 为什么选 meshctx？

| 能力 | Hermes | OpenClaw | Copaw | Cowork | **meshctx** |
|------|--------|----------|-------|--------|-------------|
| 层次记忆 L0-L4 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 自由能驱动决策 | ❌ | ❌ | ❌ | ❌ | ✅★ v1.1 |
| 主动推理 (探索vs利用) | ❌ | ❌ | ❌ | ❌ | ✅★ v1.1 |
| 全局工作空间 (多专家竞争) | ❌ | ❌ | ❌ | ❌ | ✅★ v1.1 |
| 异稳态资源调节 | ❌ | ❌ | ❌ | ❌ | ✅★ v1.1 |
| 元认知自进化 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 预测引擎 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自主Agent循环 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 自愈恢复 | ❌ | ❌ | ❌ | ❌ | ✅★ |
| 企业微信/飞书/TG | ✅ | ❌ | ❌ | ❌ | ✅ |
| 开源 | ✅ | ✅ | ⚠️ | ❌ | ✅ |

## 🧠 v1.1 脑启发架构 (新增)

```
自由能智能体 (Free Energy Agent)
├── 预测加工 (Predictive Processing) — 层级生成模型，自上而下预测
├── 主动推理 (Active Inference) — 行动=最小化期望自由能
├── 全局工作空间 (Global Workspace) — 7专家竞争+意识点火+注意瓶颈
├── 异稳态调节 (Homeostasis) — PID控制+预测性资源管理
├── 精密加权 (Precision Weighting) — 注意力驱动的学习率调节
├── 多时间尺度学习 — 快/中/慢三时间尺度并行更新
└── 自组织临界性 — 维持混沌边缘最大化信息处理
```

**跨学科基础**: 脑科学+物理学+数学+认知科学+心理学+控制论+经济学

## 🧩 完整架构

```
12插件微内核 → 事件总线 → 30+ API端点
 L0-L4记忆 元认知 多Agent编排 预测 自愈 Gateway WebSocket
 v1.1: FEA自由能 AI主动推理 GW全局工作空间 异稳态
 Hermes集成: 55+技能目录 意图解析 技能链 ContextPortal
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
