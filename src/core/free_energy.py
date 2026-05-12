"""
meshctx v1.1 — 自由能计算引擎 (Free Energy Engine)

跨学科融合：
- 脑科学: Friston自由能原理 → 变分推断在神经网络中的实现
- 物理学: 热力学熵最小化 → KL散度作为系统"惊讶"度量
- 数学: 信息几何 → 信念在统计流形上的自然梯度运动
- 认知科学: 主动推理 → 感知与行动的数学统一
- 心理学: 预测性加工 → 贝叶斯脑假说的算法实现

核心公式:
  F = D_KL[q(s)||p(s)] - E_q[ln p(o|s)]
  
  其中:
  - q(s): 智能体的近似后验信念
  - p(s): 先验预期
  - p(o|s): 给定信念下观察的似然
  - D_KL: Kullback-Leibler散度 (信念与现实的差距)
  - E_q: 期望证据 (模型解释观察的能力)

精密加权 (Precision Weighting):
  预测误差的权重 ∝ 1/σ² (逆方差)
  高精密度的误差 → 更大的信念更新
  低精密度的误差 → 被忽略 (噪声)

自组织临界性 (Self-Organized Criticality):
  系统维持在"混沌边缘" — 介于有序和随机之间的临界态
  信息处理能力在此处最大化
  通过调节温度参数 T 来控制探索-利用平衡
"""

import math
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

# scipy is optional — fallback to math module if unavailable
try:
    from scipy.special import digamma, gammaln
    _HAS_SCIPY = True
except ImportError:
    import math as _math
    _HAS_SCIPY = False
    # Approximate digamma for positive arguments (Abramowitz & Stegun 6.3.18)
    def _digamma_scalar(x):
        if x < 0.5:
            return _digamma_scalar(x + 1) - 1.0 / x
        # More accurate approximation for small x
        if x < 3:
            x_val = float(x)
            # Use recurrence + log for better accuracy
            result = -0.5772156649  # Euler-Mascheroni constant
            for k in range(int(x_val - 0.5)):
                result += 1.0 / (k + 1)
            return result
        return _math.log(x) - 0.5/x - 1/(12*x*x) + 1/(120*x**4) - 1/(252*x**6)
    digamma = np.vectorize(_digamma_scalar)
    def gammaln(x):
        x = np.asarray(x, dtype=float)
        return 0.5*_math.log(2*_math.pi) + (x-0.5)*np.log(x) - x + 1/(12*x) - 1/(360*x**3)

logger = logging.getLogger("meshctx.free_energy")


# ═══════════════════════════════════════════════════════════════════════
# 信念状态 — 贝叶斯脑的核心数据结构
# ═══════════════════════════════════════════════════════════════════════

class BeliefType(Enum):
    """信念表示类型"""
    DIRICHLET = "dirichlet"    # 类别信念 (哪个策略/工具最好)
    GAUSSIAN = "gaussian"      # 连续信念 (任务预计耗时)
    CATEGORICAL = "categorical"  # 离散选择 (A/B/C)
    POISSON = "poisson"        # 计数信念 (还需要几次尝试)


