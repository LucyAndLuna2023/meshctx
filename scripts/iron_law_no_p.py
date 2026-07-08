#!/usr/bin/env python3
"""Iron Law enforcement: remove ALL module-level __getattr__ returning _P.
Replace with explicit __all__ exports. No more _P stubs."""
import re, os, ast

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

count_getattr = 0
count_import = 0

for root, dirs, files in os.walk('src'):
    for fname in files:
        if not fname.endswith('.py'): continue
        if fname == '_stub.py': continue
        path = os.path.join(root, fname)
        
        with open(path) as f:
            content = f.read()
        
        modified = False
        
        # 1. Remove module-level __getattr__ that returns _P
        # Pattern: def __getattr__(name):\n    return _P(name)
        old_pat = r'\n+def __getattr__\(name[^)]*\):\s*\n\s+return _P\([^)]+\)\s*'
        if re.search(old_pat, content):
            content = re.sub(old_pat, '', content)
            count_getattr += 1
            modified = True
        
        # Also match: __getattr__ = lambda name: _P(name) or similar
        old_lam = r'\n+__getattr__\s*=\s*lambda[^:\n]*:\s*_P\s*\([^)]+\)\s*'
        if re.search(old_lam, content):
            content = re.sub(old_lam, '', content)
            count_getattr += 1
            modified = True
        
        # 2. Remove from ._stub import _P (only if _P not used elsewhere)
        if 'from ._stub import _P' in content or 'from .core._stub import _P' in content:
            # Check if _P is used elsewhere in the file
            remaining = content.replace('from ._stub import _P', '').replace('from .core._stub import _P', '')
            if '_P(' not in remaining and 'import _P' not in remaining and 'class _P' not in remaining:
                content = re.sub(r'from \.(\w+\.)*_stub import _P\s*\n', '', content)
                content = re.sub(r'from \.core\._stub import _P\s*\n', '', content)
                count_import += 1
                modified = True
        
        # 3. Add __all__ if missing and module has real exports
        if modified and '__all__' not in content:
            try:
                tree = ast.parse(content)
                exports = []
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                        exports.append(node.name)
                    elif isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                        exports.append(node.name)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and not target.id.startswith('_'):
                                exports.append(target.id)
                if exports:
                    all_line = f'__all__ = {exports}\n'
                    # Insert after docstring
                    lines = content.split('\n')
                    insert_at = 0
                    if lines[0].startswith('"""') or lines[0].startswith("'''"):
                        for i, l in enumerate(lines[1:], 1):
                            if '"""' in l or "'''" in l:
                                insert_at = i + 1
                                break
                    lines.insert(insert_at, all_line)
                    content = '\n'.join(lines)
            except:
                pass
        
        if modified:
            with open(path, 'w') as f:
                f.write(content)

print(f"Removed {count_getattr} module-level __getattr__(_P)")
print(f"Removed {count_import} unused _P imports")
