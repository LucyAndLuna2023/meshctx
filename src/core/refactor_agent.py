#!/usr/bin/env python3
"""refactor_agent.py — Intelligent refactoring, safe renaming, and duplicate detection.

Zero pip dependencies. Pure Python stdlib. AST-aware, cross-file, scope-respecting.

Components:
    RefactorAgent        — Orchestrator: scans a project and emits structured suggestions.
    SafeRenamer          — Scope-aware, cross-file rename with validation and diff preview.
    DuplicateDetector    — AST-normalized structural hash + token-sequence near-match.
    ComplexityReducer    — Cyclomatic complexity, nesting depth, and function-length flags.
    ExtractMethod        — Detects extractable code blocks inside functions.
    RefactorSuggestion   — Immutable data record for a single refactoring opportunity.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import io
import textwrap
import os
import re
import tokenize as _tokenize_module
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Iterator


class Severity(Enum):
    INFO = auto(); LOW = auto(); MEDIUM = auto(); HIGH = auto(); CRITICAL = auto()

class Effort(Enum):
    TRIVIAL = auto(); SMALL = auto(); MODERATE = auto(); LARGE = auto(); MAJOR = auto()

class Impact(Enum):
    NEGLIGIBLE = auto(); LOW = auto(); MEDIUM = auto(); HIGH = auto(); TRANSFORMATIVE = auto()

class RefactorKind(Enum):
    RENAME = auto(); EXTRACT_METHOD = auto(); INLINE = auto(); SIMPLIFY = auto()
    DUPLICATE = auto(); COMPLEXITY = auto(); DEAD_CODE = auto(); STYLE = auto()
    IMPORT = auto(); OTHER = auto()

@dataclass(frozen=True)
class CodeLocation:
    file: Path
    line: int
    col: int
    end_line: int = -1
    end_col: int = -1

    def __post_init__(self) -> None:
        if self.end_line == -1:
            object.__setattr__(self, "end_line", self.line)
        if self.end_col == -1:
            object.__setattr__(self, "end_col", self.col)

@dataclass(frozen=True)
class RefactorSuggestion:
    severity: Severity
    kind: RefactorKind
    location: CodeLocation
    description: str
    effort: Effort = Effort.SMALL
    impact: Impact = Impact.MEDIUM
    suggested_fix: str = ""
    rule_id: str = ""
    context_lines: tuple[str, ...] = ()

    def __str__(self) -> str:
        ctx = "\n".join(f"    {l}" for l in self.context_lines) if self.context_lines else ""
        return (
            f"[{self.severity.name:<8}] {self.kind.name:<16} "
            f"{self.location.file.name}:{self.location.line}  "
            f"effort={self.effort.name:<10} impact={self.impact.name}\n"
            f"  {self.description}\n{ctx}"
        )

@dataclass
class ComplexityReport:
    name: str
    file: Path
    line: int
    end_line: int
    cyclomatic: int
    nesting_depth: int
    line_count: int
    n_params: int
    n_locals: int

@dataclass
class RenameResult:
    success: bool
    old_name: str
    new_name: str
    files_changed: list[Path] = field(default_factory=list)
    diffs: dict[Path, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

@dataclass
class DuplicateGroup:
    blocks: list[CodeLocation]
    similarity: float
    normalized_source: str = ""

#  Utilities

_BOM_PATTERN = re.compile(r"^[\ufeff]")
_PY_EXT = frozenset({".py", ".pyi", ".pyx", ".pxd"})

def _read_source(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _BOM_PATTERN.sub("", raw).replace("\r\n", "\n").replace("\r", "\n")

def _iter_python_files(root: Path, max_depth: int = 20) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        depth = Path(dirpath).relative_to(root)
        if len(depth.parts) > max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for fname in filenames:
            if Path(fname).suffix in _PY_EXT:
                yield Path(dirpath) / fname

def _source_lines(source: str) -> list[str]:
    return source.splitlines(keepends=True)

def _node_text(source: str, node: ast.AST) -> str:
    lines = _source_lines(source)
    sl = getattr(node, "lineno", 1)
    el = getattr(node, "end_lineno", sl)
    co = getattr(node, "col_offset", 0)
    eco = getattr(node, "end_col_offset", 0)
    if sl == el:
        return lines[sl - 1][co:eco] if sl - 1 < len(lines) else ""
    relevant = lines[sl - 1 : el]
    if relevant:
        relevant[-1] = relevant[-1][:eco] if eco else relevant[-1]
        relevant[0] = relevant[0][co:]
    return "".join(relevant)

def _node_text_for_lines(source: str, start: int, end: int) -> str:
    return "".join(_source_lines(source)[start - 1 : end])

def _unified_diff(old: str, new: str, label: str = "file") -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=label, tofile=label, lineterm="",
    ))

#  AST normalization (for duplicate detection)

class _AstNormalizer(ast.NodeTransformer):
    def __init__(self) -> None:
        super().__init__()
        self._name_map: dict[str, str] = {}
        self._idx = 0

    def visit_Name(self, node: ast.Name) -> ast.Name:
        key = node.id
        if key not in self._name_map:
            self._name_map[key] = f"v{self._idx}"
            self._idx += 1
        return ast.Name(id=self._name_map[key], ctx=ast.Load())

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            return ast.Constant(value="<str>")
        if isinstance(node.value, bool):
            return ast.Constant(value=True)
        if isinstance(node.value, (int, float, complex)):
            return ast.Constant(value=0)
        if node.value is None:
            return ast.Constant(value=None)
        return ast.Constant(value="<const>")

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        return ast.Attribute(value=node.value, attr="attr", ctx=ast.Load())

def _structural_fingerprint(tree: ast.AST) -> str:
    try:
        raw = ast.dump(_AstNormalizer().visit(tree), annotate_fields=False)
    except Exception:
        raw = ast.dump(tree)
    return hashlib.sha256(raw.encode()).hexdigest()

def _token_sequence(source: str) -> tuple[int, ...]:
    tokens: list[int] = []
    try:
        for tok in _tokenize_module.generate_tokens(io.StringIO(source).readline):
            if tok.type not in (
                _tokenize_module.ENCODING, _tokenize_module.ENDMARKER,
                _tokenize_module.NL, _tokenize_module.COMMENT, _tokenize_module.NEWLINE,
            ):
                tokens.append(tok.type)
    except _tokenize_module.TokenError:
        pass
    return tuple(tokens)

def _seq_similarity(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    ca, cb = Counter(a), Counter(b)
    all_keys = set(ca) | set(cb)
    intersection = sum(min(ca[k], cb[k]) for k in all_keys)
    union = sum(max(ca[k], cb[k]) for k in all_keys)
    return intersection / union if union > 0 else 0.0

def _seq_hash(seq: tuple[int, ...]) -> str:
    return hashlib.md5(bytes(seq)).hexdigest()

#  Scope analysis

class _Scope:
    def __init__(self, parent: _Scope | None = None, kind: str = "module") -> None:
        self.parent = parent
        self.kind = kind
        self.names: dict[str, ast.AST] = {}

    def define(self, name: str, node: ast.AST) -> None:
        self.names[name] = node

    def lookup(self, name: str) -> ast.AST | None:
        if name in self.names:
            return self.names[name]
        return self.parent.lookup(name) if self.parent else None

class _ScopeBuilder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.root = _Scope()
        self.current = self.root
        self.all_defs: dict[ast.AST, _Scope] = {}

    def _push(self, kind: str) -> None:
        self.current = _Scope(parent=self.current, kind=kind)

    def _pop(self) -> None:
        if self.current.parent is not None:
            self.current = self.current.parent

    def _define(self, name: str, node: ast.AST) -> None:
        self.current.define(name, node)
        self.all_defs[node] = self.current

    def _define_targets(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self._define(target.id, target)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._define_targets(elt)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._define(node.name, node)
        self._push("function")
        for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            self._define(a.arg, a)
        if node.args.vararg:
            self._define(node.args.vararg.arg, node.args.vararg)
        if node.args.kwarg:
            self._define(node.args.kwarg.arg, node.args.kwarg)
        self.generic_visit(node)
        self._pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._define(node.name, node)
        self._push("class")
        self.generic_visit(node)
        self._pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._push("lambda")
        for a in node.args.args:
            self._define(a.arg, a)
        self.generic_visit(node)
        self._pop()

    def _visit_comp(self, node: ast.AST) -> None:
        self._push("comprehension")
        self.generic_visit(node)
        self._pop()
    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_DictComp = _visit_comp
    visit_GeneratorExp = _visit_comp

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._define(node.id, node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._define(alias.asname or alias.name.split(".")[0], node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._define(alias.asname or alias.name, node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._define(node.name, node)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._define_targets(node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)  # type: ignore[arg-type]

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._define_targets(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars:
                self._define_targets(item.optional_vars)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)  # type: ignore[arg-type]

# ═══════════════════════════════════════════════════════════════════════════════
#  1. SafeRenamer — scope-aware, cross-file rename
# ═══════════════════════════════════════════════════════════════════════════════

class SafeRenamer:
    def __init__(self, roots: list[Path] | None = None) -> None:
        self._roots: list[Path] = roots or [Path.cwd()]
        self._files: dict[Path, str] = {}
        self._trees: dict[Path, ast.AST] = {}
        self._scopes: dict[Path, _Scope] = {}
        self._name_index: dict[str, list[tuple[Path, ast.AST]]] = defaultdict(list)

    def scan(self, max_files: int = 2000) -> None:
        count = 0
        for root in self._roots:
            for fpath in _iter_python_files(root):
                if count >= max_files:
                    return
                try:
                    source = _read_source(fpath)
                except OSError:
                    continue
                self._files[fpath] = source
                try:
                    tree = ast.parse(source, filename=str(fpath))
                except SyntaxError:
                    continue
                self._trees[fpath] = tree
                builder = _ScopeBuilder()
                builder.visit(tree)
                self._scopes[fpath] = builder.root
                for node in builder.all_defs:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        self._name_index[node.name].append((fpath, node))
                count += 1

    def find_references(self, name: str, file_path: Path) -> list[CodeLocation]:
        if file_path not in self._trees:
            return []
        tree = self._trees[file_path]
        builder = _ScopeBuilder()
        builder.visit(tree)
        target_def = next((n for n in builder.all_defs
                          if (getattr(n, "name", None) or getattr(n, "id", None)) == name), None)
        if target_def is None:
            return []

        refs: list[CodeLocation] = []
        scope = builder.root

        class _RefFinder(ast.NodeVisitor):
            def visit_FunctionDef(self, fn: ast.FunctionDef) -> None:
                nonlocal scope
                if fn is target_def:
                    self.generic_visit(fn)
                    return
                scope.define(fn.name, fn)
                scope = _Scope(parent=scope, kind="function")
                self.generic_visit(fn)
                scope = scope.parent or scope

            def visit_ClassDef(self, cd: ast.ClassDef) -> None:
                nonlocal scope
                if cd is target_def:
                    self.generic_visit(cd)
                    return
                scope.define(cd.name, cd)
                scope = _Scope(parent=scope, kind="class")
                self.generic_visit(cd)
                scope = scope.parent or scope

            def visit_Lambda(self, lb: ast.Lambda) -> None:
                nonlocal scope
                scope = _Scope(parent=scope, kind="lambda")
                for a in lb.args.args:
                    scope.define(a.arg, a)
                if lb.args.vararg:
                    scope.define(lb.args.vararg.arg, lb.args.vararg)
                if lb.args.kwarg:
                    scope.define(lb.args.kwarg.arg, lb.args.kwarg)
                for a in lb.args.kwonlyargs:
                    scope.define(a.arg, a)
                for a in lb.args.posonlyargs:
                    scope.define(a.arg, a)
                self.generic_visit(lb)
                scope = scope.parent or scope

            def visit_Name(self, nd: ast.Name) -> None:
                nonlocal scope
                if nd.id == name and scope.lookup(name) is target_def:
                    el = getattr(nd, "end_lineno", nd.lineno) or nd.lineno
                    eco = (getattr(nd, "end_col_offset", nd.col_offset + len(name))
                           or nd.col_offset + len(name))
                    refs.append(CodeLocation(file=file_path, line=nd.lineno,
                        col=nd.col_offset, end_line=el, end_col=eco))
                self.generic_visit(nd)

        _RefFinder().visit(tree)
        return refs

    def find_cross_file_references(self, name: str) -> dict[Path, list[CodeLocation]]:
        return {fp: refs for fp in self._trees
                if (refs := self.find_references(name, fp))}

    def rename(self, old_name: str, new_name: str, file_path: Path,
               line: int, col: int, *, cross_file: bool = True,
               dry_run: bool = False) -> RenameResult:
        warnings, errors, diffs, changed = [], [], {}, []
        if not new_name.isidentifier():
            return RenameResult(False, old_name, new_name, [], {},
                                [f"'{new_name}' is not a valid Python identifier"], [])
        if new_name == old_name:
            return RenameResult(False, old_name, new_name, [], {},
                                ["New name is identical to old name"], [])

        all_refs: dict[Path, list[CodeLocation]] = {
            file_path: self.find_references(old_name, file_path)}
        if cross_file:
            for fp, refs in self.find_cross_file_references(old_name).items():
                if fp != file_path:
                    all_refs[fp] = refs

        for fp, refs in list(all_refs.items()):
            if not refs:
                del all_refs[fp]
            elif fp in self._scopes and new_name in self._scopes[fp].names:
                warnings.append(
                    f"'{new_name}' already defined in {fp.name}; may create ambiguity")

        total_refs = sum(len(v) for v in all_refs.values())
        if total_refs == 0:
            errors.append(f"No references found for '{old_name}' at {file_path}:{line}")
            return RenameResult(False, old_name, new_name, [], {}, warnings, errors)

        for fp, refs in all_refs.items():
            if fp not in self._files:
                try:
                    source = _read_source(fp)
                except OSError:
                    errors.append(f"Cannot read {fp}")
                    continue
            else:
                source = self._files[fp]
            lines = _source_lines(source)
            rlist = sorted(((r.line, r.col, r.end_line, r.end_col) for r in refs),
                           reverse=True)
            new_source = source
            for rl, rc, el, ec in rlist:
                off_s = sum(len(ln) for ln in lines[:rl - 1]) + rc
                off_e = sum(len(ln) for ln in lines[:el - 1]) + ec
                new_source = new_source[:off_s] + new_name + new_source[off_e:]
            if new_source != source:
                diffs[fp] = _unified_diff(source, new_source, str(fp))
                changed.append(fp)
                if not dry_run:
                    fp.write_text(new_source, encoding="utf-8")
                    self._files[fp] = new_source
                    try:
                        self._trees[fp] = ast.parse(new_source, filename=str(fp))
                    except SyntaxError:
                        errors.append(f"Syntax error after renaming in {fp}")

        return RenameResult(len(errors) == 0 and len(changed) > 0,
                            old_name, new_name, changed, diffs, warnings, errors)

# ═══════════════════════════════════════════════════════════════════════════════
#  2. DuplicateDetector — AST hash + token-sequence similarity
# ═══════════════════════════════════════════════════════════════════════════════

_MIN_DUPLICATE_LINES = 4
_MIN_TOKENS = 20

class DuplicateDetector:
    def __init__(self, min_lines: int = _MIN_DUPLICATE_LINES,
                 similarity_threshold: float = 0.85) -> None:
        self.min_lines = min_lines
        self.similarity_threshold = similarity_threshold

    def detect(self, root: Path) -> list[DuplicateGroup]:
        body_records: list[tuple[Path, ast.AST, str, int, int]] = []
        for fpath in _iter_python_files(root):
            try:
                source = _read_source(fpath)
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(fpath))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                el = getattr(node, "end_lineno", node.lineno) or node.lineno
                if el - node.lineno + 1 >= self.min_lines:
                    body_records.append((fpath, node, source, node.lineno, el))

        # Strategy 1: exact structural match
        hash_groups: dict[str, list[tuple[Path, int, int, str]]] = defaultdict(list)
        for fpath, node, source, sl, el in body_records:
            fp = _structural_fingerprint(node)
            hash_groups[fp].append((fpath, sl, el, _node_text(source, node)))

        seen: set[tuple[str, str]] = set()
        groups: list[DuplicateGroup] = []
        for fp, entries in hash_groups.items():
            if len(entries) < 2:
                continue
            blocks = [CodeLocation(file=f, line=s, col=0, end_line=e, end_col=0)
                      for f, s, e, _ in entries]
            groups.append(DuplicateGroup(blocks=blocks, similarity=1.0,
                                         normalized_source=entries[0][3]))
            for entry in entries:
                seen.add((str(entry[0]), fp))

        # Strategy 2: near-match via token-sequence
        token_seqs: list[tuple[Path, int, int, tuple[int, ...]]] = []
        for fpath, node, source, sl, el in body_records:
            if (str(fpath), _structural_fingerprint(node)) in seen:
                continue
            tseq = _token_sequence(_node_text(source, node))
            if len(tseq) >= _MIN_TOKENS:
                token_seqs.append((fpath, sl, el, tseq))

        for i in range(len(token_seqs)):
            for j in range(i + 1, len(token_seqs)):
                af, a_s, a_e, aseq = token_seqs[i]
                bf, b_s, b_e, bseq = token_seqs[j]
                if af == bf and a_s == b_s:
                    continue
                sim = _seq_similarity(aseq, bseq)
                if sim >= self.similarity_threshold:
                    groups.append(DuplicateGroup(
                        blocks=[CodeLocation(file=af, line=a_s, col=0, end_line=a_e, end_col=0),
                                CodeLocation(file=bf, line=b_s, col=0, end_line=b_e, end_col=0)],
                        similarity=round(sim, 3)))
                    seen.add((str(af), _seq_hash(aseq)))
                    seen.add((str(bf), _seq_hash(bseq)))
        return groups

# ═══════════════════════════════════════════════════════════════════════════════
#  3. ComplexityReducer — cyclomatic, nesting, length
# ═══════════════════════════════════════════════════════════════════════════════

_LONG_FUNCTION = 50
_HIGH_CYCLOMATIC = 10
_DEEP_NESTING = 4
_TOO_MANY_PARAMS = 6
_TOO_MANY_LOCALS = 12

_BRANCH_NODES = (ast.If, ast.While, ast.For, ast.AsyncFor,
                  ast.ExceptHandler, ast.With, ast.AsyncWith,
                  ast.BoolOp, ast.IfExp, ast.Assert)

def _count_branches(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODES):
            if isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
            elif isinstance(child, ast.If):
                count += 1 + sum(1 for s in child.orelse if isinstance(s, ast.If))
            else:
                count += 1
    return count

_NESTING_NODES = (ast.If, ast.For, ast.While, ast.AsyncFor,
                   ast.With, ast.AsyncWith, ast.Try,
                   ast.FunctionDef, ast.AsyncFunctionDef)

def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    max_depth = current
    for child in ast.iter_child_nodes(node):
        inc = 1 if isinstance(child, _NESTING_NODES) else 0
        max_depth = max(max_depth, _max_nesting_depth(child, current + inc))
    return max_depth

class ComplexityReducer:
    def __init__(self, max_lines: int = _LONG_FUNCTION,
                 max_cyclomatic: int = _HIGH_CYCLOMATIC,
                 max_nesting: int = _DEEP_NESTING,
                 max_params: int = _TOO_MANY_PARAMS,
                 max_locals: int = _TOO_MANY_LOCALS) -> None:
        self.max_lines = max_lines
        self.max_cyclomatic = max_cyclomatic
        self.max_nesting = max_nesting
        self.max_params = max_params
        self.max_locals = max_locals

    def analyze(self, root: Path) -> list[ComplexityReport]:
        reports: list[ComplexityReport] = []
        for fpath in _iter_python_files(root):
            try:
                source = _read_source(fpath)
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(fpath))
            except SyntaxError:
                continue
            reports.extend(self._analyze_tree(tree, fpath))
        return reports

    def _analyze_tree(self, tree: ast.AST, fpath: Path) -> list[ComplexityReport]:
        reports: list[ComplexityReport] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                reports.append(self._analyze_func(node, fpath))
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        reports.append(self._analyze_func(item, fpath, node.name))
        return reports

    def _analyze_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                      fpath: Path, class_name: str = "") -> ComplexityReport:
        prefix = f"{class_name}." if class_name else ""
        el = getattr(node, "end_lineno", node.lineno) or node.lineno
        n_params = (len(node.args.args) + len(node.args.kwonlyargs)
                    + len(node.args.posonlyargs) + (1 if node.args.vararg else 0)
                    + (1 if node.args.kwarg else 0))
        locals_set = {c.id for c in ast.walk(node)
                      if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Store)}
        return ComplexityReport(
            name=f"{prefix}{node.name}", file=fpath, line=node.lineno,
            end_line=el, cyclomatic=1 + _count_branches(node),
            nesting_depth=_max_nesting_depth(node, 0),
            line_count=el - node.lineno + 1, n_params=n_params,
            n_locals=len(locals_set))

    def suggest(self, report: ComplexityReport) -> list[RefactorSuggestion]:
        loc = CodeLocation(file=report.file, line=report.line, col=0)
        rn = report.name
        rules = [
            (report.line_count, self.max_lines, Severity.MEDIUM, RefactorKind.EXTRACT_METHOD,
             Effort.MODERATE, Impact.HIGH, "C001-long",
             f"'{rn}' {report.line_count} lines (>{self.max_lines}). Extract helpers."),
            (report.cyclomatic, self.max_cyclomatic, Severity.HIGH, RefactorKind.SIMPLIFY,
             Effort.MODERATE, Impact.HIGH, "C002-cyclo",
             f"'{rn}' cyclomatic={report.cyclomatic} (>{self.max_cyclomatic}). Split."),
            (report.nesting_depth, self.max_nesting, Severity.MEDIUM, RefactorKind.SIMPLIFY,
             Effort.SMALL, Impact.MEDIUM, "C003-nest",
             f"'{rn}' nesting={report.nesting_depth} (>{self.max_nesting}). Flatten."),
            (report.n_params, self.max_params, Severity.LOW, RefactorKind.SIMPLIFY,
             Effort.MODERATE, Impact.MEDIUM, "C004-params",
             f"'{rn}' {report.n_params} params (>{self.max_params}). Group into class."),
            (report.n_locals, self.max_locals, Severity.LOW, RefactorKind.EXTRACT_METHOD,
             Effort.MODERATE, Impact.MEDIUM, "C005-locals",
             f"'{rn}' {report.n_locals} locals (>{self.max_locals}). Extract."),
        ]
        return [RefactorSuggestion(severity=sv, kind=rk, location=loc, rule_id=rid,
                                   description=desc, effort=ef, impact=imp)
                for val, thresh, sv, rk, ef, imp, rid, desc in rules if val > thresh]

# ═══════════════════════════════════════════════════════════════════════════════
#  4. ExtractMethod — detect extractable code blocks
# ═══════════════════════════════════════════════════════════════════════════════

_MIN_EXTRACT_LINES = 3
_MIN_EXTRACT_STMTS = 3

class ExtractMethod:
    def __init__(self, min_statements: int = _MIN_EXTRACT_STMTS,
                 min_lines: int = _MIN_EXTRACT_LINES,
                 max_external_refs: int = 5) -> None:
        self.min_statements = min_statements
        self.min_lines = min_lines
        self.max_external_refs = max_external_refs

    def detect(self, root: Path) -> list[RefactorSuggestion]:
        suggestions: list[RefactorSuggestion] = []
        for fpath in _iter_python_files(root):
            try:
                source = _read_source(fpath)
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(fpath))
            except SyntaxError:
                continue
            suggestions.extend(self._detect_in_tree(tree, fpath, source))
        return suggestions

    def _detect_in_tree(self, tree: ast.AST, fpath: Path,
                        source: str) -> list[RefactorSuggestion]:
        suggestions: list[RefactorSuggestion] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body
            n = len(body)
            for win_size in range(self.min_statements, min(n + 1, 20)):
                for start in range(n - win_size + 1):
                    block = body[start:start + win_size]
                    sl = block[0].lineno
                    el = (getattr(block[-1], "end_lineno", block[-1].lineno)
                          or block[-1].lineno)
                    if el - sl + 1 < self.min_lines:
                        continue
                    if s := self._evaluate_block(block, node, sl, el, fpath, source):
                        suggestions.append(s)
        return suggestions

    def _evaluate_block(self, block: list[ast.stmt],
                        parent: ast.FunctionDef | ast.AsyncFunctionDef,
                        start_line: int, end_line: int, fpath: Path,
                        source: str) -> RefactorSuggestion | None:
        uses: set[str] = set()
        defines: set[str] = set()
        for stmt in block:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Name):
                    if isinstance(child.ctx, ast.Load):
                        uses.add(child.id)
                    elif isinstance(child.ctx, (ast.Store, ast.Del)):
                        defines.add(child.id)

        parent_params = {a.arg for a in (parent.args.args + parent.args.kwonlyargs
                                          + parent.args.posonlyargs)}
        if parent.args.vararg:
            parent_params.add(parent.args.vararg.arg)
        if parent.args.kwarg:
            parent_params.add(parent.args.kwarg.arg)

        parent_locals: set[str] = set()
        for stmt in parent.body:
            if stmt is block[0]:
                break
            for child in ast.walk(stmt):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    parent_locals.add(child.id)

        external_uses = uses - defines - (parent_params | parent_locals | {"self", "cls"})
        if len(external_uses) > self.max_external_refs:
            return None

        found_block = False
        defined_used_later: set[str] = set()
        for stmt in parent.body:
            if stmt is block[0]:
                found_block = True
                continue
            if not found_block:
                continue
            for child in ast.walk(stmt):
                if (isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                        and child.id in defines):
                    defined_used_later.add(child.id)

        if not defined_used_later and not defines:
            return None

        params_str = ", ".join(sorted(external_uses))
        returns_str = ", ".join(sorted(defined_used_later))
        if len(defined_used_later) > 1:
            rp = f" -> tuple[{returns_str}]"
        elif len(defined_used_later) == 1:
            rp = f" -> {returns_str}"
        else:
            rp = ""
        sig = f"def extracted({params_str}){rp}:"
        raw_lines = _node_text_for_lines(source, start_line, end_line).splitlines(True)
        dedented = textwrap.dedent("".join(raw_lines))
        block_src = "".join(
            f"    {line}" if line.rstrip("\n") else line
            for line in dedented.splitlines(True)
        )

        return RefactorSuggestion(
            severity=Severity.LOW, kind=RefactorKind.EXTRACT_METHOD,
            location=CodeLocation(file=fpath, line=start_line, col=0,
                                   end_line=end_line, end_col=0),
            rule_id="E001-extractable-block",
            description=(f"Extract {end_line - start_line + 1}-line block from "
                         f"'{parent.name}'. External: {external_uses or 'none'}. "
                         f"Later use: {defined_used_later or 'none'}."),
            effort=Effort.SMALL, impact=Impact.MEDIUM,
            suggested_fix=f"{sig}\n{block_src}",
        )

# ═══════════════════════════════════════════════════════════════════════════════
#  5. RefactorAgent — main orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

_SORT_KEYS: dict[str, Any] = {
    "severity": lambda s: s.severity.value,
    "effort": lambda s: s.effort.value,
    "impact": lambda s: s.impact.value,
    "file": lambda s: str(s.location.file),
    "kind": lambda s: s.kind.value,
}

_DEFAULT_ENABLED: dict[RefactorKind, bool] = {
    RefactorKind.RENAME: False,
    RefactorKind.EXTRACT_METHOD: True,
    RefactorKind.SIMPLIFY: True,
    RefactorKind.DUPLICATE: True,
    RefactorKind.COMPLEXITY: True,
    RefactorKind.DEAD_CODE: False,
    RefactorKind.STYLE: False,
    RefactorKind.IMPORT: False,
    RefactorKind.INLINE: False,
    RefactorKind.OTHER: False,
}

class RefactorAgent:
    """Main orchestrator: scan a codebase and emit structured refactoring suggestions.

    Usage:
        agent = RefactorAgent(root=Path("src/"))
        agent.configure(complexity_max_lines=80)
        suggestions = agent.analyze()
        for line in agent.summarize(suggestions):
            print(line)
        result = agent.safe_rename("old_name", "new_name", Path("src/main.py"), 10, 4)
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path.cwd()
        self._renamer = SafeRenamer([self._root])
        self._duplicates = DuplicateDetector()
        self._complexity = ComplexityReducer()
        self._extractor = ExtractMethod()
        self.config: dict[str, Any] = {
            "complexity_max_lines": _LONG_FUNCTION,
            "complexity_max_cyclomatic": _HIGH_CYCLOMATIC,
            "complexity_max_nesting": _DEEP_NESTING,
            "complexity_max_params": _TOO_MANY_PARAMS,
            "complexity_max_locals": _TOO_MANY_LOCALS,
            "duplicate_min_lines": _MIN_DUPLICATE_LINES,
            "duplicate_similarity_threshold": 0.85,
            "extract_min_statements": _MIN_EXTRACT_STMTS,
            "extract_min_lines": _MIN_EXTRACT_LINES,
            "extract_max_external_refs": 5,
            "sort_by": "severity",
            "max_files": 2000,
            "enabled_kinds": dict(_DEFAULT_ENABLED),
        }
        self._scanned = False

    def configure(self, **kwargs: Any) -> None:
        self.config.update(kwargs)
        c = self.config
        self._complexity.max_lines = c["complexity_max_lines"]
        self._complexity.max_cyclomatic = c["complexity_max_cyclomatic"]
        self._complexity.max_nesting = c["complexity_max_nesting"]
        self._complexity.max_params = c["complexity_max_params"]
        self._complexity.max_locals = c["complexity_max_locals"]
        self._duplicates.min_lines = c["duplicate_min_lines"]
        self._duplicates.similarity_threshold = c["duplicate_similarity_threshold"]
        self._extractor.min_statements = c["extract_min_statements"]
        self._extractor.min_lines = c["extract_min_lines"]
        self._extractor.max_external_refs = c["extract_max_external_refs"]

    def scan(self) -> None:
        self._renamer.scan(max_files=self.config["max_files"])
        self._scanned = True

    def analyze(self) -> list[RefactorSuggestion]:
        if not self._scanned:
            self.scan()
        enabled = self.config["enabled_kinds"]
        all_s: list[RefactorSuggestion] = []

        if enabled.get(RefactorKind.COMPLEXITY, False):
            for report in self._complexity.analyze(self._root):
                all_s.extend(self._complexity.suggest(report))

        if enabled.get(RefactorKind.DUPLICATE, False):
            for group in self._duplicates.detect(self._root):
                sev = Severity.MEDIUM if group.similarity >= 0.95 else Severity.LOW
                imp = Impact.HIGH if group.similarity >= 0.95 else Impact.MEDIUM
                ctx = (tuple(group.normalized_source.splitlines()[:6])
                       if group.normalized_source else ())
                for block in group.blocks:
                    all_s.append(RefactorSuggestion(
                        severity=sev, kind=RefactorKind.DUPLICATE, location=block,
                        description=(f"Duplicated ({len(group.blocks) - 1}+ other sites, "
                                     f"similarity={group.similarity:.2f}). Extract shared function."),
                        effort=Effort.MODERATE, impact=imp, rule_id="D001-duplicate-code",
                        context_lines=ctx))

        if enabled.get(RefactorKind.EXTRACT_METHOD, False):
            all_s.extend(self._extractor.detect(self._root))

        seen: set[tuple[str, int, int]] = set()
        unique: list[RefactorSuggestion] = []
        for s in all_s:
            key = (str(s.location.file), s.location.line, s.location.end_line)
            if key not in seen:
                seen.add(key)
                unique.append(s)

        sort_fn = _SORT_KEYS.get(self.config["sort_by"], _SORT_KEYS["severity"])
        unique.sort(key=sort_fn, reverse=True)
        return unique

    def safe_rename(self, old_name: str, new_name: str, file_path: Path,
                    line: int, col: int, *, cross_file: bool = True,
                    dry_run: bool = False) -> RenameResult:
        if not self._scanned:
            self.scan()
        return self._renamer.rename(old_name, new_name, file_path, line, col,
                                    cross_file=cross_file, dry_run=dry_run)

    def summarize(self, suggestions: list[RefactorSuggestion],
                  *, min_severity: Severity = Severity.INFO) -> list[str]:
        flt = [s for s in suggestions if s.severity.value >= min_severity.value]
        sc, kc = Counter(s.severity for s in flt), Counter(s.kind for s in flt)
        return [
            "── RefactorAgent Summary ──",
            f"  Files scanned: {len(self._renamer._trees)}",
            f"  Suggestions:   {len(flt)} total",
            "  By severity:",
        ] + [f"    {s.name:<10} {sc[s]}" for s in Severity if sc[s]] + [
            "  By kind:",
        ] + [f"    {k.name:<18} {kc[k]}" for k in RefactorKind if kc[k]]

    def report(self, suggestions: list[RefactorSuggestion],
               *, min_severity: Severity = Severity.INFO,
               max_items: int = 50) -> str:
        flt = [s for s in suggestions if s.severity.value >= min_severity.value]
        parts = self.summarize(flt, min_severity=min_severity)
        parts += ["", "── Top suggestions ──"]
        parts += [f"\n{i + 1}. {s}" for i, s in enumerate(flt[:max_items])]
        return "\n".join(parts)

    def analyze_file(self, file_path: Path) -> list[RefactorSuggestion]:
        if not self._scanned:
            self.scan()
        ek = self.config["enabled_kinds"]
        suggestions: list[RefactorSuggestion] = []
        try:
            source = _read_source(file_path)
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, SyntaxError):
            return suggestions
        if ek.get(RefactorKind.COMPLEXITY, False):
            for report in self._complexity._analyze_tree(tree, file_path):
                suggestions.extend(self._complexity.suggest(report))
        if ek.get(RefactorKind.EXTRACT_METHOD, False):
            suggestions.extend(self._extractor._detect_in_tree(tree, file_path, source))
        return suggestions
