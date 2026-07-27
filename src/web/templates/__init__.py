"""
meshctx Web UI v2 Templates — 2 入口 + 齿轮布局
从 web_ui.py 5693 行单体文件拆分出来

优化前: 11 tab (💬🤖📊🔌🧪📜🧠🔌🖥️📂🪟) 全摊开
优化后: 2 入口 (💬 Chat + 📂 Projects) + ⚙️ 齿轮 → 设置
         历史 → Chat 侧栏 | 开发者 → Ctrl+Shift+D
"""

# ═══════════════════════════════════════════════════════════════
# 主仪表板: 2 入口卡片 + 齿轮设置 Modal
# ═══════════════════════════════════════════════════════════════

DASHBOARD_V2 = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
</head>
<body>...</body>
</html>"""

# 实际模板在 web_ui.py 的 _TEMPLATES dict 中以字符串形式嵌入
# 此文件标记模块结构
