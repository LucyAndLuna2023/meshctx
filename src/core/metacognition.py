"""
meshctx Meta-Cognition Loop — full implementation (v3.115.16)
Self-evaluation → pattern extraction → knowledge graph update → behavior adjustment.
Implements the core "gets smarter every time" claim from meshctx.com.
"""
__all__ = ['MetaTaskStatus', 'Strategy', 'LearnedPattern', 'MetaEvaluation', 'MetaCognitionEngine', 'get_meta_cognition']

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import time

class MetaTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class Strategy(str, Enum):
    """Learned strategies for task execution."""
    DECOMPOSE = "decompose"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    DELEGATE = "delegate"
    RETRY = "retry"
    FALLBACK = "fallback"


@dataclass
class LearnedPattern:
    """A pattern extracted from task execution history."""
    pattern_id: str
    trigger_keywords: List[str]
    successful_strategy: Strategy
    failure_reasons: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    last_seen: float = field(default_factory=time.time)
    confidence: float = 0.0
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


@dataclass
class MetaEvaluation:
    """Result of a meta-cognition evaluation cycle."""
    task_id: str
    task_description: str
    status: MetaTaskStatus
    duration_ms: float
    patterns_matched: List[str] = field(default_factory=list)
    patterns_learned: List[str] = field(default_factory=list)
    strategy_used: Optional[Strategy] = None
    insights: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class MetaCognitionEngine:
    """Post-task self-evaluation and continuous learning engine.
    
    After each task:
    1. Self-evaluate: did we succeed? What went wrong?
    2. Extract patterns: find recurring success/failure triggers
    3. Update knowledge: adjust confidence scores and strategies
    4. Adjust behavior: recommend better strategies for future tasks
    """
    
    def __init__(self):
        self.patterns: Dict[str, LearnedPattern] = {}
        self.history: List[MetaEvaluation] = []
        self.strategy_scores: Dict[Strategy, float] = {
            s: 0.5 for s in Strategy
        }
        self._lock = Lock()
        self._eval_count = 0
        self._pattern_id_counter = 0
    
    def evaluate(self, task_id: str, task_description: str,
                 status: MetaTaskStatus, duration_ms: float,
                 strategy_used: Strategy = None,
                 error_message: str = None,
                 tool_calls: List[str] = None) -> MetaEvaluation:
        """Run a meta-cognition cycle on a completed task."""
        with self._lock:
            self._eval_count += 1
            
            evaluation = MetaEvaluation(
                task_id=task_id,
                task_description=task_description,
                status=status,
                duration_ms=duration_ms,
                strategy_used=strategy_used,
            )
            
            # Step 1: Self-evaluate
            evaluation.insights = self._self_evaluate(
                task_description, status, duration_ms, error_message
            )
            
            # Step 2: Extract patterns
            keywords = self._extract_keywords(task_description)
            evaluation.patterns_matched = self._match_patterns(keywords)
            
            # Step 3: Learn from outcome
            new_patterns = self._learn_from_outcome(
                task_description, keywords, status, strategy_used,
                duration_ms, error_message
            )
            evaluation.patterns_learned = [p.pattern_id for p in new_patterns]
            
            # Step 4: Adjust strategy scores
            evaluation.improvement_suggestions = self._adjust_strategies(
                status, strategy_used, duration_ms
            )
            
            # Step 5: Update pattern success/failure stats
            for pid in evaluation.patterns_matched:
                if pid in self.patterns:
                    p = self.patterns[pid]
                    p.last_seen = time.time()
                    if status == MetaTaskStatus.SUCCESS:
                        p.success_count += 1
                    else:
                        p.failure_count += 1
                    p.confidence = self._calc_confidence(p)
            
            self.history.append(evaluation)
            if len(self.history) > 1000:
                self.history = self.history[-500:]
            
            return evaluation
    
    def _self_evaluate(self, description: str, status: MetaTaskStatus,
                       duration_ms: float, error: str) -> List[str]:
        """Generate self-evaluation insights."""
        insights = []
        
        if status == MetaTaskStatus.SUCCESS:
            insights.append(f"Task completed successfully in {duration_ms:.0f}ms")
            if duration_ms < 1000:
                insights.append("Task was fast — consider batching with similar tasks")
            elif duration_ms > 30000:
                insights.append("Task was slow — consider decomposition for parallel execution")
        elif status == MetaTaskStatus.FAILED:
            insights.append(f"Task failed: {error or 'unknown error'}")
            if error and "timeout" in error.lower():
                insights.append("Timeout detected — increase timeout or split task")
            if error and "permission" in error.lower():
                insights.append("Permission error — check access rights")
        elif status == MetaTaskStatus.PARTIAL:
            insights.append("Task partially completed — review partial results")
        
        return insights
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords for pattern matching."""
        import re
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        stopwords = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'been'}
        return [w for w in words if w not in stopwords][:10]
    
    def _match_patterns(self, keywords: List[str]) -> List[str]:
        """Find existing patterns matching the keywords."""
        matched = []
        for pid, pattern in self.patterns.items():
            overlap = set(keywords) & set(pattern.trigger_keywords)
            if len(overlap) >= 2:
                matched.append(pid)
        return matched
    
    def _learn_from_outcome(self, description: str, keywords: List[str],
                            status: MetaTaskStatus, strategy: Strategy,
                            duration_ms: float, error: str) -> List[LearnedPattern]:
        """Learn new patterns from task outcome."""
        new_patterns = []
        
        # Create new pattern for novel keyword combinations
        if keywords and status == MetaTaskStatus.SUCCESS:
            existing_triggers = set()
            for p in self.patterns.values():
                existing_triggers.update(p.trigger_keywords)
            
            novel_keywords = [k for k in keywords if k not in existing_triggers]
            if len(novel_keywords) >= 3:
                self._pattern_id_counter += 1
                pid = f"P{self._pattern_id_counter:04d}"
                pattern = LearnedPattern(
                    pattern_id=pid,
                    trigger_keywords=novel_keywords[:5],
                    successful_strategy=strategy or Strategy.DECOMPOSE,
                    success_count=1,
                )
                pattern.confidence = self._calc_confidence(pattern)
                self.patterns[pid] = pattern
                new_patterns.append(pattern)
        
        # Update failure reasons
        if status == MetaTaskStatus.FAILED and error:
            for pid in self._match_patterns(keywords):
                if pid in self.patterns:
                    reason = error[:100]
                    if reason not in self.patterns[pid].failure_reasons:
                        self.patterns[pid].failure_reasons.append(reason)
        
        return new_patterns
    
    def _adjust_strategies(self, status: MetaTaskStatus, strategy: Strategy,
                          duration_ms: float) -> List[str]:
        """Adjust strategy confidence scores based on outcome."""
        suggestions = []
        
        if status == MetaTaskStatus.SUCCESS and strategy:
            # Boost successful strategy
            self.strategy_scores[strategy] = min(
                1.0, self.strategy_scores[strategy] + 0.05
            )
            # Decay others slightly
            for s in Strategy:
                if s != strategy:
                    self.strategy_scores[s] = max(0.1, self.strategy_scores[s] - 0.01)
        
        elif status == MetaTaskStatus.FAILED and strategy:
            # Penalize failed strategy
            self.strategy_scores[strategy] = max(0.1, self.strategy_scores[strategy] - 0.1)
            # Suggest alternatives
            best = self.best_strategy()
            if best and best != strategy:
                suggestions.append(
                    f"Strategy '{strategy.value}' failed. "
                    f"Recommend '{best.value}' (score: {self.strategy_scores[best]:.2f})"
                )
        
        if duration_ms > 30000:
            suggestions.append("Consider task decomposition for parallel execution")
        
        return suggestions
    
    def _calc_confidence(self, pattern: LearnedPattern) -> float:
        """Bayesian confidence estimate for a pattern."""
        total = pattern.success_count + pattern.failure_count
        if total == 0:
            return 0.1
        # Wilson score interval lower bound (simplified)
        p = pattern.success_count / total
        z = 1.96  # 95% confidence
        n = total
        return max(0.0, (p + z*z/(2*n) - z * ((p*(1-p) + z*z/(4*n))/n)**0.5) / (1 + z*z/n))
    
    def best_strategy(self) -> Optional[Strategy]:
        """Get the current best-performing strategy."""
        if not self.strategy_scores:
            return None
        return max(self.strategy_scores, key=self.strategy_scores.get)
    
    def recommend_strategy(self, task_description: str) -> Tuple[Strategy, float]:
        """Recommend best strategy for a new task based on learned patterns."""
        keywords = self._extract_keywords(task_description)
        matches = self._match_patterns(keywords)
        
        if matches:
            # Use the most confident matching pattern's strategy
            best_pattern = max(
                (self.patterns[pid] for pid in matches),
                key=lambda p: p.confidence
            )
            return best_pattern.successful_strategy, best_pattern.confidence
        
        # Fall back to global best strategy
        best = self.best_strategy()
        return (best, self.strategy_scores.get(best, 0.5)) if best else (Strategy.DECOMPOSE, 0.5)
    
    def stats(self) -> dict:
        with self._lock:
            return {
                "evaluations": self._eval_count,
                "patterns_learned": len(self.patterns),
                "history_size": len(self.history),
                "strategy_scores": {s.value: round(v, 3) for s, v in self.strategy_scores.items()},
                "best_strategy": self.best_strategy().value if self.best_strategy() else None,
                "top_patterns": [
                    {"id": p.pattern_id, "keywords": p.trigger_keywords,
                     "success_rate": p.success_rate, "confidence": p.confidence}
                    for p in sorted(self.patterns.values(), key=lambda x: -x.confidence)[:5]
                ]
            }
    
    def reset(self):
        with self._lock:
            self.patterns.clear()
            self.history.clear()
            self.strategy_scores = {s: 0.5 for s in Strategy}
            self._eval_count = 0


# Global singleton
_global_meta: Optional[MetaCognitionEngine] = None

def get_meta_cognition() -> MetaCognitionEngine:
    global _global_meta
    if _global_meta is None:
        _global_meta = MetaCognitionEngine()
    return _global_meta