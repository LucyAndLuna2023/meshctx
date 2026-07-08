"""meshctx context_compression — sliding window + truncation compressor

Strategy:
  1. Split text into sentences
  2. Preserve sentences containing user-specified keywords
  3. Apply sliding window to remaining sentences to keep top-N by length/importance
  4. Truncate to fit within a reasonable fraction
  5. Return CompressionResult with compression ratio

Design constraints: pure Python, no external deps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CompressionResult:
    """Result of a single compression pass."""

    text: str
    original_length: int
    compressed_length: int

    @property
    def ratio(self) -> float:
        """Compression ratio: compressed_len / original_len (1.0 = no change)."""
        if self.original_length == 0:
            return 1.0
        return self.compressed_length / self.original_length


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

_SENTENCE_PAT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    """Split text into sentences, preserving delimiters loosely."""
    parts = _SENTENCE_PAT.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# ContextCompressor
# ---------------------------------------------------------------------------

class ContextCompressor:
    """Sliding-window + truncation context compressor.

    Usage::

        c = ContextCompressor()
        result = c.compress(long_text, preserve_keywords=["important"])
        print(result.ratio)
    """

    # Tuning knobs -----------------------------------------------------------
    SHORT_TEXT_THRESHOLD: int = 50       # below this char count, never compress
    DEFAULT_KEEP_FRAC: float = 0.6       # fraction of sentences to retain
    SLIDING_WINDOW_SIZE: int = 3         # sentences per window

    def __init__(self) -> None:
        self._stats: Dict[str, Any] = {"compressions": 0}

    # -- public API ----------------------------------------------------------

    def compress(
        self,
        text: str,
        preserve_keywords: Optional[List[str]] = None,
        keep_frac: Optional[float] = None,
    ) -> CompressionResult:
        """Compress *text* using sliding-window sentence selection.

        *preserve_keywords* — sentences containing any of these words are
        always kept (case-insensitive match).

        Returns a ``CompressionResult`` whose ``.ratio`` property gives the
        compression ratio (1.0 = no change).
        """
        original_len = len(text)

        # Short circuit: nothing to compress
        if original_len <= self.SHORT_TEXT_THRESHOLD:
            self._stats["compressions"] += 1
            return CompressionResult(
                text=text,
                original_length=original_len,
                compressed_length=original_len,
            )

        sentences = _sentences(text)
        if len(sentences) <= 2:
            self._stats["compressions"] += 1
            return CompressionResult(
                text=text,
                original_length=original_len,
                compressed_length=original_len,
            )

        preserve = set(k.lower() for k in (preserve_keywords or []))

        # Separate preserved (keyword) sentences from candidates
        preserved: list[str] = []
        candidates: list[str] = []
        for s in sentences:
            if preserve and any(k in s.lower() for k in preserve):
                preserved.append(s)
            else:
                candidates.append(s)

        frac = keep_frac if keep_frac is not None else self.DEFAULT_KEEP_FRAC
        target_count = max(1, int(len(sentences) * frac))

        # If preserved sentences already fill the budget, use only them
        if len(preserved) >= target_count:
            selected = preserved[:target_count]
        else:
            budget = target_count - len(preserved)
            # Sliding window: score each candidate sentence by length
            # (longer sentences carry more information) and pick the
            # top-scoring sentences from each window.
            selected_candidates = self._sliding_window_select(candidates, budget)
            selected = preserved + selected_candidates

        compressed = " ".join(selected)
        self._stats["compressions"] += 1

        return CompressionResult(
            text=compressed,
            original_length=original_len,
            compressed_length=len(compressed),
        )

    def hierarchical_compress(
        self,
        text: str,
        levels: int = 2,
        preserve_keywords: Optional[List[str]] = None,
    ) -> List[CompressionResult]:
        """Apply compression repeatedly, each level more aggressive.

        Returns a list of ``CompressionResult``, one per level.
        """
        results: List[CompressionResult] = []
        current = text
        for level in range(levels):
            # Each successive level keeps a smaller fraction
            frac = max(0.2, self.DEFAULT_KEEP_FRAC - (level * 0.25))
            r = self.compress(current, preserve_keywords=preserve_keywords, keep_frac=frac)
            results.append(r)
            current = r.text
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Return internal statistics dict (includes ``compressions`` count)."""
        return dict(self._stats)

    # -- internals -----------------------------------------------------------

    def _sliding_window_select(self, sentences: list[str], budget: int) -> list[str]:
        """Pick up to *budget* sentences via sliding-window scoring."""
        if not sentences or budget <= 0:
            return []
        if len(sentences) <= budget:
            return sentences

        n = len(sentences)
        w = self.SLIDING_WINDOW_SIZE
        # Score each sentence as the max-length sentence in its window
        scores: list[tuple[int, float]] = []
        for i in range(n):
            lo = max(0, i - w // 2)
            hi = min(n, i + w // 2 + 1)
            window_max = max(len(sentences[j]) for j in range(lo, hi))
            scores.append((i, window_max))

        # Sort by score descending, pick top budget, then restore original order
        selected_indices = sorted(
            [idx for idx, _ in sorted(scores, key=lambda x: x[1], reverse=True)[:budget]]
        )
        return [sentences[i] for i in selected_indices]


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_compressor: Optional[ContextCompressor] = None


def get_context_compressor() -> ContextCompressor:
    """Return the singleton ``ContextCompressor`` instance."""
    global _compressor
    if _compressor is None:
        _compressor = ContextCompressor()
    return _compressor
