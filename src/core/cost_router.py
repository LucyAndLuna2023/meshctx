"""
meshctx Cost-Aware Model Router v1.0 — Flash/Pro Tiered Routing

Design (inspired by DeepSeek-Reasonix cost tier system):
  - flash model: cheap, fast, for simple tasks (< 500 token estimate)
  - pro model: quality, expensive, for complex tasks
  - Automatic routing based on task analysis
  - Manual override via #flash, #pro, #auto task tags

Routing rules:
  1. Task with #flash tag → flash model (no analysis)
  2. Task with #pro tag → pro model (no analysis)
  3. < 500 estimated tokens → flash (quick question, small file, regex)
  4. < 2000 tokens → mix (flash plan + pro execute if needed)
  5. >= 2000 tokens → pro (complex code generation, multi-step refactor)
  6. Tool error > 2 → escalate to pro (tool-call repair needed)

Usage:
  router = CostRouter(flash_model="deepseek-flash", pro_model="deepseek-pro")
  model, reason = router.select(task="Fix a typo in README.md", token_estimate=100)
  # → ("deepseek-flash", "quick_fix")
  model, reason = router.select(task="Refactor entire auth module", token_estimate=5000)
  # → ("deepseek-pro", "complex_task")
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import logging
import time

logger = logging.getLogger("meshctx.cost_router")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

# Token estimate thresholds for routing
THRESHOLD_FLASH = 500       # ≤ this → always flash
THRESHOLD_MIX = 2000        # flash ≤ this < mix → flash + optional pro escalation
# Above THRESHOLD_MIX → always pro

# Cost per 1M tokens (approximate, adjust per provider)
COST_PER_1M_FLASH = 0.14   # DeepSeek flash
COST_PER_1M_PRO = 2.19      # DeepSeek pro

# Tags for manual override
TAG_FLASH = "#flash"
TAG_PRO = "#pro"
TAG_AUTO = "#auto"

# Task pattern heuristics
QUICK_PATTERNS = [
    r'^(?:fix|typo|spelling|grammar)\b',
    r'\b(?:typo|spelling|grammar)\b',
    r'^(?:what is|how do I|explain)\b',
    r'^(?:find|search|locate)\b',
    r'\b(?:simple|small|quick|minor|trivial)\b',
]

COMPLEX_PATTERNS = [
    r'\b(?:refactor|rewrite|redesign|architect)\b',
    r'\b(?:complex|major|complete|full|entire)\b',
    r'\b(?:security|authentication|authorization|encrypt)\b',
    r'\b(?:migrate|upgrade|downgrade|compat)\b',
    r'\b(?:optimize|performance|scale|benchmark)\b',
    r'\b(?:generate|create all|build all|implement all)\b',
]

MULTI_FILE_PATTERNS = [
    r'\b(?:all|every|each|multiple|several|across)\b.*?\b(?:files?|modules?|components?)\b',
    r'\b(?:codebase|project|repository|whole)\b',
]


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class RouteReason(str, Enum):
    EXPLICIT_FLASH = "explicit_flash_tag"
    EXPLICIT_PRO = "explicit_pro_tag"
    QUICK_FIX = "quick_fix"
    SIMPLE_QUERY = "simple_query"
    MIX_LOW = "mix_flash_ok"
    COMPLEX_TASK = "complex_task"
    HIGH_TOKENS = "high_tokens"
    MULTI_FILE = "multi_file"
    ERROR_ESCALATE = "error_escalate"
    DEFAULT = "default"


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

@dataclass
class RouteDecision:
    """Result of cost-based routing."""
    model: str
    reason: RouteReason
    is_flash: bool
    estimated_cost: float  # USD
    
    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "reason": self.reason.value,
            "is_flash": self.is_flash,
            "estimated_cost_usd": round(self.estimated_cost, 6),
        }


@dataclass
class CostMetrics:
    """Aggregated cost tracking."""
    total_requests: int = 0
    flash_requests: int = 0
    pro_requests: int = 0
    total_tokens_flash: int = 0
    total_tokens_pro: int = 0
    total_cost_usd: float = 0.0
    saved_vs_all_pro: float = 0.0  # Cost saved vs always using pro
    
    @property
    def flash_ratio(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.flash_requests / self.total_requests


# ═══════════════════════════════════════════════════════════
# Cost Router
# ═══════════════════════════════════════════════════════════

class CostRouter:
    """
    Intelligent cost-aware model router.
    
    Combines:
      1. Explicit tag overrides (#flash, #pro, #auto)
      2. Token estimate thresholds
      3. Pattern-based task complexity analysis
      4. Tool-error escalation tracking
    """
    
    def __init__(self, flash_model: str = "deepseek-flash",
                 pro_model: str = "deepseek-pro",
                 flash_cost_per_1m: float = COST_PER_1M_FLASH,
                 pro_cost_per_1m: float = COST_PER_1M_PRO,
                 flash_threshold: int = THRESHOLD_FLASH,
                 mix_threshold: int = THRESHOLD_MIX):
        self.flash_model = flash_model
        self.pro_model = pro_model
        self.flash_cost = flash_cost_per_1m
        self.pro_cost = pro_cost_per_1m
        self.flash_threshold = flash_threshold
        self.mix_threshold = mix_threshold
        
        self.metrics = CostMetrics()
        self._error_counts: Dict[str, int] = {}  # session_id -> error count
        
        # Compile patterns
        self._quick_re = [re.compile(p, re.IGNORECASE) for p in QUICK_PATTERNS]
        self._complex_re = [re.compile(p, re.IGNORECASE) for p in COMPLEX_PATTERNS]
        self._multifile_re = [re.compile(p, re.IGNORECASE) for p in MULTI_FILE_PATTERNS]
    
    # ── Routing ─────────────────────────────────────────────
    
    def select(self, task: str, token_estimate: int = 0,
               session_id: str = "") -> RouteDecision:
        """
        Select flash or pro model for a task.
        
        Args:
            task: User's task description
            token_estimate: Estimated tokens for completion
            session_id: For error escalation tracking
        
        Returns:
            RouteDecision with selected model and reason
        """
        # 1. Explicit tags
        if TAG_FLASH in task:
            return self._decide(self.flash_model, RouteReason.EXPLICIT_FLASH, token_estimate)
        if TAG_PRO in task:
            return self._decide(self.pro_model, RouteReason.EXPLICIT_PRO, token_estimate)
        
        # 2. Error escalation: if same session has >2 tool errors, go pro
        if session_id and self._error_counts.get(session_id, 0) > 2:
            return self._decide(self.pro_model, RouteReason.ERROR_ESCALATE, token_estimate)
        
        # 3. Pattern-based complexity analysis
        complexity = self._analyze_complexity(task)
        
        if complexity == "quick":
            return self._decide(self.flash_model, RouteReason.QUICK_FIX, token_estimate)
        
        if complexity == "complex":
            return self._decide(self.pro_model, RouteReason.COMPLEX_TASK, token_estimate)
        
        if complexity == "multi_file":
            return self._decide(self.pro_model, RouteReason.MULTI_FILE, token_estimate)
        
        # 4. Token threshold routing
        if token_estimate <= self.flash_threshold:
            return self._decide(self.flash_model, RouteReason.SIMPLE_QUERY, token_estimate)
        
        if token_estimate <= self.mix_threshold:
            return self._decide(self.flash_model, RouteReason.MIX_LOW, token_estimate)
        
        # 5. Default: high tokens → pro
        return self._decide(self.pro_model, RouteReason.HIGH_TOKENS, token_estimate)
    
    def select_bulk(self, tasks: List[Tuple[str, int]]) -> List[RouteDecision]:
        """Batch routing for multiple tasks."""
        return [self.select(task, est) for task, est in tasks]
    
    # ── Error Tracking ──────────────────────────────────────
    
    def report_error(self, session_id: str):
        """Increment error count for a session (triggers escalation)."""
        self._error_counts[session_id] = self._error_counts.get(session_id, 0) + 1
    
    def clear_errors(self, session_id: str):
        """Reset error count for a session."""
        self._error_counts.pop(session_id, None)
    
    # ── Metrics ─────────────────────────────────────────────
    
    def record(self, model: str, tokens: int):
        """Record a completed request for cost tracking."""
        self.metrics.total_requests += 1
        is_flash = model == self.flash_model
        
        if is_flash:
            self.metrics.flash_requests += 1
            self.metrics.total_tokens_flash += tokens
        else:
            self.metrics.pro_requests += 1
            self.metrics.total_tokens_pro += tokens
        
        # Calculate cost
        cost_per_1m = self.flash_cost if is_flash else self.pro_cost
        cost = (tokens / 1_000_000) * cost_per_1m
        self.metrics.total_cost_usd += cost
        
        # Calculate savings vs all-pro
        pro_cost = (tokens / 1_000_000) * self.pro_cost
        self.metrics.saved_vs_all_pro += (pro_cost - cost)
    
    def get_report(self) -> str:
        """Human-readable cost report."""
        m = self.metrics
        return (
            f"Cost Router Report\n"
            f"──────────────────\n"
            f"Requests: {m.total_requests} "
            f"(flash: {m.flash_requests} [{m.flash_ratio:.1%}], "
            f"pro: {m.pro_requests})\n"
            f"Tokens: {m.total_tokens_flash + m.total_tokens_pro} "
            f"(flash: {m.total_tokens_flash}, pro: {m.total_tokens_pro})\n"
            f"Cost: ${m.total_cost_usd:.4f}\n"
            f"Saved vs all-pro: ${m.saved_vs_all_pro:.4f}\n"
        )
    
    # ── Internal ────────────────────────────────────────────
    
    def _analyze_complexity(self, task: str) -> str:
        """
        Analyze task complexity from text patterns.
        
        Returns: "quick", "complex", "multi_file", or "normal"
        """
        # Quick patterns
        for pat in self._quick_re:
            if pat.search(task):
                # Double-check: not also complex
                for cpat in self._complex_re:
                    if cpat.search(task):
                        return "complex"
                return "quick"
        
        # Multi-file patterns (highest priority)
        for pat in self._multifile_re:
            if pat.search(task):
                return "multi_file"
        
        # Complex patterns
        for pat in self._complex_re:
            if pat.search(task):
                return "complex"
        
        return "normal"
    
    def _decide(self, model: str, reason: RouteReason,
                token_estimate: int) -> RouteDecision:
        is_flash = model == self.flash_model
        cost_per_1m = self.flash_cost if is_flash else self.pro_cost
        cost = (token_estimate / 1_000_000) * cost_per_1m
        
        logger.debug(f"Route: {model} ({reason.value}) for ~{token_estimate} tokens")
        
        return RouteDecision(
            model=model,
            reason=reason,
            is_flash=is_flash,
            estimated_cost=cost,
        )
    
    # ── Stats ────────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Router statistics."""
        return {
            "flash_model": self.flash_model,
            "pro_model": self.pro_model,
            "flash_cost_per_1m": self.flash_cost,
            "pro_cost_per_1m": self.pro_cost,
            "metrics": {
                "total_requests": self.metrics.total_requests,
                "flash_ratio": self.metrics.flash_ratio,
                "total_cost_usd": round(self.metrics.total_cost_usd, 4),
                "saved_vs_all_pro": round(self.metrics.saved_vs_all_pro, 4),
            },
            "error_sessions": len(self._error_counts),
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_router: Optional[CostRouter] = None


def get_cost_router(**kwargs) -> CostRouter:
    """Get or create the global cost router."""
    global _router
    if _router is None:
        _router = CostRouter(**kwargs)
    return _router
