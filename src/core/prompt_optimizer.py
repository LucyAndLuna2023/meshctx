"""
meshctx v3.105 — Prompt Optimizer (提示词优化器)

功能:
  1. 自动优化prompt — 启发式规则+质量评分自动改进提示词
  2. A/B测试不同版本 — 对比两个prompt变体，统计显著性判断
  3. 模板库管理 — 存储/检索/渲染可复用提示词模板
  4. 效果追踪 — 追踪每个版本的质量、延迟、token消耗等指标
"""

import hashlib
import json
import logging
import re
import statistics
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.prompt_optimizer")


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class OptimizationStrategy(Enum):
    """优化策略"""
    ADD_CONTEXT = "add_context"               # 补充上下文
    CLARIFY_INSTRUCTIONS = "clarify"          # 明确指令
    ADD_EXAMPLES = "add_examples"             # 添加示例
    SIMPLIFY = "simplify"                     # 简化表达
    RESTRUCTURE = "restructure"               # 重构结构
    ADJUST_TONE = "adjust_tone"               # 调整语气
    ADD_CONSTRAINTS = "add_constraints"       # 添加约束
    REMOVE_REDUNDANCY = "remove_redundancy"   # 删除冗余


class ABTestStatus(Enum):
    """A/B测试状态"""
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TemplateCategory(Enum):
    """模板分类"""
    GENERAL = "general"
    CODE = "code"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    CUSTOM = "custom"


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class PromptVariant:
    """单个prompt版本"""
    prompt_id: str = ""                        # 唯一ID
    version: int = 1                           # 版本号
    name: str = ""                             # 可读名称
    content: str = ""                          # prompt文本
    strategy_used: Optional[str] = None        # 使用的优化策略
    parent_id: Optional[str] = None            # 父版本ID
    created_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:12]


@dataclass
class EffectMetrics:
    """效果指标"""
    prompt_id: str = ""
    total_uses: int = 0
    avg_quality_score: float = 0.0             # 质量评分 (0-100)
    avg_latency_ms: float = 0.0                # 平均延迟
    avg_tokens_input: int = 0                   # 平均输入token
    avg_tokens_output: int = 0                  # 平均输出token
    success_rate: float = 1.0                   # 成功率
    user_satisfaction: float = 0.0             # 用户满意度 (0-1)
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    score_history: deque = field(default_factory=lambda: deque(maxlen=100))


@dataclass
class ABTestResult:
    """A/B测试结果"""
    test_id: str = ""
    name: str = ""
    prompt_a_id: str = ""                      # 变体A的prompt_id
    prompt_b_id: str = ""                      # 变体B的prompt_id
    prompt_a_content: str = ""
    prompt_b_content: str = ""
    results_a: List[float] = field(default_factory=list)
    results_b: List[float] = field(default_factory=list)
    status: str = ABTestStatus.RUNNING.value
    winner: Optional[str] = None               # 'a' or 'b' or 'tie'
    confidence: float = 0.0
    p_value: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def mean_a(self) -> float:
        return statistics.mean(self.results_a) if self.results_a else 0.0

    def mean_b(self) -> float:
        return statistics.mean(self.results_b) if self.results_b else 0.0

    def sample_count(self) -> int:
        return min(len(self.results_a), len(self.results_b))

    def effect_size(self) -> float:
        """Cohen's d"""
        ma, mb = self.mean_a(), self.mean_b()
        if len(self.results_a) < 2 or len(self.results_b) < 2:
            return 0.0
        pooled_std = statistics.stdev(self.results_a + self.results_b)
        if pooled_std == 0:
            return 0.0
        return abs(ma - mb) / pooled_std


