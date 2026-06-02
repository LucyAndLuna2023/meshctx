"""
MeshCtx v3.35 — Brain-Inspired Router (脑启发模型路由器)
符号投影+稀疏注意力+Psi参数化复杂度+脑启发路由
"""
import math
import numpy as np
from typing import Optional, List, Dict, Any, Tuple


class SymbolicProjector:
    """神经符号投影器 — 离散符号↔连续向量映射"""
    
    def __init__(self, symbol_dim: int = 64, vector_dim: int = 256):
        self.symbol_dim = symbol_dim
        self.vector_dim = vector_dim
        self.projection_matrix: np.ndarray = np.random.randn(vector_dim, symbol_dim) * 0.02
        self.symbol_table: Dict[str, np.ndarray] = {}
    
    def encode(self, symbol: str) -> np.ndarray:
        if symbol not in self.symbol_table:
            vec = np.random.randn(self.symbol_dim) * 0.1
            self.symbol_table[symbol] = vec
        return self.projection_matrix @ self.symbol_table[symbol]
    
    def decode(self, vector: np.ndarray, top_k: int = 3) -> List[Tuple[str, float]]:
        if not self.symbol_table:
            return []
        scores = []
        for sym, sym_vec in self.symbol_table.items():
            proj = self.projection_matrix @ sym_vec
            sim = float(np.dot(vector, proj) / (np.linalg.norm(vector) * np.linalg.norm(proj) + 1e-10))
            scores.append((sym, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    
    def get_stats(self) -> Dict[str, Any]:
        return {"num_symbols": len(self.symbol_table), "symbol_dim": self.symbol_dim, "vector_dim": self.vector_dim}


class SparseAttentionRouter:
    """稀疏注意力路由器 — k-WTA+局部抑制"""
    
    def __init__(self, num_experts: int = 8, sparsity: int = 2):
        self.num_experts = num_experts
        self.sparsity = sparsity
        self.expert_weights: np.ndarray = np.random.randn(num_experts, 256) * 0.1
        self.usage_counts: np.ndarray = np.zeros(num_experts)
    
    def route(self, query: np.ndarray) -> np.ndarray:
        # Ensure query matches expected dimension
        if len(query) > 256:
            query = query[:256]
        elif len(query) < 256:
            query = np.pad(query, (0, 256 - len(query)))
        scores = self.expert_weights @ query
        top_k_indices = np.argsort(scores)[-self.sparsity:]
        mask = np.zeros(self.num_experts)
        mask[top_k_indices] = 1.0
        self.usage_counts += mask
        return mask * scores
    
    def load_balance(self) -> float:
        total = self.usage_counts.sum()
        if total == 0:
            return 1.0
        probs = self.usage_counts / total
        entropy = -np.sum(probs * np.log(probs + 1e-10))
        return float(entropy / math.log(self.num_experts))
    
    def get_stats(self) -> Dict[str, Any]:
        return {"num_experts": self.num_experts, "sparsity": self.sparsity, "load_balance": self.load_balance()}


class PsiParameterizedComplexity:
    """Ψ参数化复杂度 — 用复杂度参数Ψ统一度量模型能力"""
    
    def __init__(self):
        self.complexity_cache: Dict[str, float] = {}
    
    def estimate(self, model_name: str, params: Optional[int] = None) -> float:
        if model_name in self.complexity_cache:
            return self.complexity_cache[model_name]
        if params is not None:
            psi = math.log(params + 1) / math.log(10)
        else:
            # Heuristic: estimate complexity from model name patterns
            ml = model_name.lower()
            if any(k in ml for k in ['gpt-4', 'gpt4', 'claude-3', 'claude3', 'gemini-ultra', 'gemini-2', 'o1', 'o3']):
                psi = 12.0
            elif any(k in ml for k in ['gpt-3.5', 'claude', 'gemini-pro', 'llama-3-70', 'mixtral', 'command-r']):
                psi = 10.5
            elif any(k in ml for k in ['large', 'pro', 'turbo', 'llama-3', 'qwen-72', 'deepseek']):
                psi = 9.0
            elif any(k in ml for k in ['medium', 'llama-2-13', 'mistral', 'qwen-14', 'phi-3']):
                psi = 7.0
            elif any(k in ml for k in ['small', 'tiny', 'mini', 'llama-2-7', 'qwen-7', 'phi-2']):
                psi = 5.0
            else:
                psi = 3.0
        self.complexity_cache[model_name] = psi
        return psi
    
    def compare(self, model_a: str, model_b: str) -> float:
        return self.estimate(model_a) - self.estimate(model_b)
    
    def get_optimal_model(self, task_complexity: float, candidates: List[str]) -> str:
        best = candidates[0]
        best_diff = float('inf')
        for c in candidates:
            diff = abs(self.estimate(c) - task_complexity)
            if diff < best_diff:
                best_diff = diff
                best = c
        return best


class BrainInspiredRouter:
    """脑启发路由器 — 融合3个子系统"""
    
    def __init__(self, n_experts: int = 8, input_dim: int = 256, **kwargs):
        self.n_experts = n_experts
        self.input_dim = input_dim
        self.projector = SymbolicProjector()
        self.attention = SparseAttentionRouter(num_experts=n_experts)
        self.complexity = PsiParameterizedComplexity()
    
    def route(self, query_text: str, candidates: List[str]) -> str:
        if not candidates:
            return ""
        query_vec = self.projector.encode(query_text[:20])
        scores = self.attention.route(query_vec)
        # Find the best-scoring expert within candidate range
        top_indices = np.argsort(scores)[::-1]
        for idx in top_indices:
            if int(idx) < len(candidates):
                return candidates[int(idx)]
        # Fallback: use Psi complexity to pick the best match
        psi_scores = [(m, self.complexity.estimate(m)) for m in candidates]
        return max(psi_scores, key=lambda x: x[1])[0]
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "projector": self.projector.get_stats(),
            "attention": self.attention.get_stats(),
            "complexity_models": len(self.complexity.complexity_cache),
        }
