# -*- coding: utf-8 -*-
"""meshctx SMA Phase 2 — 输出验证器库 (Validator Suite).

用途: 弱模型 (乃至旗舰) 输出的机器可判校验 — 失败即触发自修复链
(带错误反馈重试 → 级联升级), 是"弱模型+系统≈强模型"的可靠性支柱。

原则: 只做**确定性机器判定** (可解析/可编译/可执行/引用存在),
不做语义判断 (那是模型/审计的事)。全部零网络、零执行副作用
(Python 仅 ast.parse 编译期检查, 不运行代码)。

守门: tests/test_validators.py
"""
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ValidationResult:
    ok: bool
    kind: str
    errors: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_feedback(self) -> str:
        """转自修复反馈提示词片段 (带错误清单)."""
        errs = "\n".join(f"- {e}" for e in self.errors) or "- (无)"
        return f"上次输出未通过 {self.kind} 校验, 错误:\n{errs}\n请修正后重新输出完整结果。"


# ── JSON ────────────────────────────────────────────────────

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def validate_json_output(text: str) -> ValidationResult:
    """JSON 输出校验: 支持 ```json 围栏或裸 JSON; 提取首个可解析对象。"""
    if not text or not text.strip():
        return ValidationResult(False, "json", ["输出为空"])
    candidates = [m.group(1).strip() for m in _JSON_FENCE.finditer(text)]
    candidates.append(text.strip())
    last_err = "无可解析 JSON"
    for cand in candidates:
        # 宽松预处理: 去尾逗号 (常见弱模型错误)
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                obj = json.loads(attempt)
                return ValidationResult(True, "json", meta={"parsed": obj})
            except Exception as e:
                last_err = f"JSON 解析失败: {e}"
    return ValidationResult(False, "json", [last_err])


# ── Python 代码 (编译期, 零执行) ─────────────────────────────

_PY_FENCE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.S)


def validate_python_code(text: str) -> ValidationResult:
    """Python 代码块校验: 提取 ```python 围栏或裸代码 → ast.parse 编译期检查 (不执行)."""
    blocks = [m.group(1).strip() for m in _PY_FENCE.finditer(text)]
    if not blocks and ("def " in text or "import " in text or "class " in text):
        blocks = [text.strip()]
    if not blocks:
        return ValidationResult(False, "python", ["未找到 Python 代码块"])
    errors = []
    parsed = 0
    for i, code in enumerate(blocks):
        if not code:
            continue
        try:
            ast.parse(code)
            parsed += 1
        except SyntaxError as e:
            errors.append(f"代码块{i+1} 语法错误: line {e.lineno}: {e.msg}")
    if errors or parsed == 0:
        return ValidationResult(False, "python", errors or ["全部代码块为空"])
    return ValidationResult(True, "python", meta={"blocks": parsed})


# ── 文件引用存在性 (warn 级 — 形似路径才检查) ────────────────

_PATH_RE = re.compile(r"(?:^|[\s`\"'>])(/[A-Za-z0-9_\-./]{4,}|[A-Za-z0-9_\-]+\.(?:py|md|json|ya?ml|txt|sh|toml))")


def validate_file_refs(text: str, base: Optional[Path] = None) -> ValidationResult:
    """校验输出中引用的文件路径存在性。形似绝对路径/带代码扩展名的 token 才查。

    warn 级: 不确定的引用 (纯虚构路径无法判定) 不算 fail — 只对 base 下
    应存在而缺失的相对路径报错 (编辑/读取任务最常见失败模式)。
    """
    errors, checked = [], 0
    base = Path(base) if base else Path.cwd()
    for m in _PATH_RE.finditer(text or ""):
        p = m.group(1).strip("`\"'>")
        if p.startswith("/"):
            if Path(p).exists():
                checked += 1
            # 绝对路径不存在不报错 (可能在远端/待创建)
            continue
        cand = base / p
        checked += 1
        if not cand.exists():
            errors.append(f"引用的相对路径不存在: {p}")
    ok = not errors
    return ValidationResult(ok, "file_refs", errors, meta={"checked": checked})


# ── 汇总 ────────────────────────────────────────────────────

def validate_response(text: str, checks: List[str],
                      base: Optional[Path] = None) -> List[ValidationResult]:
    """按 check 名单跑验证器: json / python / file_refs。"""
    out = []
    for c in checks:
        if c == "json":
            out.append(validate_json_output(text))
        elif c == "python":
            out.append(validate_python_code(text))
        elif c == "file_refs":
            out.append(validate_file_refs(text, base=base))
    return out
