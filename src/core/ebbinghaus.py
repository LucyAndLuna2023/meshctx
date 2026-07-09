"""
Ebbinghaus Forgetting Curve — Spaced Repetition Scheduler
==========================================================
Implements the Ebbinghaus forgetting curve model for optimal spaced
repetition scheduling. Based on the empirical observation that memory
strength decays exponentially over time unless reinforced.

Core algorithms:
  1. Ebbinghaus Forgetting Curve (Ebbinghaus, 1885):
     R(t) = e^{-t/S}  where S is memory stability (strength).
     After each successful review, stability increases multiplicatively.

  2. SM-2 Algorithm (SuperMemo, Wozniak, 1990s):
     - EF (Ease Factor) adjusts based on response quality.
     - Interval = previous_interval * EF.
     - Minimum EF = 1.3 to prevent overly aggressive scheduling.

  3. Leitner System (Leitner, 1972):
     - Box-based scheduling: items move up boxes on correct recall,
       down on failure. Each box has progressively longer review intervals.

  4. Optimal Review Scheduling (minimize forgetting rate):
     - Given desired retention rate (e.g., 90%), compute optimal interval
       from the forgetting curve: t = -S * ln(R_target).
     - Power-law forgetting variant: R(t) = (1 + t/S)^{-β}.

  5. Memory Strength Tracking:
     - Track stability (S) and difficulty (D) per item.
     - Adjust S after each review based on response quality.
     - D3 stability increase model (Piotr Wozniak, 2018).

References:
  - Ebbinghaus H (1885) Über das Gedächtnis (Memory: A Contribution to
    Experimental Psychology)
  - Wozniak PA (1990-2018) SuperMemo Algorithm SM-2 through SM-18
  - Leitner S (1972) So lernt man lernen (How to Learn to Learn)
  - Wixted JT, Carpenter SK (2007) The Wickelgren power law and Ebbinghaus

Usage:
  ef = EbbinghausForgetting()
  next_review = ef.schedule_review(quality=4, previous_interval_days=1, ef=2.5)
  # → (next_interval_days=6, new_ef=2.5)
"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Union
import logging

logger = logging.getLogger("meshctx.ebbinghaus")


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

class ReviewQuality(Enum):
    """SM-2 style response quality (0-5 scale)."""
    COMPLETE_BLACKOUT = 0    # Total failure to recall
    INCORRECT_BUT_RECALLED = 1  # Wrong, but correct answer remembered upon seeing
    INCORRECT_EASY_RECALL = 2   # Wrong, but correct answer seemed easy upon seeing
    CORRECT_DIFFICULT = 3       # Correct with serious difficulty
    CORRECT_HESITANT = 4        # Correct after hesitation
    CORRECT_PERFECT = 5         # Perfect response

    @property
    def is_pass(self) -> bool:
        """Quality >= 3 counts as a successful recall (SM-2 convention)."""
        return self.value >= 3

    @classmethod
    def from_int(cls, value: int) -> "ReviewQuality":
        if value < 0:
            value = 0
        elif value > 5:
            value = 5
        return cls(value)


@dataclass
class MemoryItem:
    """A single item tracked by the spaced repetition system.

    Tracks stability, difficulty, and review history for optimal scheduling.
    """
    item_id: str
    stability: float = 1.0            # Memory stability S (days), higher = slower decay
    difficulty: float = 0.3            # Intrinsic difficulty D [0, 1], 1 = hardest
    ease_factor: float = 2.5           # SM-2 ease factor (minimum 1.3)
    interval_days: float = 1.0         # Current scheduled interval
    reviews: int = 0                   # Total review count
    lapses: int = 0                    # Number of times forgotten
    last_review: float = 0.0           # Unix timestamp of last review
    next_review: float = 0.0           # Unix timestamp of next scheduled review
    created_at: float = field(default_factory=time.time)

    def days_since_last_review(self) -> float:
        """Days elapsed since last review."""
        if self.last_review == 0:
            return 0.0
        return (time.time() - self.last_review) / 86400.0

    def retention_probability(self) -> float:
        """Estimate current retention probability using Ebbinghaus curve.

        R(t) = e^{-t / S}  where t = days since last review
        """
        t = self.days_since_last_review()
        if t <= 0 or self.stability <= 0:
            return 1.0
        return math.exp(-t / self.stability)

    def is_due(self) -> bool:
        """Check if this item is due for review."""
        if self.next_review == 0:
            return True
        return time.time() >= self.next_review


@dataclass
class ReviewResult:
    """Result of a single review session for one item."""
    item_id: str
    quality: ReviewQuality
    passed: bool
    previous_interval: float
    new_interval: float
    previous_ease: float
    new_ease: float
    previous_stability: float
    new_stability: float
    estimated_retention: float        # Retention probability at review time
    next_review_timestamp: float
    scheduled_days: float             # Days until next review from now


@dataclass
class LeitnerBox:
    """A box in the Leitner system."""
    level: int
    items: List[str] = field(default_factory=list)
    review_interval_days: float = 1.0


# ═══════════════════════════════════════════════════════════════════
# EbbinghausForgetting
# ═══════════════════════════════════════════════════════════════════

class EbbinghausForgetting:
    """Ebbinghaus forgetting curve engine for spaced repetition.

    Combines multiple evidence-based scheduling algorithms:
      - SM-2 algorithm for ease-factor-based interval scheduling
      - Ebbinghaus exponential decay for retention estimation
      - Leitner box system for group scheduling
      - Power-law forgetting variant (Wixted & Carpenter)
      - Optimal interval computation from target retention rate

    Example:
        ef = EbbinghausForgetting()
        result = ef.review("item_1", quality=4)
        # → schedules next review in 6 days
    """

    # SM-2 constants
    DEFAULT_EASE_FACTOR = 2.5
    MIN_EASE_FACTOR = 1.3
    EASE_BONUS = 0.1
    EASE_PENALTY = 0.2
    EASE_PENALTY_LARGE = 0.35

    # Stability increase factor (per successful review)
    STABILITY_INCREASE = 1.3    # S_new = S_old * 1.3 on success
    STABILITY_DECREASE = 0.5    # S_new = S_old * 0.5 on lapse (SM-2 reset)

    # Leitner defaults
    LEITNER_LEVELS = 7
    LEITNER_BASE_INTERVAL = 1.0    # days for level 0

    def __init__(
        self,
        target_retention: float = 0.90,
        default_stability: float = 1.0,
        default_ease: float = 2.5,
        use_power_law: bool = False,
        power_law_beta: float = 0.5,
    ):
        """Initialize the forgetting curve engine.

        Args:
            target_retention: Desired retention probability (0-1, default 0.90)
            default_stability: Initial stability S for new items (days)
            default_ease: Initial SM-2 ease factor
            use_power_law: Use power-law R(t) = (1+t/S)^{-β} instead of exponential
            power_law_beta: β exponent for power-law variant (default 0.5)
        """
        self.target_retention = target_retention
        self.default_stability = default_stability
        self.default_ease = default_ease
        self.use_power_law = use_power_law
        self.power_law_beta = power_law_beta

        # Item store
        self._items: Dict[str, MemoryItem] = {}

        # Leitner boxes
        self._leitner_boxes: List[LeitnerBox] = []

    # ── Core Forgetting Curve ───────────────────────────────────

    def retention(self, t_days: float, stability: float) -> float:
        """Compute retention probability after t days with stability S.

        Exponential form (Ebbinghaus):        R(t) = exp(-t / S)
        Power-law form (Wixted & Carpenter):  R(t) = (1 + t/S)^{-β}

        Args:
            t_days: Time elapsed since last review (days)
            stability: Memory stability S

        Returns:
            Retention probability in [0, 1]
        """
        if t_days <= 0:
            return 1.0
        if stability <= 0:
            return 0.0

        if self.use_power_law:
            return (1.0 + t_days / stability) ** (-self.power_law_beta)
        else:
            return math.exp(-t_days / stability)

    def optimal_interval(self, stability: float) -> float:
        """Compute optimal review interval for target retention rate.

        Exponential:  R = exp(-t / S)  →  t = -S * ln(R_target)
        Power-law:    R = (1 + t/S)^{-β}  →  t = S * (R^{-1/β} - 1)

        Args:
            stability: Current stability S

        Returns:
            Optimal interval in days
        """
        if self.use_power_law:
            return stability * (
                self.target_retention ** (-1.0 / self.power_law_beta) - 1.0
            )
        else:
            return -stability * math.log(max(self.target_retention, 0.01))

    def forgetting_rate(self, stability: float) -> float:
        """Compute instantaneous forgetting rate at t=0.

        For exponential: dR/dt|_{t=0} = -1/S  (rate = 1/S)
        For power-law:   dR/dt|_{t=0} = -β/S  (rate = β/S)
        """
        if self.use_power_law:
            return self.power_law_beta / stability
        else:
            return 1.0 / stability

    # ── SM-2 Scheduling ─────────────────────────────────────────

    def _sm2_ease_factor(
        self, current_ef: float, quality: ReviewQuality
    ) -> float:
        """Adjust SM-2 ease factor based on review quality.

        Quality 5:  EF += 0.1
        Quality 4:  EF unchanged
        Quality 3:  EF -= 0.14
        Quality 2:  EF -= 0.22
        Quality 1:  EF -= 0.32
        Quality 0:  EF -= 0.40

        Minimum EF is 1.3 (Wozniak).
        """
        q = quality.value
        if q >= 5:
            new_ef = current_ef + self.EASE_BONUS
        elif q == 4:
            new_ef = current_ef
        elif q == 3:
            new_ef = current_ef - 0.14
        elif q == 2:
            new_ef = current_ef - 0.22
        elif q == 1:
            new_ef = current_ef - 0.32
        else:  # q == 0
            new_ef = current_ef - 0.40

        return max(new_ef, self.MIN_EASE_FACTOR)

    def _sm2_interval(
        self,
        quality: ReviewQuality,
        previous_interval: float,
        ease_factor: float,
        reviews: int,
    ) -> float:
        """Compute next interval using SM-2 algorithm.

        First review after lapse (quality < 3): reset to 1 day
        First successful review: 1 day
        Second successful review: 6 days
        Subsequent: previous_interval * ease_factor
        """
        if not quality.is_pass:
            return 1.0

        if reviews == 0:
            return 1.0
        elif reviews == 1:
            return 6.0
        else:
            interval = previous_interval * ease_factor
            return max(interval, 1.0)

    # ── Stability Update (D3-like) ──────────────────────────────

    def _update_stability(
        self,
        current_stability: float,
        difficulty: float,
        quality: ReviewQuality,
        days_elapsed: float,
    ) -> float:
        """Update memory stability based on review outcome.

        On success: S_new = S_old * (1 + gain * (1 - difficulty) * q_factor)
          - gain is proportional to review quality
          - Harder items (high difficulty) benefit less
        On failure: S_new = S_old * STABILITY_DECREASE (halve stability)

        This is a simplified D3-model approach (Piotr Wozniak, 2018).
        """
        if quality.is_pass:
            # Quality bonus: 0.1 for q=3, 1.0 for q=5
            q_factor = (quality.value - 2) / 3.0  # [0.33, 1.0]
            gain = 0.5 + 1.5 * q_factor           # [0.5, 2.0] based on quality
            increase = 1.0 + gain * (1.0 - difficulty)
            new_stability = current_stability * increase
        else:
            # Lapse: stability degrades
            new_stability = current_stability * self.STABILITY_DECREASE

        # Clamp to reasonable range
        return max(new_stability, 0.01)

    def _update_difficulty(
        self, current_difficulty: float, quality: ReviewQuality
    ) -> float:
        """Update intrinsic difficulty estimate.

        Successful review → item becomes slightly easier (lower D)
        Failed review → item becomes slightly harder (higher D)
        D is bounded in [0, 1].
        """
        q = quality.value
        # Map quality to difficulty delta
        # q=5 → -0.05, q=4 → -0.02, q=3 → +0.01, q=2 → +0.05, q=1 → +0.08, q=0 → +0.10
        deltas = {5: -0.05, 4: -0.02, 3: 0.01, 2: 0.05, 1: 0.08, 0: 0.10}
        delta = deltas.get(q, 0.0)
        new_d = current_difficulty + delta
        return max(0.0, min(1.0, new_d))

    # ── Public Scheduling API ───────────────────────────────────

    def review(
        self,
        item_id: str,
        quality: Union[int, ReviewQuality],
        item_data: Optional[Dict[str, Any]] = None,
    ) -> ReviewResult:
        """Process a review for an item and schedule next review.

        Args:
            item_id: Unique identifier for the item
            quality: Review quality (0-5 int or ReviewQuality enum)
            item_data: Optional initial data for new items (dict with keys:
                       stability, difficulty, ease_factor, interval_days)

        Returns:
            ReviewResult with scheduling details
        """
        if isinstance(quality, int):
            quality = ReviewQuality.from_int(quality)

        # Get or create item
        item = self._items.get(item_id)
        if item is None:
            item = MemoryItem(item_id=item_id)
            if item_data:
                item.stability = item_data.get("stability", self.default_stability)
                item.difficulty = item_data.get("difficulty", 0.3)
                item.ease_factor = item_data.get("ease_factor", self.default_ease)
                item.interval_days = item_data.get("interval_days", 1.0)
            else:
                item.stability = self.default_stability
                item.ease_factor = self.default_ease
            self._items[item_id] = item

        # Capture pre-review state
        days_elapsed = item.days_since_last_review()
        estimated_retention = item.retention_probability()
        prev_interval = item.interval_days
        prev_ease = item.ease_factor
        prev_stability = item.stability

        # Update difficulty
        item.difficulty = self._update_difficulty(item.difficulty, quality)

        # Update ease factor (SM-2)
        item.ease_factor = self._sm2_ease_factor(item.ease_factor, quality)

        # Compute next interval (SM-2)
        new_interval = self._sm2_interval(
            quality, item.interval_days, item.ease_factor, item.reviews
        )
        item.interval_days = new_interval

        # Update stability
        item.stability = self._update_stability(
            item.stability, item.difficulty, quality, days_elapsed
        )

        # Update review counters
        now = time.time()
        item.last_review = now
        item.next_review = now + new_interval * 86400.0
        item.reviews += 1
        if not quality.is_pass:
            item.lapses += 1

        return ReviewResult(
            item_id=item_id,
            quality=quality,
            passed=quality.is_pass,
            previous_interval=prev_interval,
            new_interval=new_interval,
            previous_ease=prev_ease,
            new_ease=item.ease_factor,
            previous_stability=prev_stability,
            new_stability=item.stability,
            estimated_retention=estimated_retention,
            next_review_timestamp=item.next_review,
            scheduled_days=new_interval,
        )

    def get_item(self, item_id: str) -> Optional[MemoryItem]:
        """Retrieve a tracked memory item by ID."""
        return self._items.get(item_id)

    def get_due_items(self) -> List[str]:
        """Return IDs of all items currently due for review."""
        now = time.time()
        return [
            item_id for item_id, item in self._items.items()
            if item.next_review == 0 or item.next_review <= now
        ]

    def get_retention_estimate(self, item_id: str) -> Optional[float]:
        """Get current retention probability for an item."""
        item = self._items.get(item_id)
        if item is None:
            return None
        return item.retention_probability()

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from tracking. Returns True if it existed."""
        return self._items.pop(item_id, None) is not None

    # ── Leitner Box System ──────────────────────────────────────

    def init_leitner(
        self,
        levels: int = 7,
        base_interval: float = 1.0,
    ) -> None:
        """Initialize Leitner box system.

        Box i (0-indexed) has review interval = base_interval * 2^i.
        """
        self.LEITNER_LEVELS = levels
        self.LEITNER_BASE_INTERVAL = base_interval
        self._leitner_boxes = [
            LeitnerBox(level=i, review_interval_days=base_interval * (2 ** i))
            for i in range(levels)
        ]

    def leitner_add(self, item_id: str) -> None:
        """Add an item to the Leitner system (starts in box 0)."""
        if not self._leitner_boxes:
            self.init_leitner()
        self._leitner_boxes[0].items.append(item_id)

    def leitner_promote(self, item_id: str) -> int:
        """Move an item to next higher box (correct recall).
        Returns new box level, or -1 if item not in any box."""
        for i, box in enumerate(self._leitner_boxes):
            if item_id in box.items:
                box.items.remove(item_id)
                new_level = min(i + 1, len(self._leitner_boxes) - 1)
                self._leitner_boxes[new_level].items.append(item_id)
                return new_level
        return -1

    def leitner_demote(self, item_id: str) -> int:
        """Move an item back to box 0 (incorrect recall).
        Returns 0 on success, -1 if item not in any box."""
        for box in self._leitner_boxes:
            if item_id in box.items:
                box.items.remove(item_id)
                self._leitner_boxes[0].items.append(item_id)
                return 0
        return -1

    def leitner_get_due(self) -> List[Tuple[str, int, float]]:
        """Get items due for review in the Leitner system.
        Returns list of (item_id, box_level, interval_days)."""
        due = []
        now = time.time()
        for i, box in enumerate(self._leitner_boxes):
            interval_seconds = box.review_interval_days * 86400.0
            for item_id in box.items:
                item = self._items.get(item_id)
                if item is None or item.last_review == 0:
                    due.append((item_id, i, box.review_interval_days))
                elif now - item.last_review >= interval_seconds:
                    due.append((item_id, i, box.review_interval_days))
        return due

    # ── Batch Scheduling ────────────────────────────────────────

    def schedule_batch(
        self, items: List[Tuple[str, int]]
    ) -> List[ReviewResult]:
        """Process multiple reviews at once.

        Args:
            items: List of (item_id, quality) tuples

        Returns:
            List of ReviewResult for each item
        """
        return [self.review(item_id, quality) for item_id, quality in items]

    # ── Statistics ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics about tracked items."""
        if not self._items:
            return {"total_items": 0}

        items = list(self._items.values())
        stabilities = [item.stability for item in items]
        difficulties = [item.difficulty for item in items]
        intervals = [item.interval_days for item in items]

        return {
            "total_items": len(items),
            "due_items": len(self.get_due_items()),
            "avg_stability": sum(stabilities) / len(stabilities),
            "avg_difficulty": sum(difficulties) / len(difficulties),
            "avg_interval_days": sum(intervals) / len(intervals),
            "max_interval_days": max(intervals),
            "total_reviews": sum(item.reviews for item in items),
            "total_lapses": sum(item.lapses for item in items),
            "target_retention": self.target_retention,
            "curve_type": "power-law" if self.use_power_law else "exponential",
        }

    def get_retention_curve(
        self, stability: float, max_days: int = 30, points: int = 100
    ) -> List[Tuple[float, float]]:
        """Compute the retention curve for a given stability over time.

        Args:
            stability: Memory stability S
            max_days: Maximum days to plot
            points: Number of points on the curve

        Returns:
            List of (days, retention_probability) pairs
        """
        curve = []
        for i in range(points):
            t = (i / (points - 1)) * max_days if points > 1 else 0
            r = self.retention(t, stability)
            curve.append((t, r))
        return curve


# ═══════════════════════════════════════════════════════════════════
# Convenience factory
# ═══════════════════════════════════════════════════════════════════

def get_ebbinghaus_forgetting(
    target_retention: float = 0.90,
    use_power_law: bool = False,
) -> EbbinghausForgetting:
    """Factory for EbbinghausForgetting with sensible defaults."""
    return EbbinghausForgetting(
        target_retention=target_retention,
        use_power_law=use_power_law,
    )
