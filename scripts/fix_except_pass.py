#!/usr/bin/env python3
"""Fix silent except:pass in critical files — add logging."""
import re, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

files_to_fix = ['src/main.py', 'src/web_ui.py']
count = 0

for path in files_to_fix:
    with open(path) as f:
        content = f.read()
    lines = content.split('\n')
    modified = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this is an except line followed by pass
        if re.match(r'\s*except\b', line):
            # Check next non-empty line
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            if j < len(lines) and re.match(r'\s*pass\s*$', lines[j]):
                # Get indent
                indent = re.match(r'(\s*)', line).group(1) + '    '
                # Replace pass with logger
                exc_info = line.strip()
                lines[j] = f'{indent}logger.debug("Suppressed {exc_info}: {{}}", exc_info=True)'
                count += 1
        i += 1
    
    new_content = '\n'.join(lines)
    with open(path, 'w') as f:
        f.write(new_content)
    print(f"  {path}: fixed {count} except:pass")

print(f"\n✅ Total: {count} replacements")
