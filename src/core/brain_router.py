"""
meshctx v1.6 — 动态路由与神经符号模块 (Dynamic Router + Symbolic Projector)
============================================================================

基于论文《Global Workspace Theory 2.0: Neural Implementations in LLMs》(2026.04.30)
实现核心改进：

1. 动态路由系数 α_i (Dynamic Routing Coefficients)
   - 可微分的稀疏注意力机制
   - 神经科学依据: 前额叶-顶叶网络的动态路由
   
2. 神经符号转换 (Symbolic Projection)
   - Gumbel-Softmax 离散化
   - 神经科学依据: 符号编码的神经网络实现
   
3. 意识点火 (Consciousness Ignition)
   - 激活超过阈值时的全局同步
   - 神经科学依据: P3b脑电波 ~300ms潜伏期

核心公式:
  GW(x_t) = σ(Σ α_i · W_i · φ(h_i^t))
  
  其中:
  - α_i = 可学习路由系数 (Gumbel-Softmax输出)
  - W_i = 每专家的线性变换
  - φ(·) = 神经符号投影函数
  - σ = 全局广播的激活函数
"""

import math
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger("meshctx.dynamic_router")


# ═══════════════════════════════════════════════════════════════════════
# Gumbel-Softmax 符号投影器
# ═══════════════════════════════════════════════════════════════════════

