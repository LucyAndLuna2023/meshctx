# 🚨 最高优先级 — 开发铁律
- **纯本地+GitHub开发模式**: 测试在本地执行，无远程UAT服务器
- 本地测试命令: cd ~/meshctx-public && python3 -m pytest tests/ -v
- GitHub push: git push origin main
- 本机是唯一开发+测试环境

# 🚨 开源+闭源整体铁律 (最高优先级·护城河)
- **开源仓库(LucyAndLuna2023/meshctx) + 闭源仓库(LucyAndLuna2023/meshctx-core) = 产品的【一个整体】，缺一不可**
- **闭源 119 个 src/core 模块 = 核心护城河**（IIT意识引擎/JEPA世界模型/元认知等核心实现），不可删除、不可遗漏、不可轻视
- **安装时必须【全部安装、不能分离】**：开源 284 模块 + 闭源 119 模块 = 完整产品
- 闭源 119 模块与开源的关系：**112 个覆盖开源同名 stub + 7 个闭源独有模块**（desktop_tool / lsp_tool / mcp_gateway / obs_integration / patch_generator / ppt_generator / spreadsheet_tool，开源仓库完全没有）
- **三平台安装脚本（install.sh / install-mac.sh / install.bat）必须同时拉取开源 + 闭源**，闭源代码覆盖/补充到同一安装目录 `~/.meshctx`，安装后不得缺失任何闭源模块
- 验证标准：安装完成后 `~/.meshctx/src/core/*.py` 模块数 ≥ 开源284 + 闭源独有7（即闭源真实实现替换 stub 后仍完整）

# 🚨 自主行动铁律
- 不问/不等/自己做/只汇报结果
- 用户说修什么就修什么
- 改完验证才算完成

# 🚨 meshctx 竞争差距铁律 (2026-Q3)
- SWE-bench v8: 启发式评估（已修正 verified 语义），不对标官方 FAIL_TO_PASS/PASS_TO_PASS；官方口径对标 Lite 49-60% / Verified 72.8-76.8%
- 多Agent: swarm 0 worker vs CrewAI/AutoGen 成熟
- 工具生态: 61% stub → 持续消减中
- 可观测性: print日志 vs Langfuse 全链路 tracing
- MCP协议: 已集成 (src/mcp_server.py, 312行, 13 defs/classes)
- Docker沙箱: 已有 (docker-compose.yml + Dockerfile, 多模型API Key支持)
- 生产: 单机 vs 企业HA+灰度
唯一护城河: IIT意识引擎(Φ计算) + JEPA世界模型 + 元认知
追赶优先级: P0=MCP(2天)+Docker(3天) P1=消stub+训练JEPA P2=观测+HA

# 当前状态
- v3.116.0 纯本地开发模式
- 28插件全量: 9核心 + 19第三方
- 6核心模块已实现: learn_loop / memory_v2 / metacognition / agent_swarm / super_brain / jepa_world_model
- pytest 基线: 2846 passed / 118 failed / 92 errors / 418 skipped（Python 3.14 环境，失败主因 pytest tmpdir cleanup bug + stub 降级，持续修复中）
- BrainInspiredRouter 已自愈（优雅降级机制）

# 测试目标
- Windows 7本地化测试: 192.168.3.47
- 所有语言/本地化/I18N相关测试必须在192.168.3.47上执行

# 🔧 meshctx 能力清单 (v3.115)
## 模型
- 主模型: deepseek-v4-pro (本地代理 127.0.0.1:8897)
- reasoning_effort: high
- max_turns: 90

## 工具集: hermes-meshctx (62 工具，兼容 openclaw 全能力)
### 核心工具
- 🌐 Web: web_search, web_extract
- 🖥 终端: terminal, process
- 📁 文件: read_file, write_file, patch, search_files
- 🌐 浏览器: browser_navigate, browser_snapshot, browser_click, browser_type, browser_scroll, browser_back, browser_press, browser_get_images, browser_vision, browser_console
- 👁 视觉: vision_analyze
- 🎨 图片生成: image_generate
- 🔊 TTS: text_to_speech
- 📋 任务: todo
- 💾 记忆: memory (holographic provider)
- 🔎 会话搜索: session_search
- ❓ 澄清: clarify
- ⚡ 代码执行: execute_code
- 👥 代理委派: delegate_task (max_depth=2, 3并发)
- ⏰ 定时任务: cronjob

### 通讯平台
- 📨 跨平台消息: send_message
- 🏠 Home Assistant: ha_list_entities, ha_get_state, ha_list_services, ha_call_service

### 飞书
- 📄 飞书文档: feishu_doc_read
- 💬 飞书评论: feishu_drive_list_comments, feishu_drive_list_comment_replies, feishu_drive_reply_comment, feishu_drive_add_comment

### Discord
- 💬 Discord: discord, discord_admin

### Spotify
- 🎵 Spotify: spotify_playback, spotify_devices, spotify_queue, spotify_search, spotify_playlists, spotify_albums, spotify_library

### 高级推理
- 🧠 MoA: mixture_of_agents
