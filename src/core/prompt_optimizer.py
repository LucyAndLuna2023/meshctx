<<<<<<< Updated upstream
"""Prompt Optimizer — token estimation, compression, template library (v3.115+)

Claude Code 对标: 自动prompt优化 + token节省。无pip依赖。
Core strategies: whitespace compression, few-shot trimming, template selection.
"""

from __future__ import annotations
import re
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── token estimation (word-based, no tiktoken) ──────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token count: ~1.3 tokens per word (GPT/Claude heuristic)."""
    if not text:
        return 0
    words = len(re.findall(r'\w+|[^\w\s]', text))
    return max(1, int(words * 1.3))


def estimate_cost(tokens: int, model: str = "claude-sonnet-4") -> float:
    """Estimate USD cost. Approximate pricing per 1K tokens."""
    rates: dict[str, tuple[float, float]] = {
        "claude-sonnet-4": (0.003, 0.015),   # input/output per 1K
        "claude-opus-4":  (0.015, 0.075),
        "gpt-4o":         (0.005, 0.015),
        "gpt-4o-mini":    (0.00015, 0.0006),
        "deepseek-v3":    (0.00027, 0.0011),
    }
    ri, ro = rates.get(model, (0.003, 0.015))
    return round(tokens / 1000 * ri, 6)


# ── dataclasses ─────────────────────────────────────────────────────────

@dataclass
class PromptTemplate:
    """Reusable prompt template with metadata."""
    name: str
    template: str
    category: str = "general"
    description: str = ""
    variables: list[str] = field(default_factory=list)
    estimated_tokens: int = 0

    def __post_init__(self):
        self.variables = re.findall(r'\{\{(\w+)\}\}', self.template)
        self.estimated_tokens = estimate_tokens(self.template)

    def render(self, **kwargs) -> str:
        """Fill template variables {{name}} with kwargs."""
        result = self.template
        for var in self.variables:
            val = kwargs.get(var, f"{{{{{var}}}}}")
            result = result.replace(f"{{{{{var}}}}}", str(val))
        return result


@dataclass
class OptimizationResult:
    """Result of a prompt optimization pass."""
    original_tokens: int
    optimized_tokens: int
    savings_pct: float
    strategies_applied: list[str] = field(default_factory=list)
    optimized_text: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return self.original_tokens - self.optimized_tokens


# ── built-in templates ──────────────────────────────────────────────────

BUILTIN_TEMPLATES: list[PromptTemplate] = [
    PromptTemplate(
        name="code-review",
        category="code",
        description="Standard code review prompt",
        template=(
            "Review the following {{language}} code for bugs, security issues, "
            "and style problems. Focus on:\n"
            "1. Logic errors and edge cases\n"
            "2. Security vulnerabilities (injection, XSS, hardcoded secrets)\n"
            "3. Code style and readability\n"
            "4. Performance concerns\n\n"
            "Code:\n```{{language}}\n{{code}}\n```\n\n"
            "Provide a structured review with severity levels."
        ),
    ),
    PromptTemplate(
        name="fix-bug",
        category="code",
        description="Bug fix prompt",
        template=(
            "Fix the following bug in {{language}} code:\n\n"
            "Bug description: {{description}}\n"
            "Error message: {{error}}\n\n"
            "Code:\n```{{language}}\n{{code}}\n```\n\n"
            "Provide the fixed code and explain the root cause."
        ),
    ),
    PromptTemplate(
        name="write-tests",
        category="testing",
        description="Generate unit tests",
        template=(
            "Write comprehensive unit tests for the following {{language}} function. "
            "Cover: happy path, edge cases, error handling, and boundary conditions.\n\n"
            "Function:\n```{{language}}\n{{code}}\n```\n\n"
            "Use {{framework}} testing framework."
        ),
    ),
    PromptTemplate(
        name="explain-code",
        category="docs",
        description="Explain code to a human",
        template=(
            "Explain the following {{language}} code in plain language. "
            "Target audience: {{audience}}.\n\n"
            "Code:\n```{{language}}\n{{code}}\n```"
        ),
    ),
    PromptTemplate(
        name="refactor",
        category="code",
        description="Refactoring prompt",
        template=(
            "Refactor the following {{language}} code for better readability "
            "and maintainability. Preserve all functionality.\n\n"
            "Goals: {{goals}}\n\n"
            "Code:\n```{{language}}\n{{code}}\n```"
        ),
    ),
    PromptTemplate(
        name="summarize",
        category="text",
        description="Summarization prompt",
        template=(
            "Summarize the following content in {{length}} words or fewer. "
            "Focus on key points and actionable insights.\n\n"
            "Content:\n{{content}}"
        ),
    ),
]


# ── compression strategies ──────────────────────────────────────────────

def compress_whitespace(text: str) -> str:
    """Collapse multiple blank lines and trailing whitespace."""
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def compress_code_comments(text: str) -> str:
    """Remove inline comments from code blocks (preserve docstrings)."""
    lines = text.split('\n')
    result = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            # Remove inline comments but keep the code
            # Only remove if comment is after code (not a docstring line)
            if '#' in line and not line.strip().startswith('#'):
                code_part = line.split('#')[0].rstrip()
                if code_part.strip():
                    result.append(code_part)
                else:
                    result.append(line)  # whole line is comment
            else:
                result.append(line)
        else:
            result.append(line)
    return '\n'.join(result)


def trim_fewshot_examples(text: str, max_examples: int = 3) -> str:
    """Reduce excessive few-shot examples."""
    example_blocks = re.split(r'(?:\n|^)(?:Example|示例|例)\s*\d*[:：]', text, flags=re.IGNORECASE)
    if len(example_blocks) <= max_examples + 1:
        return text
    # Keep first block (preamble) + first max_examples examples
    kept = [example_blocks[0]]
    for block in example_blocks[1:max_examples + 1]:
        kept.append(block)
    result = kept[0]
    for i, block in enumerate(kept[1:], 1):
        result += f"\nExample {i}:{block}"
    result += f"\n(... {len(example_blocks) - 1 - max_examples} more examples omitted ...)"
    return result


def shorten_long_lines(text: str, max_line_length: int = 200) -> str:
    """Truncate excessively long lines."""
    lines = text.split('\n')
    result = []
    for line in lines:
        if len(line) > max_line_length:
            result.append(line[:max_line_length - 3] + '...')
        else:
            result.append(line)
    return '\n'.join(result)


STRATEGIES = [
    ("whitespace", compress_whitespace, "Collapse redundant whitespace"),
    ("comments", compress_code_comments, "Remove inline code comments"),
    ("fewshot", trim_fewshot_examples, "Trim excessive few-shot examples"),
    ("longlines", shorten_long_lines, "Truncate overly long lines"),
]


# ── main optimizer ──────────────────────────────────────────────────────

class PromptOptimizer:
    """Prompt optimization engine — compress, template, estimate."""

    def __init__(self, max_input_tokens: int = 100000):
        self.max_input_tokens = max_input_tokens
        self._templates: dict[str, PromptTemplate] = {
            t.name: t for t in BUILTIN_TEMPLATES
        }
        self._history: list[OptimizationResult] = []
        self._total_saved: int = 0

    # ── template API ──

    def add_template(self, template: PromptTemplate):
        self._templates[template.name] = template

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        return self._templates.get(name)

    def list_templates(self, category: str | None = None) -> list[PromptTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return sorted(templates, key=lambda t: t.name)

    def render_template(self, name: str, **kwargs) -> str:
        tmpl = self._templates.get(name)
        if tmpl is None:
            available = ', '.join(sorted(self._templates.keys()))
            raise KeyError(f"Template '{name}' not found. Available: {available}")
        return tmpl.render(**kwargs)

    # ── optimization ──

    def optimize(self, prompt: str, aggressive: bool = False,
                 target_tokens: int = 0) -> OptimizationResult:
        """Apply compression strategies to reduce prompt token count."""
        original_tokens = estimate_tokens(prompt)
        current = prompt
        applied: list[str] = []

        for name, strategy_fn, desc in STRATEGIES:
            if name == "fewshot" and not aggressive:
                continue
            before = estimate_tokens(current)
            candidate = strategy_fn(current)
            after = estimate_tokens(candidate)
            if after < before and len(candidate) < len(current):
                current = candidate
                applied.append(desc)
                if target_tokens and after <= target_tokens:
                    break

        optimized_tokens = estimate_tokens(current)
        savings_pct = round((1 - optimized_tokens / max(original_tokens, 1)) * 100, 1)

        result = OptimizationResult(
            original_tokens=original_tokens,
            optimized_tokens=optimized_tokens,
            savings_pct=savings_pct,
            strategies_applied=applied,
            optimized_text=current if current != prompt else prompt,
        )

        if optimized_tokens > self.max_input_tokens:
            result.warnings.append(
                f"Optimized prompt ({optimized_tokens} tokens) still exceeds "
                f"max ({self.max_input_tokens})"
            )

        self._history.append(result)
        if len(self._history) > 200:
            self._history = self._history[-100:]
        self._total_saved += result.saved

        logger.info(
            "Prompt optimized: %d→%d tokens (-%s%%) strategies=%s",
            original_tokens, optimized_tokens, savings_pct, applied,
        )
        return result

    def estimate(self, prompt: str, model: str = "claude-sonnet-4") -> dict:
        tokens = estimate_tokens(prompt)
        return {
            "tokens": tokens,
            "chars": len(prompt),
            "words": len(prompt.split()),
            "lines": prompt.count('\n') + 1,
            "cost_usd": estimate_cost(tokens, model),
            "within_limit": tokens <= self.max_input_tokens,
        }

    # ── stats ──

    def stats(self) -> dict:
        recent = self._history[-10:] if self._history else []
        return {
            "total_optimizations": len(self._history),
            "total_tokens_saved": self._total_saved,
            "avg_savings_pct": (
                round(sum(r.savings_pct for r in self._history) / len(self._history), 1)
                if self._history else 0
            ),
            "templates_available": len(self._templates),
            "template_categories": list(set(t.category for t in self._templates.values())),
            "max_input_tokens": self.max_input_tokens,
            "recent": [
                {"original": r.original_tokens, "optimized": r.optimized_tokens,
                 "savings_pct": r.savings_pct, "strategies": r.strategies_applied}
                for r in recent
            ],
        }


# ── _P compatibility ────────────────────────────────────────────────────
=======
"""meshctx prompt_optimizer — 开源版 (stub)"""
class _Stub:
    def __init__(self, *a, **kw): pass
    def __getattr__(self, n): return lambda *a,**kw: None
>>>>>>> Stashed changes

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

<<<<<<< Updated upstream

def __getattr__(name):
    return _P(name)
=======
def __getattr__(name):
    return _P(name)

>>>>>>> Stashed changes