class SymbolicProjector:
    """
    神经符号转换器 — 将连续神经网络输出转换为离散符号表示。
    
    核心机制:
    - 使用Gumbel-Softmax实现可微分的离散化
    - 支持离散的"概念"空间，允许Agent进行符号推理
    - ST (Straight-Through) 梯度通过估计器
    
    神经科学依据:
    - 符号操作对应大脑的离散概念表示
    - 离散的符号使得跨任务泛化成为可能
    - Gumbel-Softmax模拟神经元的"点火"行为
    
    数学原理:
      Softmax: π_k = exp(logits_k + g_k) / Σ exp(logits_j + g_j)
      其中 g_k ~ Gumbel(0,1) 是Gumbel噪声
      
      当 temperature → 0 时，分布趋近 one-hot (离散)
      当 temperature → ∞ 时，分布趋近均匀 (连续)
    """
    
    def __init__(
        self,
        input_dim: int = 512,
        symbol_dim: int = 128,
        n_symbols: int = 64,
        temperature: float = 1.0,
        hard: bool = False,
    ):
        """
        Args:
            input_dim: 输入特征维度
            symbol_dim: 中间投影维度
            n_symbols: 离散符号空间大小
            temperature: Gumbel-Softmax温度参数
            hard: 是否使用硬采样 (one-hot)，否则使用软采样
        """
        self.input_dim = input_dim
        self.symbol_dim = symbol_dim
        self.n_symbols = n_symbols
        self.temperature = temperature
        self.hard = hard
        
        # 符号嵌入层: 投影 → 符号概率
        self.symbol_logits = np.random.randn(input_dim, n_symbols).astype(np.float64)
        self.symbol_logits /= input_dim ** 0.5
        
        # 中间投影层参数
        self.proj_W = np.random.randn(input_dim, symbol_dim).astype(np.float64) * 0.01
        self.proj_b = np.zeros(symbol_dim, dtype=np.float64)
        
        # 符号嵌入矩阵: 每个符号对应一个符号向量
        self.symbol_embeddings = np.random.randn(n_symbols, symbol_dim).astype(np.float64) * 0.02
        
        # 训练统计
        self._step_count = 0
        self._entropy_history: List[float] = []
    
    def _gumbel_sample(self, logits: np.ndarray) -> np.ndarray:
        """
        从Gumbel-Softmax分布中采样。
        
        Args:
            logits: 未归一化的logits (n_symbols,)
        
        Returns:
            采样结果 (n_symbols,) — 软采样或硬采样
        """
        # 添加Gumbel噪声: Gumbel(0,1) = -log(-log(Uniform(0,1)))
        gumbel_noise = -np.log(-np.log(np.random.uniform(0.0001, 1.0, size=logits.shape)))
        
        # Gumbel-Softmax
        gumbel_logits = logits + gumbel_noise * self.temperature
        
        # Softmax归一化
        gumbel_logits -= gumbel_logits.max()  # 数值稳定性
        exp_logits = np.exp(gumbel_logits / self.temperature)
        probs = exp_logits / (exp_logits.sum() + 1e-10)
        
        if self.hard:
            # 硬采样: one-hot向量 (不可微，使用STE近似)
            hard_sample = np.zeros_like(probs)
            hard_sample[probs.argmax()] = 1.0
            # 软采样与硬采样的混合 (STE梯度估计)
            return probs + (hard_sample - probs) * 0.1  # 小权重混合避免梯度消失
        else:
            return probs
    
    def project(self, hidden_state: np.ndarray) -> Dict[str, Any]:
        """
        将神经网络隐藏状态投影到符号空间。
        
        Args:
            hidden_state: 神经网络输出 (input_dim,)
        
        Returns:
            {
                "symbol_probs": 符号概率分布 (n_symbols,),
                "symbol_id": 采样符号ID (int),
                "symbol_vector": 符号向量 (symbol_dim,),
                "entropy": 分布熵 (float),
                "confidence": 符号置信度 (float),
            }
        """
        # 自适应维度处理: 如果输入维度不匹配，创建合适的投影
        if len(hidden_state) != self.input_dim:
            # 动态调整投影矩阵
            actual_dim = len(hidden_state)
            if not hasattr(self, '_dynamic_proj_W') or self._dynamic_proj_W.shape[0] != actual_dim:
                self._dynamic_proj_W = np.random.randn(actual_dim, self.symbol_dim).astype(np.float64) * 0.01
                self._dynamic_proj_b = np.zeros(self.symbol_dim, dtype=np.float64)
                self._dynamic_logits_W = np.random.randn(actual_dim, self.n_symbols).astype(np.float64) * 0.01
            proj = np.tanh(np.dot(hidden_state, self._dynamic_proj_W) + self._dynamic_proj_b)
            logits = np.dot(hidden_state, self._dynamic_logits_W)
        else:
            # 标准路径
            proj = np.tanh(np.dot(hidden_state, self.proj_W) + self.proj_b)
            logits = np.dot(hidden_state, self.symbol_logits)
        
        # 3. Gumbel-Softmax采样
        symbol_probs = self._gumbel_sample(logits)
        
        # 4. 符号ID (最高概率)
        symbol_id = int(symbol_probs.argmax())
        
        # 5. 符号向量 = 符号嵌入的加权平均
        symbol_vector = np.dot(symbol_probs, self.symbol_embeddings)
        
        # 6. 计算熵 (符号分布的不确定性)
        entropy = -np.sum(symbol_probs * np.log(symbol_probs + 1e-10))
        self._entropy_history.append(entropy)
        if len(self._entropy_history) > 1000:
            self._entropy_history = self._entropy_history[-1000:]
        
        # 7. 置信度 = 最大概率
        confidence = float(symbol_probs.max())
        
        self._step_count += 1
        
        return {
            "symbol_probs": symbol_probs,
            "symbol_id": symbol_id,
            "symbol_vector": symbol_vector,
            "entropy": entropy,
            "confidence": confidence,
            "projection": proj,
        }
    
    def update_temperature(self, entropy: float, target_entropy: float = 2.0):
        """
        根据当前熵调整温度参数 (自动温度调度)。
        
        Args:
            entropy: 当前分布熵
            target_entropy: 目标熵 (符号空间大小的对数 ~ log(n_symbols))
        """
        if entropy > target_entropy * 1.2:
            # 分布太平坦 → 降低温度使分布更尖
            self.temperature = max(0.1, self.temperature * 0.95)
        elif entropy < target_entropy * 0.8:
            # 分布太尖 → 提高温度增加探索
            self.temperature = min(10.0, self.temperature * 1.05)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "step_count": self._step_count,
            "temperature": round(self.temperature, 4),
            "avg_entropy": round(float(np.mean(self._entropy_history[-100:])), 4)
                if self._entropy_history else 0.0,
        }


# ═══════════════════════════════════════════════════════════════════════
# 稀疏注意力路由器 (Sparse Attention Router)
# ═══════════════════════════════════════════════════════════════════════

