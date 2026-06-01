"""
v3.83 Thinking Depth Controller — @think=N 推理深度控制

功能:
1. @think=N 参数解析: 从用户输入提取 @think=0~4
2. 推理深度映射: 0最深(多步分解+自检) → 4最浅(直接回答)
3. 模型参数适配: 根据深度自动调整 max_tokens / temperature
4. 链式思考注入: 不同深度对应不同的 system prompt 引导
5. agent_loop 集成接口: 与 ResponseGenerator / AgentLoopPlugin 协同

用法:
    ctrl = ThinkingDepthController()
    parsed = ctrl.parse("@think=2 解释量子纠缠")
    # parsed.think_depth == 2
    # parsed.clean_text == "解释量子纠缠"
    params = ctrl.get_model_params(2)
    # params == {"max_tokens": 4096, "temperature": 0.5}
    prompt = ctrl.get_system_prompt(2)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 推理深度枚举
# ═══════════════════════════════════════════════════════════════

class ThinkDepth(IntEnum):
    """推理深度等级

    0 = 最深推理 — 多步分解 + 自我校验 + 替代方案探索
    4 = 最浅推理 — 直接回答，无需思考过程
    """
    DEEPEST = 0       # 多步分解 + 自检 + 替代方案探索
    DEEP = 1          # 详细推理 + 最终校验
    BALANCED = 2      # 适度推理，清晰回答（默认）
    SHALLOW = 3       # 简短推理后回答
    SHALLOWEST = 4    # 直接回答，无需阐述


# ═══════════════════════════════════════════════════════════════
# 深度 → 模型参数映射
# ═══════════════════════════════════════════════════════════════

DEPTH_MODEL_PARAMS: Dict[int, Dict[str, Any]] = {
    0: {
        "max_tokens": 16384,
        "temperature": 0.3,
        "top_p": 0.95,
        "description": "Deepest: multi-step decomposition + self-check + alternatives",
    },
    1: {
        "max_tokens": 8192,
        "temperature": 0.4,
        "top_p": 0.95,
        "description": "Deep: detailed reasoning with verification",
    },
    2: {
        "max_tokens": 4096,
        "temperature": 0.5,
        "top_p": 0.95,
        "description": "Balanced: moderate reasoning, clear answer (default)",
    },
    3: {
        "max_tokens": 2048,
        "temperature": 0.7,
        "top_p": 0.95,
        "description": "Shallow: brief reasoning then answer",
    },
    4: {
        "max_tokens": 1024,
        "temperature": 0.9,
        "top_p": 0.95,
        "description": "Shallowest: direct answer, no elaboration",
    },
}

# ═══════════════════════════════════════════════════════════════
# 深度 → 链式思考 System Prompt
# ═══════════════════════════════════════════════════════════════

_DEEPEST_PROMPT = """You are in DEEPEST reasoning mode (think=0).
For every problem, follow this rigorous process:
1. DECOMPOSE: Break the problem into atomic sub-problems. List each one explicitly.
2. ANALYZE: For each sub-problem, explore multiple solution paths. Compare pros/cons.
3. SYNTHESIZE: Combine sub-solutions into a coherent whole.
4. SELF-VERIFY: Critically examine your answer. Look for edge cases, logical gaps, and arithmetic errors.
5. ALTERNATIVES: Provide at least one alternative approach and explain why your chosen approach is better.
6. CONFIDENCE: Rate your confidence (0-100%) and explain any uncertainty.

Output format: Use structured sections with clear headers. Show your work."""

_DEEP_PROMPT = """You are in DEEP reasoning mode (think=1).
For each question:
1. Think step-by-step, explaining your reasoning clearly.
2. Verify your conclusion before presenting it.
3. If applicable, mention assumptions and edge cases.

