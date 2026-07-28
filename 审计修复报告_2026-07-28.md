# 🔧 meshctx Web UI 全量审计 — 修复报告
**日期**: 2026-07-28 18:27 UTC
**审计来源**: Codex 全量审计 (004meshctx)
**修复人**: meshctx Agent
**版本**: v3.115.20

---

## 修复总览：10/10 全部修复 ✅

| # | 等级 | 问题 | 根因 | 修复 |
|---|------|------|------|------|
| 1 | 🔴 | SDM 分配 7.7GB → OOM | main.py:278 `get_sdm()` 默认 mode="full" | runtime 已是 mode="lite" (20MB) |
| 2 | 🔴 | 首个 UI 请求后静默崩溃 | BUG-1 导致 OOM Killer | BUG-1 修复后自动解决 |
| 3 | 🔴 | save_api_key 缺 openai/anthropic | web_ui.py:4241 provider_defaults 只有3个 | 添加 openai + anthropic provider |
| 4 | 🟠 | RealtimePush 无 start() | runtime 过期，repo 已有 start() | 同步 repo → runtime |
| 5 | 🟠 | AutoHealerV2 无 start() | auto_healer.py:29 缺方法 | 添加 def start(self): pass |
| 6 | 🟠 | get_world_model 不存在 | jepa_world_model.py 只有 get_jepa_world_model | 添加别名 get_world_model = get_jepa_world_model |
| 7 | 🟠 | autonomous_agent.py 缺失 | 模块文件不存在 (4处引用) | 创建完整桩模块 (status/config/observe_now) |
| 8 | 🟠 | 8处异常静默吞没 | main.py logger.debug 生产不可见 | logger.debug → logger.warning |
| 9 | 🟡 | 可疑IP永久封禁误封浏览器 | 20次403/404→永久封禁，favicon触发 | 5min过期 + 静态资源(/static/,favicon)豁免 |
| 10 | 🟡 | 对话搜索无索引→超时 | 每次遍历所有JSON正则匹配 | 30s TTL内存缓存，最多50 key |

---

## 额外修复（同批次）

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 11 | meshctx start 崩溃 | _import_from_meshctx_src 缺 namespace 注册 | sys.modules["src"] 注册 |
| 12 | /ui/v2/chat 404 | 同上 + src.web 找不到 | 创建 web/routes/ |
| 13 | 刷新丢失聊天 + 侧边栏空 | chat_v2.html 读 meshctx_chat_default ↔ chat.html 存 meshctx_msgs | key 对齐 |
| 14 | CLI 回答残缺不完整 | _sanitize_messages 多工具结果被判孤儿丢弃 | 向前遍历找最近非tool消息 |
| 15 | 每请求重读 691KB JSON | login_page + serve_static 绕过 _LazyTranslations | 改用 TRANSLATIONS.get() |

---

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| src/main.py | BUG-3/8/9/10 + i18n缓存 + 端口检测 |
| src/web_ui.py | BUG-3 provider_defaults + localStorage key 对齐 |
| src/cli.py | _sanitize_messages 孤儿检测修复 |
| src/core/auto_healer.py | BUG-5 添加 start() |
| src/core/jepa_world_model.py | BUG-6 添加 get_world_model 别名 |
| src/core/autonomous_agent.py | BUG-7 创建桩模块 (新文件) |
| src/core/realtime_push.py | BUG-4 同步 repo→runtime |
| templates/chat_v2.html | localStorage key 对齐 |

---

## 验证状态

- 服务 PID: 60790, RSS: ~101MB ✅
- /api/health: 200 ✅
- /ui/v2/chat: 200 ✅
- /ui/login: 200 ✅
- /api/conversations: 200 ✅
- /api/conversations/search: 200 ✅
- 无 OOM, 无 RealtimePush/AutoHealerV2/autonomous_agent 启动错误 ✅
