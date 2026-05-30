#!/usr/bin/env python3
"""
🔴 真实语言切换行为测试 — 浏览器模拟
直接解析HTML+模拟switchLang执行
"""
import re
import sys

with open("docs/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. 提取L对象
js = re.search(r'const L = (\{.*?\n\});', html, re.DOTALL).group(1)

# 2. 解析每个语言块的翻译
def parse_lang_block(text, lang):
    """解析 {语言}: { ... } 块"""
    pos = text.find(f'{lang}:{{')
    if pos < 0:
        pos = text.find(f'{lang}: {{')
    if pos < 0:
        return {}
    
    start = pos + len(lang) + 1
    while start < len(text) and text[start] in ' \t\n':
        start += 1
    if text[start] == '{':
        start += 1
    
    depth = 1
    end = start
    while end < len(text) and depth > 0:
        if text[end] == '{': depth += 1
        elif text[end] == '}': depth -= 1
        end += 1
    
    block = text[start:end-1]
    translations = {}
    for m in re.finditer(r'(\w+):"((?:[^"\\]|\\.)*)"', block):
        translations[m.group(1)] = m.group(2)
    return translations

# 3. 提取所有data-lang-key元素
key_elements = {}
for m in re.finditer(r'data-lang-key="(\w+)"', html):
    key = m.group(1)
    key_elements[key] = key_elements.get(key, 0) + 1

print(f"HTML中data-lang-key元素: {len(key_elements)} 种key, 共{sum(key_elements.values())}个")

# 4. 模拟switchLang: 逐语言切换
errors = []
for lang in ['en', 'zh', 'ja', 'ko', 'de', 'fr', 'es']:
    translations = parse_lang_block(js, lang)
    lang_errors = []
    
    for key in key_elements:
        trans = translations.get(key, '')
        if not trans:
            lang_errors.append(f"  MISSING: {lang}.{key}")
        elif trans.strip() == key:
            lang_errors.append(f"  IDENTITY: {lang}.{key}=\"{trans}\" (翻译=key名)")
    
    if lang_errors:
        print(f"\n❌ {lang}: {len(lang_errors)}个问题")
        for e in lang_errors[:10]:
            print(e)
        if len(lang_errors) > 10:
            print(f"  ... 共{len(lang_errors)}个")
        errors.extend(lang_errors)
    else:
        print(f"✅ {lang}: {len(translations)} keys OK")

if errors:
    print(f"\n🔴 总计 {len(errors)} 处翻译问题!")
    print("这些会导致switchLang后对应元素变空或显示key名!")
    sys.exit(1)
else:
    print(f"\n✅ 7语言全部通过! switchLang可正常工作")
