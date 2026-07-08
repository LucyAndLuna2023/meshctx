"""
meshctx Prompt Engine v3.50 — 提示词模板引擎
=============================================
提供 Jinja2 风格的 Prompt 模板系统，支持变量注入、
条件渲染、Few-shot 管理、版本控制和 Token 估算。

核心功能:
  1. 模板渲染 — {{ variable }} 语法，支持嵌套和过滤器
  2. 条件渲染 — {% if/elif/else/endif %} 条件块
  3. Few-shot 管理 — 动态插入/管理少样本示例
  4. 版本管理 — Prompt 版本追踪与回滚
  5. Token 估算 — 基于字符/词的 Token 规模估算
  6. 角色分离 — system / user / assistant 消息结构

设计对标:
  - Jinja2 模板语法
  - LangChain PromptTemplate
  - OpenAI ChatCompletion messages 格式

使用示例:
  engine = get_prompt_engine()

  # 注册模板
  engine.register_template("code_review", "Review this code:\n```\n{{ code }}\n```\nFocus on: {{ focus }}")

  # 渲染
  prompt = engine.render("code_review", {"code": "print('hello')", "focus": "security"})

  # Few-shot
  engine.add_few_shot("sentiment", {"input": "I love this!", "output": "positive"})
  prompt = engine.render_with_few_shot("sentiment", {"text": "This is terrible"})
"""

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.prompt_engine")


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

# Token 估算: 英文约 1 token / 4 字符, 中文约 1 token / 1.5 字符
TOKEN_ESTIMATE_EN: float = 0.25   # 每字符 token 数
TOKEN_ESTIMATE_ZH: float = 0.67   # 每字符 token 数
CHINESE_CHAR_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class PromptRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class TemplateTag(str, Enum):
    """模板标签"""
    GENERAL = "general"
    CODE = "code"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    INSTRUCTION = "instruction"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class FewShotExample:
    """少样本示例"""
    example_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    explanation: str = ""
    weight: float = 1.0                     # 示例权重
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "input": self.input_data,
            "output": self.output_data,
            "explanation": self.explanation,
            "weight": self.weight,
            "tags": self.tags,
        }


@dataclass
class PromptTemplate:
    """提示模板定义"""
    template_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    system_prompt: str = ""                 # 系统提示
    user_template: str = ""                 # 用户提示模板 (含 {{ }} 变量)
    role: PromptRole = PromptRole.USER
    tags: List[str] = field(default_factory=list)
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    variables: Set[str] = field(default_factory=set)   # 从模板自动提取的变量名
    metadata: Dict[str, Any] = field(default_factory=dict)
    few_shot_examples: List[FewShotExample] = field(default_factory=list)
    max_few_shot: int = 5                  # 渲染时最多插入几个 few-shot

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "user_template": self.user_template,
            "version": self.version,
            "variables": sorted(self.variables),
            "tags": self.tags,
            "few_shot_count": len(self.few_shot_examples),
        }


@dataclass
class PromptVersion:
    """模板版本快照"""
    version: int
    system_prompt: str
    user_template: str
    created_at: float = field(default_factory=time.time)
    change_note: str = ""


@dataclass
class RenderedPrompt:
    """渲染结果"""
    template_name: str
    system_prompt: str
    user_prompt: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    estimated_tokens: int = 0
    variables_used: Dict[str, Any] = field(default_factory=dict)
    few_shot_count: int = 0

    def to_openai_messages(self, **kw) -> List[Dict[str, str]]:
        """转换为 OpenAI ChatCompletion 消息格式"""
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(self.messages)
        if self.user_prompt:
            msgs.append({"role": "user", "content": self.user_prompt})
        return msgs


# ═══════════════════════════════════════════════════════════
# PromptEngine
# ═══════════════════════════════════════════════════════════

