"""FSRS Spaced Repetition Scheduler — D/S/R state machine (v1, phase-1)

Implements a Free Spaced Repetition Scheduler inspired by the FSRS model
(Ye et al., 2024, "Optimizing Memory Accuracy and Efficiency with Free
Spaced Repetition Scheduler", KDD 2024; py-fsrs open-source implementation).

Three-parameter memory state per item:
  D  — difficulty [0, 10], higher = harder
  S  — stability (days), higher = decays slower
  R  — retrievability R(t) = 10^(-t/S) at review time (computed)

Core update rules (simplified FSRS v4):
  - Success (grade 3/4/5):  f = 0.5 + 0.5*(grade-3)/2
                            S' = S * exp(w8 * (11 - D) * f)
                            D' = D - w6 * (grade - 3)
  - Failure (grade < 3):    S' = S * decay_factor, interval reset to 1 day
  - Interval:               I' = S' * (target_retention ^ (-1/0.25) - 1)
                            (inverse of power-law-ish retention; clamped >= 1d)

This module is pure-python / zero-dependency and intentionally decoupled from
storage so it can be unit-tested in isolation and reused by HierarchicalMemoryStore.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "MemoryCard",
    "FSRSScheduler",
    "Grade",
]

DEFAULT_W = {
    "w8": 0.8,      # stability increase gain
    "w6": 0.03,     # difficulty reduction on success
    "w9": 1.2,      # retrievability exponent (FSRS v4)
}


def _grade_is_pass(grade: int) -> bool:
    return grade >= 3


def _success_factor(grade: int) -> float:
    """Map grade (0-5) to a success factor f in [0.5, 1.0].

    grade 5 → 1.0 (perfect), grade 4 → 0.75, grade 3 → 0.5.
    """
    g = max(3, min(5, grade))
    return 0.5 + 0.5 * (g - 3) / 2.0


@dataclass
class MemoryCard:
    """FSRS tracking state for one memory item."""

    item_id: str
    difficulty: float = 5.0          # D in [0, 10]
    stability: float = 1.0           # S in days
    interval_days: float = 1.0       # current scheduled interval
    reviews: int = 0
    lapses: int = 0
    last_review: float = 0.0
    next_review: float = 0.0
    created_at: float = field(default_factory=time.time)

    # ── helpers ──────────────────────────────────────────────
    def days_since_last_review(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        if self.last_review <= 0:
            return 0.0
        return max(0.0, (now - self.last_review) / 86400.0)

    def retrievability(self, now: Optional[float] = None) -> float:
        """R(t) = 10^(-t / S), clamped to (0, 1]."""
        t = self.days_since_last_review(now)
        if t <= 0 or self.stability <= 0:
            return 1.0
        r = 10.0 ** (-t / self.stability)
        return max(1e-4, min(1.0, r))

    def is_due(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        if self.next_review <= 0:
            return True
        return now >= self.next_review

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "difficulty": self.difficulty,
            "stability": self.stability,
            "interval_days": self.interval_days,
            "reviews": self.reviews,
            "lapses": self.lapses,
            "last_review": self.last_review,
            "next_review": self.next_review,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryCard":
        return cls(
            item_id=d.get("item_id", ""),
            difficulty=float(d.get("difficulty", 5.0)),
            stability=float(d.get("stability", 1.0)),
            interval_days=float(d.get("interval_days", 1.0)),
            reviews=int(d.get("reviews", 0)),
            lapses=int(d.get("lapses", 0)),
            last_review=float(d.get("last_review", 0.0)),
            next_review=float(d.get("next_review", 0.0)),
            created_at=float(d.get("created_at", time.time())),
        )


@dataclass
class ReviewOutcome:
    """Result of scheduling a single review."""

    item_id: str
    grade: int
    passed: bool
    previous_stability: float
    new_stability: float
    previous_difficulty: float
    new_difficulty: float
    previous_interval: float
    new_interval: float
    estimated_retrievability: float
    next_review: float
    lapses: int


class FSRSScheduler:
    """FSRS scheduler — pure state machine over MemoryCard objects.

    Usage:
        sched = FSRSScheduler()
        card = sched.get_or_create("mem_1")
        outcome = sched.review(card, grade=4)   # mutates card in place
    """

    def __init__(
        self,
        target_retention: float = 0.90,
        w: Optional[Dict[str, float]] = None,
        default_stability: float = 1.0,
        default_difficulty: float = 5.0,
        decay_factor: float = 0.5,
        max_stability: float = 3650.0,   # 安全上限 10 年（py-fsrs 亦有 hard cap）
    ):
        self.target_retention = target_retention
        self.w = {**DEFAULT_W, **(w or {})}
        self.default_stability = default_stability
        self.default_difficulty = default_difficulty
        self.decay_factor = decay_factor
        self.max_stability = max_stability
        self._cards: Dict[str, MemoryCard] = {}

    # ── storage ──────────────────────────────────────────────
    def get_or_create(self, item_id: str) -> MemoryCard:
        card = self._cards.get(item_id)
        if card is None:
            card = MemoryCard(
                item_id=item_id,
                stability=self.default_stability,
                difficulty=self.default_difficulty,
            )
            self._cards[item_id] = card
        return card

    def get_card(self, item_id: str) -> Optional[MemoryCard]:
        return self._cards.get(item_id)

    def set_card(self, card: MemoryCard) -> None:
        self._cards[card.item_id] = card

    def due_items(self, now: Optional[float] = None) -> List[str]:
        now = now or time.time()
        return [i for i, c in self._cards.items() if c.is_due(now)]

    def retention(self, item_id: str, now: Optional[float] = None) -> Optional[float]:
        card = self._cards.get(item_id)
        if card is None:
            return None
        return card.retrievability(now)

    # ── core update rules ────────────────────────────────────
    def _next_stability(self, card: MemoryCard, grade: int, retrievability: float) -> float:
        if _grade_is_pass(grade):
            # 首次复习（last_review=0，无 R 可依）: 用经验初始增益，
            # 避免 R=1.0 时标准公式增益=1（首次复习无进展）。
            if card.last_review <= 0:
                f = _success_factor(grade)
                gain = math.exp(self.w["w8"] * (11.0 - card.difficulty) * f)
                return min(max(card.stability * gain, 0.01), self.max_stability)
            # FSRS v4: S' = S * (1 + exp(w8*(11-D)) * (R^(-w9) - 1) * f)
            # 复习时保留度 R 越高，本次成功对稳定性的增益越小（间隔与遗忘状态相关）
            f = _success_factor(grade)
            r_factor = max(0.0, retrievability ** (-self.w["w9"]) - 1.0)
            gain = 1.0 + math.exp(self.w["w8"] * (11.0 - card.difficulty)) * r_factor * f
            return min(max(card.stability * gain, 0.01), self.max_stability)
        # lapse: stability decays, interval resets
        return max(card.stability * self.decay_factor, 0.01)

    def _next_interval(self, stability: float, grade: int, reviews: int) -> float:
        if not _grade_is_pass(grade):
            return 1.0
        if reviews == 0:
            return 1.0
        # 幂律自洽: R(t)=10^(-t/S) 的逆解 t = -S·log10(R_target)
        # 使复习间隔与自身遗忘曲线互逆（审计点2）: r=0.9 → 0.046·S
        if 0 < self.target_retention < 1:
            factor = -math.log10(self.target_retention)
        else:
            factor = 0.046
        return max(1.0, stability * factor)

    def _next_difficulty(self, difficulty: float, grade: int) -> float:
        if _grade_is_pass(grade):
            d = difficulty - self.w["w6"] * (grade - 3)
        else:
            d = difficulty + 0.5  # failure makes item harder
        return max(0.0, min(10.0, d))

    # ── public API ───────────────────────────────────────────
    def review(
        self,
        card: MemoryCard,
        grade: int,
        now: Optional[float] = None,
    ) -> ReviewOutcome:
        """Process a review outcome and update the card in place."""
        grade = max(0, min(5, int(grade)))
        now = now or time.time()

        prev_stability = card.stability
        prev_difficulty = card.difficulty
        prev_interval = card.interval_days
        est_r = card.retrievability(now)

        card.difficulty = self._next_difficulty(card.difficulty, grade)
        card.stability = self._next_stability(card, grade, est_r)
        card.interval_days = self._next_interval(card.stability, grade, card.reviews)
        card.last_review = now
        card.next_review = now + card.interval_days * 86400.0
        card.reviews += 1
        if not _grade_is_pass(grade):
            card.lapses += 1

        return ReviewOutcome(
            item_id=card.item_id,
            grade=grade,
            passed=_grade_is_pass(grade),
            previous_stability=prev_stability,
            new_stability=card.stability,
            previous_difficulty=prev_difficulty,
            new_difficulty=card.difficulty,
            previous_interval=prev_interval,
            new_interval=card.interval_days,
            estimated_retrievability=est_r,
            next_review=card.next_review,
            lapses=card.lapses,
        )

    def get_stats(self) -> dict:
        if not self._cards:
            return {"total_cards": 0}
        cards = list(self._cards.values())
        return {
            "total_cards": len(cards),
            "due_cards": len(self.due_items()),
            "avg_stability_days": sum(c.stability for c in cards) / len(cards),
            "avg_difficulty": sum(c.difficulty for c in cards) / len(cards),
            "avg_interval_days": sum(c.interval_days for c in cards) / len(cards),
            "total_reviews": sum(c.reviews for c in cards),
            "total_lapses": sum(c.lapses for c in cards),
        }


def grade_from_confidence(confidence: float) -> int:
    """Map a model/user confidence in [0,1] to an SM-2/FSRS grade (0-5).

    confidence >= 0.95 → 5, >= 0.8 → 4, >= 0.6 → 3,
    >= 0.4 → 2, >= 0.2 → 1, else → 0.
    """
    if confidence >= 0.95:
        return 5
    if confidence >= 0.80:
        return 4
    if confidence >= 0.60:
        return 3
    if confidence >= 0.40:
        return 2
    if confidence >= 0.20:
        return 1
    return 0
