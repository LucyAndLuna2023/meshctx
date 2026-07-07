"""meshctx context_compressor — Context compression with vector memory"""

from dataclasses import dataclass, field
from enum import Enum
import numpy as np


class CompressionLevel(Enum):
    LIGHT = "light"
    MEDIUM = "medium"
    DEEP = "deep"


@dataclass
class Frame:
    role: str
    text: str
    timestamp: float = 0.0


class CompressedMemory:
    """Vector-indexed memory with deduplication and FIFO eviction."""

    def __init__(self, dim: int = 64, capacity: int = 100):
        self.dim = dim
        self.capacity = capacity
        self.slots: list = []  # list of (vector, meta) tuples

    def add(self, vector, meta=None):
        """Add a vector to memory with optional metadata."""
        v = np.asarray(vector, dtype=np.float64)
        # Deduplicate: check if highly similar vector exists
        for slot_vec, _ in self.slots:
            sim = self._cosine_sim(v, slot_vec)
            if sim > 0.99:
                return  # near-duplicate, skip
        # FIFO eviction
        if len(self.slots) >= self.capacity:
            self.slots.pop(0)
        self.slots.append((v, meta or {}))

    def retrieve(self, query_vector, top_k: int = 5):
        """Retrieve top-k most similar vectors."""
        q = np.asarray(query_vector, dtype=np.float64)
        scored = []
        for slot_vec, meta in self.slots:
            sim = self._cosine_sim(q, slot_vec)
            scored.append((meta, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _cosine_sim(self, a, b):
        """Cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))


class ContextCompressor:
    """Compresses conversation context using vector-based summarization."""

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.frames: list = []
        self._memory = CompressedMemory(dim=dim, capacity=100)
        self._stats = {"total_frames": 0, "compressions": 0, "tokens_saved_est": 0}
        self._import_time = __import__("time").time()

    def add_frame(self, role: str, text: str):
        """Add a conversation frame."""
        f = Frame(role=role, text=text, timestamp=__import__("time").time())
        self.frames.append(f)
        self._stats["total_frames"] = len(self.frames)
        # Store a simple vector embedding (hash-based)
        vec = self._text_to_vector(text)
        self._memory.add(vec, {"role": role, "idx": len(self.frames) - 1})
        return f

    def _text_to_vector(self, text: str):
        """Convert text to a simple vector representation."""
        h = hash(text) % (2**31)
        np.random.seed(abs(h))
        return np.random.randn(self.dim).astype(np.float64) * 0.1

    def compress(self, level: CompressionLevel):
        """Compress frames according to the specified level."""
        self._stats["compressions"] += 1
        total = len(self.frames)

        if level == CompressionLevel.LIGHT:
            # Keep everything but remove highly similar adjacent frames
            kept = [self.frames[0]] if self.frames else []
            for i in range(1, len(self.frames)):
                prev = self.frames[i - 1]
                curr = self.frames[i]
                # Skip if nearly identical to previous
                if self._text_similarity(prev.text, curr.text) < 0.95:
                    kept.append(curr)
            result = kept
        elif level == CompressionLevel.MEDIUM:
            # Keep system + last N frames, summarize middle
            system_frames = [f for f in self.frames if f.role == "system"]
            non_system = [f for f in self.frames if f.role != "system"]
            keep_recent = min(6, len(non_system))
            recent = non_system[-keep_recent:] if non_system else []
            result = system_frames + recent
        elif level == CompressionLevel.DEEP:
            # Keep only system + very recent frames
            system_frames = [f for f in self.frames if f.role == "system"]
            non_system = [f for f in self.frames if f.role != "system"]
            keep_recent = min(5, len(non_system))
            recent = non_system[-keep_recent:] if non_system else []
            result = system_frames + recent
        else:
            result = list(self.frames)

        # Estimate tokens saved
        original_tokens = sum(len(f.text) for f in self.frames)
        kept_tokens = sum(len(f.text) for f in result)
        self._stats["tokens_saved_est"] += max(0, original_tokens - kept_tokens)

        return result

    def _text_similarity(self, a: str, b: str):
        """Simple character-level similarity."""
        if not a and not b:
            return 1.0
        shorter = min(len(a), len(b))
        if shorter == 0:
            return 0.0
        matches = sum(1 for i in range(shorter) if a[i] == b[i])
        return matches / shorter

    def reconstruct_context(self):
        """Reconstruct a text context from compressed frames."""
        parts = []
        for f in self.frames:
            parts.append(f"[{f.role}] {f.text}")
        return "\n".join(parts)

    def get_stats(self):
        """Get compressor statistics."""
        total = self._stats["total_frames"]
        tokens_saved = self._stats["tokens_saved_est"]
        return {
            "total_frames": total,
            "compression_ratio": 1.0 if total == 0 else max(0.3, 1.0 - tokens_saved / max(1, total * 10)),
            "tokens_saved_est": tokens_saved,
        }
