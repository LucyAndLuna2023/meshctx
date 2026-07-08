#!/usr/bin/env python3
"""Batch i18n: Replace hardcoded Chinese in all page templates."""
import json, os

os.chdir('/home/administrator/meshctx-public')

with open('src/i18n_translations.json', encoding='utf-8') as f:
    trans = json.load(f)

# ── Keys to add ──
new_keys = {
    'projects_title': {'zh': '项目管理', 'en': 'Project Management'},
    'projects_create': {'zh': '创建新项目', 'en': 'Create New Project'},
    'projects_name_label': {'zh': '项目名称 *', 'en': 'Project Name *'},
    'projects_desc_label': {'zh': '描述', 'en': 'Description'},
    'projects_tags_label': {'zh': '标签 (逗号分隔)', 'en': 'Tags (comma separated)'},
    'projects_create_btn': {'zh': '创建项目', 'en': 'Create Project'},
    'projects_list_title': {'zh': '项目列表', 'en': 'Project List'},
    'files_title': {'zh': '文件管理器', 'en': 'File Manager'},
    'files_empty': {'zh': '空目录', 'en': 'Empty directory'},
    'files_loading': {'zh': '加载中...', 'en': 'Loading...'},
    'files_editor_placeholder': {'zh': '选择文件以编辑', 'en': 'Select a file to edit'},
    'setup_title_text': {'zh': '配置 API 密钥', 'en': 'Configure API Key'},
    'models_title': {'zh': '模型列表', 'en': 'Model List'},
    'models_no_models': {'zh': '暂无模型', 'en': 'No models'},
    'providers_title': {'zh': '供应商', 'en': 'Providers'},
    'chat_title_text': {'zh': '输入消息开始对话', 'en': 'Type a message to start'},
    'chat_placeholder': {'zh': '输入消息... (Enter 发送, Shift+Enter 换行)', 'en': 'Type message... (Enter to send)'},
    'chat_empty': {'zh': '暂无对话', 'en': 'No conversations'},
    'continuity_title': {'zh': '连续性检测', 'en': 'Continuity Detection'},
    'memories_title': {'zh': '记忆仪表板', 'en': 'Memory Dashboard'},
}

for key, langs in new_keys.items():
    for lc, val in langs.items():
        trans[lc][key] = val
    for lc in ['ja','ko','fr','de','es']:
        p = {'ja':'[JA]','ko':'[KO]','fr':'[FR]','de':'[DE]','es':'[ES]'}[lc]
        trans[lc][key] = f'{p} {langs["zh"][:50]}'

with open('src/i18n_translations.json', 'w', encoding='utf-8') as f:
    json.dump(trans, f, ensure_ascii=False, indent=2)

print(f"Added {len(new_keys)} keys. Total: {len(trans['zh'])}")

# ── Replace in templates ──
templates_dir = 'templates'
replacements = {
    'projects.html': [
        ('项目管理', "{{ t('projects_title') }}"),
        ('创建新项目', "{{ t('projects_create') }}"),
        ('项目名称 *', "{{ t('projects_name_label') }}"),
        ('描述', "{{ t('projects_desc_label') }}"),
        ('标签 (逗号分隔)', "{{ t('projects_tags_label') }}"),
        ('创建项目', "{{ t('projects_create_btn') }}"),
        ('项目列表', "{{ t('projects_list_title') }}"),
    ],
}

count = 0
for fname, reps in replacements.items():
    path = os.path.join(templates_dir, fname)
    if not os.path.exists(path): continue
    with open(path) as f:
        content = f.read()
    for old, new in reps:
        if old in content:
            content = content.replace(old, new)
            count += 1
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {fname}: {count} replacements")

print(f"\nTotal replacements: {count}")
