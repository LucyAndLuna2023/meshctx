#!/usr/bin/env python3
"""验证/重建 docs/i18n/{lang}.json — 从 landing.json 拆分各语言独立文件

用法: python3 tools/split_i18n.py [docs/index.html]
(为兼容旧 workflow 签名, 仍接受 index.html 参数; 数据源为 docs/i18n/landing.json)
产出: docs/i18n/en.json zh.json ja.json ko.json de.json fr.json es.json it.json
"""
import json, os, sys

HTML = sys.argv[1] if len(sys.argv) > 1 else 'docs/index.html'
OUT = os.path.join(os.path.dirname(HTML), 'i18n')
SRC = os.path.join(OUT, 'landing.json')
LANGS = ['en', 'zh', 'ja', 'ko', 'de', 'fr', 'es', 'it']

if not os.path.exists(SRC):
    print(f"[split_i18n] FAIL: {SRC} not found (index.html 已迁移为 landing.json 加载, 不再内嵌 const L)")
    sys.exit(1)

with open(SRC, 'r', encoding='utf-8') as f:
    data = json.load(f)

if not isinstance(data, dict):
    print("[split_i18n] FAIL: landing.json 顶层必须是 {lang: {key: value}}")
    sys.exit(1)

os.makedirs(OUT, exist_ok=True)
total_keys = 0
for lang in LANGS:
    block = data.get(lang)
    if not isinstance(block, dict):
        print(f"[split_i18n] SKIP {lang}: block not found in landing.json")
        continue
    path = os.path.join(OUT, f'{lang}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(block, f, ensure_ascii=False, indent=2)
    print(f'[split_i18n] {path} ({len(block)} keys)')
    total_keys += len(block)

print(f'[split_i18n] Done: {total_keys} total keys → {OUT}/')
