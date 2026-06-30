#!/usr/bin/env python3
"""Auto test generation + coverage analysis + mutation testing.

Provides a pure-stdlib toolkit for:
  1. Analyzing Python source code and generating unit tests (pytest/unittest).
  2. Parsing coverage reports to find uncovered branches.
  3. Prioritizing functions by risk for test ordering.
  4. Performing mutation testing to verify test quality.

Typical usage::

    python -m src.core.test_generator analyze mymodule.py
    python -m src.core.test_generator generate mymodule.py --format pytest
    python -m src.core.test_generator coverage coverage.xml
    python -m src.core.test_generator mutate mymodule.py pytest

Zero pip dependencies — uses only Python stdlib.
"""

from __future__ import annotations

import ast
import enum
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import traceback
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

# ============================================================================
# Enums
# ============================================================================


class TestFormat(enum.Enum):
    """Supported unit test framework formats."""
    PYTEST = "pytest"
    UNITTEST = "unittest"


class RiskLevel(enum.IntEnum):
    """Risk severity for test prioritization (higher = riskier)."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class MutationKind(enum.Enum):
    """Kinds of mutations to apply during mutation testing."""
    ARITHMETIC_OP = "arithmetic_op"
    COMPARISON_OP = "comparison_op"
    LOGICAL_OP = "logical_op"
    DELETE_LINE = "delete_line"
    CONSTANT_MUTATE = "constant_mutate"
    CONDITION_INVERT = "condition_invert"
    RETURN_MUTATE = "return_mutate"
    BOUNDARY_SHIFT = "boundary_shift"


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class FunctionInfo:
    """Metadata extracted from a Python function via AST analysis.

    Attributes:
        name: Function name.
        lineno: Starting line number in source.
        end_lineno: Ending line number (approximate).
        args: Ordered parameter names.
        defaults: Mapping of parameter name → default value AST node.
        annotations: Mapping of parameter name → type annotation string.
        return_annotation: Return type annotation string (or empty).
        is_async: True if this is an async function.
        is_method: True if first parameter is 'self' or 'cls'.
        docstring: Function docstring (or empty string).
        decorators: List of decorator name strings.
        source: Full source code of the function body.
        complexity: Cyclomatic complexity score (McCabe).
        raises: Set of exception names found in raise statements.
        dependencies: Set of names this function references globally.
    """
    name: str
    lineno: int
    end_lineno: int = 0
    args: List[str] = field(default_factory=list)
    defaults: Dict[str, Optional[ast.expr]] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    return_annotation: str = ""
    is_async: bool = False
    is_method: bool = False
    docstring: str = ""
    decorators: List[str] = field(default_factory=list)
    source: str = ""
    complexity: int = 1
    raises: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)


@dataclass
class TestCase:
    """A single auto-generated test case.

    Attributes:
        name: Suggested test function name.
        description: Human-readable description of what is tested.
        code: Full test function body (Python source code).
        format: Whether this test targets pytest or unittest.
        tags: Keywords for categorization (happy_path, boundary, exception).
        function_name: Name of the function under test.
        priority: Higher number = run earlier.
    """
    name: str
    description: str
    code: str
    format: TestFormat = TestFormat.PYTEST
    tags: List[str] = field(default_factory=list)
    function_name: str = ""
    priority: int = 0


@dataclass
class CoverageResult:
    """Coverage information for a single source file.

    Attributes:
        filename: Relative path to the source file.
        line_rate: Fraction of lines covered (0.0–1.0).
        branch_rate: Fraction of branches covered (0.0–1.0).
        uncovered_lines: Sorted list of uncovered line numbers.
        uncovered_branches: List of (line, branch_description) tuples.
        covered_lines: Total number of covered lines.
        total_lines: Total number of executable lines.
    """
    filename: str
    line_rate: float = 0.0
    branch_rate: float = 0.0
    uncovered_lines: List[int] = field(default_factory=list)
    uncovered_branches: List[Tuple[int, str]] = field(default_factory=list)
    covered_lines: int = 0
    total_lines: int = 0

    @property
    def coverage_pct(self) -> float:
        """Coverage percentage (0–100)."""
        return round(self.line_rate * 100, 2)


@dataclass
class MutationResult:
    """Outcome of a single mutation test.

    Attributes:
        mutation_kind: Type of mutation applied.
        original_line: The line number that was mutated.
        original_code: The original line(s) of code.
        mutated_code: The mutated line(s) of code.
        test_passed: True if tests passed (bad — mutation undetected).
        test_output: Captured stdout/stderr from the test run.
        killed: True if at least one test failed (good — mutation detected).
    """
    mutation_kind: MutationKind
    original_line: int
    original_code: str
    mutated_code: str
    test_passed: bool = False
    test_output: str = ""
    killed: bool = False


@dataclass
class RiskProfile:
    """Risk assessment for a single function.

    Attributes:
        function_name: Name of the function.
        complexity: Cyclomatic complexity score.
        coupling: Number of external dependencies.
        churn: Estimated change frequency (0 if unknown).
        risk_score: Composite risk score (higher = riskier).
        risk_level: Categorical risk level.
        reasons: Human-readable reasons for this risk level.
    """
    function_name: str
    complexity: int = 1
    coupling: int = 0
    churn: int = 0
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    reasons: List[str] = field(default_factory=list)


# ============================================================================
# AST helpers
# ============================================================================


def _compute_cyclomatic_complexity(tree: ast.AST) -> int:
    """Compute McCabe cyclomatic complexity of an AST node."""
    complexity = 1

    class V(ast.NodeVisitor):
        def visit_If(self, n):
            nonlocal complexity; complexity += 1; self.generic_visit(n)
        def visit_While(self, n):
            nonlocal complexity; complexity += 1; self.generic_visit(n)
        def visit_For(self, n):
            nonlocal complexity; complexity += 1; self.generic_visit(n)
        def visit_ExceptHandler(self, n):
            nonlocal complexity; complexity += 1; self.generic_visit(n)
        def visit_BoolOp(self, n):
            nonlocal complexity; complexity += len(n.values) - 1; self.generic_visit(n)
        def visit_IfExp(self, n):
            nonlocal complexity; complexity += 1; self.generic_visit(n)

    V().visit(tree)
    return complexity


def _collect_raises(tree: ast.AST) -> Set[str]:
    """Collect exception names raised in an AST subtree."""
    raises: Set[str] = set()

    class C(ast.NodeVisitor):
        def visit_Raise(self, n):
            if n.exc:
                if isinstance(n.exc, ast.Call) and isinstance(n.exc.func, ast.Name):
                    raises.add(n.exc.func.id)
                elif isinstance(n.exc, ast.Name):
                    raises.add(n.exc.id)
            self.generic_visit(n)

    C().visit(tree)
    return raises


def _collect_dependencies(tree: ast.AST) -> Set[str]:
    """Collect externally-referenced names (not locals, not builtins)."""
    local_names: Set[str] = set()
    dep_names: Set[str] = set()

    class D(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            local_names.add(n.name)
            for a in n.args.args:
                local_names.add(a.arg)
            self.generic_visit(n)

        def visit_AsyncFunctionDef(self, n):
            local_names.add(n.name)
            for a in n.args.args:
                local_names.add(a.arg)
            self.generic_visit(n)

        def visit_Name(self, n):
            if isinstance(n.ctx, ast.Load) and n.id not in local_names:
                if not n.id.startswith("_"):
                    dep_names.add(n.id)
            self.generic_visit(n)

        def visit_Attribute(self, n):
            if isinstance(n.value, ast.Name):
                dep_names.add(n.value.id)
            self.generic_visit(n)

        def visit_Assign(self, n):
            self.generic_visit(n)
            for t in n.targets:
                for nn in ast.walk(t):
                    if isinstance(nn, ast.Name):
                        local_names.add(nn.id)

    D().visit(tree)
    builtins_set = set(dir(__builtins__))
    return {d for d in dep_names if d not in builtins_set}


def _get_annotation_str(annotation: Optional[ast.expr]) -> str:
    """Convert AST annotation to string (safely)."""
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation) if hasattr(ast, "unparse") else ""
    except Exception:
        return ""


def _get_default_value(default_node: Optional[ast.expr]) -> Any:
    """Evaluate a default value AST node to a Python constant."""
    if default_node is None:
        return None
    try:
        if isinstance(default_node, ast.Constant):
            return default_node.value
        if isinstance(default_node, ast.UnaryOp) and isinstance(default_node.op, ast.USub):
            operand = default_node.operand
            if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                return -operand.value
        return None
    except Exception:
        return None


def _infer_value_from_annotation(annotation_str: str) -> Any:
    """Generate a plausible test value from a type annotation string."""
    mapping: Dict[str, Any] = {
        "int": 42, "float": 3.14, "str": "test", "bool": True,
        "list": [], "List": [], "List[int]": [1, 2, 3],
        "dict": {}, "Dict": {}, "Dict[str, int]": {"key": 1},
        "tuple": (), "Tuple": (), "set": set(), "Set": set(),
        "bytes": b"test", "Any": "test", "None": None, "NoneType": None,
    }
    clean = annotation_str.strip()
    if clean in mapping:
        return mapping[clean]
    if clean.startswith("Optional[") and clean.endswith("]"):
        return _infer_value_from_annotation(clean[9:-1].strip())
    if clean.startswith("Union[") and clean.endswith("]"):
        inner = clean[6:-1].strip()
        for part in _split_union(inner):
            val = _infer_value_from_annotation(part)
            if val is not None:
                return val
    base_match = re.match(r"^Optional\[(.+)]$", clean)
    if base_match:
        return _infer_value_from_annotation(base_match.group(1))
    return None


def _split_union(inner: str) -> List[str]:
    """Split a Union[]/Optional[] inner string on commas, respecting brackets."""
    parts: List[str] = []
    depth, current = 0, []
    for ch in inner:
        if ch == "," and depth == 0:
            parts.append("".join(current).strip()); current = []
        else:
            if ch == "[": depth += 1
            elif ch == "]": depth -= 1
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


# ============================================================================
# TestGenerator
# ============================================================================


class TestGenerator:
    """Analyze Python source code and auto-generate unit tests.

    Supports pytest and unittest output formats. Detects function signatures,
    generates tests for happy paths, boundary conditions, exception paths,
    and parameterized test suites.

    Example::

        gen = TestGenerator(format=TestFormat.PYTEST)
        tests = gen.generate_from_file("mymodule.py")
        for test in tests:
            print(test.code)

    Attributes:
        format: Output test framework format.
        max_tests_per_function: Cap on generated test cases per function.
    """

    def __init__(
        self,
        format: TestFormat = TestFormat.PYTEST,
        max_tests_per_function: int = 20,
    ):
        """Initialize the test generator.

        Args:
            format: Target test framework (pytest or unittest).
            max_tests_per_function: Cap on test cases per function.
        """
        self.format = format
        self.max_tests_per_function = max_tests_per_function

    # ---- public API ----

    def analyze_module(self, source: str) -> List[FunctionInfo]:
        """Parse Python source code and extract function metadata."""
        tree = ast.parse(source)
        funcs: List[FunctionInfo] = []
        for node in ast.iter_child_nodes(tree):
            info = self._extract_function_info(node, source)
            if info:
                funcs.append(info)
        return funcs

    def generate_from_file(self, filepath: Union[str, Path]) -> List[TestCase]:
        """Generate unit tests for all functions in a Python file."""
        p = Path(filepath)
        return self.generate_from_source(p.read_text(encoding="utf-8"), module_name=p.stem)

    def generate_from_source(
        self, source: str, module_name: str = "module"
    ) -> List[TestCase]:
        """Generate unit tests from Python source code."""
        functions = self.analyze_module(source)
        all_tests: List[TestCase] = []
        for func in functions:
            all_tests.extend(self._generate_for_function(func, module_name)[:self.max_tests_per_function])
        return all_tests

    def render_tests(self, tests: List[TestCase], module_import: str = "") -> str:
        """Render a list of TestCases into a complete test file."""
        if self.format == TestFormat.PYTEST:
            return self._render_pytest_file(tests, module_import)
        return self._render_unittest_file(tests, module_import)

    # ---- function extraction ----

    def _extract_function_info(
        self, node: ast.AST, source: str
    ) -> Optional[FunctionInfo]:
        """Extract FunctionInfo from a top-level AST node if it is a function."""
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        if node.name.startswith("_") and not node.name.startswith("__"):
            return None

        args: List[str] = []
        defaults_map: Dict[str, Optional[ast.expr]] = {}
        annotations_map: Dict[str, str] = {}

        for arg in node.args.args:
            args.append(arg.arg)
            annotations_map[arg.arg] = _get_annotation_str(arg.annotation)

        num_defaults = len(node.args.defaults)
        if num_defaults > 0:
            for i, arg_name in enumerate(args[-num_defaults:]):
                defaults_map[arg_name] = node.args.defaults[i]

        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")

        for kwarg, kwdefault in zip(node.args.kwonlyargs, node.args.kw_defaults):
            args.append(kwarg.arg)
            annotations_map[kwarg.arg] = _get_annotation_str(kwarg.annotation)
            if kwdefault is not None:
                defaults_map[kwarg.arg] = kwdefault

        is_method = bool(args) and args[0] in ("self", "cls")
        return_annotation = _get_annotation_str(node.returns)

        end_lineno: int = (
            node.end_lineno
            if hasattr(node, "end_lineno") and node.end_lineno is not None
            else node.lineno
        )

        try:
            func_source = ast.get_source_segment(source, node) or ""
        except Exception:
            func_source = ""

        decorators = [ast.unparse(d) for d in node.decorator_list] if hasattr(ast, "unparse") else []
        docstring = ast.get_docstring(node) or ""

        return FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=end_lineno,
            args=args,
            defaults=defaults_map,
            annotations=annotations_map,
            return_annotation=return_annotation,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=is_method,
            docstring=docstring,
            decorators=decorators,
            source=func_source,
            complexity=_compute_cyclomatic_complexity(node),
            raises=_collect_raises(node),
            dependencies=_collect_dependencies(node),
        )

    # ---- test generation ----

    def _generate_for_function(
        self, func: FunctionInfo, module_name: str
    ) -> List[TestCase]:
        """Generate all test categories for one function."""
        call_args = [a for a in func.args if a not in ("self", "cls") and not a.startswith("*")]
        tests: List[TestCase] = []
        tests.extend(self._generate_happy_path(func, call_args, module_name))
        tests.extend(self._generate_boundary_cases(func, call_args, module_name))
        tests.extend(self._generate_exception_paths(func, call_args, module_name))
        tests.extend(self._generate_parametrized_tests(func, call_args, module_name))
        for t in tests:
            t.function_name = func.name
        return tests

    def _generate_happy_path(
        self, func: FunctionInfo, call_args: List[str], module_name: str
    ) -> List[TestCase]:
        """Generate a happy-path test case."""
        arg_values: Dict[str, Any] = {}
        for arg in call_args:
            val = _infer_value_from_annotation(func.annotations.get(arg, ""))
            if val is None:
                val = 42
            if arg in func.defaults:
                dv = _get_default_value(func.defaults[arg])
                if dv is not None:
                    val = dv
            arg_values[arg] = val

        args_repr = ", ".join(
            f"{k}={repr(v)}" if isinstance(v, str) else f"{k}={v}"
            for k, v in arg_values.items()
        )

        if self.format == TestFormat.PYTEST:
            code = textwrap.dedent(f"""\
                def test_{func.name}_happy_path():
                    \"\"\"Happy path for {func.name}.\"\"\"
                    from {module_name} import {func.name}
                    result = {func.name}({args_repr})
                    assert result is not None, "Expected non-None result"
            """)
        else:
            code = textwrap.dedent(f"""\
                def test_{func.name}_happy_path(self):
                    \"\"\"Happy path for {func.name}.\"\"\"
                    from {module_name} import {func.name}
                    result = {func.name}({args_repr})
                    self.assertIsNotNone(result)
            """)
        return [TestCase(
            name=f"test_{func.name}_happy_path",
            description=f"Happy path for {func.name}",
            code=code, format=self.format, tags=["happy_path"],
        )]

    def _generate_boundary_cases(
        self, func: FunctionInfo, call_args: List[str], module_name: str
    ) -> List[TestCase]:
        """Generate boundary-value test cases."""
        boundary_map: Dict[str, List[Any]] = {
            "int": [0, -1, 1, sys.maxsize, -sys.maxsize],
            "float": [0.0, -1.0, 1.0, float("inf"), float("-inf")],
            "str": ["", " ", "x" * 1024],
            "bool": [True, False],
            "list": [[], [None]],
            "dict": [{}, {"": None}],
        }
        tests: List[TestCase] = []
        if len(call_args) > 2:
            return tests

        for arg in call_args:
            anno = func.annotations.get(arg, "")
            base = re.match(r"^(\w+)", anno.strip())
            typ = base.group(1) if base else "Any"
            for val in boundary_map.get(typ, [None, 0, ""]):
                vals: Dict[str, Any] = {}
                for a in call_args:
                    if a == arg:
                        vals[a] = val
                    elif a in func.defaults:
                        vals[a] = _get_default_value(func.defaults[a])
                    else:
                        vals[a] = _infer_value_from_annotation(func.annotations.get(a, ""))
                args_repr = ", ".join(
                    f"{k}={repr(v)}" if isinstance(v, str) else f"{k}={v}"
                    for k, v in vals.items()
                )
                val_label = repr(val)[:20]
                tag = hashlib.md5(val_label.encode()).hexdigest()[:6]
                if self.format == TestFormat.PYTEST:
                    code = textwrap.dedent(f"""\
                        def test_{func.name}_{arg}_boundary_{tag}():
                            \"\"\"Boundary: {arg}={val_label}.\"\"\"
                            from {module_name} import {func.name}
                            try:
                                result = {func.name}({args_repr})
                            except Exception:
                                pass
                    """)
                else:
                    code = textwrap.dedent(f"""\
                        def test_{func.name}_{arg}_boundary_{tag}(self):
                            \"\"\"Boundary: {arg}={val_label}.\"\"\"
                            from {module_name} import {func.name}
                            try:
                                result = {func.name}({args_repr})
                            except Exception:
                                pass
                    """)
                tests.append(TestCase(
                    name=f"test_{func.name}_{arg}_boundary",
                    description=f"Boundary {arg}={val_label}",
                    code=code, format=self.format, tags=["boundary"],
                ))
            if len(tests) >= self.max_tests_per_function:
                break
        return tests

    def _generate_exception_paths(
        self, func: FunctionInfo, call_args: List[str], module_name: str
    ) -> List[TestCase]:
        """Generate tests for expected exceptions."""
        tests: List[TestCase] = []
        # If function declares raises, generate explicit exception tests
        # Build a call expression that includes args if the function has required params
        arg_str = ", ".join(call_args) if call_args else ""
        if func.raises:
            for exc in sorted(func.raises):
                if self.format == TestFormat.PYTEST:
                    code = textwrap.dedent(f"""\
                        def test_{func.name}_raises_{exc}():
                            \"\"\"Verify {func.name} raises {exc}.\"\"\"
                            from {module_name} import {func.name}
                            import pytest
                            with pytest.raises({exc}):
                                {func.name}({arg_str})
                    """)
                else:
                    code = textwrap.dedent(f"""\
                        def test_{func.name}_raises_{exc}(self):
                            \"\"\"Verify {func.name} raises {exc}.\"\"\"
                            from {module_name} import {func.name}
                            with self.assertRaises({exc}):
                                {func.name}({arg_str})
                    """)
                tests.append(TestCase(
                    name=f"test_{func.name}_raises_{exc}",
                    description=f"Exception test for {func.name}: {exc}",
                    code=code, format=self.format, tags=["exception"],
                ))
        else:
            # Generate a generic invalid-type test
            for arg in call_args:
                anno = func.annotations.get(arg, "")
                if anno and "int" in anno:
                    vals: Dict[str, str] = {}
                    for a in call_args:
                        vals[a] = "'not_an_int'" if a == arg else "None"
                    args_repr = ", ".join(f"{k}={v}" for k, v in vals.items())
                    if self.format == TestFormat.PYTEST:
                        code = textwrap.dedent(f"""\
                            def test_{func.name}_{arg}_invalid_type():
                                \"\"\"Verify {func.name} rejects invalid '{arg}' type.\"\"\"
                                from {module_name} import {func.name}
                                import pytest
                                with pytest.raises((TypeError, ValueError)):
                                    {func.name}({args_repr})
                        """)
                    else:
                        code = textwrap.dedent(f"""\
                            def test_{func.name}_{arg}_invalid_type(self):
                                \"\"\"Verify {func.name} rejects invalid '{arg}' type.\"\"\"
                                from {module_name} import {func.name}
                                with self.assertRaises((TypeError, ValueError)):
                                    {func.name}({args_repr})
                        """)
                    tests.append(TestCase(
                        name=f"test_{func.name}_{arg}_invalid_type",
                        description=f"Exception test: invalid {arg} type",
                        code=code, format=self.format, tags=["exception"],
                    ))
                    break
        return tests

    def _generate_parametrized_tests(
        self, func: FunctionInfo, call_args: List[str], module_name: str
    ) -> List[TestCase]:
        """Generate parametrized test cases."""
        if not call_args or len(call_args) > 3:
            return []

        if len(call_args) == 1:
            param_sets = [[0], [1], [10], [-5], [100]]
        elif len(call_args) == 2:
            param_sets = [[0, 0], [1, 1], [10, -5], [-3, 7], [0, 100]]
        else:
            param_sets = [[0, 0, 0], [1, 2, 3], [-1, -2, -3], [10, 0, -10]]

        code = textwrap.dedent(f"""\
            import pytest
            from {module_name} import {func.name}

            @pytest.mark.parametrize("args", {json.dumps(param_sets)})
            def test_{func.name}_parametrized(args):
                \"\"\"Parametrized test for {func.name}.\"\"\"
                result = {func.name}(*args)
                assert result is not None, f"Expected non-None result for {{args}}"
        """)
        return [TestCase(
            name=f"test_{func.name}_parametrized",
            description=f"Parametrized test for {func.name}",
            code=code, format=self.format, tags=["parametrized"],
        )]

    # ---- rendering ----

    def _render_pytest_file(self, tests: List[TestCase], module_import: str) -> str:
        """Render tests as a complete pytest file."""
        lines = ['"""Auto-generated tests.\n\nGenerated by test_generator.py\n"""', "import pytest"]
        if module_import:
            lines.append(f"import {module_import}")
        lines.append("\n")
        for t in tests:
            lines.append(t.code.strip() + "\n")
        return "\n".join(lines)

    def _render_unittest_file(self, tests: List[TestCase], module_import: str) -> str:
        """Render tests as a complete unittest file."""
        lines = ['"""Auto-generated tests.\n\nGenerated by test_generator.py\n"""', "import unittest"]
        if module_import:
            lines.append(f"import {module_import}")
        lines.append(f"\n\nclass Test{module_import.capitalize() if module_import else 'Module'}(unittest.TestCase):")
        if module_import:
            lines.append(f'    """Auto-generated test cases for {module_import}."""')
        lines.append("")
        for t in tests:
            lines.append(textwrap.indent(t.code.strip(), "    ") + "\n")
        lines.append('\nif __name__ == "__main__":\n    unittest.main()\n')
        return "\n".join(lines)


# ============================================================================
# CoverageAnalyzer
# ============================================================================


class CoverageAnalyzer:
    """Parse coverage report files and identify uncovered code.

    Supports coverage.py XML, JSON, and LCOV tracefile formats.
    Can also invoke ``coverage`` directly if installed.

    Example::

        analyzer = CoverageAnalyzer()
        results = analyzer.parse_file("coverage.xml")
        for r in results:
            print(f"{r.filename}: {r.coverage_pct}%")

    Attributes:
        strict: If True, raise on parse errors.
    """

    def __init__(self, strict: bool = False):
        """Initialize the coverage analyzer.

        Args:
            strict: When True, raise exceptions on parse failures.
        """
        self.strict = strict

    def parse_file(self, filepath: Union[str, Path]) -> List[CoverageResult]:
        """Parse a coverage report file, auto-detecting format."""
        p = Path(filepath)
        if not p.exists():
            if self.strict:
                raise FileNotFoundError(f"Coverage file not found: {filepath}")
            return []
        suffix = p.suffix.lower()
        if suffix == ".xml":
            return self.parse_xml(p)
        elif suffix == ".json":
            return self.parse_json(p)
        elif suffix in (".lcov", ".info"):
            return self.parse_lcov(p)
        # Auto-detect from content
        content = p.read_text(encoding="utf-8").strip()
        if content.startswith("<?xml") or content.startswith("<coverage"):
            return self.parse_xml(p)
        if content.startswith("{"):
            return self.parse_json(p)
        if content.startswith("SF:"):
            return self.parse_lcov(p)
        if self.strict:
            raise ValueError(f"Unknown format: {filepath}")
        return []

    def parse_xml(self, filepath: Union[str, Path]) -> List[CoverageResult]:
        """Parse a coverage.py XML report."""
        results: List[CoverageResult] = []
        try:
            tree = ET.parse(str(filepath))
            root = tree.getroot()
            for elem in root.findall(".//package") or root.findall(".//class"):
                filename = elem.get("filename", elem.get("name", ""))
                if not filename:
                    continue
                r = CoverageResult(filename=filename)
                lr = elem.get("line-rate")
                if lr is not None:
                    r.line_rate = float(lr)
                br = elem.get("branch-rate")
                if br is not None:
                    r.branch_rate = float(br)
                for line_elem in elem.findall(".//line"):
                    lineno_str = line_elem.get("number")
                    if lineno_str is None:
                        continue
                    lineno = int(lineno_str)
                    r.total_lines += 1
                    try:
                        hits = int(line_elem.get("hits", "1"))
                    except (ValueError, TypeError):
                        hits = 0
                    if hits > 0:
                        r.covered_lines += 1
                    else:
                        r.uncovered_lines.append(lineno)
                    if line_elem.get("branch") == "true":
                        cond = line_elem.get("condition-coverage", "")
                        r.uncovered_branches.append((lineno, cond))
                r.uncovered_lines.sort()
                results.append(r)
        except (ET.ParseError, Exception):
            if self.strict:
                raise
        return results

    def parse_json(self, filepath: Union[str, Path]) -> List[CoverageResult]:
        """Parse a coverage.py JSON report."""
        results: List[CoverageResult] = []
        try:
            with open(str(filepath), encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            if self.strict:
                raise
            return results
        for filename, fd in data.get("files", {}).items():
            r = CoverageResult(filename=filename)
            summary = fd.get("summary", {})
            r.covered_lines = summary.get("covered_lines", 0)
            r.total_lines = summary.get("num_statements", 0)
            if r.total_lines > 0:
                r.line_rate = r.covered_lines / r.total_lines
            r.uncovered_lines = sorted(fd.get("missing_lines", []))
            for mb in fd.get("missing_branches", []):
                if isinstance(mb, list) and len(mb) >= 2:
                    r.uncovered_branches.append((mb[0], str(mb[1:])))
                elif isinstance(mb, int):
                    r.uncovered_branches.append((mb, "branch not taken"))
            results.append(r)
        return results

    def parse_lcov(self, filepath: Union[str, Path]) -> List[CoverageResult]:
        """Parse an LCOV tracefile."""
        results: List[CoverageResult] = []
        current: Optional[CoverageResult] = None
        try:
            with open(str(filepath), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SF:"):
                        current = CoverageResult(filename=line[3:])
                        results.append(current)
                    elif current is None:
                        continue
                    elif line.startswith("DA:"):
                        parts = line[3:].split(",")
                        if len(parts) >= 2:
                            lineno, hits = int(parts[0]), int(parts[1])
                            current.total_lines += 1
                            if hits > 0:
                                current.covered_lines += 1
                            else:
                                current.uncovered_lines.append(lineno)
                    elif line.startswith("BRDA:"):
                        parts = line[5:].split(",")
                        if len(parts) >= 4:
                            lineno = int(parts[0])
                            if int(parts[3]) == 0:
                                current.uncovered_branches.append((lineno, f"branch {parts[2]}"))
                    elif line.startswith("LF:"):
                        current.total_lines = int(line[3:])
                    elif line.startswith("LH:"):
                        current.covered_lines = int(line[3:])
                    elif line.startswith("end_of_record"):
                        if current and current.total_lines > 0:
                            current.line_rate = current.covered_lines / current.total_lines
                        current = None
        except OSError:
            if self.strict:
                raise
        for r in results:
            r.uncovered_lines.sort()
        return results

    def find_uncovered_branches(
        self, results: List[CoverageResult]
    ) -> Dict[str, List[Tuple[int, str]]]:
        """Extract uncovered branches from coverage results."""
        uncovered: Dict[str, List[Tuple[int, str]]] = {}
        for r in results:
            if r.uncovered_branches:
                uncovered[r.filename] = r.uncovered_branches
        return uncovered

    def generate_report(self, results: List[CoverageResult]) -> str:
        """Generate a human-readable coverage report."""
        lines = ["=" * 60, "COVERAGE ANALYSIS REPORT", "=" * 60, ""]
        total_cov = sum(r.covered_lines for r in results)
        total_lines = sum(r.total_lines for r in results)
        overall = (total_cov / total_lines * 100) if total_lines > 0 else 0.0
        lines.append(f"Overall line coverage: {overall:.1f}%")
        lines.append(f"Total files analyzed: {len(results)}\n")
        for r in sorted(results, key=lambda x: x.line_rate):
            icon = "✅" if r.line_rate >= 0.8 else ("⚠️" if r.line_rate >= 0.6 else "❌")
            lines.append(f"  {icon} {r.filename}: {r.coverage_pct}% ({r.covered_lines}/{r.total_lines})")
            if r.uncovered_lines:
                preview = r.uncovered_lines[:20]
                lines.append(f"     Uncovered lines: {preview}" + (" ..." if len(r.uncovered_lines) > 20 else ""))
            if r.uncovered_branches:
                lines.append(f"     Uncovered branches: {len(r.uncovered_branches)}")
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def run_coverage(
        self, test_command: Union[str, List[str]], source_dir: Union[str, Path] = "."
    ) -> List[CoverageResult]:
        """Run coverage.py and parse results. Requires 'coverage' installed."""
        source_dir = Path(source_dir)
        try:
            rc = textwrap.dedent(f"""\
                [run]
                source = {source_dir.resolve()}
                [report]
                show_missing = True
            """)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".coveragerc", delete=False) as tmp:
                tmp.write(rc)
                rc_path = tmp.name
            if isinstance(test_command, str):
                test_command = test_command.split()
            subprocess.run(["coverage", "run", f"--rcfile={rc_path}"] + test_command,
                           check=True, capture_output=True, text=True)
            json_path = source_dir / ".coverage.json"
            subprocess.run(["coverage", "json", f"--rcfile={rc_path}", "-o", str(json_path)],
                           check=True, capture_output=True, text=True)
            results = self.parse_json(json_path)
            Path(rc_path).unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)
            return results
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            if self.strict:
                raise RuntimeError(f"Coverage run failed: {e}")
            return []


# ============================================================================
# TestPrioritizer
# ============================================================================


class TestPrioritizer:
    """Rank functions by risk to determine testing priority.

    Risk is computed from cyclomatic complexity, coupling (external deps),
    and churn (change frequency). Higher scores = test first.

    Example::

        prioritizer = TestPrioritizer()
        prioritized = prioritizer.prioritize(functions)
        for func, risk in prioritized:
            print(f"{func.name}: {risk.risk_level.name} ({risk.risk_score})")

    Attributes:
        complexity_weight: Weight for complexity in risk score.
        coupling_weight: Weight for coupling in risk score.
        churn_weight: Weight for churn in risk score.
    """

    def __init__(
        self,
        complexity_weight: float = 0.5,
        coupling_weight: float = 0.3,
        churn_weight: float = 0.2,
    ):
        """Initialize the prioritizer.

        Args:
            complexity_weight: Cyclomatic complexity weight (default 0.5).
            coupling_weight: Dependency count weight (default 0.3).
            churn_weight: Change frequency weight (default 0.2).
        """
        self.complexity_weight = complexity_weight
        self.coupling_weight = coupling_weight
        self.churn_weight = churn_weight

    def prioritize(
        self, functions: List[FunctionInfo]
    ) -> List[Tuple[FunctionInfo, RiskProfile]]:
        """Rank functions from highest to lowest risk."""
        profiles = [(f, self.analyze_risk(f)) for f in functions]
        profiles.sort(key=lambda x: (x[1].risk_level.value, x[1].risk_score), reverse=True)
        return profiles

    def analyze_risk(self, func: FunctionInfo) -> RiskProfile:
        """Compute a risk profile for a single function."""
        complexity = func.complexity
        coupling = len(func.dependencies)
        churn = 0  # placeholder — integrate with git in practice

        norm_c = min(complexity / 10.0, 1.0)
        norm_d = min(coupling / 5.0, 1.0)
        norm_h = min(churn / 10.0, 1.0)

        risk_score = (
            self.complexity_weight * norm_c
            + self.coupling_weight * norm_d
            + self.churn_weight * norm_h
        )

        if risk_score >= 0.75:
            level = RiskLevel.CRITICAL
        elif risk_score >= 0.5:
            level = RiskLevel.HIGH
        elif risk_score >= 0.25:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        reasons: List[str] = []
        if complexity >= 10:
            reasons.append(f"High complexity ({complexity})")
        elif complexity >= 5:
            reasons.append(f"Moderate complexity ({complexity})")
        if coupling >= 5:
            reasons.append(f"High coupling ({coupling} deps)")
        if func.raises:
            reasons.append(f"Raises: {', '.join(sorted(func.raises))}")
        if not reasons:
            reasons.append("Low risk")

        return RiskProfile(
            function_name=func.name,
            complexity=complexity,
            coupling=coupling,
            churn=churn,
            risk_score=round(risk_score, 4),
            risk_level=level,
            reasons=reasons,
        )

    def generate_priority_report(
        self, prioritized: List[Tuple[FunctionInfo, RiskProfile]]
    ) -> str:
        """Generate a human-readable prioritization report."""
        lines = ["=" * 60, "TEST PRIORITIZATION REPORT", "=" * 60, ""]
        icons = {RiskLevel.CRITICAL: "🔴", RiskLevel.HIGH: "🟠",
                 RiskLevel.MEDIUM: "🟡", RiskLevel.LOW: "🟢"}
        for func, risk in prioritized:
            lines.append(f"  {icons[risk.risk_level]} {func.name} — {risk.risk_level.name} (score: {risk.risk_score})")
            for reason in risk.reasons:
                lines.append(f"     • {reason}")
            lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)


# ============================================================================
# MutationTester
# ============================================================================


# Operator string lookups (module-level constants)
_ARITHMETIC_SWAPS: Dict[type, List[Tuple[type, str]]] = {
    ast.Add: [(ast.Sub, "-"), (ast.Mult, "*"), (ast.Div, "/")],
    ast.Sub: [(ast.Add, "+"), (ast.Mult, "*")],
    ast.Mult: [(ast.Add, "+"), (ast.Div, "/"), (ast.Pow, "**")],
    ast.Div: [(ast.Mult, "*"), (ast.FloorDiv, "//")],
    ast.FloorDiv: [(ast.Div, "/")],
    ast.Mod: [(ast.Mult, "*"), (ast.Add, "+")],
    ast.Pow: [(ast.Mult, "*")],
}

_COMPARISON_SWAPS: Dict[type, List[Tuple[type, str]]] = {
    ast.Eq: [(ast.NotEq, "!=")],
    ast.NotEq: [(ast.Eq, "==")],
    ast.Lt: [(ast.Gt, ">"), (ast.LtE, "<=")],
    ast.Gt: [(ast.Lt, "<"), (ast.GtE, ">=")],
    ast.LtE: [(ast.Lt, "<"), (ast.GtE, ">=")],
    ast.GtE: [(ast.Gt, ">"), (ast.LtE, "<=")],
}

_OP_STRINGS: Dict[type, str] = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
}

_CMP_STRINGS: Dict[type, str] = {
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.Gt: ">",
    ast.LtE: "<=", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
    ast.In: "in", ast.NotIn: "not in",
}


class MutationTester:
    """Simple mutation testing to verify test suite effectiveness.

    Generates mutants by applying small transformations (changing operators,
    deleting lines, flipping conditions) and runs tests against each mutant.
    If tests still pass, the mutant "survived" — indicating a testing gap.

    Example::

        tester = MutationTester()
        results = tester.run(
            source="mymodule.py",
            test_command="pytest tests/",
            kinds=[MutationKind.ARITHMETIC_OP],
        )
        print(f"Mutation score: {tester.mutation_score(results):.1%}")

    Attributes:
        timeout: Seconds allowed per test run.
        max_mutants: Maximum number of mutants to generate.
    """

    def __init__(self, timeout: int = 30, max_mutants: int = 50):
        """Initialize the mutation tester.

        Args:
            timeout: Per-test timeout in seconds.
            max_mutants: Cap on generated mutants.
        """
        self.timeout = timeout
        self.max_mutants = max_mutants

    def mutation_score(self, results: List[MutationResult]) -> float:
        """Compute mutation score: fraction of mutants killed."""
        if not results:
            return 1.0
        return sum(1 for r in results if r.killed) / len(results)

    def generate_mutants(
        self, source: str, kinds: Optional[Sequence[MutationKind]] = None,
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Generate source-code mutants from a source string.

        Returns list of (mutated_source, kind, lineno, original_line, mutated_line).
        """
        if kinds is None:
            kinds = list(MutationKind)
        src_lines = source.splitlines(keepends=True)
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []

        generators = {
            MutationKind.ARITHMETIC_OP: self._mutate_arithmetic,
            MutationKind.COMPARISON_OP: self._mutate_comparison,
            MutationKind.LOGICAL_OP: self._mutate_logical,
            MutationKind.CONDITION_INVERT: self._mutate_condition_invert,
            MutationKind.CONSTANT_MUTATE: self._mutate_constants,
            MutationKind.DELETE_LINE: self._mutate_delete_line,
            MutationKind.RETURN_MUTATE: self._mutate_return,
            MutationKind.BOUNDARY_SHIFT: self._mutate_boundary_shift,
        }

        for kind in kinds:
            if kind in generators:
                mutants.extend(generators[kind](source, src_lines))
            if len(mutants) >= self.max_mutants:
                break

        return mutants[:self.max_mutants]

    def run(
        self,
        source: str,
        test_command: Union[str, List[str]],
        kinds: Optional[Sequence[MutationKind]] = None,
        work_dir: Optional[Union[str, Path]] = None,
    ) -> List[MutationResult]:
        """Generate mutants and run tests against each one.

        Args:
            source: Python source code string or path to a .py file.
            test_command: Shell command to run tests (e.g., 'pytest -x').
            kinds: Mutation kinds to apply (all if None).
            work_dir: Working directory for test execution.

        Returns:
            List of MutationResult objects.
        """
        source_path: Optional[Path] = None
        if "\n" not in source and Path(source).is_file():
            source_path = Path(source)
            source = source_path.read_text(encoding="utf-8")
        if work_dir is None and source_path:
            work_dir = source_path.parent

        mutants = self.generate_mutants(source, kinds)
        results: List[MutationResult] = []
        for mut_src, kind, lineno, orig, mutd in mutants:
            results.append(self._run_single(mut_src, kind, lineno, orig, mutd,
                                            test_command, work_dir))
        return results

    # ---- mutation generators ----

    def _mutate_arithmetic(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Mutate arithmetic operators."""
        return self._mutate_binop(source, src_lines, _ARITHMETIC_SWAPS, MutationKind.ARITHMETIC_OP)

    def _mutate_comparison(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Mutate comparison operators."""
        return self._mutate_compare(source, src_lines, _COMPARISON_SWAPS, MutationKind.COMPARISON_OP)

    def _mutate_logical(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Mutate logical operators (and ↔ or)."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        for i, line in enumerate(src_lines):
            if len(mutants) >= self.max_mutants // 2:
                break
            lineno = i + 1
            if re.search(r'\band\b', line):
                new_line = re.sub(r'\band\b', 'or', line, count=1)
            elif re.search(r'\bor\b', line):
                new_line = re.sub(r'\bor\b', 'and', line, count=1)
            else:
                continue
            mutant = "".join(src_lines[:i] + [new_line] + src_lines[i+1:])
            mutants.append((mutant, MutationKind.LOGICAL_OP, lineno, line.rstrip(), new_line.rstrip()))
        return mutants

    def _mutate_condition_invert(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Invert if/while conditions."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return mutants

        class Inverter(ast.NodeVisitor):
            def __init__(self, s, sl, coll, mx):
                self.s = s; self.sl = sl; self.coll = coll; self.mx = mx; self.n = 0
            def visit_If(self, node):
                if self.n >= self.mx:
                    return
                ts = ast.get_source_segment(self.s, node.test)
                if not ts:
                    return
                inv = f"not ({ts})"
                old = self.sl[node.lineno - 1]
                new = old.replace(ts, inv, 1)
                if new != old:
                    mutant = "".join(self.sl[:node.lineno-1] + [new] + self.sl[node.lineno:])
                    self.n += 1
                    self.coll.append((mutant, MutationKind.CONDITION_INVERT, node.lineno, old.rstrip(), new.rstrip()))

        coll: list = []
        Inverter(source, src_lines, coll, self.max_mutants // 2).visit(tree)
        return coll

    def _mutate_constants(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Mutate numeric constants."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return mutants

        class ConstMut(ast.NodeVisitor):
            def __init__(self, s, sl, coll, mx):
                self.s = s; self.sl = sl; self.coll = coll; self.mx = mx; self.n = 0
            def visit_Constant(self, node):
                if self.n >= self.mx:
                    return
                if isinstance(node.value, (int, float)):
                    old_val = str(node.value)
                    new_val = "1" if node.value == 0 else ("0" if isinstance(node.value, int) else "0.0")
                    old = self.sl[node.lineno - 1]
                    # Use regex with digit boundaries to avoid substring mismatches
                    # e.g. replacing "0" in "x = 10" should NOT match
                    escaped = re.escape(old_val)
                    new = re.sub(rf"(?<![\d.]){escaped}(?![\d.])", new_val, old, count=1)
                    if new != old:
                        mutant = "".join(self.sl[:node.lineno-1] + [new] + self.sl[node.lineno:])
                        self.n += 1
                        self.coll.append((mutant, MutationKind.CONSTANT_MUTATE, node.lineno, old.rstrip(), new.rstrip()))
                self.generic_visit(node)

        coll: list = []
        ConstMut(source, src_lines, coll, self.max_mutants).visit(tree)
        return coll

    def _mutate_delete_line(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Remove non-essential lines one at a time."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        for i, line in enumerate(src_lines):
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(("def ", "class ", "@", "import ", "from ")):
                continue
            if s.startswith(('"""', "'''")) or s in ("return", "pass", "..."):
                continue
            mutant = "".join(src_lines[:i] + src_lines[i+1:])
            mutants.append((mutant, MutationKind.DELETE_LINE, i + 1, line.rstrip(), "<DELETED>"))
            if len(mutants) >= self.max_mutants:
                break
        return mutants

    def _mutate_return(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Mutate return statements to return None."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return mutants

        class RetMut(ast.NodeVisitor):
            def __init__(self, s, sl, coll, mx):
                self.s = s; self.sl = sl; self.coll = coll; self.mx = mx; self.n = 0
            def visit_Return(self, node):
                if self.n >= self.mx:
                    return
                if node.value is not None:
                    vs = ast.get_source_segment(self.s, node.value)
                    if vs:
                        old = self.sl[node.lineno - 1]
                        new = old.replace(vs, "None", 1)
                        if new != old:
                            mutant = "".join(self.sl[:node.lineno-1] + [new] + self.sl[node.lineno:])
                            self.n += 1
                            self.coll.append((mutant, MutationKind.RETURN_MUTATE, node.lineno, old.rstrip(), new.rstrip()))
                self.generic_visit(node)

        coll: list = []
        RetMut(source, src_lines, coll, self.max_mutants).visit(tree)
        return coll

    def _mutate_boundary_shift(
        self, source: str, src_lines: List[str]
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Shift boundary comparisons (>0 → >=0, etc.)."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        patterns = [
            (r"(\b\w+\s*)>\s*(\d+)", r"\1>= \2"),
            (r"(\b\w+\s*)<\s*(\d+)", r"\1<= \2"),
            (r"(\b\w+\s*)>=\s*(\d+)", r"\1> \2"),
            (r"(\b\w+\s*)<=\s*(\d+)", r"\1< \2"),
        ]
        for i, line in enumerate(src_lines):
            for pat, rep in patterns:
                new_line = re.sub(pat, rep, line)
                if new_line != line:
                    mutant = "".join(src_lines[:i] + [new_line] + src_lines[i+1:])
                    mutants.append((mutant, MutationKind.BOUNDARY_SHIFT, i + 1, line.rstrip(), new_line.rstrip()))
                    if len(mutants) >= self.max_mutants:
                        return mutants
                    break
        return mutants

    # ---- generic AST-based mutators ----

    def _mutate_binop(
        self, source: str, src_lines: List[str],
        swap_map: Dict, kind: MutationKind,
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Generic BinOp mutator."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return mutants

        class Mut(ast.NodeVisitor):
            def __init__(self, s, sl, coll, sw, k, mx):
                self.s = s; self.sl = sl; self.coll = coll; self.sw = sw; self.k = k; self.mx = mx; self.n = 0
            def visit_BinOp(self, node):
                if self.n >= self.mx:
                    return
                op_type = type(node.op)
                if op_type in self.sw:
                    seg = ast.get_source_segment(self.s, node)
                    if not seg:
                        return
                    old_op = _OP_STRINGS.get(op_type, "")
                    for _, new_op_s in self.sw[op_type]:
                        new_seg = seg.replace(old_op, new_op_s, 1)
                        if new_seg != seg:
                            old_line = self.sl[node.lineno - 1]
                            new_line = old_line.replace(seg, new_seg, 1)
                            if new_line != old_line:
                                mutant = "".join(self.sl[:node.lineno-1] + [new_line] + self.sl[node.lineno:])
                                self.n += 1
                                self.coll.append((mutant, self.k, node.lineno, old_line.rstrip(), new_line.rstrip()))
                                break
                self.generic_visit(node)

        coll: list = []
        Mut(source, src_lines, coll, swap_map, kind, self.max_mutants).visit(tree)
        return coll

    def _mutate_compare(
        self, source: str, src_lines: List[str],
        swap_map: Dict, kind: MutationKind,
    ) -> List[Tuple[str, MutationKind, int, str, str]]:
        """Generic Compare mutator."""
        mutants: List[Tuple[str, MutationKind, int, str, str]] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return mutants

        class Mut(ast.NodeVisitor):
            def __init__(self, s, sl, coll, sw, k, mx):
                self.s = s; self.sl = sl; self.coll = coll; self.sw = sw; self.k = k; self.mx = mx; self.n = 0
            def visit_Compare(self, node):
                if self.n >= self.mx:
                    return
                for op in node.ops:
                    op_type = type(op)
                    if op_type in self.sw:
                        seg = ast.get_source_segment(self.s, node)
                        if not seg:
                            continue
                        old_op = _CMP_STRINGS.get(op_type, "")
                        for _, new_op_s in self.sw[op_type]:
                            new_seg = seg.replace(old_op, new_op_s, 1)
                            if new_seg != seg:
                                old_line = self.sl[node.lineno - 1]
                                new_line = old_line.replace(seg, new_seg, 1)
                                if new_line != old_line:
                                    mutant = "".join(self.sl[:node.lineno-1] + [new_line] + self.sl[node.lineno:])
                                    self.n += 1
                                    self.coll.append((mutant, self.k, node.lineno, old_line.rstrip(), new_line.rstrip()))
                                    break
                self.generic_visit(node)

        coll: list = []
        Mut(source, src_lines, coll, swap_map, kind, self.max_mutants).visit(tree)
        return coll

    # ---- test execution ----

    def _run_single(
        self,
        mutant_source: str,
        kind: MutationKind,
        lineno: int,
        original: str,
        mutated: str,
        test_command: Union[str, List[str]],
        work_dir: Optional[Union[str, Path]],
    ) -> MutationResult:
        """Run tests against a single mutant."""
        result = MutationResult(
            mutation_kind=kind, original_line=lineno,
            original_code=original, mutated_code=mutated,
        )
        tmp_path: str = ""
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
                tmp.write(mutant_source)
                tmp.flush()
                tmp_path = tmp.name
            if isinstance(test_command, str):
                test_command = test_command.split()
            proc = subprocess.run(
                list(test_command), capture_output=True, text=True,
                timeout=self.timeout, cwd=str(work_dir) if work_dir else None,
            )
            result.test_output = proc.stdout[-2000:] + "\n" + proc.stderr[-2000:]
            result.test_passed = proc.returncode == 0
            result.killed = not result.test_passed
        except subprocess.TimeoutExpired:
            result.test_output = "Test run timed out"
            result.test_passed = True
            result.killed = False
        except Exception as e:
            result.test_output = f"Error: {e}"
            result.test_passed = True
            result.killed = False
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        return result


# ============================================================================
# CLI
# ============================================================================


def _cli_help() -> int:
    """Print usage and exit."""
    print(__doc__)
    print("Commands: analyze, generate, coverage, mutate, prioritize")
    return 0


def _cli_analyze(args: List[str]) -> int:
    """Analyze a Python file and list functions."""
    if not args:
        print("Usage: analyze <file.py>", file=sys.stderr)
        return 1
    p = Path(args[0])
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 1
    gen = TestGenerator()
    functions = gen.analyze_module(p.read_text(encoding="utf-8"))
    print(f"\n📁 {p}\n   Found {len(functions)} testable functions:\n")
    for f in functions:
        print(f"   • {f.name}({', '.join(f.args)})")
        print(f"     Lines: {f.lineno}-{f.end_lineno}  Complexity: {f.complexity}")
        if f.raises:
            print(f"     Raises: {', '.join(f.raises)}")
        if f.dependencies:
            print(f"     Deps: {', '.join(sorted(f.dependencies)[:10])}")
        print()
    return 0


def _cli_generate(args: List[str]) -> int:
    """Generate unit tests for a Python file."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate unit tests")
    parser.add_argument("file", help="Python source to analyze")
    parser.add_argument("--format", choices=["pytest", "unittest"], default="pytest")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    ns = parser.parse_args(args)
    p = Path(ns.file)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 1
    fmt = TestFormat.PYTEST if ns.format == "pytest" else TestFormat.UNITTEST
    gen = TestGenerator(format=fmt)
    tests = gen.generate_from_file(p)
    if not tests:
        print(f"No testable functions in {p}", file=sys.stderr)
        return 1
    rendered = gen.render_tests(tests, module_import=p.stem)
    if ns.output:
        Path(ns.output).write_text(rendered, encoding="utf-8")
        print(f"Generated {len(tests)} tests → {ns.output}")
    else:
        print(rendered)
    return 0


def _cli_coverage(args: List[str]) -> int:
    """Analyze a coverage report file."""
    if not args:
        print("Usage: coverage <coverage.xml|coverage.json|.lcov>", file=sys.stderr)
        return 1
    analyzer = CoverageAnalyzer()
    results = analyzer.parse_file(args[0])
    if not results:
        print("No coverage data found.", file=sys.stderr)
        return 1
    print(analyzer.generate_report(results))
    return 0


def _cli_mutate(args: List[str]) -> int:
    """Run mutation testing on a source file."""
    import argparse
    parser = argparse.ArgumentParser(description="Mutation testing")
    parser.add_argument("source", help="Python source file to mutate")
    parser.add_argument("test_command", nargs="?", default="pytest", help="Test command")
    parser.add_argument("--kinds", help="Comma-separated mutation kinds")
    parser.add_argument("--max", type=int, default=20, help="Max mutants")
    ns = parser.parse_args(args)
    p = Path(ns.source)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 1
    kinds = None
    if ns.kinds:
        kinds = [MutationKind[k.strip().upper()] for k in ns.kinds.split(",")]
    tester = MutationTester(max_mutants=ns.max)
    results = tester.run(source=p.read_text(encoding="utf-8"), test_command=ns.test_command,
                         kinds=kinds, work_dir=p.parent)
    print(f"\n🧬 MUTATION TESTING — {p}")
    print(f"   Mutants: {len(results)}  Score: {tester.mutation_score(results):.1%}\n")
    killed = [r for r in results if r.killed]
    survived = [r for r in results if not r.killed]
    if killed:
        print(f"   ✅ Killed ({len(killed)}):")
        for r in killed[:10]:
            print(f"      L{r.original_line}: {r.mutation_kind.value} — {r.original_code[:50]} → {r.mutated_code[:50]}")
    if survived:
        print(f"\n   ❌ Survived ({len(survived)}):")
        for r in survived[:10]:
            print(f"      L{r.original_line}: {r.mutation_kind.value} — {r.original_code[:50]} → {r.mutated_code[:50]}")
    print()
    return 0


def _cli_prioritize(args: List[str]) -> int:
    """Prioritize functions by test risk."""
    if not args:
        print("Usage: prioritize <file.py>", file=sys.stderr)
        return 1
    p = Path(args[0])
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 1
    gen = TestGenerator()
    functions = gen.analyze_module(p.read_text(encoding="utf-8"))
    prioritizer = TestPrioritizer()
    report = prioritizer.generate_priority_report(prioritizer.prioritize(functions))
    print(report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Usage: python -m src.core.test_generator <command> [args...]

    Commands: analyze, generate, coverage, mutate, prioritize
    """
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return _cli_help()
    handlers = {
        "analyze": _cli_analyze, "generate": _cli_generate,
        "coverage": _cli_coverage, "mutate": _cli_mutate,
        "prioritize": _cli_prioritize,
    }
    handler = handlers.get(argv[0].lower())
    if handler is None:
        print(f"Unknown command: {argv[0]}. Available: {', '.join(sorted(handlers))}", file=sys.stderr)
        return 1
    try:
        return handler(argv[1:])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
