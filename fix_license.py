#!/usr/bin/env python3
"""一键修复 pyproject.toml 许可证声明 (MIT → AGPLv3)"""
import re

path = 'pyproject.toml'
with open(path) as f:
    content = f.read()

# 修复 license
old = 'license = "MIT"'
new = 'license = "AGPL-3.0-only"'
if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print(f'✅ {path}: {old} → {new}')
else:
    print(f'⚠️  {old} not found — may already be fixed')

# 修复 version_info.txt
vpath = 'version_info.txt'
with open(vpath) as f:
    vcontent = f.read()
vcontent = vcontent.replace('MIT License', 'AGPLv3 License')
with open(vpath, 'w') as f:
    f.write(vcontent)
print(f'✅ {vpath}: MIT → AGPLv3')
