#!/usr/bin/env python3
"""Phase 3 v2: Generate TRANSLATIONS additions as Python code, insert by language boundaries"""
import json, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

# Load current TRANSLATIONS
import sys; sys.path.insert(0, 'src')
from i18n import TRANSLATIONS

with open('scripts/i18n_phase2_output.json') as f:
    data = json.load(f)

new_keys = data['new']

COMMON_EN = {
    '会话详情': 'Session Details', '无匹配会话': 'No matching sessions',
    '会话历史': 'Session History', '暂无存档会话': 'No archived sessions',
    '会话历史浏览器': 'Session History Browser', '最近任务': 'Recent Tasks',
    '进程监控': 'Process Monitor', '自省循环': 'Introspection Loop',
    '思考过程': 'Thinking Process', '执行失败': 'Execution failed',
    '停止运行': 'Stop Running', '复制代码': 'Copy Code', '复制回复': 'Copy Response',
    '编辑并重发': 'Edit & Resend', '运行此代码块': 'Run Code Block', '上传文件': 'Upload File',
    '执行中': 'Running...', '思考中': 'Thinking...', '已中断': 'Interrupted',
    '已停止': 'Stopped', '已手动停止': 'Manually Stopped', '发送中': 'Sending...',
    '停止中': 'Stopping...', '运行中': 'Running', '发送失败': 'Send failed',
    '网络错误': 'Network error', '请求失败': 'Request failed', '生成中': 'Generating...',
    '已保存': 'Saved', '已配置': 'Configured', '已安装': 'Installed', '已卸载': 'Uninstalled',
    '已激活': 'Activated', '已清理': 'Cleaned', '已截断': 'Truncated', '已完成': 'Completed',
    '未配置': 'Not configured', '未设置': 'Not set', '未选择': 'Not selected',
    '安装中': 'Installing...', '卸载中': 'Uninstalling...', '扫描中': 'Scanning...',
    '测试中': 'Testing...', '全局命令面板': 'Command Palette', '快捷操作': 'Quick Actions',
    '插件市场': 'Plugin Market', '社区推荐': 'Community Picks', '暂无插件': 'No plugins',
    '插件列表': 'Plugin List', '安装成功': 'Install Success', '系统信息': 'System Info',
    '项目管理': 'Project Management', '项目名称': 'Project Name', '项目不存在': 'Project not found',
    '确定删除': 'Confirm Delete', '模型列表': 'Model List', '模型总数': 'Total Models',
    '基准测试': 'Benchmark', '网页搜索': 'Web Search', '退出码': 'Exit Code',
    '文件引用': 'File Reference', '条消息': ' messages', '个模型': ' models',
    '快速提问': 'Quick Ask', '连接成功': 'Connected', '即将上线': 'Coming Soon',
}

def get_en(zh):
    for k, v in COMMON_EN.items():
        if k in zh or zh[:15] in k:
            return v
    return f'[EN] {zh[:50]}'

# Add to TRANSLATIONS
langs = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es']
prefixes = {'ja': '[JA]', 'ko': '[KO]', 'fr': '[FR]', 'de': '[DE]', 'es': '[ES]'}

for key, trans in sorted(new_keys.items()):
    zh_text = trans['zh'].replace('\n', ' ').replace('"', '\\"')[:100]
    TRANSLATIONS['zh'][key] = zh_text
    TRANSLATIONS['en'][key] = get_en(trans['zh'])
    for lc in ['ja', 'ko', 'fr', 'de', 'es']:
        TRANSLATIONS[lc][key] = f'{prefixes[lc]} {trans["zh"][:50]}'

# Validate
from i18n import validate_keys
r = validate_keys()
print(f"Validation: {r['ok']} | {r['total_keys']} keys")
if r['missing']:
    for lang, missing in r['missing'].items():
        print(f"  {lang}: missing {len(missing)}")

# Now write to file - rebuild TRANSLATIONS block
import pprint

# Read original file
with open('src/i18n.py') as f:
    orig = f.read()

# Find boundaries
t_start = orig.find('TRANSLATIONS = {')
func_start = orig.find('\ndef parse_accept_language')
if t_start < 0 or func_start < 0:
    print("ERROR: Cannot find boundaries")
    exit(1)

# Generate the TRANSLATIONS dict as formatted Python
lines = ['TRANSLATIONS = {']
for lang in langs:
    lines.append(f'    "{lang}": {{')
    for key in sorted(TRANSLATIONS[lang].keys()):
        val = TRANSLATIONS[lang][key].replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '')
        lines.append(f'        "{key}": "{val}",')
    lines.append('    },')
lines.append('}')

new_block = '\n'.join(lines)

# Reconstruct file
new_content = orig[:t_start] + new_block + '\n' + orig[func_start:]

with open('src/i18n.py', 'w') as f:
    f.write(new_content)

print(f"✅ Written. File size: {len(new_content)} bytes")
