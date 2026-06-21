"""meshctx smart_router — 智能模型路由"""
import re
from enum import Enum

class TaskComplexity(Enum):
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    EXPERT = 5

class ModelTier(Enum):
    BUDGET = 1
    STANDARD = 2
    PREMIUM = 3

class ModelInfo:
    def __init__(self, cost_per_1k_input, cost_per_1k_output, provider="openai", tier=ModelTier.STANDARD):
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self.provider = provider
        self.tier = tier

class RouteDecision:
    def __init__(self, selected_model, complexity, reasoning, fallback_model=""):
        self.selected_model = selected_model
        self.complexity = complexity
        self.reasoning = reasoning
        self.fallback_model = fallback_model or selected_model

class SmartModelRouter:
    def __init__(self):
        self._DEFAULT_MODELS = {
            "deepseek-chat": ModelInfo(0.14, 0.28, "deepseek", ModelTier.BUDGET),
            "deepseek-coder": ModelInfo(0.14, 0.28, "deepseek", ModelTier.BUDGET),
            "qwen-turbo": ModelInfo(0.07, 0.07, "qwen", ModelTier.BUDGET),
            "gpt-4o-mini": ModelInfo(0.15, 0.60, "openai", ModelTier.BUDGET),
            "gpt-4o": ModelInfo(2.5, 10.0, "openai", ModelTier.STANDARD),
            "claude-sonnet-4": ModelInfo(3.0, 15.0, "anthropic", ModelTier.STANDARD),
            "claude-sonnet-4-20250514": ModelInfo(3.0, 15.0, "anthropic", ModelTier.STANDARD),
            "gemini-2.5-pro": ModelInfo(1.25, 5.0, "google", ModelTier.STANDARD),
            "gemini-2.5-flash": ModelInfo(0.15, 0.60, "google", ModelTier.BUDGET),
            "claude-opus-4": ModelInfo(15.0, 75.0, "anthropic", ModelTier.PREMIUM),
            "gpt-4.5-preview": ModelInfo(12.5, 50.0, "openai", ModelTier.PREMIUM),
            "mistral-large": ModelInfo(2.0, 6.0, "mistral", ModelTier.STANDARD),
        }
        self._stats = {}
        self._budget = float("inf")
        self._spent_today = 0.0

    def estimate_complexity(self, prompt):
        prompt = str(prompt)
        score = 1
        if len(prompt) < 3:
            return TaskComplexity.TRIVIAL
        if len(prompt) >= 10:
            score = max(score, 2)
        if len(prompt) > 100:
            score = max(score, 3)
        if len(prompt) > 500:
            score = max(score, 4)
        if any(kw in prompt for kw in ["解释", "explain", "refactor", "重构", "优化", "optimize"]):
            score = max(score, 3)
        if any(kw in prompt for kw in ["架构", "architecture", "设计", "design", "分布式", "distributed"]):
            score = max(score, 4)
        if any(kw in prompt for kw in ["从零", "from scratch", "multi-agent", "multi agent"]):
            score = max(score, 5)
        return TaskComplexity(min(score, 5))

    def route(self, prompt, task_type="chat", preferred_provider=None):
        complexity = self.estimate_complexity(prompt)
        if complexity.value <= 2:
            tier_limit = ModelTier.BUDGET
        elif complexity.value <= 3:
            tier_limit = ModelTier.STANDARD
        else:
            tier_limit = ModelTier.PREMIUM

        # Collect candidate model IDs
        candidates = [(mid, m) for mid, m in self._DEFAULT_MODELS.items() if m.tier.value <= tier_limit.value]

        if preferred_provider:
            filtered = [(mid, m) for mid, m in candidates if m.provider == preferred_provider]
            if filtered:
                candidates = filtered
            else:
                # Fallback: any model from preferred provider regardless of tier
                any_provider = [(mid, m) for mid, m in self._DEFAULT_MODELS.items() if m.provider == preferred_provider]
                if any_provider:
                    candidates = any_provider

        if not candidates:
            selected = list(self._DEFAULT_MODELS.keys())[0]
        else:
            selected = candidates[0][0]

        reasoning = f"任务复杂度 {complexity.value}, 选择 {selected}"
        return RouteDecision(selected, complexity, reasoning, fallback_model=list(self._DEFAULT_MODELS.keys())[1])

    def record_usage(self, model_id, task_type, input_tokens, output_tokens, cost):
        if model_id not in self._stats:
            self._stats[model_id] = {"calls": 0, "total_tokens": 0, "total_cost": 0.0, "task_types": {}}
        self._stats[model_id]["calls"] += 1
        self._stats[model_id]["total_tokens"] += input_tokens + output_tokens
        info = self._DEFAULT_MODELS.get(model_id)
        if info:
            actual_cost = (input_tokens/1000)*info.cost_per_1k_input + (output_tokens/1000)*info.cost_per_1k_output
            self._stats[model_id]["total_cost"] += actual_cost
            self._spent_today += actual_cost
        if task_type not in self._stats[model_id]["task_types"]:
            self._stats[model_id]["task_types"][task_type] = 0
        self._stats[model_id]["task_types"][task_type] += 1

    def get_usage_report(self):
        total_calls = sum(s["calls"] for s in self._stats.values())
        total_cost = sum(s["total_cost"] for s in self._stats.values())
        by_model = {mid: {"calls": s["calls"], "cost": s["total_cost"]} for mid, s in self._stats.items()}
        by_task = {}
        for s in self._stats.values():
            for tt, cnt in s.get("task_types", {}).items():
                by_task[tt] = by_task.get(tt, 0) + cnt
        return {
            "total_calls": total_calls,
            "total_cost_usd": total_cost,
            "by_model": by_model,
            "by_task": by_task,
            "budget_cap": self._budget if self._budget != float("inf") else 0.0,
        }

    def get_optimization_tips(self):
        tips = []
        for mid, s in self._stats.items():
            info = self._DEFAULT_MODELS.get(mid)
            if info and info.tier == ModelTier.PREMIUM and s["calls"] > 10:
                tips.append(f"过度使用高级模型 {mid}，建议降级")
        return tips

    def can_afford(self, cost):
        if self._budget == float("inf"):
            return True
        return (self._spent_today + cost) <= self._budget

    def set_budget(self, amount):
        self._budget = float(amount)

def get_model_router():
    return SmartModelRouter()

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

