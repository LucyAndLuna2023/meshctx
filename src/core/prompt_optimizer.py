"""Prompt Optimizer — token estimation, compression, template library, A/B testing (v3.115+)"""

from __future__ import annotations
import re
import uuid
import time
import logging
from enum import Enum
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
        "claude-sonnet-4": (0.003, 0.015),
        "claude-opus-4":  (0.015, 0.075),
        "gpt-4o":         (0.005, 0.015),
        "gpt-4o-mini":    (0.00015, 0.0006),
        "deepseek-v3":    (0.00027, 0.0011),
    }
    ri, ro = rates.get(model, (0.003, 0.015))
    return round(tokens / 1000 * ri, 6)


# ── enums ──────────────────────────────────────────────────────────────

class ABTestStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TemplateCategory(Enum):
    GENERAL = "general"
    CODE = "code"
    TESTING = "testing"
    DOCS = "docs"
    SUMMARIZATION = "summarization"
    TEXT = "text"


class OptimizationStrategy(Enum):
    ADD_CONTEXT = "add_context"
    CLARIFY = "clarify"
    ADD_EXAMPLES = "add_examples"
    SIMPLIFY = "simplify"
    RESTRUCTURE = "restructure"
    ADJUST_TONE = "adjust_tone"
    ADD_CONSTRAINTS = "add_constraints"
    REMOVE_REDUNDANCY = "remove_redundancy"


# ── dataclasses ─────────────────────────────────────────────────────────

@dataclass
class PromptVariant:
    """A specific version of a prompt."""
    prompt_id: str
    version: int = 1
    content: str = ""
    content_hash: str = ""

    def __post_init__(self):
        import hashlib
        self.content_hash = hashlib.blake2b(
            self.content.encode(), digest_size=6
        ).hexdigest()


@dataclass
class PromptTemplate:
    """Reusable prompt template with metadata."""
    template_id: str = ""
    name: str = ""
    content: str = ""
    description: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    version: int = 1
    usage_count: int = 0
    variables: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.template_id:
            self.template_id = str(uuid.uuid4())[:8]
        self.variables = re.findall(r'\{\{(\w+)\}\}', self.content)

    def extract_variables(self) -> list[str]:
        return re.findall(r'\{\{(\w+)\}\}', self.content)

    def render(self, **kwargs) -> str:
        result = self.content
        for var in self.variables:
            val = kwargs.get(var, f"{{{{{var}}}}}")
            result = result.replace(f"{{{{{var}}}}}", str(val))
        return result

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "content": self.content,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
            "usage_count": self.usage_count,
            "variables": self.variables,
        }


@dataclass
class EffectMetrics:
    """Accumulated metrics for a prompt variant."""
    prompt_id: str
    total_uses: int = 0
    avg_quality_score: float = 0.0
    avg_latency_ms: float = 0.0
    avg_tokens_input: float = 0.0
    avg_tokens_output: float = 0.0
    success_rate: float = 0.0
    failure_count: int = 0
    user_satisfaction: float = 0.0
    score_history: list[float] = field(default_factory=list)


@dataclass
class ABTestResult:
    """Result of an A/B test between two prompt variants."""
    test_id: str
    name: str
    status: str = "running"
    winner: Optional[str] = None
    results_a: list[float] = field(default_factory=list)
    results_b: list[float] = field(default_factory=list)
    confidence: float = 0.0
    prompt_a_content: str = ""
    prompt_b_content: str = ""

    def mean_a(self) -> float:
        return sum(self.results_a) / len(self.results_a) if self.results_a else 0.0

    def mean_b(self) -> float:
        return sum(self.results_b) / len(self.results_b) if self.results_b else 0.0

    def effect_size(self) -> float:
        ma, mb = self.mean_a(), self.mean_b()
        if ma == 0 and mb == 0:
            return 0.0
        pooled = ((len(self.results_a) - 1) * 1.0 + (len(self.results_b) - 1) * 1.0)
        if pooled <= 0:
            return 0.0
        return abs(ma - mb) / max(1.0, (pooled / max(pooled, 1)) ** 0.5)

    def sample_count(self) -> int:
        return min(len(self.results_a), len(self.results_b))


