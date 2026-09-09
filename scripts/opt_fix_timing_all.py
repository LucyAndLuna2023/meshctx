# -*- coding: utf-8 -*-
"""v3.129.0 优化④b: 系统性耗时测量 perf_counter 化 (作用域安全版)。

规则: 在每个函数作用域内, 若变量 VAR 满足
  ① 存在 VAR = time.time() 赋值, 且
  ② VAR 的全部"读取"都出现在 (time.time() - VAR) 形态的减法里,
则该作用域内与 VAR 配对的 time.time() 全部改 perf_counter。
VAR 参与任何其他运算/返回/存储 → 整组保留墙钟不动 (防误伤持久化时间戳)。
改后逐文件 ast.parse 验证; 只重写受影响行, 注释不丢。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRY = "--dry-run" in sys.argv


def is_time_now(call):
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "time"
            and isinstance(f.value, ast.Name) and f.value.id == "time"
            and not call.args and not call.keywords)


class ScopeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.pairs = []  # [(assign_nodes..., sub_nodes...) 扁平化后逐节点]

    def visit_FunctionDef(self, node):
        self._scan(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan(self, fn):
        assigns = {}   # var -> [assign nodes]
        subs = {}      # var -> [BinOp nodes]
        for node in ast.walk(fn):
            if node is not fn and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # 嵌套函数作用域独立
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                    and is_time_now(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        assigns.setdefault(t.id, []).append(node)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                left, right = node.left, node.right
                call_side = left if isinstance(left, ast.Call) and is_time_now(left) else \
                    right if isinstance(right, ast.Call) and is_time_now(right) else None
                name_side = right if call_side is left else left if call_side is right else None
                if call_side is not None and isinstance(name_side, ast.Name):
                    subs.setdefault(name_side.id, []).append(node)
        # 阻断审查: VAR 的所有 Name 出现, 除 Store 目标与已登记减法外, 均视为其他用途
        sub_nodes = {id(u) for lst in subs.values() for u in lst}
        for v, a_nodes in assigns.items():
            if v not in subs:
                continue
            ok = True
            for n2 in ast.walk(fn):
                if n2 is not fn and isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if isinstance(n2, ast.Name) and n2.id == v and not isinstance(n2.ctx, ast.Store):
                    # 该读取必须在已登记的减法节点内
                    if not any(n2 in ast.walk(u) for u in subs[v]):
                        ok = False
                        break
                # 赋值节点本身允许 (Store 上下文已被上面排除, 但 Assign.value 无 Name)
            if not ok:
                continue
            for a in a_nodes:
                self.pairs.append(a.value)  # time.time() Call in assign
            for u in subs[v]:
                for side in (u.left, u.right):
                    if isinstance(side, ast.Call) and is_time_now(side):
                        self.pairs.append(side)


def rewrite(path: Path) -> int:
    source = path.read_bytes().decode("utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    visitor = ScopeVisitor()
    visitor.visit(tree)
    if not visitor.pairs:
        return 0
    # (lineno, col_offset) 定位 time.time() 调用, 文本级替换该行
    spots = {(c.lineno, c.col_offset) for c in visitor.pairs}
    lines = source.splitlines(keepends=True)
    changed = 0
    for (ln, col) in sorted(spots):
        line = lines[ln - 1]
        idx = line.find("time.time()", col)
        if idx < 0:
            idx = line.find("time.time()")
        if idx < 0:
            continue
        # 同一行多处: 循环替换全部 (先统计该行 spots 数, 逐个替换)
        lines[ln - 1] = line = line.replace("time.time()", "time.perf_counter()", 1)
        changed += 1
    # 同行多个配对调用处理: 若该行登记的调用数 > 1, 剩余的全部替换
    from collections import Counter
    line_counts = Counter(ln for (ln, _) in spots)
    for ln, cnt in line_counts.items():
        if cnt > 1 and "time.time()" in lines[ln - 1]:
            extra = lines[ln - 1].count("time.time()")
            lines[ln - 1] = lines[ln - 1].replace("time.time()", "time.perf_counter()")
            changed += extra
    if not changed:
        return 0
    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except SyntaxError:
        print(f"[skip-err] {path.relative_to(ROOT)}")
        return 0
    if not DRY:
        path.write_bytes(new_source.encode("utf-8"))
    print(f"[ok] {path.relative_to(ROOT)}: {changed} calls")
    return changed


total = files = 0
for py in sorted((ROOT / "src").rglob("*.py")):
    if "__pycache__" in str(py):
        continue
    n = rewrite(py)
    if n:
        total += n
        files += 1
mode = "(dry-run)" if DRY else "PATCHED"
print(f"\nTOTAL: {total} calls in {files} files {mode}")
