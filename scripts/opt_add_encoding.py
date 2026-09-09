# -*- coding: utf-8 -*-
"""v3.129.0 优化①: 为所有裸 open() 文本调用补齐 encoding="utf-8"。

中文 Windows 默认 locale 编码 (cp936) 下, 未显式指定编码的 open()
读 UTF-8 文件会产生 UnicodeDecodeError 或乱码。本脚本基于 AST
精确定位所有缺 encoding 的文本模式 open() 调用, 在闭括号前插入
encoding="utf-8", 跳过:
  - 二进制模式 (mode 含 "b")
  - 已含 encoding 参数的调用
改写后逐文件 ast.parse 验证语法正确性, 验证失败则不落盘。

用法: python scripts/opt_add_encoding.py [--dry-run]
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "src"]
INSERT = ', encoding="utf-8"'


def mode_of(call: ast.Call) -> str:
    """返回 open() 调用的 mode 字符串 (非字面量则返回 '' 表示跳过判断)。"""
    if len(call.args) >= 2:
        a = call.args[1]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        return ""
    for kw in call.keywords:
        if kw.arg == "mode":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
            return ""
    return "r"


def has_encoding(call: ast.Call) -> bool:
    if any(kw.arg == "encoding" for kw in call.keywords):
        return True
    return len(call.args) >= 4  # open(file, mode, buffering, encoding)


def find_bare_opens(tree: ast.AST):
    """返回 [(end_line, end_col)] 需补 encoding 的 open() 调用结尾位置。

    end_col 为 AST 的 end_col_offset (闭括号后一位), 插入点 = end_col - 1。
    """
    spots = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        is_open = (isinstance(f, ast.Name) and f.id == "open") or (
            isinstance(f, ast.Attribute) and f.attr == "open"
        )
        if not is_open or has_encoding(node):
            continue
        mode = mode_of(node)
        if "b" in mode:
            continue
        spots.append((node.end_lineno, node.end_col_offset))
    return spots


def process_file(path: Path, dry: bool) -> int:
    raw = path.read_bytes()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        print(f"[skip-decode-err] {path.relative_to(ROOT)}")
        return 0
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[skip-parse-err] {path.relative_to(ROOT)}: {e}")
        return 0
    spots = find_bare_opens(tree)
    if not spots:
        return 0
    lines = source.splitlines(keepends=True)
    # 倒序插入 (同 行,列 降序), 左侧插入不受右侧影响
    for (l2, c2) in sorted(spots, reverse=True):
        line = lines[l2 - 1]
        # 安全断言: 插入点前一个字符必须是调用闭括号 ')'
        if c2 - 1 >= len(line) or line[c2 - 1] != ")":
            print(f"[skip-mismatch] {path.relative_to(ROOT)}:{l2}")
            continue
        lines[l2 - 1] = line[: c2 - 1] + INSERT + line[c2 - 1 :]
    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        print(f"[skip-rewrite-err] {path.relative_to(ROOT)}: {e}")
        return 0
    if not dry:
        path.write_bytes(new_source.encode("utf-8"))
    print(f"[ok] {path.relative_to(ROOT)}: +encoding x{len(spots)}")
    return len(spots)


def main():
    dry = "--dry-run" in sys.argv
    total = files = 0
    for base in TARGETS:
        for py in sorted(base.rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            n = process_file(py, dry)
            if n:
                total += n
                files += 1
    print(f"\nTOTAL: {total} call sites in {files} files {'(dry-run)' if dry else 'PATCHED'}")


if __name__ == "__main__":
    main()
