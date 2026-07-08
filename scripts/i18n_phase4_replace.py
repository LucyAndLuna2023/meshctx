#!/usr/bin/env python3
"""Phase 4: Replace hardcoded Chinese in web_ui.py with __t() / t() calls"""
import re, json, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

with open('scripts/i18n_phase2_output.json') as f:
    data = json.load(f)

existing = data['existing']  # {key: chinese_text}
new_keys = data['new']       # {key: {zh: text, ...}}

# Build: Chinese text → key mapping
text_to_key = {}
for key, zh_text in existing.items():
    text_to_key[zh_text.strip()] = key
for key, trans in new_keys.items():
    text_to_key[trans['zh'].strip()] = key

# Read web_ui.py
with open('src/web_ui.py') as f:
    content = f.read()

# Pattern to find Chinese text in template strings
# This is tricky because Chinese might appear in:
# 1. Jinja2 template text (between HTML tags)
# 2. JS string literals ('...' or "...")
# 3. Jinja2 expressions {{ ... }}

# Strategy: find each Chinese span, determine context, replace
pattern = re.compile(r'[\u4e00-\u9fff][\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s\d，。！？、：；（）《》【】…\-\+\.\/\,\!\?\:\;\(\)\[\]\{\}\s]*[\u4e00-\u9fff]')

replacements = []  # (start, end, replacement)

for m in pattern.finditer(content):
    text = m.group().strip()
    if len(text) < 2:
        continue
    
    # Skip already-i18n'd or comment contexts
    ctx_start = max(0, m.start() - 60)
    ctx = content[ctx_start:m.end()+10]
    if '__t(' in ctx or 'TRANSLATIONS' in ctx or 'window.__t' in ctx or "{{ t(" in ctx:
        continue
    
    # Check if this text maps to a key
    matched_key = None
    for zh, key in text_to_key.items():
        if zh in text or text in zh:
            # Must be substantial match
            if len(set(zh) & set(text)) / max(len(zh), len(text)) > 0.5:
                matched_key = key
                break
    
    if not matched_key:
        continue
    
    # Determine context: Jinja2 or JS?
    # Look at surrounding characters
    before = content[max(0, m.start()-2):m.start()]
    after = content[m.end():m.end()+2]
    
    # Check if inside Jinja2 template (outside script tags)
    line_start = content.rfind('\n', 0, m.start()) + 1
    line_before = content[line_start:m.start()]
    
    # If inside <script>...</script> OR in a JS string const, use window.__t()
    # Otherwise use {{ t('key') }}
    
    is_js = False
    # Check if we're in a <script> block
    script_start = content.rfind('<script', 0, m.start())
    script_end = content.rfind('</script>', 0, m.start())
    if script_start > script_end:
        is_js = True
    
    # Also check if inside backtick template literal, single-quoted, or double-quoted JS string
    if "'" in before or '"' in before or '`' in before:
        is_js = True
    
    # Skip if this is Python code (not template)
    if line_before.strip().startswith('#') or line_before.strip().startswith('"') or line_before.strip().startswith("'"):
        continue
    
    if is_js:
        replacement = f"window.__t('{matched_key}')"
    else:
        replacement = f"{{{{ t('{matched_key}') }}}}"
    
    replacements.append((m.start(), m.end(), replacement, text[:50], matched_key))

# Apply replacements in reverse order (to preserve positions)
replacements.sort(key=lambda x: -x[0])
count = 0
for start, end, repl, orig, key in replacements:
    # Only replace if the original text still matches
    current = content[start:end]
    if current.strip()[:20] == orig.strip()[:20]:
        content = content[:start] + repl + content[end:]
        count += 1

print(f"Replaced {count} strings in web_ui.py")

# Write
with open('src/web_ui.py', 'w') as f:
    f.write(content)

print("✅ Done. Check with: python3 -c \"compile(open('src/web_ui.py').read(),'x','exec'); print('OK')\"")
