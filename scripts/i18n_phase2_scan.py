#!/usr/bin/env python3
"""Phase 2+3: Auto-extract Chinese → generate keys → 7-language translation → output JSON"""
import re, sys, os, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

from i18n import TRANSLATIONS

# ── 1. Build reverse lookup ──
zh_to_key = {}
for key, val in TRANSLATIONS.get('zh', {}).items():
    clean = val
    for ch in '📁📊⚙️🔑💾✅❌📭🔗📝💬📎🧠🔧📋📖🐧🪟⬇📦📚🤖🔌🔄🌓🌙💻🖥️📂🔍⏹▶✏️📄⭐🔵🟢🟡🔴⏳⚠️✓✗●':
        clean = clean.replace(ch, '')
    zh_to_key[clean.strip()] = key

# ── 2. Domain-based key generation ──
DOMAINS = {
    'chat': ['消息', '发送', '输入', '对话', '聊天', '提问', '上传', '文件引用', '思考', '编辑并重发', '停止', '复制', '运行', '执行', '快速提问', '重试', '中断'],
    'project': ['项目', '创建', '删除', '描述', '标签', '状态', '更新', '管理'],
    'memory': ['记忆', '图谱', '搜索', '语义', '知识', '回忆', '实体', '关系'],
    'agent': ['Agent', '代理', '会话', '任务', '活跃', '循环', '统计', '监控'],
    'files': ['文件', '目录', '保存', '刷新', '编辑器', '路径', '语言', '大小', '修改'],
    'setup': ['配置', '密钥', '模型', '供应商', '测试', '基准', '密钥', 'API'],
    'dashboard': ['仪表板', '概览', '统计', '面板', '刷新'],
    'plugin': ['插件', '安装', '卸载', '市场', '社区', '推荐', '导入'],
    'common': ['加载', '错误', '失败', '成功', '取消', '确定', '复制', '搜索', '过滤'],
    'search': ['搜索', '网页', '查询', '结果'],
    'sandbox': ['沙箱', '代码', '运行', '输出', '退出码'],
    'windows': ['Windows', 'PowerShell', '服务', '进程', '系统信息', '软件'],
}

def generate_key(text):
    """Generate i18n key from Chinese text using naming convention"""
    text = text.strip()[:60]
    # Find domain
    domain = 'common'
    for dom, keywords in DOMAINS.items():
        for kw in keywords:
            if kw in text:
                domain = dom
                break
        if domain != 'common':
            break
    
    # Generate suffix: Pinyin abbreviation or descriptive
    # Use a simple hash-based approach for unique short keys
    import hashlib
    h = hashlib.md5(text.encode()).hexdigest()[:6]
    
    # Try to create meaningful suffix from first/last keywords
    suffix = 'text'
    for kw in ['标题', '描述', '按钮', '占位符', '错误', '提示', '消息', '列表', '详情', '状态', '搜索', '配置']:
        if kw in text:
            suffix_map = {'标题':'title','描述':'desc','按钮':'btn','占位符':'placeholder',
                         '错误':'error','提示':'hint','消息':'msg','列表':'list',
                         '详情':'detail','状态':'status','搜索':'search','配置':'config'}
            suffix = suffix_map.get(kw, 'text')
            break
    
    return f"{domain}_{suffix}_{h}"

# ── 3. Scan web_ui.py ──
with open('src/web_ui.py') as f:
    content = f.read()

pattern = re.compile(r'[\u4e00-\u9fff][\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s\d，。！？、：；（）《》【】…\-\+\.\/\,\!\?\:\;\(\)\[\]\{\}\s]*[\u4e00-\u9fff]')

new_translations = {}  # {key: {lang: text}}
existing_usage = {}    # {key: chinese_text}

for m in pattern.finditer(content):
    text = m.group().strip()
    if len(text) < 3:
        continue
    ctx_start = max(0, m.start() - 50)
    ctx = content[ctx_start:m.end()+10]
    if '__t(' in ctx or 'TRANSLATIONS' in ctx or 'window.__t' in ctx:
        continue
    line_begin = content.rfind('\n', 0, m.start()) + 1
    line = content[line_begin:m.end()].strip()
    if line.startswith('#') or line.startswith('//'):
        continue
    # Skip docstrings/comments in Python
    if line.startswith('"') or line.startswith("'"):
        continue
    
    # Check existing
    found = None
    for zh, k in zh_to_key.items():
        if text[:15] == zh[:15]:
            found = k
            break
    
    if found:
        existing_usage[found] = text[:60]
    else:
        key = generate_key(text)
        if key not in new_translations:
            new_translations[key] = {'zh': text}

# ── 4. Auto-translate (simplified: use placeholders, human review needed) ──
# For production, use the same text as Chinese placeholder with [lang] prefix
LANG_MAP = {'en': 'EN', 'ja': 'JA', 'ko': 'KO', 'fr': 'FR', 'de': 'DE', 'es': 'ES'}
for key, langs in new_translations.items():
    zh = langs['zh']
    for lc, prefix in LANG_MAP.items():
        # Placeholder: mark for human translation
        langs[lc] = f"[{prefix}] {zh}"

# ── 5. Output ──
print(f"=== 可复用现有 key: {len(existing_usage)} ===")
for k, v in sorted(existing_usage.items()):
    print(f"  {k:35s} ← '{v}'")

print(f"\n=== 需新增 key: {len(new_translations)} ===")
for k, v in sorted(new_translations.items()):
    print(f"  {k:35s} ← '{v['zh'][:60]}'")

# Save to file for next phase
output = {
    'existing': {k: v for k, v in existing_usage.items()},
    'new': new_translations
}
with open('scripts/i18n_phase2_output.json', 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n✅ 输出: scripts/i18n_phase2_output.json")
print(f"   现有 key: {len(existing_usage)} | 新增 key: {len(new_translations)}")
