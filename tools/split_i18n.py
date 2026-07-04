#!/usr/bin/env python3
"""将 L 翻译对象拆分为 docs/i18n/{lang}.json — 每种语言独立文件

用法: python3 tools/split_i18n.py [docs/index.html]
产出: docs/i18n/en.json zh.json ja.json ko.json de.json fr.json es.json
"""
import re, json, os, sys

HTML = sys.argv[1] if len(sys.argv) > 1 else 'docs/index.html'
OUT = os.path.join(os.path.dirname(HTML), 'i18n')
LANGS = ['en', 'zh', 'ja', 'ko', 'de', 'fr', 'es']

with open(HTML, 'r') as f:
    html = f.read()

# 定位 L 对象
m = re.search(r'const L\s*=\s*\{', html)
if not m:
    print("[split_i18n] FAIL: const L object not found")
    sys.exit(1)

l_body = html[m.start():]
depth = 0
for i, ch in enumerate(l_body):
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0:
            l_body = l_body[:i+1]
            break

os.makedirs(OUT, exist_ok=True)

# Backslash-aware string parser: handles \" and \\ inside values
str_pat = r'(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
kv_pat = re.compile(r'(["\']?)(\w+)\1\s*:\s*' + str_pat)

total_keys = 0
for lang in LANGS:
    lm = re.search(r'\b' + lang + r'\s*:\s*\{\s*\n?', l_body)
    if not lm:
        print(f'[split_i18n] SKIP {lang}: block not found')
        continue

    # 提取该语言块
    ls = lm.start()
    ld = 0
    block = None
    for i in range(ls, len(l_body)):
        if l_body[i] == '{':
            ld += 1
        elif l_body[i] == '}':
            ld -= 1
            if ld == 0:
                block = l_body[ls:i+1]
                break
    if not block:
        print(f'[split_i18n] SKIP {lang}: cannot extract block')
        continue

    # 解析所有键值对
    data = {}
    for km in kv_pat.finditer(block):
        key = km.group(2)
        val = km.group(3) if km.group(3) is not None else km.group(4)
        if key != lang:  # 跳过语言名本身
            # 反转义： \" → ", \\ → \
            val = val.replace('\\"', '"').replace('\\\\', '\\')
            data[key] = val

    path = os.path.join(OUT, f'{lang}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'[split_i18n] {path} ({len(data)} keys)')
    total_keys += len(data)

print(f'[split_i18n] Done: {total_keys} total keys → {OUT}/')
