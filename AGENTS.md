     1|# 🚨 最高优先级 — 服务器铁律
     2|- **所有测试/部署/验证必须在服务器47.120.0.239上执行**
     3|- SSH: sshpass -p "LucyAndLuna@20230609" ssh root@47.120.0.239
     4|- 绝对禁止在本地跑测试
     5|- 服务器代码路径: /opt/meshctx/
     6|- 服务器端口: 3001
     7|- 重启命令: systemctl restart meshctx
     8|- 本机只是写代码的地方，不是测试的地方
     9|
    10|# 🚨 自主行动铁律
    11|- 不问/不等/自己做/只汇报结果
    12|- 用户说修什么就修什么
    13|- 改完验证才算完成
    14|
    15|# 当前任务
    16|- v3.47服务器上已部署但BrainInspiredRouter参数bug导致无法启动
    17|- 需要修复后测试服务是否正常
    18|
    19|# 测试目标服务器
    20|- Windows 7本地化测试: 192.168.3.47
    21|- 所有语言/本地化/I18N相关测试必须在192.168.3.47上执行
    22|- 不允许在本机做本地化测试
    23|
    24|# 🚨 服务器铁律
    25|- **meshctx UAT唯一**: 47.120.0.239:3001 (root / LucyAndLuna@20230609#)
    26|- **可做代理**: CloudCone 66.154.101.18
    27|- **禁止meshctx用途**: 8.130.179.205 及其他服务器
    28|
    29|# 🔧 meshctx 能力清单 (v3.48 升级)
    30|## 模型
    31|- 主模型: deepseek-v4-pro (本地代理 127.0.0.1:8897)
    32|- reasoning_effort: high
    33|- max_turns: 90
    34|
    35|## 工具集: hermes-meshctx (62 工具，兼容 openclaw 全能力)
    36|### 核心工具
    37|- 🌐 Web: web_search, web_extract
    38|- 🖥 终端: terminal, process
    39|- 📁 文件: read_file, write_file, patch, search_files
    40|- 🌐 浏览器: browser_navigate, browser_snapshot, browser_click, browser_type, browser_scroll, browser_back, browser_press, browser_get_images, browser_vision, browser_console, browser_cdp, browser_dialog
    41|- 👁 视觉: vision_analyze
    42|- 🎨 图片生成: image_generate
    43|- 🔊 TTS: text_to_speech
    44|- 📋 任务: todo
    45|- 💾 记忆: memory (holographic provider)
    46|- 🔎 会话搜索: session_search
    47|- ❓ 澄清: clarify
    48|- ⚡ 代码执行: execute_code
    49|- 👥 代理委派: delegate_task (max_depth=2, 3并发)
    50|- ⏰ 定时任务: cronjob
    51|
    52|### 通讯平台
    53|- 📨 跨平台消息: send_message
    54|- 🏠 Home Assistant: ha_list_entities, ha_get_state, ha_list_services, ha_call_service
    55|
    56|### 飞书 (已配置凭证)
    57|- 📄 飞书文档: feishu_doc_read
    58|- 💬 飞书评论: feishu_drive_list_comments, feishu_drive_list_comment_replies, feishu_drive_reply_comment, feishu_drive_add_comment
    59|
    60|### Discord
    61|- 💬 Discord: discord, discord_admin
    62|
    63|### 元宝
    64|- 🤖 元宝: yb_query_group_info, yb_query_group_members, yb_send_dm, yb_search_sticker, yb_send_sticker
    65|
    66|### Spotify
    67|- 🎵 Spotify: spotify_playback, spotify_devices, spotify_queue, spotify_search, spotify_playlists, spotify_albums, spotify_library
    68|
    69|### 高级推理
    70|- 🧠 MoA: mixture_of_agents
    71|
