#!/usr/bin/env python3
"""Perfect i18n: replace ALL Chinese strings in cli.py + main.py + web_ui.py templates"""
import re, json, os, hashlib

os.chdir('/home/administrator/meshctx-public')

with open('src/i18n_translations.json', encoding='utf-8') as f:
    trans = json.load(f)

def make_key(text):
    """Generate a unique i18n key from Chinese text"""
    # Use first 4 chars of MD5 for uniqueness + domain prefix
    h = hashlib.md5(text.encode()).hexdigest()[:6]
    # Try to extract domain from text
    domain = 'common'
    for kw, dm in [('扫描','scan'),('模型','model'),('配置','config'),('安装','install'),
                    ('错误','error'),('失败','fail'),('创建','create'),('删除','delete'),
                    ('测试','test'),('会话','session'),('文件','file'),('插件','plugin'),
                    ('项目','project'),('聊天','chat'),('搜索','search'),('导出','export')]:
        if kw in text: domain = dm; break
    key = f"i18n_{domain}_{h}"
    return key

# ── Process a file: find all Chinese text, generate keys, return replacements ──
def process_file(path, quote_chars):
    with open(path) as f:
        content = f.read()
    
    replacements = []
    # Find quoted Chinese strings
    for q in quote_chars:
        pattern = re.compile(rf'{q}([^{q}]*[\u4e00-\u9fff][^{q}]*?){q}')
        for m in pattern.finditer(content):
            text = m.group(1)
            if len(text.strip()) < 2: continue
            # Skip already i18n'd
            ctx_start = max(0, m.start()-15)
            ctx = content[ctx_start:m.end()+10]
            if "t('" in ctx or 't("' in ctx or '__t(' in ctx:
                continue
            if 'TRANSLATIONS' in ctx or 'i18n' in ctx:
                continue
            
            key = make_key(text.strip())
            # Add to translations if new
            if key not in trans['zh']:
                trans['zh'][key] = text
                trans['en'][key] = f'[EN] {text[:80]}'
                for lc in ['ja','ko','fr','de','es']:
                    p = {'ja':'[JA]','ko':'[KO]','fr':'[FR]','de':'[DE]','es':'[ES]'}[lc]
                    trans[lc][key] = f'{p} {text[:60]}'
            
            replacements.append((m.start(), m.end(), q, text, key))
    
    # Apply replacements in reverse order
    replacements.sort(key=lambda x: -x[0])
    count = 0
    for start, end, q, text, key in replacements:
        old = content[start:end]
        expected = f'{q}{text}{q}'
        if old == expected:
            new = f"t('{key}')"
            content = content[:start] + new + content[end:]
            count += 1
    
    with open(path, 'w') as f:
        f.write(content)
    
    return count, replacements

# ── Process each file ──
print("=== cli.py ===")
n1, _ = process_file('src/cli.py', ['"', "'"])
print(f"Replaced: {n1}")

print("=== main.py ===")
n2, _ = process_file('src/main.py', ['"', "'"])
print(f"Replaced: {n2}")

print("=== web_ui.py ===")
n3, _ = process_file('src/web_ui.py', ['"', "'"])
print(f"Replaced: {n3}")

# Save translations
with open('src/i18n_translations.json', 'w', encoding='utf-8') as f:
    json.dump(trans, f, ensure_ascii=False, indent=2)

print(f"\nKeys: {len(trans['zh'])} | Total replacements: {n1+n2+n3}")
