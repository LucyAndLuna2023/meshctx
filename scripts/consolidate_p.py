#!/usr/bin/env python3
"""Replace all scattered class _P definitions with from ._stub import _P"""
import re, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

count = 0
for root, dirs, files in os.walk('src'):
    for fname in files:
        if not fname.endswith('.py'): continue
        if fname == '_stub.py': continue  # skip the canonical definition
        path = os.path.join(root, fname)
        
        with open(path) as f:
            content = f.read()
        
        if 'class _P:' not in content:
            continue
        
        # Find the _P class definition block
        # Pattern: from "class _P:" to the next top-level definition or module __getattr__
        pattern = r'\nclass _P:.*?(?=\n(def |class |# ──|$|\Z))'
        
        # Check if this file has the standard _P (40 lines with __slots__)
        if '__slots__' in content or 'object.__setattr__' in content:
            # Standard _P — can replace with import
            # Find the class block and replace it
            match = re.search(r'\nclass _P:.*?(?=\n(def [^_]|\nclass [^_]|\n# ──|\n__all__|\Z))', content, re.DOTALL)
            if match:
                old_block = match.group(0)
                # Determine relative import path
                rel_path = os.path.relpath(os.path.join(root, '_stub'), os.path.dirname(path))
                rel_import = '.' + rel_path.replace('/', '.')
                
                new_block = f'\nfrom {rel_import} import _P'
                content = content.replace(old_block, new_block, 1)
                count += 1
                
                with open(path, 'w') as f:
                    f.write(content)
                print(f"  {path}: class _P → import _P")

print(f"\n✅ Replaced {count} _P class definitions")