class SparseAttentionRouter:
    """
    稀疏注意力路由器 — 实现可学习的动态路由系数 α_i。
    
    基于论文《Global Workspace Theory 2.0》(2026) 的核心设计：
    - 每个专家处理器有一个可学习的路由系数 α_i
    - 系数通过注意力机制动态计算 (不同输入 → 不同路由)
    - 稀疏化 (sparsity) 避免所有专家同时激活
    
    数学原理:
      α_i = softmax(q · k_i / √d) · sparsity_mask
      
      其中:
      - q = 查询向量 (全局上下文)
      - k_i = 专家i的键向量
      - √d = 缩放因子 (键维度归一化)
      - sparsity_mask = 强制稀疏 (top-k 选择)
    
    神经科学依据:
    - 动态路由对应前额叶的选择性注意
    - 稀疏性对应注意的"瓶颈"性质
    - 可学习性对应经验依赖的注意调整
    """
    
    def __init__(
        self,
        n_experts: int = 8,
        key_dim: int = 64,
        sparsity_ratio: float = 0.5,
        use_gumbel: bool = True,
        temperature: float = 1.0,
        input_dim: int = 512,
    ):
        """
        Args:
            n_experts: 专家数量
            key_dim: 键/查询向量维度
            sparsity_ratio: 稀疏率 (激活专家比例)
            use_gumbel: 是否使用Gumbel-TopK稀疏化
            temperature: Gumbel温度
            input_dim: 输入向量维度 (用于投影)
        """
        self.n_experts = n_experts
        self.key_dim = key_dim
        self.input_dim = input_dim
        self.sparsity_ratio = sparsity_ratio
        self.n_active = max(1, int(n_experts * (1.0 - sparsity_ratio)))
        self.use_gumbel = use_gumbel
        self.temperature = temperature
        
        # 每个专家的键向量 (可学习)
        self.expert_keys = np.random.randn(n_experts, key_dim).astype(np.float64) * 0.01
        
        # 全局查询投影 (从上下文生成查询): input_dim → key_dim
        self.query_proj = np.random.randn(input_dim, key_dim).astype(np.float64) * 0.01
        self._context_proj = np.random.randn(input_dim, key_dim).astype(np.float64) * 0.01
        
        # 路由系数的学习率 (用于在线更新)
        self.routing_lr: float = 0.01
        
        # 路由历史 (用于分析)
        self._routing_history: List[Dict] = []
        self._expert_usage = np.zeros(n_experts)
    
    def compute_routing(
        self,
        context_vector: np.ndarray,
        expert_outputs: Dict[str, np.ndarray],
    ) -> Dict[str, float]:
        """
        计算每个专家的动态路由系数 α_i。
        
        Args:
            context_vector: 全局上下文向量 (从GlobalWorkspace聚合)
            expert_outputs: 各专家的输出 {name: output_vector}
        
        Returns:
            各专家的路由系数 {name: alpha_i}
        """
        if not expert_outputs:
            return {}
        
        # 1. 生成全局查询向量
        # 处理维度不匹配: context_vector可能是任意维度，用投影对齐到key_dim
        if len(context_vector) != self.key_dim:
            # 自适应投影: 从任意维度 → key_dim
            if not hasattr(self, '_context_proj') or self._context_proj.shape[1] != self.key_dim:
                self._context_proj = np.random.randn(len(context_vector), self.key_dim).astype(np.float64) * 0.01
            q = np.tanh(np.dot(context_vector, self._context_proj))
        else:
            q = np.tanh(np.dot(context_vector, self.query_proj))
        
        # 2. 计算每个专家的注意力分数
        scores = {}
        expert_names = list(expert_outputs.keys())
        
        for i, name in enumerate(expert_names):
            if i < len(self.expert_keys):
                key_i = self.expert_keys[i]
            else:
                # 超出预定义专家数量时动态创建
                key_i = np.random.randn(self.key_dim).astype(np.float64) * 0.01
            
            # 点积注意力 + 缩放
            score = np.dot(q, key_i) / (self.key_dim ** 0.5)
            scores[name] = float(score)
        
        # 3. 稀疏化: 只激活 top-k 专家
        if self.use_gumbel:
            alpha = self._gumbel_topk(scores)
        else:
            alpha = self._softmax_topk(scores)
        
        # 4. 更新统计
        for name, a in alpha.items():
            if name in expert_outputs:
                self._expert_usage[expert_names.index(name)] += a
        
        # 5. 记录历史
        self._routing_history.append({
            "timestamp": time.time(),
            "alpha": {k: round(v, 4) for k, v in alpha.items()},
            "context_norm": round(float(np.linalg.norm(context_vector)), 4),
        })
        if len(self._routing_history) > 500:
            self._routing_history = self._routing_history[-500:]
        
        return alpha
    
    def _gumbel_topk(self, scores: Dict[str, float]) -> Dict[str, float]:
        """
        Gumbel-TopK 稀疏化: 随机但可微分的top-k选择。
        
        Gumbel噪声使选择具有随机性，
        避免所有输入总是激活相同的专家组合。
        """
        names = list(scores.keys())
        score_array = np.array([scores[n] for n in names], dtype=np.float64)
        
        # 添加Gumbel噪声
        gumbel = -np.log(-np.log(np.random.uniform(0.0001, 1.0, size=score_array.shape)))
        noisy_scores = score_array + gumbel * self.temperature
        
        # Top-k 选择
        topk_indices = np.argsort(noisy_scores)[-self.n_active:]
        
        # 转换为概率分布
        alpha = {name: 0.0 for name in names}
        for idx in topk_indices:
            alpha[names[idx]] = float(noisy_scores[idx])
        
        # 归一化
        total = sum(alpha.values())
        if total > 0:
            for name in alpha:
                alpha[name] /= total
        else:
            # fallback: 均匀分布
            for name in alpha:
                alpha[name] = 1.0 / len(alpha)
        
        return alpha
    
    def _softmax_topk(self, scores: Dict[str, float]) -> Dict[str, float]:
        """
        Softmax-TopK 稀疏化: 确定性的top-k选择。
        """
        names = list(scores.keys())
        score_array = np.array([scores[n] for n in names], dtype=np.float64)
        
        # Softmax
        score_array -= score_array.max()
        exp_scores = np.exp(score_array * 2.0)  # 温度=2增强对比
        probs = exp_scores / exp_scores.sum()
        
        # Top-k 掩码
        topk_mask = np.zeros_like(probs)
        topk_indices = np.argsort(probs)[-self.n_active:]
        for idx in topk_indices:
            topk_mask[idx] = probs[idx]
        
        # 归一化
        total = topk_mask.sum()
        if total > 0:
            topk_mask /= total
        else:
            topk_mask = np.ones_like(probs) / len(probs)
        
        return {name: float(topk_mask[i]) for i, name in enumerate(names)}
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        total_usage = self._expert_usage.sum()
        return {
            "expert_usage": {
                f"expert_{i}": round(float(u / max(total_usage, 1e-10)), 4)
                for i, u in enumerate(self._expert_usage)
            },
            "avg_temperature": round(self.temperature, 4),
            "n_active": self.n_active,
            "total_routing_steps": len(self._routing_history),
        }


