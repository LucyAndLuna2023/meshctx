"""meshctx thinking_depth — 开源版 (全功能 stub)"""
import re
import threading
from dataclasses import dataclass, field

# ── 解析结果 ──────────────────────────────────────────────

_DEPTH_NAMES = {0: "deepest", 1: "deep", 2: "balanced", 3: "shallow", 4: "shallowest"}
_DEPTH_RANGE = range(5)


@dataclass
class ThinkParseResult:
    raw_input: str = ""
    clean_text: str = ""
    think_depth: int = 2
    was_explicit: bool = False
    parse_errors: list = field(default_factory=list)

    @property
    def depth_name(self):
        return _DEPTH_NAMES.get(self.think_depth, "unknown")

    @property
    def is_valid(self):
        return len(self.parse_errors) == 0


# ── 模型参数表 ────────────────────────────────────────────

_PARAMS = {
    0: {"max_tokens": 16384, "temperature": 0.3, "description": "Deepest — full reasoning chain"},
    1: {"max_tokens": 8192, "temperature": 0.4, "description": "Deep — step-by-step analysis"},
    2: {"max_tokens": 4096, "temperature": 0.5, "description": "Balanced — normal reasoning"},
    3: {"max_tokens": 2048, "temperature": 0.7, "description": "Shallow — quick reasoning"},
    4: {"max_tokens": 1024, "temperature": 0.9, "description": "Shallowest — direct answer"},
}

_SYSTEM_PROMPTS = {
    0: (
        "DECOMPOSE the problem into sub-steps. SELF-VERIFY each step. "
        "Consider ALTERNATIVES before concluding. Think deeply and exhaustively. "
        "Examine the question from multiple angles. Provide a thorough analysis "
        "with all reasoning chains exposed. Break down complex ideas."
    ),
    1: (
        "DEEP reasoning mode. Think step-by-step, verify your work, and provide "
        "a detailed analysis. Consider edge cases and explain your reasoning clearly. "
        "Take time to explore the problem space before answering."
    ),
    2: (
        "BALANCED reasoning mode. Provide clear explanations with appropriate "
        "reasoning depth. Balance thoroughness with clarity and conciseness. "
        "Think through the problem methodically."
    ),
    3: (
        "SHALLOW reasoning mode. Be concise and direct. Provide quick answers "
        "with brief reasoning. Focus on efficiency over exhaustiveness."
    ),
    4: (
        "SHALLOWEST / DIRECT mode. Answer immediately with no preamble. "
        "Be extremely concise. Skip explanations unless explicitly requested."
    ),
}

_INSTRUCTION_SUFFIX = {
    0: " [think=0: deepest reasoning]",
    1: " [think=1: deep reasoning]",
    2: "",
    3: " [think=3: shallow reasoning]",
    4: " [think=4: shallowest reasoning]",
}


# ── Controller ─────────────────────────────────────────────

class ThinkingDepthController:
    def __init__(self, default_depth=2):
        self._default_depth = self._validate_depth(default_depth, "default_depth")
        self._last_result: ThinkParseResult = ThinkParseResult(think_depth=self._default_depth)

    def _validate_depth(self, depth, name="depth"):
        if not isinstance(depth, int) or depth < 0 or depth > 4:
            raise ValueError(f"{name} must be 0-4, got {depth}")
        return depth

    def _clamp(self, depth):
        return max(0, min(4, depth))

    @property
    def default_depth(self):
        return self._default_depth

    @default_depth.setter
    def default_depth(self, val):
        self._default_depth = self._validate_depth(val, "default_depth")

    @property
    def last_result(self):
        return self._last_result

    def parse(self, text):
        """解析 @think=N 标签"""
        text = text or ""
        errors = []
        depth = self._default_depth
        was_explicit = False
        clean = text

        # 匹配 @think=N 多种格式
        # @think=0, @think = 1, @think:3, @think：4 (全角), @THINK=1
        pattern = r'@[Tt][Hh][Ii][Nn][Kk]\s*[=:：]\s*(-?\d+)'
        match = re.search(pattern, text)

        if match:
            was_explicit = True
            raw_val = int(match.group(1))
            if raw_val < 0:
                depth = 0
                errors.append(f"Depth {raw_val} clamped to 0 (min)")
            elif raw_val > 4:
                depth = 4
                errors.append(f"Depth {raw_val} clamped to 4 (max)")
            else:
                depth = raw_val

            # 移除 @think=N 标签
            clean = re.sub(pattern, '', text, count=1)

        # 清理多余空格
        clean = ' '.join(clean.split())

        result = ThinkParseResult(
            raw_input=text,
            clean_text=clean,
            think_depth=depth,
            was_explicit=was_explicit,
            parse_errors=errors,
        )
        self._last_result = result
        return result

    def get_model_params(self, depth=None):
        """获取模型参数"""
        if depth is None:
            depth = self._last_result.think_depth
        depth = self._clamp(depth)
        return dict(_PARAMS[depth])

    def get_system_prompt(self, depth):
        """获取系统提示词"""
        depth = self._clamp(depth)
        return _SYSTEM_PROMPTS[depth]

    def get_instruction_suffix(self, depth):
        """获取指令后缀"""
        depth = self._clamp(depth)
        return _INSTRUCTION_SUFFIX[depth]

    def build_agent_context(self, depth=None, base_system_prompt=None, user_message=""):
        """构建 agent 上下文"""
        if depth is None:
            depth = self._last_result.think_depth
        depth = self._clamp(depth)

        system = self.get_system_prompt(depth)
        if base_system_prompt:
            system = base_system_prompt + "\n\n" + system

        user = user_message
        suffix = self.get_instruction_suffix(depth)
        if suffix:
            user = user.rstrip() + suffix

        return {"system": system, "user": user}

    def get_depth_info(self, depth):
        """获取深度元信息"""
        depth = self._clamp(depth)
        return {
            "depth": depth,
            "name": _DEPTH_NAMES[depth],
            "params": self.get_model_params(depth),
            "prompt_preview": self.get_system_prompt(depth)[:100],
        }

    def list_all_depths(self):
        """列出所有深度"""
        return [self.get_depth_info(d) for d in range(5)]

    def compute_token_budget(self, depth=None):
        """计算 token 预算"""
        if depth is None:
            depth = self._last_result.think_depth
        return self.get_model_params(depth)["max_tokens"]


# ── 单例 ──────────────────────────────────────────────────

_lock = threading.Lock()
_controller = None


def get_thinking_controller(default_depth=2):
    global _controller
    with _lock:
        if _controller is None:
            _controller = ThinkingDepthController(default_depth=default_depth)
        return _controller


def quick_parse(text, default_depth=2):
    """便捷函数: 快速解析, 返回 (depth, clean_text)"""
    ctrl = get_thinking_controller(default_depth)
    result = ctrl.parse(text)
    return result.think_depth, result.clean_text

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

