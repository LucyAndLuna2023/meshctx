"""
meshctx v3.87 — Model Compare Blind Test (模型对比盲测引擎)

并行多模型同prompt → 盲测评分(速度/质量/成本) → 排行榜

Capabilities:
  1. Parallel execution — ThreadPoolExecutor concurrent multi-model calls
  2. Blind testing — random model IDs assigned during scoring to eliminate bias
  3. Multi-dimensional scoring — Speed (latency), Quality (completeness+relevance), Cost (token efficiency)
  4. Leaderboard — ranked model comparison with detailed per-dimension breakdown
  5. Configurable models list and scoring weights
  6. Backward-compatible with v3.67 API (compare, score_responses, get_stats)
"""

import logging
import time
import uuid
import concurrent.futures
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional, Tuple

logger = logging.getLogger("meshctx.model_compare")

# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class ModelResponse:
    """Single model response with scoring metadata"""
    model: str
    response: str
    latency_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    score: float = 0.0
    speed_score: float = 0.0
    quality_score: float = 0.0
    cost_score: float = 0.0
    error: str = ""
    blind_id: str = ""  # Anonymous ID for blind testing

    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "response": self.response[:500],
            "latency_ms": self.latency_ms,
            "tokens": self.tokens,
            "cost": self.cost,
            "score": self.score,
            "speed_score": self.speed_score,
            "quality_score": self.quality_score,
            "cost_score": self.cost_score,
            "error": self.error,
            "blind_id": self.blind_id,
        }


@dataclass
class CompareResult:
    """Complete comparison result with leaderboard"""
    prompt: str
    responses: List[ModelResponse] = field(default_factory=list)
    leaderboard: List[ModelResponse] = field(default_factory=list)
    total_time_ms: float = 0.0
    blind_mode: bool = True
    model_count: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "prompt": self.prompt[:200],
            "total_time_ms": self.total_time_ms,
            "blind_mode": self.blind_mode,
            "model_count": self.model_count,
            "error_count": self.error_count,
            "leaderboard": [
                {"rank": i + 1, "model": r.model, "score": r.score,
                 "speed": r.speed_score, "quality": r.quality_score,
                 "cost": r.cost_score, "latency_ms": r.latency_ms}
                for i, r in enumerate(self.leaderboard)
            ],
        }


# ═══════════════════════════════════════════════════════════
# Scoring Weights & Model Registry
# ═══════════════════════════════════════════════════════════

# Default scoring weights (must sum to 1.0)
DEFAULT_WEIGHTS = {
    "speed": 0.30,
    "quality": 0.45,
    "cost": 0.25,
}

# Cost per 1K tokens (approximate, USD) for known models
MODEL_COST_PER_1K = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-v4-pro": {"input": 0.00014, "output": 0.00028},
    "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
}

# Default models to compare
DEFAULT_MODELS = [
    "deepseek-chat",
    "deepseek-v4-pro",
    "gpt-4o-mini",
    "claude-3.5-sonnet",
    "claude-3-haiku",
]


# ═══════════════════════════════════════════════════════════
# Model Compare Engine v3.87
# ═══════════════════════════════════════════════════════════