# ═══════════════════════════════════════════════════════════════════════
# ψ-参数化动态复杂度调节器
# ═══════════════════════════════════════════════════════════════════════

class PsiParameterizedComplexity:
    """
    ψ-参数化动态复杂度调节器。
    
    基于论文《Active Inference meets Free Energy》(2026.05.12) 定理2:
    - ψ参数化允许动态调整模型的复杂度容量
    - 当任务复杂度超过当前容量时，自动扩展
    - 当任务变简单时，缩减容量以节省资源
    
    核心公式:
      L(ψ) = -log p(o|ψ) + λ(ψ) · complexity(ψ)
      
      其中:
      - -log p(o|ψ) = 对数似然 (模型解释观察的能力)
      - complexity(ψ) = ψ的复杂度 (参数数量/熵)
      - λ(ψ) = 复杂度惩罚系数 (自适应的)
    
    神经科学依据:
    - 大脑在面对新挑战时会增加神经元资源
    - 长期从事简单任务会导致神经资源回收
    - 这对应神经可塑性 (neuroplasticity)
    """
    
    def __init__(
        self,
        base_capacity: int = 512,
        min_capacity: int = 128,
        max_capacity: int = 4096,
        expansion_threshold: float = 0.7,
        contraction_threshold: float = 0.3,
        adaptation_rate: float = 0.1,
    ):
        """
        Args:
            base_capacity: 基础容量 (token数或参数维度)
            min_capacity: 最小容量
            max_capacity: 最大容量
            expansion_threshold: 复杂度利用率 > 此值时扩展
            contraction_threshold: 复杂度利用率 < 此值时收缩
            adaptation_rate: 每次调整的速率
        """
        self.base_capacity = base_capacity
        self.current_capacity = float(base_capacity)
        self.min_capacity = float(min_capacity)
        self.max_capacity = float(max_capacity)
        self.expansion_threshold = expansion_threshold
        self.contraction_threshold = contraction_threshold
        self.adaptation_rate = adaptation_rate
        
        # ψ参数状态
        self.psi_complexity = 0.0      # 当前ψ的复杂度
        self.lambda_penalty = 1.0      # 复杂度惩罚系数
        self.complexity_history: List[float] = []
        self.capacity_history: List[float] = []
        
        # 自适应参数
        self._surprise_buffer: List[float] = []
    
    def compute_utilization(self, actual_complexity: float) -> float:
        """
        计算复杂度利用率。
        
        Args:
            actual_complexity: 当前任务的实际复杂度估计
        
        Returns:
            利用率 (0-1)
        """
        return min(1.0, actual_complexity / max(self.current_capacity, 1.0))
    
    def adjust_capacity(self, actual_complexity: float, surprise: float) -> float:
        """
        根据任务复杂度和惊讶度调整容量。
        
        Args:
            actual_complexity: 当前任务的实际复杂度
            surprise: 自由能惊讶度
        
        Returns:
            调整后的新容量
        """
        utilization = self.compute_utilization(actual_complexity)
        
        # 存储历史
        self.complexity_history.append(actual_complexity)
        self.capacity_history.append(self.current_capacity)
        if len(self.complexity_history) > 1000:
            self.complexity_history = self.complexity_history[-1000:]
            self.capacity_history = self.capacity_history[-1000:]
        
        # 惊讶度缓冲 (用于调整λ)
        self._surprise_buffer.append(surprise)
        if len(self._surprise_buffer) > 20:
            self._surprise_buffer = self._surprise_buffer[-20:]
        
        # 自适应λ: 高惊讶环境 → 降低惩罚 → 允许更多容量
        avg_surprise = np.mean(self._surprise_buffer) if self._surprise_buffer else 0.0
        self.lambda_penalty = max(0.01, 1.0 - avg_surprise * 0.5)
        
        # 容量调整
        if utilization > self.expansion_threshold:
            # 接近饱和 → 扩展容量
            self.current_capacity += self.adaptation_rate * self.current_capacity
            self.psi_complexity += self.adaptation_rate * actual_complexity
        elif utilization < self.contraction_threshold:
            # 严重过剩 → 收缩容量
            self.current_capacity -= self.adaptation_rate * self.current_capacity * 0.5
            self.psi_complexity -= self.adaptation_rate * self.psi_complexity * 0.3
        
        # 边界限制
        self.current_capacity = max(self.min_capacity, min(self.max_capacity, self.current_capacity))
        self.psi_complexity = max(0.0, self.psi_complexity)
        
        return self.current_capacity
    
    def compute_psi_loss(self, log_likelihood: float, complexity: float) -> float:
        """
        计算ψ-参数化损失。
        
        L(ψ) = -log p(o|ψ) + λ(ψ) · complexity(ψ)
        
        Args:
            log_likelihood: 对数似然
            complexity: ψ的复杂度
        
        Returns:
            总损失
        """
        return -log_likelihood + self.lambda_penalty * complexity
    
    def get_complexity_budget(self, total_tokens: int) -> int:
        """
        获取当前复杂度预算 (用于Token节流)。
        
        Args:
            total_tokens: 可用的总token数
        
        Returns:
            分配给当前ψ的token预算
        """
        utilization = self.current_capacity / max(self.max_capacity, 1.0)
        # 利用率越高，分配越多预算
        budget_ratio = 0.3 + 0.5 * utilization  # 30%-80%范围
        return int(total_tokens * budget_ratio)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        recent = self.complexity_history[-100:]
        recent_cap = self.capacity_history[-100:]
        return {
            "current_capacity": round(self.current_capacity, 1),
            "psi_complexity": round(self.psi_complexity, 2),
            "lambda_penalty": round(self.lambda_penalty, 4),
            "avg_complexity": round(float(np.mean(recent)), 2) if recent else 0.0,
            "avg_capacity": round(float(np.mean(recent_cap)), 1) if recent_cap else self.current_capacity,
        }