@dataclass
class PromptTemplate:
    """可复用提示词模板"""
    template_id: str = ""
    name: str = ""
    description: str = ""
    category: str = TemplateCategory.GENERAL.value
    content: str = ""                          # 模板文本，使用 {{var}} 占位符
    version: int = 1
    variables: List[str] = field(default_factory=list)  # 自动提取的变量名
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    usage_count: int = 0

    def extract_variables(self) -> List[str]:
        """从模板中提取 {{variable}} 占位符"""
        pattern = r'\{\{(\w+)\}\}'
        return list(dict.fromkeys(re.findall(pattern, self.content)))

    def render(self, **kwargs) -> str:
        """渲染模板"""
        result = self.content
        for key, value in kwargs.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))
        return result


@dataclass
class OptimizationRecord:
    """优化记录"""
    record_id: str = ""
    original_prompt_id: str = ""
    optimized_prompt_id: str = ""
    strategy: str = ""
    quality_before: float = 0.0
    quality_after: float = 0.0
    improvement_pct: float = 0.0
    timestamp: float = field(default_factory=time.time)
    notes: str = ""


# ═══════════════════════════════════════════════════════════
# Prompt Optimizer Engine
# ═══════════════════════════════════════════════════════════

class PromptOptimizer:
    """
    v3.105 提示词优化器

    四大核心功能:
      1. 自动优化prompt — 多策略启发式优化引擎
      2. A/B测试不同版本 — 统计显著性对比测试
      3. 模板库管理 — 可复用模板存储与渲染
      4. 效果追踪 — 全维度指标记录与分析
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._prompts: Dict[str, PromptVariant] = {}
        self._prompt_versions: Dict[str, List[str]] = defaultdict(list)  # base_id → [version_ids]
        self._templates: Dict[str, PromptTemplate] = {}
        self._ab_tests: Dict[str, ABTestResult] = {}
        self._metrics: Dict[str, EffectMetrics] = {}
        self._optimization_history: List[OptimizationRecord] = []
        self._effect_records: deque = deque(maxlen=1000)

        # 启发式优化规则
        self._optimization_rules = self._build_optimization_rules()

    # ══════════════════════════════════════════════════════
    # 1. Auto-Optimize Prompts
    # ══════════════════════════════════════════════════════

    def _build_optimization_rules(self) -> Dict[str, Callable]:
        """构建优化规则集"""
        return {
            OptimizationStrategy.ADD_CONTEXT.value: self._opt_add_context,
            OptimizationStrategy.CLARIFY_INSTRUCTIONS.value: self._opt_clarify,
            OptimizationStrategy.ADD_EXAMPLES.value: self._opt_add_examples,
            OptimizationStrategy.SIMPLIFY.value: self._opt_simplify,
            OptimizationStrategy.RESTRUCTURE.value: self._opt_restructure,
            OptimizationStrategy.ADJUST_TONE.value: self._opt_adjust_tone,
            OptimizationStrategy.ADD_CONSTRAINTS.value: self._opt_add_constraints,
            OptimizationStrategy.REMOVE_REDUNDANCY.value: self._opt_remove_redundancy,
        }

    def _opt_add_context(self, prompt: str) -> str:
        """补充上下文: 在开头添加角色和任务说明"""
        prefix = (
            "You are an expert AI assistant. "
            "Please provide a thorough, accurate, and well-structured response to the following:\n\n"
        )
        if prompt.startswith("You are") or prompt.startswith("Act as"):
            return prompt
        return prefix + prompt

    def _opt_clarify(self, prompt: str) -> str:
        """明确指令: 添加具体要求"""
        suffix = (
            "\n\nPlease ensure your response:\n"
            "- Directly addresses the question\n"
            "- Is clear and well-organized\n"
            "- Includes relevant details and examples where appropriate"
        )
        if "ensure your response" in prompt.lower():
            return prompt
        return prompt + suffix

    def _opt_add_examples(self, prompt: str) -> str:
        """添加示例请求"""
        suffix = (
            "\n\nIf applicable, please include 1-2 concrete examples to illustrate your points."
        )
        if "example" in prompt.lower():
            return prompt
        return prompt + suffix

    def _opt_simplify(self, prompt: str) -> str:
        """简化: 移除过于冗长的修饰"""
        # Remove excessively long sentences (heuristic)
        sentences = re.split(r'(?<=[.!?])\s+', prompt)
        if len(sentences) > 3:
            # Keep first + last two
            simplified = ' '.join([sentences[0]] + sentences[-2:])
            if len(simplified) < len(prompt) * 0.8:
                return "Summarize concisely: " + simplified
        return prompt

    def _opt_restructure(self, prompt: str) -> str:
        """重构: 添加编号/分点"""
        if any(marker in prompt for marker in ['\n1.', '\n-', '\n•', '\n*']):
            return prompt
        lines = [l.strip() for l in prompt.split('\n') if l.strip()]
        if len(lines) > 1:
            # Add structure markers between logical sections
            result = lines[0] + "\n"
            for i, line in enumerate(lines[1:], 1):
                marker = f"\n{i}. " if not line.startswith(("1.", "-", "•")) else "\n"
                result += marker + line
            return result
        return prompt

    def _opt_adjust_tone(self, prompt: str) -> str:
        """调整语气: 更专业的表达"""
        replacements = {
            "please": "Please",
            "can you": "I need you to",
            "tell me": "provide detailed information about",
            "what is": "Please define and explain",
            "how to": "Please provide step-by-step instructions for",
        }
        result = prompt
        modified = False
        for old, new in replacements.items():
            if old in result.lower() and old not in result:
                result = result.replace(old, new)
                modified = True
            elif old in result:
                # case-insensitive match
                pattern = re.compile(re.escape(old), re.IGNORECASE)
                result = pattern.sub(new, result, count=1)
                modified = True
        return result if modified else prompt + "\n\nPlease respond in a professional tone."

    def _opt_add_constraints(self, prompt: str) -> str:
        """添加约束条件"""
        suffix = (
            "\n\nConstraints:\n"
            "- Be concise: aim for clarity and brevity\n"
            "- Be accurate: verify facts before stating them\n"
            "- Be helpful: focus on actionable information"
        )
        if "Constraints:" in prompt or "constraints:" in prompt.lower():
            return prompt
        return prompt + suffix

    def _opt_remove_redundancy(self, prompt: str) -> str:
        """删除冗余: 去除重复短语"""
        words = prompt.split()
        if len(words) > 50:
            seen = set()
            deduped = []
            for word in words:
                wl = word.lower().strip('.,;:!?')
                if wl not in seen or len(wl) <= 3:
                    deduped.append(word)
                    seen.add(wl)
            return ' '.join(deduped)
        return prompt

    def optimize(
        self,
        prompt: str,
        name: str = "",
        strategies: Optional[List[str]] = None,
        auto_apply: bool = True,
    ) -> Dict[str, Any]:
        """
        自动优化prompt

        Args:
            prompt: 原始prompt文本
            name: prompt名称
            strategies: 要使用的优化策略列表 (None=全部)
            auto_apply: 是否自动保存最佳版本

        Returns:
            {
                "original": PromptVariant,
                "optimized": PromptVariant,
                "improvements": [{"strategy": ..., "quality_before": ..., "quality_after": ...}],
                "best_strategy": str,
                "total_improvement": float,
            }
        """
        if strategies is None:
            strategies = [s.value for s in OptimizationStrategy]

        original_id = self._make_id("prompt")
        original = PromptVariant(
            prompt_id=original_id,
            version=1,
            name=name or "original",
            content=prompt,
        )

        # Score original
        base_quality = self._score_prompt_quality(prompt)

        # Try each strategy
        candidates = []
        for strategy_name in strategies:
            rule = self._optimization_rules.get(strategy_name)
            if rule is None:
                continue
            try:
                optimized_content = rule(prompt)
                if optimized_content == prompt:
                    continue  # No change
                opt_quality = self._score_prompt_quality(optimized_content)

                candidates.append({
                    "strategy": strategy_name,
                    "content": optimized_content,
                    "quality": opt_quality,
                    "improvement": opt_quality - base_quality,
                })
            except Exception as e:
                logger.warning(f"Optimization strategy {strategy_name} failed: {e}")

        if not candidates:
            # No improvements found; return original
            optimized = original
            improvements = []
            best_strategy = None
            total_improvement = 0.0
        else:
            # Sort by quality improvement
            candidates.sort(key=lambda c: c["quality"], reverse=True)
            best = candidates[0]

            optimized_id = self._make_id("prompt")
            optimized = PromptVariant(
                prompt_id=optimized_id,
                version=2,
                name=f"{name or 'prompt'}_optimized",
                content=best["content"],
                strategy_used=best["strategy"],
                parent_id=original_id,
            )

            improvements = candidates
            best_strategy = best["strategy"]
            total_improvement = best["improvement"]

            if auto_apply:
                self._prompts[optimized_id] = optimized
                self._prompts[original_id] = original
                base_name = name or "default"
                self._prompt_versions[base_name].extend([original_id, optimized_id])

                # Record optimization
                record = OptimizationRecord(
                    record_id=self._make_id("opt"),
                    original_prompt_id=original_id,
                    optimized_prompt_id=optimized_id,
                    strategy=best_strategy,
                    quality_before=base_quality,
                    quality_after=best["quality"],
                    improvement_pct=round(total_improvement / max(base_quality, 0.01) * 100, 1),
                )
                self._optimization_history.append(record)

        return {
            "original": original,
            "optimized": optimized,
            "improvements": [
                {
                    "strategy": c["strategy"],
                    "quality": round(c["quality"], 1),
                    "improvement": round(c["improvement"], 1),
                }
                for c in candidates
            ],
            "best_strategy": best_strategy,
            "total_improvement": round(total_improvement, 1),
        }

    def _score_prompt_quality(self, prompt: str) -> float:
        """
        启发式评分 (0-100)

        评分维度:
        - 清晰度: 是否有明确指令
        - 完整性: 是否包含足够上下文
        - 结构化: 是否有良好的组织结构
        - 简洁性: 是否避免冗余
        """
        score = 50.0  # Baseline

        # Clarity: check for question/instruction markers
        clarity_markers = ['?', 'explain', 'describe', 'analyze', 'summarize',
                          'write', 'create', 'compare', 'define', 'list']
        clarity_hits = sum(1 for m in clarity_markers if m in prompt.lower())
        score += min(15, clarity_hits * 2)

        # Completeness: length and context
        words = len(prompt.split())
        if words >= 20:
            score += 10
        elif words >= 10:
            score += 5

        # Structure: bullet points, numbered lists, paragraphs
        if '\n' in prompt:
            score += 5
        if any(m in prompt for m in ['\n1.', '\n-', '\n•', '\n*']):
            score += 5

        # Conciseness: not too verbose
        if words <= 500:
            score += 5
        if words <= 100:
            score += 5

        # Tone/politeness
        if 'please' in prompt.lower():
            score += 3
        if 'thank' in prompt.lower():
            score += 2

        return max(0.0, min(100.0, score))

    # ══════════════════════════════════════════════════════
    # 2. A/B Testing
    # ══════════════════════════════════════════════════════

    def create_ab_test(
        self,
        name: str,
        prompt_a: str,
        prompt_b: str,
        min_samples: int = 10,
    ) -> ABTestResult:
        """
        创建A/B测试

        Args:
            name: 测试名称
            prompt_a: 变体A
            prompt_b: 变体B
            min_samples: 最小样本数

        Returns:
            ABTestResult
        """
        test_id = self._make_id("abtest")
        test = ABTestResult(
            test_id=test_id,
            name=name,
            prompt_a_id=self._make_id("prompt"),
            prompt_b_id=self._make_id("prompt"),
            prompt_a_content=prompt_a,
            prompt_b_content=prompt_b,
        )
        self._ab_tests[test_id] = test
        logger.info(f"Created A/B test '{name}' ({test_id})")
        return test

    def record_ab_result(
        self,
        test_id: str,
        variant: str,
        score: float,
        latency_ms: float = 0,
        tokens: int = 0,
    ) -> Optional[ABTestResult]:
        """
        记录A/B测试结果

        Args:
            test_id: 测试ID
            variant: 'a' 或 'b'
            score: 质量评分
            latency_ms: 延迟
            tokens: token消耗
        """
        test = self._ab_tests.get(test_id)
        if test is None:
            logger.warning(f"A/B test '{test_id}' not found")
            return None

        if variant == 'a':
            test.results_a.append(score)
        elif variant == 'b':
            test.results_b.append(score)
        else:
            return None

        # Check if we can determine winner
        if len(test.results_a) >= 10 and len(test.results_b) >= 10:
            self._determine_ab_winner(test)

        # Track effect for each variant
        prompt_id = test.prompt_a_id if variant == 'a' else test.prompt_b_id
        self._record_effect_internal(
            prompt_id=prompt_id,
            quality=score,
            latency_ms=latency_ms,
            tokens_input=tokens,
            tokens_output=0,
            success=True,
        )

        return test

    def _determine_ab_winner(self, test: ABTestResult):
        """统计判定A/B测试胜者"""
        if len(test.results_a) < 10 or len(test.results_b) < 10:
            return

        mean_a = test.mean_a()
        mean_b = test.mean_b()

        if mean_a > mean_b:
            test.winner = 'a'
        elif mean_b > mean_a:
            test.winner = 'b'
        else:
            test.winner = 'tie'

        test.confidence = min(0.99, abs(mean_a - mean_b) / max(mean_a, mean_b, 1))
        test.status = ABTestStatus.COMPLETED.value
        test.completed_at = time.time()

        logger.info(
            f"A/B test '{test.name}': winner={test.winner} "
            f"(A:{mean_a:.2f} vs B:{mean_b:.2f}, conf={test.confidence:.2f})"
        )

    def get_ab_test(self, test_id: str) -> Optional[ABTestResult]:
        """获取A/B测试结果"""
        return self._ab_tests.get(test_id)

    def get_ab_winner(self, test_id: str) -> Optional[ABTestResult]:
        """获取A/B测试胜者"""
        return self._ab_tests.get(test_id)

    def list_ab_tests(self, status: Optional[str] = None) -> List[ABTestResult]:
        """列出所有A/B测试"""
        tests = list(self._ab_tests.values())
        if status:
            tests = [t for t in tests if t.status == status]
        return sorted(tests, key=lambda t: t.created_at, reverse=True)

    def cancel_ab_test(self, test_id: str) -> bool:
        """取消A/B测试"""
        test = self._ab_tests.get(test_id)
        if test is None:
            return False
        test.status = ABTestStatus.CANCELLED.value
        return True

    # ══════════════════════════════════════════════════════
    # 3. Template Library Management
    # ══════════════════════════════════════════════════════

    def add_template(
        self,
        name: str,
        content: str,
        description: str = "",
        category: str = TemplateCategory.GENERAL.value,
        tags: Optional[List[str]] = None,
    ) -> PromptTemplate:
        """添加模板"""
        template_id = self._make_id("tmpl")
        template = PromptTemplate(
            template_id=template_id,
            name=name,
            description=description,
            category=category,
            content=content,
            tags=tags or [],
        )
        template.variables = template.extract_variables()
        self._templates[template_id] = template
        logger.info(f"Added template '{name}' ({template_id}) with vars: {template.variables}")
        return template

    def get_template(self, template_id: str) -> Optional[PromptTemplate]:
        """获取模板"""
        return self._templates.get(template_id)

    def find_template_by_name(self, name: str) -> Optional[PromptTemplate]:
        """按名称查找模板"""
        for t in self._templates.values():
            if t.name == name:
                return t
        return None

    def list_templates(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[PromptTemplate]:
        """列出模板"""
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        if tag:
            templates = [t for t in templates if tag in t.tags]
        return sorted(templates, key=lambda t: t.updated_at, reverse=True)

    def render_template(self, template_id: str, **kwargs) -> Optional[str]:
        """渲染模板"""
        template = self._templates.get(template_id)
        if template is None:
            logger.warning(f"Template '{template_id}' not found")
            return None
        template.usage_count += 1
        template.updated_at = time.time()
        return template.render(**kwargs)

    def update_template(
        self,
        template_id: str,
        content: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[PromptTemplate]:
        """更新模板"""
        template = self._templates.get(template_id)
        if template is None:
            return None
        if content is not None:
            template.content = content
            template.variables = template.extract_variables()
            template.version += 1
        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if tags is not None:
            template.tags = tags
        template.updated_at = time.time()
        return template

    def delete_template(self, template_id: str) -> bool:
        """删除模板"""
        if template_id in self._templates:
            del self._templates[template_id]
            return True
        return False

    def get_template_count(self) -> int:
        return len(self._templates)

    # ══════════════════════════════════════════════════════
    # 4. Effect Tracking
    # ══════════════════════════════════════════════════════

    def record_effect(
        self,
        prompt_id: str,
        quality: float,
        latency_ms: float = 0.0,
        tokens_input: int = 0,
        tokens_output: int = 0,
        success: bool = True,
        user_satisfaction: float = 0.0,
    ) -> EffectMetrics:
        """
        记录prompt使用效果

        Args:
            prompt_id: prompt版本ID
            quality: 质量评分 (0-100)
            latency_ms: 延迟(毫秒)
            tokens_input: 输入token数
            tokens_output: 输出token数
            success: 是否成功
            user_satisfaction: 用户满意度 (0-1)
        """
        return self._record_effect_internal(
            prompt_id=prompt_id,
            quality=quality,
            latency_ms=latency_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            success=success,
            user_satisfaction=user_satisfaction,
        )

    def _record_effect_internal(
        self,
        prompt_id: str,
        quality: float = 0.0,
        latency_ms: float = 0.0,
        tokens_input: int = 0,
        tokens_output: int = 0,
        success: bool = True,
        user_satisfaction: float = 0.0,
    ) -> EffectMetrics:
        """内部效果记录"""
        if prompt_id not in self._metrics:
            self._metrics[prompt_id] = EffectMetrics(prompt_id=prompt_id)

        m = self._metrics[prompt_id]
        old_total = m.total_uses

        # Update running averages
        m.total_uses += 1
        if old_total == 0:
            m.avg_quality_score = quality
            m.avg_latency_ms = latency_ms
            m.avg_tokens_input = tokens_input
            m.avg_tokens_output = tokens_output
        else:
            m.avg_quality_score = (
                (m.avg_quality_score * old_total + quality) / m.total_uses
            )
            m.avg_latency_ms = (
                (m.avg_latency_ms * old_total + latency_ms) / m.total_uses
            )
            if tokens_input > 0:
                m.avg_tokens_input = int(
                    (m.avg_tokens_input * old_total + tokens_input) / m.total_uses
                )
            if tokens_output > 0:
                m.avg_tokens_output = int(
                    (m.avg_tokens_output * old_total + tokens_output) / m.total_uses
                )

        if not success:
            m.failure_count += 1
        m.success_rate = (m.total_uses - m.failure_count) / m.total_uses

        if user_satisfaction > 0:
            if m.user_satisfaction == 0:
                m.user_satisfaction = user_satisfaction
            else:
                m.user_satisfaction = (
                    (m.user_satisfaction * old_total + user_satisfaction) / m.total_uses
                )

        m.score_history.append(quality)
        m.last_used = time.time()

        self._effect_records.append({
            "prompt_id": prompt_id,
            "quality": quality,
            "latency_ms": latency_ms,
            "success": success,
            "timestamp": time.time(),
        })

        return m

    def get_effect_metrics(self, prompt_id: str) -> Optional[EffectMetrics]:
        """获取效果指标"""
        return self._metrics.get(prompt_id)

    def get_all_effect_metrics(self) -> Dict[str, EffectMetrics]:
        """获取所有效果指标"""
        return dict(self._metrics)

    def get_top_performing(self, n: int = 5) -> List[Tuple[str, EffectMetrics]]:
        """获取表现最好的prompt"""
        with_metrics = [
            (pid, m) for pid, m in self._metrics.items()
            if m.total_uses >= 3
        ]
        sorted_metrics = sorted(
            with_metrics,
            key=lambda x: (x[1].avg_quality_score, x[1].success_rate),
            reverse=True,
        )
        return sorted_metrics[:n]

    def get_optimization_history(self) -> List[OptimizationRecord]:
        """获取优化历史"""
        return list(self._optimization_history)

    def compare_prompts(
        self, prompt_id_a: str, prompt_id_b: str
    ) -> Dict[str, Any]:
        """对比两个prompt的效果"""
        ma = self._metrics.get(prompt_id_a)
        mb = self._metrics.get(prompt_id_b)

        if not ma or not mb:
            return {"error": "One or both prompts have no metrics"}

        return {
            "prompt_a": {
                "id": prompt_id_a,
                "uses": ma.total_uses,
                "quality": round(ma.avg_quality_score, 1),
                "latency": round(ma.avg_latency_ms, 1),
                "success_rate": round(ma.success_rate, 3),
            },
            "prompt_b": {
                "id": prompt_id_b,
                "uses": mb.total_uses,
                "quality": round(mb.avg_quality_score, 1),
                "latency": round(mb.avg_latency_ms, 1),
                "success_rate": round(mb.success_rate, 3),
            },
            "quality_diff": round(ma.avg_quality_score - mb.avg_quality_score, 1),
            "latency_diff": round(ma.avg_latency_ms - mb.avg_latency_ms, 1),
            "winner": (
                "a" if ma.avg_quality_score > mb.avg_quality_score
                else "b" if mb.avg_quality_score > ma.avg_quality_score
                else "tie"
            ),
        }

    def get_summary(self) -> Dict[str, Any]:
        """获取优化器概览"""
        return {
            "total_prompts": len(self._prompts),
            "total_templates": len(self._templates),
            "active_ab_tests": len([
                t for t in self._ab_tests.values()
                if t.status == ABTestStatus.RUNNING.value
            ]),
            "completed_ab_tests": len([
                t for t in self._ab_tests.values()
                if t.status == ABTestStatus.COMPLETED.value
            ]),
            "tracked_variants": len(self._metrics),
            "total_optimizations": len(self._optimization_history),
            "total_effect_records": len(self._effect_records),
        }

    def reset(self):
        """重置所有数据"""
        self._prompts.clear()
        self._prompt_versions.clear()
        self._templates.clear()
        self._ab_tests.clear()
        self._metrics.clear()
        self._optimization_history.clear()
        self._effect_records.clear()
        logger.info("PromptOptimizer reset")

    def _make_id(self, prefix: str) -> str:
        """生成唯一ID"""
        return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_prompt_optimizer: Optional[PromptOptimizer] = None


def get_prompt_optimizer(config: Optional[Dict] = None) -> PromptOptimizer:
    """获取全局单例"""
    global _prompt_optimizer
    if _prompt_optimizer is None:
        _prompt_optimizer = PromptOptimizer(config)
    return _prompt_optimizer


def reset_prompt_optimizer():
    """重置全局单例"""
    global _prompt_optimizer
    if _prompt_optimizer is not None:
        _prompt_optimizer.reset()
    _prompt_optimizer = None