Output format: Reasoning first, then a clear final answer."""

_BALANCED_PROMPT = """You are in BALANCED reasoning mode (think=2).
Reason through the problem systematically and provide a clear, well-structured answer.
Include enough detail to show your thinking, but prioritize clarity and conciseness."""

_SHALLOW_PROMPT = """You are in SHALLOW reasoning mode (think=3).
Provide a brief, focused answer. Include only essential reasoning.
Be concise — one or two sentences of thinking, then the answer."""

_SHALLOWEST_PROMPT = """You are in SHALLOWEST reasoning mode (think=4).
Answer directly with minimal explanation. No preamble, no elaboration.
Give the answer immediately."""

DEPTH_SYSTEM_PROMPTS: Dict[int, str] = {
    0: _DEEPEST_PROMPT,
    1: _DEEP_PROMPT,
    2: _BALANCED_PROMPT,
    3: _SHALLOW_PROMPT,
    4: _SHALLOWEST_PROMPT,
}

# ═══════════════════════════════════════════════════════════════
# 指令后缀 — 不同深度在用户消息末尾追加的引导语
# ═══════════════════════════════════════════════════════════════

DEPTH_INSTRUCTION_SUFFIX: Dict[int, str] = {
    0: "\n\n[Mode: think=0 — Deepest reasoning. Decompose, verify, explore alternatives.]",
    1: "\n\n[Mode: think=1 — Deep reasoning. Step-by-step with verification.]",
    2: "",
    3: "\n\n[Mode: think=3 — Shallow reasoning. Be brief.]",
    4: "\n\n[Mode: think=4 — Direct answer only. No explanation needed.]",
}


# ═══════════════════════════════════════════════════════════════
# 解析结果
# ═══════════════════════════════════════════════════════════════

@dataclass
class ThinkParseResult:
    """@think=N 解析结果"""
    think_depth: int                     # 解析后的深度值 0-4，默认 2
    clean_text: str                      # 去除 @think=N 后的用户原文
    raw_input: str = ""                  # 原始输入（保留）
    was_explicit: bool = False           # 是否显式指定了 @think=N
    parse_errors: list = field(default_factory=list)  # 解析中的错误/警告

    @property
    def depth_name(self) -> str:
        """返回人类可读的深度名称"""
        names = {
            0: "deepest",
            1: "deep",
            2: "balanced",
            3: "shallow",
            4: "shallowest",
        }
        return names.get(self.think_depth, "balanced")

    @property
    def is_valid(self) -> bool:
        """解析是否完全成功（无错误）"""
        return len(self.parse_errors) == 0


# ═══════════════════════════════════════════════════════════════
# Thinking Depth Controller
# ═══════════════════════════════════════════════════════════════

class ThinkingDepthController:
    """
    v3.83 推理深度控制器

    核心职责:
    - 解析用户输入中的 @think=N 指令
    - 将深度等级映射到模型参数 (max_tokens, temperature)
    - 根据深度生成对应的 system prompt 引导链式思考
    - 为 agent_loop 提供集成接口

    深度等级:
      0 = DEEPEST   — 多步分解 + 自检 + 替代方案探索
      1 = DEEP      — 详细推理 + 验证
      2 = BALANCED  — 适度推理 (默认)
      3 = SHALLOW   — 简短推理
      4 = SHALLOWEST— 直接回答

    用法:
        ctrl = ThinkingDepthController()
        result = ctrl.parse_user_input("@think=1 如何优化SQL查询？")
        params = ctrl.get_model_params(result.think_depth)
        prompt = ctrl.build_agent_context(result.think_depth, system_prompt="...")
    """

    # @think=N 正则 — 支持多种格式
    THINK_PATTERN = re.compile(
        r'@think\s*[=:：]\s*(-?\d+)', re.IGNORECASE
    )

    DEFAULT_DEPTH: int = 2          # 默认深度 (balanced)
    MIN_DEPTH: int = 0
    MAX_DEPTH: int = 4

    def __init__(self, default_depth: int = 2):
        """
        Args:
            default_depth: 当用户未指定 @think=N 时的默认深度 (0-4)
        """
        if not (self.MIN_DEPTH <= default_depth <= self.MAX_DEPTH):
            raise ValueError(
                f"default_depth must be {self.MIN_DEPTH}-{self.MAX_DEPTH}, "
                f"got {default_depth}"
            )
        self._default_depth = default_depth
        self._last_result: Optional[ThinkParseResult] = None

    # ── 核心 API ─────────────────────────────────────────────

    def parse(self, user_input: str) -> ThinkParseResult:
        """解析用户输入，提取 @think=N 指令。

        支持的格式:
          - @think=0
          - @think=3
          - @think:4
          - @think：2 (全角冒号)
          - @think = 1 (含空格)

        Args:
            user_input: 用户原始输入文本

        Returns:
            ThinkParseResult: 包含深度等级、清洗后文本等
        """
        errors: list = []
        raw = user_input.strip()
        match = self.THINK_PATTERN.search(raw)

        if not match:
            # 无 @think=N → 使用默认深度
            result = ThinkParseResult(
                think_depth=self._default_depth,
                clean_text=raw,
                raw_input=raw,
                was_explicit=False,
                parse_errors=[],
            )
            self._last_result = result
            return result

        # 提取数字
        try:
            raw_value = int(match.group(1))
        except ValueError:
            raw_value = self._default_depth

        # 钳制 + 警告
        depth = raw_value
        was_explicit = True

        if depth < self.MIN_DEPTH:
            errors.append(
                f"@think={raw_value} is below minimum ({self.MIN_DEPTH}), "
                f"clamped to {self.MIN_DEPTH}"
            )
            depth = self.MIN_DEPTH
        elif depth > self.MAX_DEPTH:
            errors.append(
                f"@think={raw_value} is above maximum ({self.MAX_DEPTH}), "
                f"clamped to {self.MAX_DEPTH}"
            )
            depth = self.MAX_DEPTH

        # 清洗文本：移除 @think=N 部分
        clean = self.THINK_PATTERN.sub("", raw).strip()
        # 清理可能遗留的多余空白
        clean = re.sub(r'\s+', ' ', clean).strip()

        result = ThinkParseResult(
            think_depth=depth,
            clean_text=clean,
            raw_input=raw,
            was_explicit=was_explicit,
            parse_errors=errors,
        )
        self._last_result = result
        return result

    # 别名，便于 agent_loop 集成
    def parse_user_input(self, user_input: str) -> ThinkParseResult:
        """parse() 的别名 — agent_loop 集成入口"""
        return self.parse(user_input)

    def get_model_params(self, depth: Optional[int] = None) -> Dict[str, Any]:
        """根据推理深度返回推荐的模型参数。

        Args:
            depth: 推理深度 0-4。若为 None，使用上次解析结果或默认深度。

        Returns:
            dict: {"max_tokens": int, "temperature": float, "top_p": float, "description": str}
        """
        if depth is None:
            depth = self._resolve_depth()

        depth = self._clamp(depth)
        return dict(DEPTH_MODEL_PARAMS.get(depth, DEPTH_MODEL_PARAMS[2]))

    def get_system_prompt(self, depth: Optional[int] = None) -> str:
        """根据推理深度返回对应的 system prompt。

        Args:
            depth: 推理深度 0-4。若为 None，使用上次解析结果或默认深度。

        Returns:
            str: 对应深度等级的 system prompt 文本
        """
        if depth is None:
            depth = self._resolve_depth()

        depth = self._clamp(depth)
        return DEPTH_SYSTEM_PROMPTS.get(depth, DEPTH_SYSTEM_PROMPTS[2])

    def get_instruction_suffix(self, depth: Optional[int] = None) -> str:
        """获取指令后缀，可追加到用户消息末尾。

        Args:
            depth: 推理深度 0-4

        Returns:
            str: 深度对应的指令后缀（depth=2 时为空字符串）
        """
        if depth is None:
            depth = self._resolve_depth()

        depth = self._clamp(depth)
        return DEPTH_INSTRUCTION_SUFFIX.get(depth, "")

    def build_agent_context(
        self,
        depth: Optional[int] = None,
        base_system_prompt: str = "",
        user_message: str = "",
    ) -> Dict[str, str]:
        """构建完整的 agent 上下文（system prompt + user message）。

        这是 agent_loop 集成的主要接口。
        将基础 system prompt 与深度引导 prompt 合并，
        可选地将指令后缀追加到用户消息。

        Args:
            depth: 推理深度 0-4
            base_system_prompt: agent 的基础 system prompt
            user_message: 用户消息文本

        Returns:
            dict: {"system": str, "user": str}
        """
        if depth is None:
            depth = self._resolve_depth()

        depth = self._clamp(depth)
        thinking_prompt = self.get_system_prompt(depth)
        suffix = self.get_instruction_suffix(depth)

        # 合并 system prompt
        if base_system_prompt:
            system = f"{base_system_prompt}\n\n{thinking_prompt}"
        else:
            system = thinking_prompt

        # 追加指令后缀
        user = user_message + suffix if suffix else user_message

        return {"system": system, "user": user}

    # ── 辅助方法 ─────────────────────────────────────────────

    def _resolve_depth(self) -> int:
        """解析当前有效深度（优先使用上次 parse 结果）"""
        if self._last_result is not None:
            return self._last_result.think_depth
        return self._default_depth

    @classmethod
    def _clamp(cls, depth: int) -> int:
        """钳制深度到有效范围"""
        return max(cls.MIN_DEPTH, min(cls.MAX_DEPTH, depth))

    @property
    def last_result(self) -> Optional[ThinkParseResult]:
        """获取最近一次解析结果"""
        return self._last_result

    @property
    def default_depth(self) -> int:
        return self._default_depth

    @default_depth.setter
    def default_depth(self, value: int):
        if not (self.MIN_DEPTH <= value <= self.MAX_DEPTH):
            raise ValueError(
                f"Depth must be {self.MIN_DEPTH}-{self.MAX_DEPTH}, got {value}"
            )
        self._default_depth = value

    # ── 深度元信息 ───────────────────────────────────────────

    @staticmethod
    def get_depth_info(depth: int) -> Dict[str, Any]:
        """获取指定深度的完整描述信息。

        Returns:
            dict: {
                "depth": int,
                "name": str,
                "params": {...},
                "prompt_preview": str (前80字符),
            }
        """
        depth = ThinkingDepthController._clamp(depth)
        params = DEPTH_MODEL_PARAMS.get(depth, DEPTH_MODEL_PARAMS[2])
        prompt = DEPTH_SYSTEM_PROMPTS.get(depth, DEPTH_SYSTEM_PROMPTS[2])
        names = {0: "deepest", 1: "deep", 2: "balanced", 3: "shallow", 4: "shallowest"}

        return {
            "depth": depth,
            "name": names.get(depth, "balanced"),
            "params": dict(params),
            "prompt_preview": prompt[:80] + "..." if len(prompt) > 80 else prompt,
        }

    @staticmethod
    def list_all_depths() -> list:
        """列出所有深度等级及其元信息"""
        return [ThinkingDepthController.get_depth_info(d) for d in range(5)]

    # ── agent_loop 集成方法 ──────────────────────────────────

    def apply_to_response_generator(
        self,
        generator,  # ResponseGenerator 实例
        depth: Optional[int] = None,
    ) -> None:
        """将推理深度注入 ResponseGenerator（修改其模板行为）。

        Args:
            generator: agent_loop 中的 ResponseGenerator 实例
            depth: 推理深度。None=使用上次解析结果。
        """
        if depth is None:
            depth = self._resolve_depth()
        depth = self._clamp(depth)

        # 深度 0-1: 详细模式 → 在 observation/decision 响应中追加推理提示
        if depth <= 1 and hasattr(generator, '_observation_response'):
            original = generator._observation_response

            def _deep_obs_response(data, style):
                response = original(data, style)
                if data.get("urgency", 0) > 0.6:
                    detail = "\n🔍 Deep analysis: breaking down into sub-problems..."
                    return response + detail
                return response

            generator._observation_response = _deep_obs_response

    def compute_token_budget(self, depth: Optional[int] = None) -> int:
        """根据深度计算 token 预算，供 agent_loop 的路由适配器使用。

        Args:
            depth: 推理深度

        Returns:
            int: 推荐的 token 预算
        """
        params = self.get_model_params(depth)
        return params["max_tokens"]


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

# 全局单例
_global_ctrl: Optional[ThinkingDepthController] = None


def get_thinking_controller(default_depth: int = 2) -> ThinkingDepthController:
    """获取全局 ThinkingDepthController 单例。

    Args:
        default_depth: 默认推理深度 (仅首次创建时生效)

    Returns:
        ThinkingDepthController
    """
    global _global_ctrl
    if _global_ctrl is None:
        _global_ctrl = ThinkingDepthController(default_depth=default_depth)
    return _global_ctrl


def quick_parse(user_input: str) -> Tuple[int, str]:
    """快速解析 @think=N，返回 (depth, clean_text)。

    Args:
        user_input: 用户输入

    Returns:
        (int, str): (深度 0-4, 清洗后文本)
    """
    ctrl = get_thinking_controller()
    result = ctrl.parse(user_input)
    return result.think_depth, result.clean_text


# ═══════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════

__all__ = [
    "ThinkDepth",
    "ThinkParseResult",
    "ThinkingDepthController",
    "get_thinking_controller",
    "quick_parse",
    "DEPTH_MODEL_PARAMS",
    "DEPTH_SYSTEM_PROMPTS",
    "DEPTH_INSTRUCTION_SUFFIX",
]
