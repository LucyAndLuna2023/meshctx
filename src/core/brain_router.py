"""meshctx brain_router — 脑启发路由"""
import numpy as np
import hashlib

class SymbolicProjector:
    def __init__(self, symbol_dim=32, vector_dim=128, **kw):
        self.symbol_dim = symbol_dim
        self.vector_dim = vector_dim
    def encode(self, text, **kw):
        h = hashlib.sha256(text.encode()).digest()
        vec = np.frombuffer(h, dtype=np.uint8).astype(float) / 255.0
        if len(vec) < self.vector_dim:
            vec = np.tile(vec, (self.vector_dim // len(vec) + 1))[:self.vector_dim]
        return vec[:self.vector_dim]
    def decode(self, vec, top_k=1, **kw):
        return ["decoded_symbol"] * min(top_k, 3)

class SparseAttentionRouter:
    def __init__(self, num_experts=8, sparsity=2, **kw):
        self.num_experts = num_experts
        self.sparsity = sparsity
    def route(self, query, **kw):
        q = np.asarray(query, dtype=float)
        # v3.115.16: deterministic routing based on query, not random
        if q.ndim == 0:
            q = np.array([q])
        # Compute scores via dot product with learned preference vectors
        seed = int(np.sum(np.abs(q)) * 1000) % 10000
        rng = np.random.RandomState(seed)
        preference = rng.randn(self.num_experts, len(q)) * 0.1
        scores = np.abs(preference @ q)
        scores = scores / (scores.max() + 1e-8)
        # Keep only top-sparsity
        threshold = np.sort(scores)[-self.sparsity]
        scores[scores < threshold] = 0
        if scores.sum() > 0:
            scores /= scores.sum()
        return scores

class PsiParameterizedComplexity:
    def __init__(self, **kw):
        pass
    def estimate(self, model_name, params=0, **kw):
        return max(0.1, np.log10(max(params, 1)) * 0.5)
    def get_optimal_model(self, target_psi, models, **kw):
        return models[0] if models else "unknown"

class BrainInspiredRouter:
    def __init__(self, **kw):
        self._projector = SymbolicProjector()
        self._route_count = 0
    def route(self, query, models, **kw):
        self._route_count += 1
        h = hashlib.sha256(query.encode()).digest()[0]
        idx = h % len(models)
        return models[idx]
    def get_stats(self, **kw):
        return {"projector": "active", "routes": self._route_count}