class ModelCompareEngine:
    """Parallel multi-model blind-test comparison engine.

    Sends the same prompt to multiple models in parallel, scores responses
    blindly (anonymized model names) on three dimensions — speed, quality,
    cost — and produces a ranked leaderboard.

    Configuration:
        max_workers:       thread pool size for parallel execution (default 10)
        default_models:    models to compare when none specified
        blind:             enable blind testing by default (default True)
        parallel:          enable parallel execution by default (default True)
        scoring_weights:   dict of {speed, quality, cost} weights
    """

    # Extended model registry (46 meshctx models + common providers)
    KNOWN_MODELS: List[str] = [
        # DeepSeek family
        "deepseek-chat", "deepseek-v4-pro", "deepseek-reasoner",
        # OpenAI family
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini",
        # Anthropic family
        "claude-3.5-sonnet", "claude-3-opus", "claude-3-haiku",
        "claude-3.5-haiku",
        # Google family
        "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash",
        # Meta / Open
        "llama-3-70b", "llama-3-405b", "llama-3.1-8b", "llama-3.1-70b",
        # Mistral
        "mistral-large", "mistral-medium", "mistral-small",
        # Cohere
        "command-r-plus", "command-r",
        # Qwen
        "qwen-max", "qwen-plus", "qwen-turbo",
        # Grok
        "grok-2", "grok-2-mini",
        # Other
        "yi-large", "yi-medium",
        "baichuan-4", "baichuan-3-turbo",
        "ernie-4.0", "ernie-3.5",
        "hunyuan-pro", "hunyuan-turbo",
        "spark-4.0", "spark-3.5",
        "abab-6.5", "abab-6.5s",
        "glm-4", "glm-4-flash",
        "phi-3-medium", "phi-3-small",
        "wizardlm-2", "mixtral-8x22b", "dbrx",
    ]

    def __init__(
        self,
        max_workers: int = 10,
        default_models: Optional[List[str]] = None,
        blind: bool = True,
        parallel: bool = True,
        scoring_weights: Optional[Dict[str, float]] = None,
    ):
        self.max_workers = max(max_workers, 1)
        self.default_models = default_models or DEFAULT_MODELS[:]
        self.blind = blind
        self.parallel = parallel
        self.weights = scoring_weights or DEFAULT_WEIGHTS.copy()

        # Normalize weights
        w_total = sum(self.weights.values())
        if w_total > 0:
            self.weights = {k: v / w_total for k, v in self.weights.items()}

        self._compare_history: List[CompareResult] = []
        self._stats = {"comparisons": 0, "total_responses": 0, "errors": 0}

    # ── Parallel Execution ──────────────────────────────────

    def _execute_single(self, prompt: str, model: str,
                        executor: Optional[Callable] = None) -> ModelResponse:
        """Execute a single model call with timing."""
        t0 = time.perf_counter()
        try:
            if executor:
                resp = executor(prompt, model)
            else:
                # Fallback: simulated response
                resp = f"[{model}] simulated response to: {prompt[:50]}..."
                time.sleep(0.05)  # Simulate minimal latency

            latency = (time.perf_counter() - t0) * 1000
            response_text = str(resp) if resp else ""

            # Estimate tokens (simple heuristic: ~4 chars per token)
            estimated_tokens = max(1, len(response_text) // 4)

            # Estimate cost
            cost = self._estimate_cost(model, len(prompt) // 4, estimated_tokens)

            return ModelResponse(
                model=model,
                response=response_text,
                latency_ms=round(latency, 2),
                tokens=estimated_tokens,
                cost=round(cost, 6),
            )
        except Exception as e:
            latency = (time.perf_counter() - t0) * 1000
            logger.warning("ModelCompare: %s failed: %s", model, e)
            return ModelResponse(
                model=model,
                response="",
                latency_ms=round(latency, 2),
                error=str(e)[:200],
            )

    def _estimate_cost(self, model: str, prompt_tokens: int,
                       completion_tokens: int) -> float:
        """Estimate API cost based on model pricing."""
        pricing = MODEL_COST_PER_1K.get(model)
        if pricing:
            return (
                prompt_tokens / 1000 * pricing["input"]
                + completion_tokens / 1000 * pricing["output"]
            )
        # Default cost estimate for unknown models
        return (prompt_tokens + completion_tokens) / 1000 * 0.001

    # ── Blind ID Generation ─────────────────────────────────

    @staticmethod
    def _generate_blind_ids(count: int) -> List[str]:
        """Generate anonymous blind IDs like 'Model-A', 'Model-B', etc."""
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if count <= 26:
            return [f"Model-{letters[i]}" for i in range(count)]
        # If more than 26, use double letters
        ids = [f"Model-{letters[i]}" for i in range(min(count, 26))]
        for i in range(26, count):
            ids.append(f"Model-{letters[i // 26 - 1]}{letters[i % 26]}")
        return ids

    # ── Core Comparison ─────────────────────────────────────

    def compare(
        self,
        prompt: str,
        models: Optional[List[str]] = None,
        executor: Optional[Callable] = None,
        blind: Optional[bool] = None,
        parallel: Optional[bool] = None,
    ) -> CompareResult:
        """Execute multi-model comparison and return ranked results.

        Args:
            prompt:    the prompt/question to send to all models
            models:    list of model names (default: DEFAULT_MODELS)
            executor:  callable(prompt, model) -> str for actual LLM execution
            blind:     enable blind testing (override instance default)
            parallel:  enable parallel execution (override instance default)

        Returns:
            CompareResult with responses, leaderboard, and metadata
        """
        _blind = blind if blind is not None else self.blind
        _parallel = parallel if parallel is not None else self.parallel
        _models = models if models is not None else self.default_models

        if not _models:
            return CompareResult(prompt=prompt, model_count=0)

        if not prompt or not prompt.strip():
            return CompareResult(prompt=prompt or "", model_count=len(_models))

        t_start = time.perf_counter()

        # Generate blind IDs upfront (before execution, to keep mapping hidden)
        blind_ids = self._generate_blind_ids(len(_models))

        t0 = time.perf_counter()
        responses: List[ModelResponse] = []

        if _parallel and len(_models) > 1:
            # Parallel execution with ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(_models))
            ) as pool:
                futures = {
                    pool.submit(self._execute_single, prompt, model, executor): (i, model)
                    for i, model in enumerate(_models)
                }
                # Collect results, preserving insertion order via index
                ordered: Dict[int, ModelResponse] = {}
                for future in concurrent.futures.as_completed(futures):
                    idx, model = futures[future]
                    try:
                        ordered[idx] = future.result(timeout=120)
                    except Exception as e:
                        logger.warning("ModelCompare: %s future failed: %s", model, e)
                        ordered[idx] = ModelResponse(
                            model=model, response="", error=str(e)[:200]
                        )
                responses = [ordered[i] for i in sorted(ordered)]
        else:
            # Sequential execution
            for model in _models:
                responses.append(self._execute_single(prompt, model, executor))

        total_time = (time.perf_counter() - t_start) * 1000

        # Assign blind IDs (after responses collected)
        if _blind:
            import random
            shuffled_ids = blind_ids[:]
            random.shuffle(shuffled_ids)
            for resp, bid in zip(responses, shuffled_ids):
                resp.blind_id = bid

        # Score and rank
        scored = self.score_responses(responses)
        leaderboard = self.get_leaderboard(scored)

        result = CompareResult(
            prompt=prompt,
            responses=scored,
            leaderboard=leaderboard,
            total_time_ms=round(total_time, 2),
            blind_mode=_blind,
            model_count=len(_models),
            error_count=sum(1 for r in responses if r.error),
        )

        self._compare_history.append(result)
        self._stats["comparisons"] += 1
        self._stats["total_responses"] += len(responses)
        self._stats["errors"] += result.error_count

        logger.info(
            "ModelCompare: %d models, %.0fms total, %d errors, blind=%s",
            len(_models), total_time, result.error_count, _blind,
        )

        return result

    # ── Multi-Dimensional Scoring ───────────────────────────

    def score_responses(
        self,
        responses: List[ModelResponse],
        weights: Optional[Dict[str, float]] = None,
    ) -> List[ModelResponse]:
        """Score responses on three dimensions: speed, quality, cost.

        Scoring logic:
          - Speed:  normalized latency (lower = higher score, 0-100)
          - Quality: completeness + relevance + structure (0-100)
          - Cost:    token efficiency vs max in batch (0-100)
          - Overall: weighted sum of the three dimensions

        Error responses receive score=0 on all dimensions.
        """
        if not responses:
            return responses

        _weights = weights or self.weights
        valid = [r for r in responses if not r.error]
        errored = [r for r in responses if r.error]

        if not valid:
            # All errored — return with zero scores
            for r in responses:
                r.score = r.speed_score = r.quality_score = r.cost_score = 0.0
            return sorted(responses, key=lambda r: -r.score)

        # ── Speed Score (latency → 0-100, faster = higher) ──
        latencies = [r.latency_ms for r in valid]
        min_lat = min(latencies)
        max_lat = max(latencies)
        lat_range = max_lat - min_lat if max_lat > min_lat else 1

        for r in valid:
            r.speed_score = round(
                100 * (1 - (r.latency_ms - min_lat) / lat_range), 2
            )

        # ── Quality Score (completeness + relevance + structure) ──
        prompt_words = set()  # not available here; use response self-quality
        for r in valid:
            text = r.response.strip() if r.response else ""

            # Completeness: adequate length relative to typical (200-2000 chars)
            length = len(text)
            completeness = min(100, max(0, (length - 50) / 15)) if length > 0 else 0

            # Relevance: sentence/paragraph structure indicators
            sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
            structure_score = min(100, len(sentences) * 15)

            # Content richness: keyword diversity
            if text:
                words = set(text.lower().split())
                diversity = min(100, len(words) * 2)
            else:
                diversity = 0

            r.quality_score = round(
                (completeness * 0.4 + structure_score * 0.3 + diversity * 0.3), 2
            )

        # ── Cost Score (lower cost/token = higher score) ──
        costs = [r.cost for r in valid]
        max_cost = max(costs) if costs else 1
        min_cost = min(costs) if costs else 0
        cost_range = max_cost - min_cost if max_cost > min_cost else 1

        for r in valid:
            # Score: cheaper = higher (invert the normalized position)
            r.cost_score = round(
                100 * (1 - (r.cost - min_cost) / cost_range) if r.cost > 0 else 100, 2
            )

        # ── Overall Score ──
        for r in valid:
            r.score = round(
                r.speed_score * _weights.get("speed", 0.30)
                + r.quality_score * _weights.get("quality", 0.45)
                + r.cost_score * _weights.get("cost", 0.25),
                2,
            )

        # Error responses get zero
        for r in errored:
            r.score = r.speed_score = r.quality_score = r.cost_score = 0.0

        # Return sorted by score descending
        return sorted(responses, key=lambda r: -r.score)

    # ── Leaderboard ─────────────────────────────────────────

    def get_leaderboard(
        self,
        responses: Optional[List[ModelResponse]] = None,
    ) -> List[ModelResponse]:
        """Return ranked leaderboard sorted by overall score descending.

        If responses is None, uses the most recent comparison result.
        """
        if responses is None:
            if not self._compare_history:
                return []
            responses = self._compare_history[-1].responses

        # Sort by score descending, then by speed_score for ties
        return sorted(
            responses,
            key=lambda r: (-r.score, -r.speed_score, -r.quality_score),
        )

    def format_leaderboard(
        self,
        responses: Optional[List[ModelResponse]] = None,
        blind: bool = False,
    ) -> str:
        """Format a human-readable leaderboard string.

        In blind mode, displays anonymous IDs instead of model names.
        """
        board = self.get_leaderboard(responses)
        if not board:
            return "# Leaderboard\n\n_No results available._"

        lines = ["# Model Compare Leaderboard", ""]
        lines.append(f"{'Rank':<5} {'Model':<22} {'Overall':<8} {'Speed':<8} {'Quality':<8} {'Cost':<8} {'Latency'}")
        lines.append(f"{'-'*5} {'-'*22} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

        for i, r in enumerate(board, 1):
            display_name = r.blind_id if (blind and r.blind_id) else r.model
            icon = "❌" if r.error else ("🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}.")
            lines.append(
                f"{icon:<5} {display_name:<22} "
                f"{r.score:>6.1f}  {r.speed_score:>6.1f}  {r.quality_score:>6.1f}  "
                f"{r.cost_score:>6.1f}  {r.latency_ms:>7.0f}ms"
            )
            if r.error:
                lines.append(f"      ⚠ Error: {r.error[:80]}")

        return "\n".join(lines)

    def reveal_blind_mapping(
        self,
        responses: Optional[List[ModelResponse]] = None,
    ) -> Dict[str, str]:
        """Reveal the blind ID → real model mapping."""
        if responses is None:
            if not self._compare_history:
                return {}
            responses = self._compare_history[-1].responses

        return {
            r.blind_id: r.model
            for r in responses
            if r.blind_id
        }

    # ── Convenience ─────────────────────────────────────────

    def compare_and_rank(
        self,
        prompt: str,
        models: Optional[List[str]] = None,
        executor: Optional[Callable] = None,
        blind: Optional[bool] = None,
    ) -> CompareResult:
        """Full pipeline: compare → score → leaderboard. Returns CompareResult."""
        return self.compare(prompt, models=models, executor=executor, blind=blind)

    def get_stats(self) -> Dict:
        """Return engine statistics."""
        return {
            "comparisons": self._stats["comparisons"],
            "total_responses": self._stats["total_responses"],
            "errors": self._stats["errors"],
            "error_rate": (
                f"{self._stats['errors'] / max(1, self._stats['total_responses']) * 100:.1f}%"
                if self._stats["total_responses"] > 0 else "0%"
            ),
            "blind_enabled": self.blind,
            "parallel_enabled": self.parallel,
            "scoring_weights": self.weights,
            "default_models": self.default_models,
            "history_size": len(self._compare_history),
        }

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Return recent comparison history summaries."""
        return [
            r.to_dict()
            for r in self._compare_history[-limit:]
        ]

    def list_known_models(self) -> List[str]:
        """Return the list of known/registered models."""
        return self.KNOWN_MODELS[:]


# ═══════════════════════════════════════════════════════════
# Singleton & Backward Compat
# ═══════════════════════════════════════════════════════════

_compare: Optional[ModelCompareEngine] = None


def get_compare_engine(**kwargs) -> ModelCompareEngine:
    """Get or create the singleton ModelCompareEngine instance."""
    global _compare
    if _compare is None:
        _compare = ModelCompareEngine(**kwargs)
    return _compare


def compare_models(prompt, models=None, executor=None, blind=None):
    """Backward-compatible: compare models, returns List[ModelResponse]."""
    engine = get_compare_engine()
    result = engine.compare(prompt, models=models, executor=executor, blind=blind)
    return result.responses


def compare_models_stream(prompt, models=None, executor=None, blind=None):
    """Backward-compatible streaming alias (returns same as compare_models)."""
    return compare_models(prompt, models=models, executor=executor, blind=blind)
