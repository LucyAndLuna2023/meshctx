#!/usr/bin/env python3
"""Phase 3: Insert 299 new i18n keys directly into i18n.py source"""
import json, re, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

with open('scripts/i18n_phase2_output.json') as f:
    data = json.load(f)

new_keys = data['new']

# Quick English translations
COMMON_EN = {
    '会话详情': 'Session Details', '无匹配会话': 'No matching sessions',
    '会话历史': 'Session History', '暂无存档会话': 'No archived sessions',
    '会话历史浏览器': 'Session History Browser', '最近任务': 'Recent Tasks',
    '进程监控': 'Process Monitor', '自省循环': 'Introspection Loop',
    '个会话': ' sessions', '思考过程': 'Thinking Process',
    '执行失败': 'Execution failed', '停止运行': 'Stop Running',
    '复制代码': 'Copy Code', '复制回复': 'Copy Response',
    '编辑并重发': 'Edit & Resend', '运行此代码块': 'Run Code Block',
    '上传文件': 'Upload File', '执行中': 'Running...', '思考中': 'Thinking...',
    '已中断': 'Interrupted', '已停止': 'Stopped', '已手动停止': 'Manually Stopped',
    '发送中': 'Sending...', '停止中': 'Stopping...', '运行中': 'Running',
    '发送失败': 'Send failed', '网络错误': 'Network error',
    '请求失败': 'Request failed', '生成中': 'Generating...',
    '已保存': 'Saved', '已配置': 'Configured', '已安装': 'Installed',
    '已卸载': 'Uninstalled', '已激活': 'Activated', '已清理': 'Cleaned',
    '已截断': 'Truncated', '已完成': 'Completed', '已切换': 'Switched',
    '未配置': 'Not configured', '未设置': 'Not set', '未选择': 'Not selected',
    '安装中': 'Installing...', '卸载中': 'Uninstalling...', '扫描中': 'Scanning...',
    '测试中': 'Testing...', '对比中': 'Comparing...', '解析中': 'Parsing...',
    '启动中': 'Starting...', '加载中': 'Loading...', '搜索中': 'Searching...',
    '全局命令面板': 'Command Palette', '快捷操作': 'Quick Actions',
    '插件市场': 'Plugin Market', '社区推荐': 'Community Picks',
    '暂无插件': 'No plugins', '插件列表': 'Plugin List', '插件健康': 'Plugin Health',
    '安装成功': 'Install Success', '安装失败': 'Install failed',
    '插件安装成功': 'Plugin installed', '导入完成': 'Import complete',
    '系统信息': 'System Info', '项目管理': 'Project Management',
    '项目名称': 'Project Name', '项目简介': 'Project Description',
    '项目上下文': 'Project Context', '项目不存在': 'Project not found',
    '确定删除': 'Confirm Delete', '确认删除': 'Confirm deletion',
    '删除模板': 'Delete Template', '添加模型': 'Add Model',
    '模型列表': 'Model List', '模型管理': 'Model Management',
    '模型总数': 'Total Models', '供应商管理': 'Provider Management',
    '自定义供应商': 'Custom Provider', '基准测试': 'Benchmark',
    '测试连接': 'Test Connection', '测试连通性': 'Test Connectivity',
    '网页搜索': 'Web Search', '搜索/筛选': 'Search/Filter',
    '搜索插件': 'Search Plugins', '搜索会话': 'Search Sessions',
    '搜索会话标题': 'Search Session Titles',
    '搜索函数/类/文件': 'Search Functions/Classes/Files',
    '文件引用': 'File Reference', '退出码': 'Exit Code', '无输出': 'No output',
    '本地文件': 'Local Files', '未找到匹配文件': 'No matching files',
    '项目文件': 'Project Files', '服务器名称': 'Server Name',
    '服务器管理': 'Server Management', '服务管理': 'Service Management',
    '多项目': 'Multi-Project', '系统资源': 'System Resources',
    '关键约定': 'Key Conventions', '技术栈': 'Tech Stack',
    '工具调用': 'Tool Call', '自愈链路': 'Self-Healing Chain',
    '预测引擎': 'Prediction Engine', '最新预测': 'Latest Prediction',
    '工作记忆': 'Working Memory', '短期记忆': 'Short-term Memory',
    '长期记忆': 'Long-term Memory', '归档记忆': 'Archived Memory',
    '条消息': ' messages', '个模型': ' models', '快速提问': 'Quick Ask',
    '连接成功': 'Connected', '即将上线': 'Coming Soon',
    '一键切换': 'One-click Switch', '一键广播': 'One-click Broadcast',
    '广播成功': 'Broadcast success', '多通道通知': 'Multi-channel Notifications',
    '飞书通知': 'Feishu Notification', '自动构建': 'Auto Build',
    '完全自定义': 'Fully Custom', '操作按钮': 'Action Button',
    '状态标签': 'Status Label', '原生客户端，下载即用': 'Native client, download & run',
    '构建页': 'Build Page',
}

def get_en(zh):
    for k, v in COMMON_EN.items():
        if k in zh or zh[:20] in k:
            return v
    return f'[EN] {zh[:50]}'

# Read source
with open('src/i18n.py') as f:
    content = f.read()

# Insert after the last key of each language block ("usable": ...)
# This is reliable because "usable" appears only once per language
lang_last_keys = {
    'zh': '"usable": "可用",',
    'en': '"usable": "Usable",',
    'ja': '"usable": "使用可能",',
    'ko': '"usable": "사용 가능",',
    'fr': '"usable": "Usable",',       # actual file value
    'de': '"usable": "Utilisable",',   # actual file value
    'es': '"usable": "Verwendbar",',   # actual file value
}

langs = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es']
insertions = {lang: [] for lang in langs}

for key, trans in sorted(new_keys.items()):
    zh_text = trans['zh']
    for lang in langs:
        if lang == 'zh':
            text = zh_text
        elif lang == 'en':
            text = get_en(zh_text)
        else:
            prefix = {'ja': '[JA]', 'ko': '[KO]', 'fr': '[FR]', 'de': '[DE]', 'es': '[ES]'}[lang]
            text = f'{prefix} {zh_text[:50]}'
        text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '')
        insertions[lang].append(f'        "{key}": "{text}",')

for lang in langs:
    marker = lang_last_keys[lang]
    pos = content.find(marker)
    if pos < 0:
        print(f"  {lang}: marker not found")
        continue
    insert_pos = pos + len(marker) + 1  # after the newline
    block = '\n'.join(insertions[lang]) + '\n'
    content = content[:insert_pos] + block + content[insert_pos:]
    print(f"  {lang}: +{len(insertions[lang])} keys")

# Write
with open('src/i18n.py', 'w') as f:
    f.write(content)

print(f"\n✅ Done. {len(new_keys)} keys added to 7 languages.")
