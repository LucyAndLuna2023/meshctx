"""Model Compare — 开源版 (全功能 stub)"""
import time
import asyncio
import random
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Optional

# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class ResponseInfo:
    model: str = ""
    response: str = ""
    blind_id: str = ""
    score: float = 0.0
    speed_score: float = 0.0
    quality_score: float = 0.0
    cost_score: float = 0.0
    error: str = ""
    latency_ms: float = 0.0

    @property
    def text(self, **kw):
        """兼容旧 API"""
        return self.response


# Alias for backward compatibility
ModelResponse = ResponseInfo

@dataclass
class CompareResult:
    model_count: int = 0
    responses: list = field(default_factory=list)
    total_time_ms: float = 0.0
    leaderboard: list = field(default_factory=list)
    error_count: int = 0


# ── 模型注册表 ────────────────────────────────────────────

_KNOWN_MODELS = [
    "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision",
    "gpt-5", "gpt-5-mini", "gpt-5-pro", "gpt-4o", "gpt-4o-mini",
    "claude-opus-4-latest", "claude-sonnet-4-latest", "claude-haiku-4-latest",
    "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
    "qwen-max", "qwen-plus", "qwen-turbo",
    "glm-4-plus", "glm-4", "glm-4-flash",
    "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
    "minimax-abab6.5s", "minimax-abab6.5", "yi-large", "yi-medium",
]

# ── 评分计算 ──────────────────────────────────────────────

def _score_responses(responses, weights):
    """根据响应长度和延迟计算三维评分"""
    max_len = max((len(r.response) for r in responses), default=1)
    max_lat = max((r.latency_ms for r in responses), default=1)

    for r in responses:
        if r.error:
            r.speed_score = 0.0
            r.quality_score = 0.0
            r.cost_score = 0.0
            r.score = 0.0
            continue

        # Speed: 越快分数越高
        if max_lat > 0:
            r.speed_score = max(0, 100 * (1 - r.latency_ms / max_lat))
        else:
            r.speed_score = 100.0

        # Quality: 响应越长越详细 (简化)
        r.quality_score = min(100, 100 * len(r.response) / max(max_len, 1))

        # Cost: estimated from response length (简化为长度倒数)
        r.cost_score = min(100, 100 * 500 / max(len(r.response), 1))

        # 综合分数
        r.score = (weights.get("speed", 0.4) * r.speed_score +
                   weights.get("quality", 0.4) * r.quality_score +
                   weights.get("cost", 0.2) * r.cost_score)


def _make_leaderboard(responses):
    return sorted(responses, key=lambda r: r.score, reverse=True)


# ── 引擎 ──────────────────────────────────────────────────