@dataclass
class BeliefState:
    """
    智能体对某个未知量的概率信念。
    
    使用自然参数化 (natural parameters) 而非标准参数化：
    - Dirichlet: α (concentration parameters)
    - Gaussian: η₁ = μ/σ², η₂ = -1/(2σ²)  (natural parameters)
    
    自然参数化的优势：贝叶斯更新变为简单的加法
    """
    name: str
    belief_type: BeliefType
    
    # Dirichlet参数 (类别信念)
    alpha: Optional[np.ndarray] = None  # concentration params
    n_categories: int = 2
    
    # Gaussian自然参数
    eta1: Optional[float] = None  # μ/σ²
    eta2: Optional[float] = None  # -1/(2σ²)
    
    # 元数据
    prior_strength: float = 1.0    # 先验的置信度 (等效样本数)
    total_observations: int = 0    # 总观察数
    last_updated: float = field(default_factory=time.time)
    surprise_history: List[float] = field(default_factory=list)  # 最近惊讶值
    
    def __post_init__(self):
        if self.alpha is None and self.belief_type == BeliefType.DIRICHLET:
            # Jeffrey's prior: α = 0.5 (最大无信息先验)
            self.alpha = np.full(self.n_categories, 0.5 * self.prior_strength)
        if self.belief_type == BeliefType.GAUSSIAN:
            # 无信息先验: 均值0, 方差很大
            if self.eta1 is None:
                self.eta1 = 0.0
            if self.eta2 is None:
                self.eta2 = -0.001  # 对应 σ² ≈ 500

    # ── 推断 ──────────────────────────────────────────────────────

    @property
    def expected_probability(self) -> np.ndarray:
        """Dirichlet的期望概率: E[p_i] = α_i / Σα_j"""
        if self.belief_type == BeliefType.DIRICHLET:
            total = self.alpha.sum()
            return self.alpha / total if total > 0 else np.ones_like(self.alpha) / len(self.alpha)
        raise ValueError(f"expected_probability not defined for {self.belief_type}")

    @property
    def uncertainty(self) -> float:
        """
        信念的不确定性 (熵或逆精度)。
        
        Dirichlet熵:
          H[Dir(α)] = ln B(α) + (α₀ - K)ψ(α₀) - Σ(αᵢ-1)ψ(αᵢ)
        
        物理类比: 熵越高 → 系统越无序 → 越需要探索
        """
        if self.belief_type == BeliefType.DIRICHLET:
            alpha = self.alpha
            alpha0 = alpha.sum()
            K = len(alpha)
            # ln Beta function
            ln_B = gammaln(alpha).sum() - gammaln(alpha0)
            entropy = ln_B + (alpha0 - K) * digamma(alpha0) - ((alpha - 1) * digamma(alpha)).sum()
            return float(entropy)
        elif self.belief_type == BeliefType.GAUSSIAN:
            # Gaussian entropy: 0.5 * ln(2πeσ²)
            sigma2 = -0.5 / self.eta2 if self.eta2 and self.eta2 < 0 else 1.0
            return 0.5 * math.log(2 * math.pi * math.e * sigma2)
        return 1.0

    @property
    def precision(self) -> float:
        """信念的精度 (逆不确定性): π = 1/H"""
        return 1.0 / (self.uncertainty + 1e-8)

    # ── 更新 ──────────────────────────────────────────────────────

    def observe(self, category: int, weight: float = 1.0):
        """
        贝叶斯更新: 观察到类别 category，以 weight 为权重。
        
        自然参数化优势: α_new = α_old + weight * one_hot(k)
        
        热力学类比:
        - 每次观察相当于向系统注入 dQ = weight 的热量
        - α₀ = 系统总能量
        - 降温 (T→0) → 信念凝固
        """
        if self.belief_type == BeliefType.DIRICHLET:
            if 0 <= category < self.n_categories:
                self.alpha[category] += weight
                self.total_observations += 1
                self.last_updated = time.time()

    def observe_gaussian(self, value: float, precision: float = 1.0):
        """Gaussian自然参数更新: η₁ += precision*value, η₂ += precision"""
        if self.belief_type == BeliefType.GAUSSIAN:
            self.eta1 += precision * value
            self.eta2 += precision
            self.total_observations += 1
            self.last_updated = time.time()

    def decay(self, half_life_seconds: float = 86400):
        """
        记忆衰减: α → α * exp(-λ * Δt)
        
        艾宾浩斯遗忘曲线: R(t) = e^(-t/τ)
        其中 τ = half_life / ln(2)
        
        这实现了物理学中的指数衰减过程。
        """
        dt = time.time() - self.last_updated
        decay_factor = math.exp(-dt * math.log(2) / half_life_seconds) if half_life_seconds > 0 else 1.0
        
        if self.belief_type == BeliefType.DIRICHLET:
            # 保留最小信念量 (不能归零)
            min_alpha = 0.1 * self.prior_strength
            self.alpha = np.maximum(self.alpha * decay_factor, min_alpha)


# ═══════════════════════════════════════════════════════════════════════
# 自由能计算
# ═══════════════════════════════════════════════════════════════════════

