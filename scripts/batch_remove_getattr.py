#!/usr/bin/env python3
"""Batch remove __getattr__ from @dataclass and Enum classes across meshctx."""
import ast, os, re, sys

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

removed_count = 0
files_modified = []

for root, dirs, files in os.walk('src'):
    for fname in files:
        if not fname.endswith('.py'): continue
        path = os.path.join(root, fname)
        try:
            with open(path) as f:
                content = f.read()
            tree = ast.parse(content)
        except SyntaxError:
            continue
        
        lines = content.split('\n')
        to_remove = set()  # line numbers (0-indexed)
        
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_dc = any(isinstance(d, ast.Name) and d.id == 'dataclass' for d in node.decorator_list)
            is_enum = any(isinstance(b, ast.Name) and b.id == 'Enum' for b in node.bases) if node.bases else False
            if not (is_dc or is_enum):
                continue
            
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == '__getattr__':
                    # Remove the function: from its first line to last line
                    start = item.lineno - 1  # 0-indexed
                    end = item.end_lineno     # exclusive
                    for i in range(start, end):
                        to_remove.add(i)
                    removed_count += 1
        
        if not to_remove:
            continue
        
        # Rebuild file without removed lines
        new_lines = [l for i, l in enumerate(lines) if i not in to_remove]
        
        # Also remove the _P import if it's now unused
        new_content = '\n'.join(new_lines)
        # Check if _P is still referenced
        if '_P(' not in new_content and 'import _P' not in new_content:
            new_content = re.sub(r'from\s+\.\S+\s+import\s+_P\s*\n', '', new_content)
            new_content = re.sub(r'from\s+\.\S+\s+import\s+.*_P.*\n', '', new_content)
        
        with open(path, 'w') as f:
            f.write(new_content)
        
        files_modified.append(f"{path} (-{len(to_remove)} lines)")
        print(f"  {path}: removed {len(to_remove)} lines ({len(to_remove)//3} __getattr__)")

print(f"\n✅ Removed {removed_count} __getattr__ from {len(files_modified)} files")
