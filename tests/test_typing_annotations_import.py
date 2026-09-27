# -*- coding: utf-8 -*-
"""typing 注解导入完整性守门 — I-3 同型 P1 三发的 bug 类根治 (第四发预防)。

背景: 004 本机 Python 3.14 PEP649 惰性注解求值, 注解里用了未导入的
Dict/Any/Optional 等也不报错; CI 与 002 侧 3.12 在 def 求值时即 NameError。
三连发: cascade_router.py(Any) / hub_receipt_watch.py(Any,Dict) /
task_progress.py(Dict)。本测试 AST 扫描 src/tools/cluster 全部 .py,
注解中出现的 typing 名必须在文件内可解析 (直接导入或 typing.xxx)。
"""
import ast
import os

import pytest

TYPING_NAMES = {'Dict', 'List', 'Optional', 'Any', 'Tuple', 'Set', 'Union',
                'Callable', 'Iterable', 'Sequence', 'Mapping', 'FrozenSet'}
SCAN_DIRS = ['src', 'tools', 'cluster']
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _iter_py_files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            for fn in files:
                if fn.endswith('.py'):
                    yield os.path.join(dirpath, fn)


def _typing_violations(path):
    src = open(path, encoding='utf-8').read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        # 002meshctx P2: 语法错误必须显式 fail — 静默放行会让最坏输入绕过全仓扫描
        return {'__SYNTAX_ERROR__'}

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'typing':
            for a in node.names:
                imported.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'typing':
                    imported.add('typing')

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in TYPING_NAMES:
            used.add(node.id)
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
              and node.value.id == 'typing'):
            used.add(node.attr)
    if 'typing' in imported:
        return set()
    return used - imported


def test_annotations_use_only_imported_typing_names():
    """全仓扫描: 注解用 typing 名必须已导入 (CI/3.12 会 NameError 的类)."""
    bad = []
    for fp in _iter_py_files():
        missing = _typing_violations(fp)
        if missing:
            bad.append(f"{os.path.relpath(fp, ROOT)}: missing {sorted(missing)}")
    assert not bad, (
        "PEP649 惰性注解在 3.12/CI 会 NameError (I-3 同型三连发), 以下文件需补导入:\n"
        + "\n".join(bad)
    )