class FreeEnergyComputer:
    """
    变分自由能计算器。
    
    两个分量:
    1. 复杂度 (Complexity): D_KL[q(s)|p(s)] — 信念与先验的偏离
    2. 不准确度 (Inaccuracy): -E_q[ln p(o|s)] — 模型解释观察的能力
    
    物理意义:
    F = 复杂度 + 不准确度 = 系统与环境的"紧张"程度
    最小化 F ≡ 找到最节能的信念状态
    """

    @staticmethod
    def dirichlet_kl(alpha_q: np.ndarray, alpha_p: np.ndarray) -> float:
        """
        KL散度 D_KL[Dir(α_q) || Dir(α_p)]
        
        信息几何解释:
        KL散度是统计流形上从p到q的"距离"
        但不是对称的 — D_KL(q||p) ≠ D_KL(p||q)
        q||p 表示"用p近似q时的信息损失"
        """
        alpha0_q = alpha_q.sum()
        alpha0_p = alpha_p.sum()
        K = len(alpha_q)
        
        kl = gammaln(alpha0_q) - gammaln(alpha0_p)
        kl += (gammaln(alpha_p) - gammaln(alpha_q)).sum()
        kl += ((alpha_q - alpha_p) * (digamma(alpha_q) - digamma(alpha0_q))).sum()
        return float(kl)

    @staticmethod
    def expected_log_evidence(belief: BeliefState, observation: int) -> float:
        """
        期望对数证据: E_q[ln p(o=k|s)]
        
        Dirichlet下: E[ln p_k] = ψ(α_k) - ψ(α₀)
        """
        if belief.belief_type == BeliefType.DIRICHLET:
            if 0 <= observation < belief.n_categories:
                alpha0 = belief.alpha.sum()
                return float(digamma(belief.alpha[observation]) - digamma(alpha0))
        return 0.0

    @staticmethod
    def epistemic_value_exact(belief: BeliefState, action: int = 0) -> float:
        """计算精确认知价值 (互信息): E_q(o|π)[D_KL[q(s|o,π) || q(s|π)]]

        对于 Dirichlet 信念:
        - 当前信念: q(s) = Dir(α)
        - 观察 o 后的后验: q(s|o) = Dir(α + e_o) (e_o 为 one-hot)
        - q(o|π) = E[q(s)] = α / Σα
        - 认知价值 = Σ_o q(o|π) × D_KL[Dir(α + e_o) || Dir(α)]

        这个值表示期望信息增益。在期望自由能中取负号 (最大化信息
        增益 ⇔ 最小化期望自由能)。

        物理类比: 麦克斯韦妖通过测量获取的信息量。
        """
        if belief.belief_type != BeliefType.DIRICHLET:
            # 非 Dirichlet 回退到启发式
            return belief.uncertainty * 0.1

        alpha = belief.alpha
        prob = belief.expected_probability  # q(o|π)
        epistemic = 0.0

        for o in range(belief.n_categories):
            # 后验信念: α_post = α + one_hot(o)
            alpha_post = alpha.copy()
            alpha_post[o] += 1.0
            # D_KL[Dir(α_post) || Dir(α)]
            kl = FreeEnergyComputer.dirichlet_kl(alpha_post, alpha)
            # 期望: q(o|π) × KL
            epistemic += prob[o] * kl

        return float(epistemic)

    @staticmethod
    def compute_free_energy(
        belief: BeliefState,
        observation: int,
        prior_alpha: Optional[np.ndarray] = None,
        temperature: float = 1.0,
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算变分自由能 F。
        
        参数:
        - belief: 当前信念状态
        - observation: 实际观察
        - prior_alpha: 先验信念 (默认均匀)
        - temperature: 温度参数 T (调节探索程度)
        
        返回:
        - F: 总自由能 (越低越好)
        - components: {complexity, inaccuracy, surprise, energy}
        
        热力学类比:
        F = U - TS  (Helmholtz自由能)
        U = 内能 (inaccuracy)
        T = 温度 (exploration temperature)
        S = 熵 (uncertainty)
        
        温度效应:
        T → 0: 只相信最强证据 (凝固态)
        T → ∞: 完全随机 (气态)  
        临界温度 Tc: 系统在"混沌边缘"，信息处理最大化
        """
        if prior_alpha is None:
            prior_alpha = np.ones(belief.n_categories) * belief.prior_strength

        # 1. 复杂度: 信念偏离先验的程度
        complexity = FreeEnergyComputer.dirichlet_kl(belief.alpha, prior_alpha)

        # 2. 不准确度: 负期望对数似然
        inaccuracy = -FreeEnergyComputer.expected_log_evidence(belief, observation)

        # 3. 惊讶值: 实际观察的信息量
        surprise = -math.log(max(belief.expected_probability[observation], 1e-10))

        # 4. 温度修正的自由能
        entropy = belief.uncertainty
        F = complexity + inaccuracy  # 基础自由能
        F_temperature_corrected = F - temperature * entropy  # Helmholtz形式

        return F_temperature_corrected, {
            "complexity": complexity,
            "inaccuracy": inaccuracy,
            "surprise": surprise,
            "entropy": entropy,
            "temperature": temperature,
            "free_energy_raw": F,
            "free_energy_helmholtz": F_temperature_corrected,
        }

    @staticmethod
    def compute_expected_free_energy(
        belief: BeliefState,
        prior_alpha: np.ndarray,
        possible_actions: int,
        preferred_outcomes: Optional[np.ndarray] = None,
        temperature: float = 1.0,
    ) -> np.ndarray:
        """
        期望自由能 G(π) — 用于主动推理中的行动选择。
        
        G(π) = 认知价值 + 实用价值
        
        认知价值 (Epistemic Value):
          采取行动π期望获得多少信息
          = -E_q[ln q(s|π) - ln p(s|o,π)]
          = 信念的期望熵减少
        
        实用价值 (Pragmatic Value):
          采取行动π期望达到偏好结果的程度
          = -E_q[ln p(o|C)]  (C = preferred outcomes)
        
        物理类比:
        认知价值 = 麦克斯韦妖的信息获取
        实用价值 = 系统向低能态的运动
        
        返回: 每个可能行动的期望自由能 (越低越好)
        """
        G = np.zeros(possible_actions)
        prob = belief.expected_probability
        
        for a in range(possible_actions):
            # 实用价值: 期望达到偏好的程度
            if preferred_outcomes is not None:
                pragmatic = -np.sum(prob * np.log(np.maximum(preferred_outcomes, 1e-10)))
            else:
                pragmatic = 0.0
            
            # 认知价值: 采取行动后的期望信息增益 (互信息)
            # 精确计算: E_q(o|π)[D_KL[q(s|o,π) || q(s|π)]]
            epistemic = -FreeEnergyComputer.epistemic_value_exact(belief, a)
            
            G[a] = pragmatic + epistemic + temperature * belief.uncertainty
        
        return G


# ═══════════════════════════════════════════════════════════════════════
# 精密加权 — 注意力机制
# ═══════════════════════════════════════════════════════════════════════

class PrecisionWeighting:
    """
    精密加权机制 — 模拟大脑的注意力系统。
    
    核心思想:
    并非所有预测误差都同等重要。
    高精密度的误差 → 大量信念更新
    低精密度的误差 → 视为噪声忽略
    
    精密度的来源:
    1. 感官精度: 输入数据的可靠性
    2. 先验精度: 对先验信念的置信度
    3. 情境精度: 当前上下文的相关性
    
    神经科学依据:
    - 乙酰胆碱调节感官精度
    - 多巴胺编码期望vs实际的差异
    - 去甲肾上腺素调节全局唤醒
    """

    def __init__(self):
        self.sensory_precision: Dict[str, float] = {}        # 感官通道精度
        self.prior_precision: Dict[str, float] = {}          # 先验精度
        self.volatility_estimate: float = 0.1                 # 环境波动估计
    
    def compute_precision(self, belief: BeliefState, observation_count: int) -> float:
        """
        计算信念更新的精密权重。
        
        π = π_sensory × π_prior × π_context
        
        精密 = 逆方差，即置信度。
        """
        # 感官精度: 观察越多 → 精度越高 (sqrt法则)
        sensory = math.sqrt(max(observation_count, 1)) / 10.0
        
        # 先验精度: 信念越确定 → 精度越高
        prior = belief.precision
        
        # 情境精度: 环境越稳定 → 精度越高
        context = 1.0 / (1.0 + self.volatility_estimate)
        
        return sensory * prior * context
    
    def update_volatility(self, recent_surprises: List[float]):
        """
        更新环境波动估计。
        
        高惊讶率 → 高波动 → 降低精度 → 更快的信念更新
        低惊讶率 → 低波动 → 提高精度 → 更稳定的信念
        """
        if recent_surprises:
            self.volatility_estimate = 0.9 * self.volatility_estimate + 0.1 * np.mean(recent_surprises)


# ═══════════════════════════════════════════════════════════════════════
# 自组织临界性 — 混沌边缘
# ═══════════════════════════════════════════════════════════════════════

class CriticalityRegulator:
    """
    自组织临界性调节器。
    
    智能体需要维持在"混沌边缘" — 既非完全有序(僵化)也非完全随机(混乱)。
    这个临界态的信息处理能力最大化。
    
    通过调节温度参数 T 来控制:
    - T 太高 → 过度探索 → 降低T
    - T 太低 → 过度利用 → 提高T
    
    物理依据:
    沙堆模型: 系统自组织到临界态，小雪崩频繁，大雪崩稀少
    雪崩规模 ~ 幂律分布 P(s) ∝ s^(-τ)
    
    智能体类比:
    小雪崩 = 微调信念
    大雪崩 = 范式转换
    """

    def __init__(self):
        self.temperature: float = 1.0          # 当前温度
        self.target_temperature: float = 1.0   # 目标温度
        self.critical_exponent: float = 1.5    # 幂律指数 (期望值: 1.5)
        self.avalanche_sizes: List[int] = []   # 近期雪崩规模
        self.branching_ratio: float = 1.0      # 分支比 ≈ 1 时为临界
    
    def adjust(self, surprise: float, expected_surprise: float) -> float:
        """
        基于惊讶值调节温度。
        
        惊讶 > 预期 → 环境变了 → 升温 (更多探索)
        惊讶 < 预期 → 环境稳定 → 降温 (更多利用)
        
        返回: 新的温度值
        """
        prediction_error = surprise - expected_surprise
        
        if prediction_error > 0.5:  # 意外的高惊讶
            self.temperature += 0.1 * prediction_error  # 升温探索
            self.avalanche_sizes.append(int(prediction_error * 10))
        elif prediction_error < -0.2:  # 低于预期的惊讶
            self.temperature -= 0.05  # 降温收敛
        
        # 维持在 (0.1, 5.0) 范围内 — 不会冻结也不会爆炸
        self.temperature = max(0.1, min(5.0, self.temperature))
        
        # 分支比计算 (维持临界态的关键指标)
        if len(self.avalanche_sizes) > 20:
            self.avalanche_sizes = self.avalanche_sizes[-20:]
            # 分支比 ≈ 1 → 临界
            avg_size = np.mean(self.avalanche_sizes) if self.avalanche_sizes else 1
            self.branching_ratio = avg_size / max(1, (avg_size - 1))
        
        return self.temperature
    
    @property
    def is_at_criticality(self) -> bool:
        """检查是否接近临界态"""
        return 0.8 < self.branching_ratio < 1.2


# ═══════════════════════════════════════════════════════════════════════
# ECE 校准追踪 — 期望校准误差
# ═══════════════════════════════════════════════════════════════════════

class BeliefCalibration:
    """ECE (Expected Calibration Error) 校准追踪器。

    跟踪模型预测概率与实际结果之间的一致性。
    ECE 越低，模型校准越好 — 即模型对其预测的置信度与实际
    准确率相匹配。

    完美校准: 预测 80% 概率的事件实际发生率为 80%。

    参考: "On Calibration of Modern Neural Networks" (Guo et al., 2017)

    使用示例:
        cal = BeliefCalibration()
        cal.record(predicted_prob=0.8, actual=1.0)   # 预测对
        cal.record(predicted_prob=0.9, actual=0.0)   # 预测错
        ece = cal.expected_calibration_error()        # 量化校准误差
    """

    def __init__(self, n_bins: int = 10):
        self.n_bins = n_bins
        self.predictions: List[Tuple[float, int]] = []   # (predicted_prob, actual)

    def record(self, predicted_prob: float, actual: float):
        """记录一次预测结果。

        参数:
            predicted_prob: 模型预测的概率 (0-1)
            actual: 实际结果 (0=失败, 1=成功)
        """
        # 用 int 存储 actual 避免浮点累积误差
        self.predictions.append((float(predicted_prob), int(round(float(actual)))))

    def expected_calibration_error(self, n_bins: int = 10) -> float:
        """计算期望校准误差 (ECE)。

        ECE = Σ_m (|B_m|/n) × |acc(B_m) - conf(B_m)|

        其中:
            B_m: 第 m 个桶中的样本
            acc(B_m): 桶中的实际准确率
            conf(B_m): 桶中的平均预测概率
            n: 总样本数

        返回 0-1 之间的 ECE 值 (越低越好)。
        """
        if not self.predictions:
            return 0.0

        n = len(self.predictions)
        bins = n_bins if n_bins else self.n_bins

        # 按预测概率排序后均匀分桶
        sorted_preds = sorted(self.predictions, key=lambda x: x[0])

        ece = 0.0
        for m in range(bins):
            start = int(m * n / bins)
            end = int((m + 1) * n / bins)
            if start >= end:
                continue

            bin_items = sorted_preds[start:end]
            bin_count = len(bin_items)

            avg_predicted = sum(p for p, a in bin_items) / bin_count
            avg_actual = sum(a for p, a in bin_items) / bin_count

            ece += (bin_count / n) * abs(avg_actual - avg_predicted)

        return float(ece)

    @property
    def total_predictions(self) -> int:
        """已记录的预测总数"""
        return len(self.predictions)

    def reset(self):
        """重置校准追踪器"""
        self.predictions.clear()


# ═══════════════════════════════════════════════════════════════════════
# 自由能智能体 — 统一入口
# ═══════════════════════════════════════════════════════════════════════

class FreeEnergyAgent:
    """
    自由能驱动的自主智能体。
    
    整合所有脑启发模块:
    1. BeliefState — 贝叶斯信念
    2. FreeEnergyComputer — 自由能计算
    3. PrecisionWeighting — 精密加权
    4. CriticalityRegulator — 临界态调节
    
    运行循环:
    1. 感知 → 更新信念 (Bayesian update with precision)
    2. 评估 → 计算自由能 (surprise + complexity)
    3. 行动 → 选择最小化期望自由能的行动
    4. 适应 → 调节温度维持临界态
    5. 巩固 → 高惊讶体验触发海马体重放
    """

    def __init__(self, n_strategies: int = 5, name: str = "fea"):
        self.name = name
        self.n_strategies = n_strategies
        
        # 核心信念: 哪个策略在当前上下文中最有效
        self.strategy_belief = BeliefState(
            name="strategy_effectiveness",
            belief_type=BeliefType.DIRICHLET,
            n_categories=n_strategies,
            prior_strength=1.0,
        )
        
        # 任务耗时信念 (Gaussian)
        self.time_belief = BeliefState(
            name="task_duration",
            belief_type=BeliefType.GAUSSIAN,
        )
        
        # 子模块
        self.free_energy = FreeEnergyComputer()
        self.precision = PrecisionWeighting()
        self.criticality = CriticalityRegulator()
        self.calibration = BeliefCalibration()  # ECE 校准追踪
        
        # 状态追踪
        self.total_free_energy: float = 0.0
        self.episode_count: int = 0
        self.surprise_buffer: List[float] = []

    def perceive(self, outcome: int, duration: float, success: bool) -> Dict[str, Any]:
        """
        感知步骤: 处理任务结果，更新信念。
        """
        # 精密加权更新 — 学习率自适应
        w = self.precision.compute_precision(self.strategy_belief, max(self.episode_count, 1))
        # 确保最小学习率 (避免冷启动太慢)
        w = max(w, 0.3)
        
        # 成功时强化，失败时不强化（但也不惩罚——保持贝叶斯优雅）
        if success:
            self.strategy_belief.observe(outcome, weight=w)
        
        # 更新时间信念
        self.time_belief.observe_gaussian(duration, precision=0.1 if success else 0.01)
        
        # 计算惊讶值
        expected_prob = self.strategy_belief.expected_probability[outcome]
        surprise = -math.log(max(expected_prob, 1e-10))
        self.surprise_buffer.append(surprise)
        if len(self.surprise_buffer) > 100:
            self.surprise_buffer = self.surprise_buffer[-100:]
        
        # 更新精密加权器的环境波动估计
        self.precision.update_volatility(self.surprise_buffer[-20:])
        
        # 临界态调节
        avg_surprise = np.mean(self.surprise_buffer[-10:]) if self.surprise_buffer else 0.0
        new_T = self.criticality.adjust(surprise, avg_surprise)
        
        # ECE 校准追踪: 记录预测概率 vs 实际结果
        self.calibration.record(
            predicted_prob=float(expected_prob),
            actual=1.0 if success else 0.0,
        )
        
        return {
            "surprise": surprise,
            "expected_probability": float(expected_prob),
            "temperature": new_T,
            "at_criticality": self.criticality.is_at_criticality,
            "belief_entropy": self.strategy_belief.uncertainty,
            "strategy_probs": self.strategy_belief.expected_probability.tolist(),
        }

    def decide(self, preferred_outcomes: Optional[np.ndarray] = None) -> int:
        """
        决策步骤: 选择最小化期望自由能的行动。
        
        当没有偏好结果时，直接用期望概率采样 (Thompson风格)。
        """
        # 如果没有偏好，直接用信念的期望概率 (等价于最小化期望惊讶)
        if preferred_outcomes is None:
            probs = self.strategy_belief.expected_probability
            # 加入温度调节探索
            T = self.criticality.temperature
            if T > 1.0:
                # 高温: 增加探索 (flatten distribution)
                probs = np.power(probs, 1.0 / T)
                probs /= probs.sum()
            action = np.random.choice(self.n_strategies, p=probs)
            return int(action)
        
        G = self.free_energy.compute_expected_free_energy(
            belief=self.strategy_belief,
            prior_alpha=np.ones(self.n_strategies),
            possible_actions=self.n_strategies,
            preferred_outcomes=preferred_outcomes,
            temperature=self.criticality.temperature,
        )
        
        # Softmin: 选择最低自由能的行动 (不是贪心)
        G_centered = G - G.min()
        weights = np.exp(-G_centered / max(self.criticality.temperature, 0.1))
        probs = weights / weights.sum()
        
        # 采样 (保留探索性)
        action = np.random.choice(self.n_strategies, p=probs)
        
        return int(action)

    def reflect(self) -> Dict[str, Any]:
        """
        反思步骤: 评估当前状态，触发必要的适应。
        
        这是元认知的数学基础:
        元认知 = 对自身信念的信念
        自由能 = 元认知的量化指标
        """
        # 信念衰减
        self.strategy_belief.decay(half_life_seconds=3600 * 24 * 7)  # 7天半衰期
        
        # 当前自由能水平
        F, components = self.free_energy.compute_free_energy(
            belief=self.strategy_belief,
            observation=0,  # dummy
            temperature=self.criticality.temperature,
        )
        
        self.total_free_energy += F
        self.episode_count += 1
        
        return {
            "free_energy": F,
            "components": components,
            "total_free_energy": self.total_free_energy,
            "average_free_energy": self.total_free_energy / max(self.episode_count, 1),
            "temperature": self.criticality.temperature,
            "branching_ratio": self.criticality.branching_ratio,
            "at_criticality": self.criticality.is_at_criticality,
            "strategy_beliefs": self.strategy_belief.expected_probability.tolist(),
            "volatility": self.precision.volatility_estimate,
        }

    def should_replay(self, surprise_threshold: float = 2.0) -> bool:
        """判断是否应该触发记忆重放(高惊讶事件)"""
        if not self.surprise_buffer:
            return False
        return np.mean(self.surprise_buffer[-5:]) > surprise_threshold