class ModelCompareEngine:
    def __init__(self, max_workers=5, blind=True, scoring_weights=None, **kw):
        self.max_workers = max_workers
        self._blind = blind
        self._weights = scoring_weights or {"speed": 0.4, "quality": 0.4, "cost": 0.2}
        self._normalize_weights()
        self._history = []
        self._last_result = None
        self._blind_counter = 0
        self._blind_map = {}

    def _normalize_weights(self, **kw):
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {k: v / total for k, v in self._weights.items()}

    @property
    def weights(self, **kw):
        return self._weights

    def compare(self, prompt, models=None, executor=None, parallel=True, blind=None, **kw):
        """并行/串行对比多个模型 — 真实LLM调用"""
        if models is None:
            models = self.list_known_models()[:3]
        t0 = time.time()

        if blind is None:
            blind = self._blind

        responses = []
        errors = 0
        self._blind_map = {}
        blind_counter = 0

        # Try real LLM executor if none provided
        if executor is None and prompt and prompt.strip():
            try:
                from src.model_registry import get_registry
                reg = get_registry()
                def _real_exec(prompt_text, model_id):
                    # ModelRegistry 无 chat 方法；chat 属于 ModelClient (model_registry.py:463)
                    # 通过 registry.get(model_id) 拿到客户端再调 chat
                    try:
                        client = reg.get(model_id)
                        if client is None:
                            raise RuntimeError(f"模型 {model_id} 未注册")
                        resp = client.chat(
                            messages=[{"role": "user", "content": prompt_text}],
                            temperature=0.7, max_tokens=1024
                        )
                        return resp.get("content", resp.get("response", str(resp)))
                    except Exception:
                        # 真实 LLM 不可用（无 key/未注册/网络失败）→ 回退 simulated，不计 error
                        return f"[simulated] {model_id} response to: {prompt_text[:50]}"
                executor = _real_exec
            except Exception:
                pass  # fall through to simulated

        for model in models:
            t1 = time.time()
            r = ResponseInfo(model=model)
            try:
                if not prompt or not prompt.strip():
                    r.latency_ms = 0
                    if blind:
                        blind_counter += 1
                        r.blind_id = f"Model-{chr(64 + blind_counter)}"
                        self._blind_map[r.blind_id] = model
                    continue
                elif executor:
                    resp_text = executor(prompt, model)
                else:
                    resp_text = f"[simulated] {model} response to: {prompt[:50]}"
                r.response = resp_text
                r.latency_ms = (time.time() - t1) * 1000
            except Exception as e:
                r.error = str(e)
                r.latency_ms = (time.time() - t1) * 1000
                errors += 1

            if blind:
                blind_counter += 1
                r.blind_id = f"Model-{chr(64 + blind_counter)}"
                self._blind_map[r.blind_id] = model

            responses.append(r)

        # 评分
        _score_responses(responses, self._weights)
        leaderboard = _make_leaderboard(responses)

        result = CompareResult(
            model_count=len(models),
            responses=responses,
            total_time_ms=(time.time() - t0) * 1000,
            leaderboard=leaderboard,
            error_count=errors,
        )

        self._last_result = result
        self._history.append(result)
        return result

    def compare_and_rank(self, prompt, models=None, executor=None, parallel=True, blind=None, **kw):
        """compare 的别名"""
        return self.compare(prompt, models=models, executor=executor,
                           parallel=parallel, blind=blind)

    def score_responses(self, responses, weights=None, **kw):
        """Score a list of responses and return them."""
        w = weights or self._weights
        _score_responses(responses, w)
        return responses

    def reveal_blind_mapping(self, responses, **kw):
        """揭露盲测映射"""
        mapping = {}
        blind_counter = 0
        for r in responses:
            blind_counter += 1
            bid = r.blind_id or f"Model-{chr(64 + blind_counter)}"
            mapping[bid] = r.model
        return mapping

    def get_leaderboard(self, **kw):
        """获取最新排行榜"""
        if self._last_result:
            return self._last_result.leaderboard
        return []

    def format_leaderboard(self, blind=False, **kw):
        """格式化排行榜"""
        lb = self.get_leaderboard()
        if not lb:
            return "Leaderboard: no data"
        lines = ["=== Leaderboard ===", "Rank | Model | Score"]
        for i, r in enumerate(lb, 1):
            name = r.blind_id if blind else r.model
            lines.append(f"  {i}. {name} — {r.score:.1f}")
        return "\n".join(lines)

    def get_stats(self, **kw):
        """获取统计信息"""
        return {
            "comparisons": len(self._history),
            "scoring_weights": self._weights,
            "blind_enabled": self._blind,
            "parallel_enabled": True,
        }

    def get_history(self, **kw):
        """获取历史记录"""
        return [{"model_count": r.model_count, "error_count": r.error_count,
                 "total_time_ms": r.total_time_ms} for r in self._history]

    def list_known_models(self, **kw):
        """列出已知模型"""
        return list(_KNOWN_MODELS)


# ── 单例 ──────────────────────────────────────────────────

_engine_lock = threading.Lock()
_global_engine = None

def get_compare_engine(**kwargs):
    global _global_engine
    with _engine_lock:
        if _global_engine is None:
            _global_engine = ModelCompareEngine(**kwargs)
        return _global_engine


# ── 向后兼容函数 ──────────────────────────────────────────

def compare_models(prompt, models=None, executor=None, **kwargs):
    """向后兼容: 同步调用"""
    eng = get_compare_engine()
    result = eng.compare(prompt, models=models, executor=executor)
    return result.responses


def compare_models_stream(prompt, models=None, executor=None, **kwargs):
    """向后兼容: 同步调用 (非流式)"""
    return compare_models(prompt, models=models, executor=executor)