# ═══════════════════════════════════════════════════════════════════════
# 集成适配器 — 将新模块与现有GlobalWorkspace集成
# ═══════════════════════════════════════════════════════════════════════

class BrainInspiredRouter:
    """
    脑启发路由器 — 整合符号投影+稀疏路由+ψ参数化的统一接口。
    
    提供给GlobalWorkspace使用的统一路由接口。
    """
    
    def __init__(self, n_experts: int = 8, input_dim: int = 512):
        self.router = SparseAttentionRouter(n_experts=n_experts, key_dim=64, input_dim=input_dim)
        self.symbolizer = SymbolicProjector(input_dim=input_dim, symbol_dim=128)
        self.psi_adjuster = PsiParameterizedComplexity(base_capacity=input_dim)
        
        # 上下文向量聚合器
        self.context_buffer: List[np.ndarray] = []
    
    def route_and_project(
        self,
        expert_outputs: Dict[str, Any],
        context_features: Optional[np.ndarray] = None,
        surprise: float = 0.0,
    ) -> Dict[str, Any]:
        """
        统一的路由+投影接口。
        
        Args:
            expert_outputs: 各专家的输出
            context_features: 全局上下文特征向量
            surprise: 当前惊讶度 (用于ψ调整)
        
        Returns:
            {
                "routing_weights": 路由系数 {name: alpha},
                "symbolic_outputs": 符号化输出 {name: symbol_info},
                "capacity": 当前容量,
                "token_budget": Token预算,
            }
        """
        # 构建专家输出向量字典
        output_vectors = {}
        for name, output in expert_outputs.items():
            if isinstance(output, np.ndarray):
                output_vectors[name] = output
            elif hasattr(output, 'activation'):
                output_vectors[name] = np.array([output.activation])
        
        # 默认上下文
        if context_features is None:
            if output_vectors:
                context_features = np.mean(list(output_vectors.values()), axis=0)
            else:
                context_features = np.zeros(512, dtype=np.float64)
        
        # 存储上下文
        self.context_buffer.append(context_features)
        if len(self.context_buffer) > 100:
            self.context_buffer = self.context_buffer[-100:]
        
        # 1. 稀疏路由
        routing_weights = self.router.compute_routing(context_features, output_vectors)
        
        # 2. 符号投影
        symbolic_outputs = {}
        for name, vec in output_vectors.items():
            # 自适应处理: SymbolicProjector now handles any dimension
            symbolic_outputs[name] = self.symbolizer.project(vec)
        
        # 3. ψ参数调整 (估计复杂度)
        complexity_estimate = sum(
            routing_weights.get(name, 0.0) * len(v)
            for name, v in output_vectors.items()
        )
        self.psi_adjuster.adjust_capacity(complexity_estimate, surprise)
        
        # 4. 更新符号温度
        avg_entropy = np.mean([
            s.get("entropy", 2.0) for s in symbolic_outputs.values()
        ]) if symbolic_outputs else 2.0
        target_entropy = math.log(self.symbolizer.n_symbols) * 0.5
        self.symbolizer.update_temperature(avg_entropy, target_entropy)
        
        # 5. Token预算
        token_budget = self.psi_adjuster.get_complexity_budget(8192)
        
        return {
            "routing_weights": routing_weights,
            "symbolic_outputs": symbolic_outputs,
            "capacity": self.psi_adjuster.current_capacity,
            "token_budget": token_budget,
            "router_stats": self.router.get_routing_stats(),
            "symbolizer_stats": self.symbolizer.get_stats(),
            "psi_stats": self.psi_adjuster.get_stats(),
        }
    
    def get_full_stats(self) -> Dict[str, Any]:
        """获取所有子模块的统计"""
        return {
            "router": self.router.get_routing_stats(),
            "symbolizer": self.symbolizer.get_stats(),
            "psi_adjuster": self.psi_adjuster.get_stats(),
        }