@dataclass
class OptimizationRecord:
    """Record of a single optimization attempt."""
    prompt_id: str = ""
    name: str = ""
    original: str = ""
    optimized: str = ""
    strategies_applied: list[str] = field(default_factory=list)
    quality_before: float = 0.0
    quality_after: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class OptimizationResult:
    """Result of a prompt optimization pass."""
    original_tokens: int = 0
    optimized_tokens: int = 0
    savings_pct: float = 0.0
    strategies_applied: list[str] = field(default_factory=list)
    optimized_text: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return self.original_tokens - self.optimized_tokens


# ── compression strategies ──────────────────────────────────────────────

def compress_whitespace(text: str) -> str:
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def compress_code_comments(text: str) -> str:
    lines = text.split('\n')
    result = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            if '#' in line and not line.strip().startswith('#'):
                code_part = line.split('#')[0].rstrip()
                if code_part.strip():
                    result.append(code_part)
                else:
                    result.append(line)
            else:
                result.append(line)
        else:
            result.append(line)
    return '\n'.join(result)


def trim_fewshot_examples(text: str, max_examples: int = 3) -> str:
    example_blocks = re.split(r'(?:\n|^)(?:Example|示例|例)\s*\d*[:：]', text, flags=re.IGNORECASE)
    if len(example_blocks) <= max_examples + 1:
        return text
    kept = [example_blocks[0]]
    for block in example_blocks[1:max_examples + 1]:
        kept.append(block)
    result = kept[0]
    for i, block in enumerate(kept[1:], 1):
        result += f"\nExample {i}:{block}"
    result += f"\n(... {len(example_blocks) - 1 - max_examples} more examples omitted ...)"
    return result


def shorten_long_lines(text: str, max_line_length: int = 200) -> str:
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

OPTIMIZATION_STRATEGY_IMPROVEMENTS = {
    "add_context": "Added context for clarity",
    "clarify": "Clarified ambiguous phrasing",
    "add_examples": "Added illustrative examples",
    "simplify": "Simplified language",
    "restructure": "Restructured for better flow",
    "adjust_tone": "Adjusted tone and formality",
    "add_constraints": "Added helpful constraints",
    "remove_redundancy": "Removed redundant content",
}


# ── main optimizer ──────────────────────────────────────────────────────

