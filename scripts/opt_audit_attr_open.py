# -*- coding: utf-8 -*-
"""审计: 找出被注入 encoding 的 X.open() 调用中, X 不支持 encoding 形参的。

支持 encoding 的 (白名单): builtins open, pathlib Path.open, gzip, bz2, lzma,
tarfile, codecs, io, tokenfile? — 以 Python 3.12 文档为准。
不支持 (必须剥离 encoding): os, webbrowser, zipfile.ZipFile, shelve, dbm,
PIL.Image, shutils 等。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# 这些根模块的 .open() 接受 encoding 形参
ENCODING_OK_ROOTS = {"gzip", "bz2", "lzma", "codecs", "io", "tarfile",
                     "pathlib", "tokenize", "linecache"}
# 这些根模块的 .open() 不接受 encoding → TypeError
ENCODING_BAD_ROOTS = {"os", "webbrowser", "zipfile", "shelve", "dbm",
                      "PIL", "Image", "fitz", "docx", "pptx", "openpyxl"}


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def has_enc(call):
    if any(kw.arg == "encoding" for kw in call.keywords):
        return True
    return len(call.args) >= 4


for py in sorted(SRC.rglob("*.py")):
    if "__pycache__" in str(py):
        continue
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "open"):
            continue
        if not has_enc(node):
            continue
        d = dotted(f)
        root = d.split(".")[0]
        if root in ENCODING_BAD_ROOTS or (root not in ENCODING_OK_ROOTS
                                          and "." in d and root not in ("gzip",)):
            print(f"{py.relative_to(SRC)}:{node.lineno}: {d}(...encoding...)")