class PromptEngine:
    """
    提示模板引擎。

    核心方法:
      - register_template(name, template_str) → PromptTemplate
      - render(name, variables) → RenderedPrompt
      - render_with_few_shot(name, variables) → RenderedPrompt
      - add_few_shot(name, input, output)
      - estimate_tokens(text) → int
      - save_version(name) → PromptVersion
      - rollback(name, version)
    """

    def __init__(self, **kw):
        self._templates: Dict[str, PromptTemplate] = {}       # name → template
        self._versions: Dict[str, List[PromptVersion]] = {}   # name → [versions]
        self._render_count: int = 0
        self._cache: Dict[str, RenderedPrompt] = {}           # render cache

    # ── 模板注册与管理 ─────────────────────────────────────

    def register_template(
        self,
        name: str,
        user_template: str,
        system_prompt: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        role: PromptRole = PromptRole.USER,
        max_few_shot: int = 5,
    ) -> PromptTemplate:
        """
        注册或更新模板。

        Args:
            name: 模板名称 (唯一标识)
            user_template: 用户提示模板，使用 {{ variable }} 语法
            system_prompt: 系统提示词
            description: 模板描述
            tags: 标签
            role: 消息角色
            max_few_shot: 最大 few-shot 数量

        Returns:
            PromptTemplate 对象
        """
        variables = self._extract_variables(user_template)
        # 也从 system_prompt 提取变量
        variables.update(self._extract_variables(system_prompt))

        if name in self._templates:
            # 更新已有模板 → 先保存版本
            existing = self._templates[name]
            self._save_version(name, existing.system_prompt, existing.user_template,
                               f"Auto-saved before update to v{existing.version + 1}")
            tmpl = existing
            tmpl.user_template = user_template
            tmpl.system_prompt = system_prompt
            tmpl.description = description or tmpl.description
            tmpl.tags = tags or tmpl.tags
            tmpl.max_few_shot = max_few_shot
            tmpl.variables = variables
            tmpl.version += 1
            tmpl.updated_at = time.time()
            logger.info(f"Updated template '{name}' to v{tmpl.version}")
        else:
            tmpl = PromptTemplate(
                name=name,
                description=description,
                system_prompt=system_prompt,
                user_template=user_template,
                role=role,
                tags=tags or [],
                variables=variables,
                max_few_shot=max_few_shot,
            )
            self._templates[name] = tmpl
            logger.info(f"Registered template '{name}' (v1)")

        # 清除缓存
        self._cache.pop(name, None)
        return tmpl

    def get_template(self, name: str, **kw) -> Optional[PromptTemplate]:
        """获取模板"""
        return self._templates.get(name)

    def list_templates(self, tag: Optional[str] = None, **kw) -> List[Dict[str, Any]]:
        """列出模板"""
        result = []
        for tmpl in self._templates.values():
            if tag and tag not in tmpl.tags:
                continue
            result.append(tmpl.to_dict())
        return result

    def delete_template(self, name: str, **kw) -> bool:
        """删除模板"""
        if name in self._templates:
            del self._templates[name]
            self._cache.pop(name, None)
            self._versions.pop(name, None)
            return True
        return False

    # ── 变量提取 ───────────────────────────────────────────

    def _extract_variables(self, template_str: str, **kw) -> Set[str]:
        """从模板字符串提取 {{ variable }} 变量名"""
        pattern = re.compile(r'\{\{\s*(\w+(?:\.\w+)*)\s*(?:\|[^}]*)?\}\}')
        return set(pattern.findall(template_str))

    # ── 模板渲染 ───────────────────────────────────────────

    def render(
        self,
        name: str,
        variables: Optional[Dict[str, Any]] = None,
        cache: bool = False,
    ) -> Optional[RenderedPrompt]:
        """
        渲染模板。

        Args:
            name: 模板名称
            variables: 变量字典
            cache: 是否缓存渲染结果

        Returns:
            RenderedPrompt 或 None (模板不存在时)
        """
        tmpl = self._templates.get(name)
        if tmpl is None:
            logger.error(f"Template '{name}' not found")
            return None

        if cache and name in self._cache:
            return self._cache[name]

        vars_dict = dict(variables or {})

        # 检查缺失变量
        missing = tmpl.variables - set(vars_dict.keys())
        for m in missing:
            vars_dict[m] = f"<MISSING:{m}>"
            logger.warning(f"Variable '{m}' not provided for template '{name}'")

        # 渲染 system prompt
        system_prompt = self._render_string(tmpl.system_prompt, vars_dict)

        # 渲染 user prompt
        user_prompt = self._render_string(tmpl.user_template, vars_dict)

        # 构建 messages
        messages = []
        for ex in tmpl.few_shot_examples[:tmpl.max_few_shot]:
            ex_input = self._render_string(
                json.dumps(ex.input_data, ensure_ascii=False), vars_dict
            )
            ex_output = str(ex.output_data) if ex.output_data is not None else ""
            messages.append({"role": "user", "content": ex_input})
            messages.append({"role": "assistant", "content": ex_output})

        total_tokens = (
            self.estimate_tokens(system_prompt) +
            self.estimate_tokens(user_prompt) +
            sum(self.estimate_tokens(m["content"]) for m in messages)
        )

        result = RenderedPrompt(
            template_name=name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            estimated_tokens=total_tokens,
            variables_used=vars_dict,
            few_shot_count=len(tmpl.few_shot_examples[:tmpl.max_few_shot]),
        )

        if cache:
            self._cache[name] = result

        self._render_count += 1
        return result

    def render_with_few_shot(
        self,
        name: str,
        variables: Optional[Dict[str, Any]] = None,
        extra_examples: Optional[List[FewShotExample]] = None,
    ) -> Optional[RenderedPrompt]:
        """
        渲染模板并附加 few-shot 示例。

        Args:
            name: 模板名称
            variables: 变量
            extra_examples: 额外的 few-shot 示例 (追加到模板已注册的示例之后)

        Returns:
            RenderedPrompt
        """
        tmpl = self._templates.get(name)
        if tmpl is None:
            logger.error(f"Template '{name}' not found")
            return None

        # 临时追加示例
        original_examples = tmpl.few_shot_examples
        if extra_examples:
            tmpl.few_shot_examples = original_examples + extra_examples

        try:
            return self.render(name, variables)
        finally:
            tmpl.few_shot_examples = original_examples

    def _render_string(self, template: str, variables: Dict[str, Any], **kw) -> str:
        """
        渲染字符串模板。

        支持:
          {{ variable }}        → 变量替换
          {{ variable|default }} → 带默认值的变量
          {{ nested.key }}      → 嵌套访问 (变量中的点分隔键)
          {% if var %}...{% endif %}  → 条件块
          {% if not var %}...{% endif %}
          {% if var %}...{% else %}...{% endif %}
        """
        result = template

        # 1. 处理条件块 {% if ... %} ... {% endif %} / {% else %}
        result = self._render_conditionals(result, variables)

        # 2. 处理变量替换 {{ ... }}
        def replace_var(match, **kw):
            inner = match.group(1).strip()
            # 检查是否有过滤器 (|)
            if '|' in inner:
                var_expr, default_val = inner.split('|', 1)
                var_expr = var_expr.strip()
                default_val = default_val.strip()
            else:
                var_expr = inner
                default_val = ""

            # 解析点分隔的嵌套键
            keys = var_expr.split('.')
            val = variables
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k, None)
                else:
                    val = None
                    break

            if val is not None:
                return str(val)
            return default_val if default_val else f"{{{{ {inner} }}}}"

        result = re.sub(r'\{\{\s*(.+?)\s*\}\}', replace_var, result)
        return result

    def _render_conditionals(self, template: str, variables: Dict[str, Any], **kw) -> str:
        """渲染 {% if ... %} ... {% endif %} 条件块"""
        # 匹配完整的 if/else/endif 块
        pattern = re.compile(
            r'\{%\s*if\s+(not\s+)?(\w+(?:\.\w+)*)\s*%\}'
            r'(.*?)'
            r'(?:\{%\s*else\s*%\}(.*?))?'
            r'\{%\s*endif\s*%\}',
            re.DOTALL
        )

        def replace_conditional(match, **kw):
            negate = match.group(1) is not None
            var_name = match.group(2)
            if_block = match.group(3)
            else_block = match.group(4) or ""

            # 解析变量值
            keys = var_name.split('.')
            val = variables
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k, None)
                else:
                    val = None
                    break

            condition = bool(val)
            if negate:
                condition = not condition

            return if_block if condition else else_block

        # 递归处理嵌套条件
        prev = None
        while prev != template:
            prev = template
            template = pattern.sub(replace_conditional, template)

        return template

    # ── Few-shot 管理 ──────────────────────────────────────

    def add_few_shot(
        self,
        template_name: str,
        input_data: Dict[str, Any],
        output_data: Any,
        explanation: str = "",
        weight: float = 1.0,
        tags: Optional[List[str]] = None,
    ) -> Optional[FewShotExample]:
        """向模板添加 few-shot 示例"""
        tmpl = self._templates.get(template_name)
        if tmpl is None:
            logger.error(f"Template '{template_name}' not found")
            return None

        example = FewShotExample(
            input_data=input_data,
            output_data=output_data,
            explanation=explanation,
            weight=weight,
            tags=tags or [],
        )
        tmpl.few_shot_examples.append(example)
        # 按权重排序 (高权重优先)
        tmpl.few_shot_examples.sort(key=lambda e: e.weight, reverse=True)
        # 清除缓存
        self._cache.pop(template_name, None)
        logger.debug(f"Added few-shot example to '{template_name}' (total: {len(tmpl.few_shot_examples)})")
        return example

    def remove_few_shot(self, template_name: str, example_id: str, **kw) -> bool:
        """移除 few-shot 示例"""
        tmpl = self._templates.get(template_name)
        if tmpl is None:
            return False
        before = len(tmpl.few_shot_examples)
        tmpl.few_shot_examples = [e for e in tmpl.few_shot_examples if e.example_id != example_id]
        if len(tmpl.few_shot_examples) < before:
            self._cache.pop(template_name, None)
            return True
        return False

    def clear_few_shots(self, template_name: str, **kw):
        """清除模板的所有 few-shot 示例"""
        tmpl = self._templates.get(template_name)
        if tmpl:
            tmpl.few_shot_examples.clear()
            self._cache.pop(template_name, None)

    def get_few_shots(self, template_name: str, **kw) -> List[FewShotExample]:
        """获取模板的 few-shot 示例"""
        tmpl = self._templates.get(template_name)
        return tmpl.few_shot_examples if tmpl else []

    # ── 版本管理 ───────────────────────────────────────────

    def _save_version(self, name: str, system_prompt: str, user_template: str, note: str = "", **kw):
        """保存模板版本"""
        if name not in self._versions:
            self._versions[name] = []
        existing = self._templates.get(name)
        version_num = existing.version if existing else len(self._versions[name]) + 1
        pv = PromptVersion(
            version=version_num,
            system_prompt=system_prompt,
            user_template=user_template,
            change_note=note,
        )
        self._versions[name].append(pv)

    def save_version(self, name: str, note: str = "", **kw) -> Optional[PromptVersion]:
        """手动保存当前模板版本"""
        tmpl = self._templates.get(name)
        if tmpl is None:
            return None
        pv = PromptVersion(
            version=tmpl.version,
            system_prompt=tmpl.system_prompt,
            user_template=tmpl.user_template,
            change_note=note,
        )
        if name not in self._versions:
            self._versions[name] = []
        self._versions[name].append(pv)
        logger.info(f"Saved version {pv.version} for template '{name}'")
        return pv

    def get_versions(self, name: str, **kw) -> List[PromptVersion]:
        """获取模板的所有版本"""
        return self._versions.get(name, [])

    def rollback(self, name: str, version: int, **kw) -> bool:
        """回滚到指定版本"""
        versions = self._versions.get(name, [])
        target = None
        for v in versions:
            if v.version == version:
                target = v
                break

        if target is None:
            logger.error(f"Version {version} not found for template '{name}'")
            return False

        # 保存当前版本
        tmpl = self._templates.get(name)
        if tmpl:
            self._save_version(name, tmpl.system_prompt, tmpl.user_template,
                              f"Auto-saved before rollback to v{version}")

        # 回滚
        self.register_template(
            name=name,
            user_template=target.user_template,
            system_prompt=target.system_prompt,
        )
        logger.info(f"Rolled back template '{name}' to v{version}")
        return True

    # ── Token 估算 ─────────────────────────────────────────

    def estimate_tokens(self, text: str, **kw) -> int:
        """
        估算文本的 token 数量。

        使用启发式方法:
          - 英文: ~4 字符 = 1 token
          - 中文: ~1.5 字符 = 1 token
          - 数字/标点: 按英文处理

        Args:
            text: 输入文本

        Returns:
            估算的 token 数
        """
        if not text:
            return 0

        zh_chars = len(CHINESE_CHAR_PATTERN.findall(text))
        en_chars = len(text) - zh_chars

        est_zh = int(zh_chars * TOKEN_ESTIMATE_ZH)
        est_en = int(en_chars * TOKEN_ESTIMATE_EN)
        return max(1, est_zh + est_en)

    def estimate_messages_tokens(self, messages: List[Dict[str, str]], **kw) -> int:
        """
        估算 OpenAI 消息格式的总 token 数。

        每条消息额外 +4 tokens (消息边界开销)
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += self.estimate_tokens(content) + 4
        return total + 2  # 对话级别开销

    # ── 批量操作 ───────────────────────────────────────────

    def render_batch(
        self,
        name: str,
        variable_sets: List[Dict[str, Any]],
    ) -> List[Optional[RenderedPrompt]]:
        """
        批量渲染同一模板的多组变量。

        Args:
            name: 模板名称
            variable_sets: 变量字典列表

        Returns:
            RenderedPrompt 列表 (缺失模板时为 None)
        """
        return [self.render(name, varset) for varset in variable_sets]

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取引擎统计"""
        total_few_shots = sum(len(t.few_shot_examples) for t in self._templates.values())
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "template_count": len(self._templates),
            "render_count": self._render_count,
            "total_few_shots": total_few_shots,
            "total_versions": total_versions,
            "cache_size": len(self._cache),
            "all_variables": sorted(set().union(*(t.variables for t in self._templates.values()))),
        }

    def clear_cache(self, **kw):
        """清除渲染缓存"""
        self._cache.clear()


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_prompt_engine: Optional[PromptEngine] = None


def get_prompt_engine() -> PromptEngine:
    """获取全局 PromptEngine 单例"""
    global _prompt_engine
    if _prompt_engine is None:
        _prompt_engine = PromptEngine()
        logger.info("PromptEngine initialized")
    return _prompt_engine


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def register_prompt(
    name: str,
    template: str,
    system_prompt: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
) -> PromptTemplate:
    """快速注册模板"""
    return get_prompt_engine().register_template(
        name=name,
        user_template=template,
        system_prompt=system_prompt,
        description=description,
        tags=tags,
    )


def render_prompt(name: str, variables: Optional[Dict[str, Any]] = None) -> Optional[RenderedPrompt]:
    """快速渲染模板"""
    return get_prompt_engine().render(name, variables)


def estimate_tokens(text: str) -> int:
    """快速估算 token 数"""
    return get_prompt_engine().estimate_tokens(text)
