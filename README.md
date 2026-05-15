<p align="center">
  <img src="docs/assets/logo.png" alt="MeshCtx" width="200">
  <h1 align="center">🧠 MeshCtx v2.12</h1>
  <h3 align="center">世界首个全脑仿真 AI Agent — 100模型·28供应商·13脑区·代码沙箱·多模型对比</h3>
</p>

<p align="center">
  <a href="LEGAL.md"><img src="https://img.shields.io/badge/license-AGPLv3+Commercial-blue"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-green"></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-673/673-brightgreen"></a>
  <a href="#"><img src="https://img.shields.io/badge/models-100-purple"></a>
  <a href="#"><img src="https://img.shields.io/badge/providers-28-orange"></a>
  <a href="#"><img src="https://img.shields.io/badge/languages-7-red"></a>
</p>

---

> **MeshCtx 是世界首个全脑仿真 AI Agent 平台。** v2.12 支持100模型28供应商，13脑区超级大脑，代码沙箱(Docker+SSE)，项目索引，多模型对比Chat，飞书通知，Windows全管理。框架AGPLv3开源 | 核心大脑源码可见，商业授权需联系。

## 🚀 快速开始

```bash
# Docker (推荐)
echo "DEEPSEEK_API_KEY=sk-xxx" > .env
docker-compose up -d

# Linux/WSL
git clone https://github.com/LucyAndLuna2023/meshctx.git
cd meshctx && python3 -m venv .venv && source .venv/bin/activate
pip install -e . && export DEEPSEEK_API_KEY=sk-xxx && mesctx start

# Windows
# 下载 meshctx-setup-v2.12.0.exe → 双击安装
```

## 🧠 核心能力

| 能力 | 说明 | 版本 |
|------|------|------|
| 超级大脑 | 13脑区全脑仿真(海马/杏仁核/DMN/丘脑/小脑/ACC...) | v2.0 |
| 代码沙箱 | Docker隔离+子进程回退+SSE流式, Python/Bash/JS | v2.7 |
| 项目索引 | 15+语言符号提取, /context上下文检索 | v2.7 |
| 多模型对比 | ⚡一键同时问3模型,并排卡片对比 | v2.11 |
| 飞书通知 | 卡片/文本/部署推送, HMAC签名 | v2.8 |
| Windows管理 | 服务/进程/注册表/PowerShell/浏览器 | v2.10 |
| 代码审查 | 12+检测规则,安全/风格/性能评分 | v2.12 |
| Web搜索 | /search命令, DuckDuckGo | v2.7 |
| Docker部署 | Dockerfile+docker-compose一键启动 | v2.12 |

## 💬 Chat 命令

`/read <路径>` `/ls <目录>` `/search <关键词>` `/run python <代码>` `/context <关键词>` `/win services|processes|system|exec`

## 📊 性能基准

| 指标 | 数值 |
|------|------|
| 项目索引 | 189文件/51K行 → 222ms |
| 搜索 | 10查询 → 16ms (1.6ms/次) |
| 上下文 | 16KB → 2ms |
| 沙箱 | 10次 → 932ms (93ms/次) |
| 测试 | 673/673 全过 |

## 🔌 插件 (9个)

sandbox-runner · project-indexer · feishu-notifier · code-reviewer-ai · web-search-tool · code-reviewer · file-manager · feishu-bot · data-visualizer

## 📡 API

`/docs` OpenAPI文档 · `llms.txt` AI可发现性 · 40+端点 · 30供应商自动扫描

## 📄 许可

框架: **AGPLv3** | 核心大脑: **源码可见·商业授权需联系** license@meshctx.com

[GitHub](https://github.com/LucyAndLuna2023/meshctx) · [文档](/docs/getting-started.html) · [下载](https://meshctx.com/#download)