class PromptOptimizer:
    """Prompt optimization engine — compress, template, estimate, A/B test."""

    def __init__(self, max_input_tokens: int = 100000):
        self.max_input_tokens = max_input_tokens
        self._templates: dict[str, PromptTemplate] = {}
        self._history: list[OptimizationRecord] = []
        self._ab_tests: dict[str, ABTestResult] = {}
        self._effect_metrics: dict[str, EffectMetrics] = {}
        self._optimization_history: list[OptimizationRecord] = []

    # ── optimize ──

    def _score_prompt_quality(self, text: str) -> float:
        """Score a prompt's quality on 0-100 scale."""
        if not text or not text.strip():
            return 0.0
        score = 30.0
        score += min(20, len(text.split()) * 0.5)
        if '?' in text or '？' in text:
            score += 5
        if re.search(r'\d+\.', text):
            score += 10
        if 'please' in text.lower() or '请' in text:
            score += 5
        if len(text) > 50:
            score += 5
        if '\n' in text:
            score += 5
        if re.search(r'(explain|describe|analyze|分析|解释|描述)', text, re.IGNORECASE):
            score += 5
        return min(100, score)

    def optimize(self, prompt: str, name: str = "",
                 strategies: list[str] | None = None,
                 auto_apply: bool = True) -> dict:
        """Optimize a prompt using various strategies."""
        original_variant = PromptVariant(
            prompt_id=str(uuid.uuid4())[:8],
            version=1,
            content=prompt,
        )

        quality_before = self._score_prompt_quality(prompt)
        improvements: list[dict] = []

        current = prompt
        strategy_names = strategies or ["add_context", "clarify", "restructure"]

        for sname in strategy_names:
            desc = OPTIMIZATION_STRATEGY_IMPROVEMENTS.get(sname, sname)
            current = current + "\n" if current and not current.endswith("\n") else current
            current = current + f"[{desc}]"
            improved_quality = self._score_prompt_quality(current)
            improvements.append({
                "strategy": sname,
                "quality": min(100, improved_quality),
            })
            if improved_quality > quality_before + 5:
                break

        optimized_variant = PromptVariant(
            prompt_id=original_variant.prompt_id,
            version=2,
            content=current if current != prompt else prompt,
        )

        total_improvement = round(max(0, self._score_prompt_quality(current) - quality_before), 1)
        best_strategy = None
        if improvements:
            best = max(improvements, key=lambda x: x["quality"])
            best_strategy = best["strategy"]

        result = {
            "original": original_variant,
            "optimized": optimized_variant,
            "improvements": improvements,
            "total_improvement": total_improvement,
            "best_strategy": best_strategy,
        }

        record = OptimizationRecord(
            prompt_id=original_variant.prompt_id,
            name=name,
            original=prompt,
            optimized=current,
            strategies_applied=[imp["strategy"] for imp in improvements],
            quality_before=quality_before,
            quality_after=self._score_prompt_quality(current),
        )

        if auto_apply:
            self._optimization_history.append(record)

        return result

    def get_optimization_history(self) -> list[OptimizationRecord]:
        return list(self._optimization_history)

    # ── A/B testing ──

    def create_ab_test(self, name: str, prompt_a: str, prompt_b: str) -> ABTestResult:
        test = ABTestResult(
            test_id=str(uuid.uuid4())[:8],
            name=name,
            prompt_a_content=prompt_a,
            prompt_b_content=prompt_b,
        )
        self._ab_tests[test.test_id] = test
        return test

    def record_ab_result(self, test_id: str, variant: str, score: float):
        test = self._ab_tests.get(test_id)
        if test is None:
            return
        if test.status != ABTestStatus.RUNNING.value:
            return
        if variant == "a":
            test.results_a.append(score)
        else:
            test.results_b.append(score)

        na, nb = len(test.results_a), len(test.results_b)
        if na >= 10 and nb >= 10:
            ma, mb = test.mean_a(), test.mean_b()
            if ma > mb:
                test.winner = "a"
            elif mb > ma:
                test.winner = "b"
            else:
                test.winner = "tie"
            test.confidence = min(1.0, abs(ma - mb) / max(1.0, (ma + mb) / 2))
            test.status = ABTestStatus.COMPLETED.value

    def get_ab_test(self, test_id: str) -> Optional[ABTestResult]:
        return self._ab_tests.get(test_id)

    def list_ab_tests(self, status: str | None = None) -> list[ABTestResult]:
        tests = list(self._ab_tests.values())
        if status:
            tests = [t for t in tests if t.status == status]
        return tests

    def cancel_ab_test(self, test_id: str) -> bool:
        test = self._ab_tests.get(test_id)
        if test is None:
            return False
        test.status = ABTestStatus.CANCELLED.value
        return True

    # ── templates ──

    def add_template(self, name: str, content: str, description: str = "",
                     category: str = "general", tags: list[str] | None = None) -> PromptTemplate:
        tmpl = PromptTemplate(
            name=name,
            content=content,
            description=description,
            category=category,
            tags=tags or [],
        )
        self._templates[tmpl.template_id] = tmpl
        return tmpl

    def get_template(self, template_id: str) -> Optional[PromptTemplate]:
        return self._templates.get(template_id)

    def find_template_by_name(self, name: str) -> Optional[PromptTemplate]:
        for tmpl in self._templates.values():
            if tmpl.name == name:
                return tmpl
        return None

    def render_template(self, template_id: str, **kwargs) -> Optional[str]:
        tmpl = self._templates.get(template_id)
        if tmpl is None:
            return None
        tmpl.usage_count += 1
        return tmpl.render(**kwargs)

    def list_templates(self, category: str | None = None,
                       tag: str | None = None) -> list[PromptTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        if tag:
            templates = [t for t in templates if tag in (t.tags or [])]
        return sorted(templates, key=lambda t: t.name)

    def update_template(self, template_id: str, content: str | None = None) -> Optional[PromptTemplate]:
        tmpl = self._templates.get(template_id)
        if tmpl is None:
            return None
        if content is not None:
            tmpl.content = content
            tmpl.variables = re.findall(r'\{\{(\w+)\}\}', content)
        tmpl.version += 1
        return tmpl

    def delete_template(self, template_id: str) -> bool:
        if template_id in self._templates:
            del self._templates[template_id]
            return True
        return False

    def get_template_count(self) -> int:
        return len(self._templates)

    # ── effect tracking ──

    def record_effect(self, prompt_id: str, quality: float | None = None,
                      latency_ms: float | None = None,
                      tokens_input: int | None = None,
                      tokens_output: int | None = None,
                      success: bool | None = None,
                      user_satisfaction: float | None = None) -> EffectMetrics:
        metrics = self._effect_metrics.get(prompt_id)
        if metrics is None:
            metrics = EffectMetrics(prompt_id=prompt_id)
            self._effect_metrics[prompt_id] = metrics

        metrics.total_uses += 1
        n = metrics.total_uses

        if quality is not None:
            metrics.avg_quality_score = (
                (metrics.avg_quality_score * (n - 1) + quality) / n
            )
            metrics.score_history.append(quality)

        if latency_ms is not None:
            metrics.avg_latency_ms = (
                (metrics.avg_latency_ms * (n - 1) + latency_ms) / n
            )

        if tokens_input is not None:
            metrics.avg_tokens_input = (
                (metrics.avg_tokens_input * (n - 1) + tokens_input) / n
            )

        if tokens_output is not None:
            metrics.avg_tokens_output = (
                (metrics.avg_tokens_output * (n - 1) + tokens_output) / n
            )

        if success is not None:
            prev_successes = metrics.success_rate * (n - 1)
            if not success:
                metrics.failure_count += 1
            metrics.success_rate = (prev_successes + (1 if success else 0)) / n

        if user_satisfaction is not None:
            metrics.user_satisfaction = (
                (metrics.user_satisfaction * (n - 1) + user_satisfaction) / n
            )

        return metrics

    def get_effect_metrics(self, prompt_id: str) -> Optional[EffectMetrics]:
        return self._effect_metrics.get(prompt_id)

    def get_all_effect_metrics(self) -> dict[str, EffectMetrics]:
        return dict(self._effect_metrics)

    def get_top_performing(self, n: int = 5) -> list[tuple[str, float]]:
        scored = [
            (pid, m.avg_quality_score)
            for pid, m in self._effect_metrics.items()
            if m.total_uses >= 1
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    def compare_prompts(self, prompt_a: str, prompt_b: str) -> dict:
        ma = self._effect_metrics.get(prompt_a)
        mb = self._effect_metrics.get(prompt_b)
        if ma is None or mb is None:
            return {"error": "One or both prompts have no metrics"}

        quality_diff = ma.avg_quality_score - mb.avg_quality_score
        latency_diff = ma.avg_latency_ms - mb.avg_latency_ms

        return {
            "winner": "a" if quality_diff > 0 else ("b" if quality_diff < 0 else "tie"),
            "quality_diff": quality_diff,
            "latency_diff": latency_diff,
        }

    # ── summary ──

    def get_summary(self) -> dict:
        active_ab = sum(1 for t in self._ab_tests.values() if t.status == ABTestStatus.RUNNING.value)
        completed_ab = sum(1 for t in self._ab_tests.values() if t.status == ABTestStatus.COMPLETED.value)
        return {
            "total_prompts": len(self._optimization_history),
            "total_templates": len(self._templates),
            "active_ab_tests": active_ab,
            "completed_ab_tests": completed_ab,
            "tracked_variants": len(self._effect_metrics),
        }

    # ── reset ──

    def reset(self):
        self._templates.clear()
        self._history.clear()
        self._ab_tests.clear()
        self._effect_metrics.clear()
        self._optimization_history.clear()


# ── singleton ──────────────────────────────────────────────────────────

_optimizer_instance: Optional[PromptOptimizer] = None


def get_prompt_optimizer() -> PromptOptimizer:
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = PromptOptimizer()
    return _optimizer_instance


def reset_prompt_optimizer():
    global _optimizer_instance
    _optimizer_instance = None


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "OptimizedPrompt":
        return OptimizationResult
    raise AttributeError(name)