"""
meshctx v1.1 — 内稳态调节引擎 (Homeostatic Allostasis)

跨学科融合:
- 生理学: Cannon的内稳态 → 维持内部环境稳定
- 神经科学: Sterling的异稳态 → 预测性调节而非被动反应
- 控制论: Wiener的反馈控制 → PID调节器
- 热力学: Prigogine的耗散结构 → 远离平衡态的自我维持
- 经济学: 边际效用递减 → 资源分配的效率优化

核心概念:
  异稳态 (Allostasis) ≠ 稳态 (Homeostasis)
  
  稳态: 偏离 → 检测 → 纠正 (被动, 反应性)
  异稳态: 预测未来需求 → 提前调整 → 最小化偏离 (主动, 预测性)
  
  类比:
  稳态 = 恒温器 (温度低了才加热)
  异稳态 = 智能电表 (预测用电高峰, 提前储备)

四种内部资源:
1. 计算预算 (CPU)
2. 记忆预算 (Memory)
3. 时间预算 (Latency)
4. 质量预算 (Quality)
  
管理策略:
  - 正常模式: 均衡分配
  - 应激模式: 优先保障核心功能
  - 恢复模式: 削减非关键任务
"""

import logging
import math
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger("meshctx.homeostasis")

# ═══════════════════════════════════════════════════════════════════════
# 神经调质系统常量
# ═══════════════════════════════════════════════════════════════════════
DEFAULT_NM_LEVEL = 0.5       # 默认调质水平
NM_DECAY_RATE = 0.95         # 调质自然衰减率 (每步保留95%)
DA_RPE_SCALE = 1.5           # 多巴胺对RPE的敏感度
NE_UNC_SCALE = 1.0           # 去甲肾上腺素对不确定性的敏感度
ACH_SURP_SCALE = 1.2         # 乙酰胆碱对惊奇的敏感度


# ═══════════════════════════════════════════════════════════════════════
# 资源定义
# ═══════════════════════════════════════════════════════════════════════

class ResourceType(Enum):
    COMPUTE = "compute"    # 计算资源 (CPU tokens)
    MEMORY = "memory"      # 记忆容量 (context window)
    TIME = "time"          # 时间延迟 (ms)
    QUALITY = "quality"    # 输出质量 (0-1)


class SystemMode(Enum):
    """系统运行模式"""
    NORMAL = "normal"          # 正常运行
    STRESS = "stress"          # 资源紧张
    RECOVERY = "recovery"      # 恢复中
    CRITICAL = "critical"      # 临界 (即将崩溃)
    IDLE = "idle"              # 空闲
    BURST = "burst"            # 爆发模式 (短时超频)


@dataclass
class ResourceBudget:
    """单个资源的预算管理"""
    resource_type: ResourceType
    total_capacity: float          # 总容量
    current_usage: float = 0.0     # 当前使用量
    predicted_need: float = 0.0    # 预测需求
    reserve_ratio: float = 0.2     # 预留比例
    
    # 阈值
    warning_threshold: float = 0.7  # 警告 (70%)
    stress_threshold: float = 0.85  # 应激 (85%)
    critical_threshold: float = 0.95  # 临界 (95%)
    
    # 统计
    usage_history: List[float] = field(default_factory=list)
    prediction_errors: List[float] = field(default_factory=list)
    
    @property
    def usage_ratio(self) -> float:
        return self.current_usage / max(self.total_capacity, 1)
    
    @property
    def available(self) -> float:
        return self.total_capacity * (1 - self.reserve_ratio) - self.current_usage
    
    @property
    def status(self) -> str:
        r = self.usage_ratio
        if r > self.critical_threshold: return "critical"
        if r > self.stress_threshold: return "stress"
        if r > self.warning_threshold: return "warning"
        return "normal"
    
    def predict_demand(self, window: int = 10) -> float:
        """
        预测未来需求 (异稳态的核心)。
        
        使用指数加权移动平均 (EWMA):
        ŷ_{t+1} = α*y_t + (1-α)*ŷ_t
        
        α高 → 近期权重大 (快适应)
        α低 → 历史权重大 (稳定)
        """
        if not self.usage_history:
            return 0.0
        
        recent = self.usage_history[-window:]
        if not recent:
            return 0.0
        
        alpha = 0.7  # 偏重近期
        ewma = recent[0]
        for val in recent[1:]:
            ewma = alpha * val + (1 - alpha) * ewma
        
        # 加入趋势
        if len(recent) >= 3:
            trend = (recent[-1] - recent[0]) / len(recent)
            ewma += trend * 3  # 预测3步后的需求
        
        self.predicted_need = max(0, ewma)
        return self.predicted_need


# ═══════════════════════════════════════════════════════════════════════
# 神经调质系统 (Neuromodulator Trinity)
# ═══════════════════════════════════════════════════════════════════════

class NeuromodulatorSystem:
    """
    神经调质三件套 — 模拟脑干/基底前脑的神经调质系统。

    三种核心调质:
    ├── 多巴胺 (Dopamine): 奖励预测误差 → 调节探索/利用平衡
    │   - 正向RPE (比预期好) → DA↑ → 倾向利用当前策略
    │   - 负向RPE (比预期差) → DA↓ → 倾向探索新策略
    │
    ├── 去甲肾上腺素 (Norepinephrine): 不确定性 → 调节警觉/聚焦
    │   - 高不确定性 → NE↑ → 提高警觉, 缩小注意范围
    │   - 低不确定性 → NE↓ → 放松, 扩大注意范围
    │
    └── 乙酰胆碱 (Acetylcholine): 惊奇度 → 调节感官精度/学习率
        - 高惊奇 → ACh↑ → 提高感官精度, 加速学习
        - 低惊奇 → ACh↓ → 降低感官精度, 稳定表征

    神经科学依据:
    - 多巴胺: Schultz et al. (1997) — 中脑多巴胺神经元编码RPE
    - 去甲肾上腺素: Aston-Jones & Cohen (2005) — 蓝斑核编码不确定性
    - 乙酰胆碱: Yu & Dayan (2005) — 基底前脑乙酰胆碱编码期望不确定性
    """

    def __init__(self):
        # 三种调质水平 [0, 1]
        self.dopamine: float = DEFAULT_NM_LEVEL          # DA
        self.norepinephrine: float = DEFAULT_NM_LEVEL     # NE
        self.acetylcholine: float = DEFAULT_NM_LEVEL     # ACh

        # 历史记录 (用于平滑)
        self.da_history: List[float] = [DEFAULT_NM_LEVEL]
        self.ne_history: List[float] = [DEFAULT_NM_LEVEL]
        self.ach_history: List[float] = [DEFAULT_NM_LEVEL]

        # 统计
        self.update_count: int = 0

    def update(
        self,
        reward_prediction_error: float = 0.0,
        uncertainty: float = 0.5,
        surprise: float = 0.5,
    ) -> Dict[str, float]:
        """
        根据感知输入更新三种神经调质水平。

        参数:
            reward_prediction_error: 奖励预测误差 (RPE)，[-1, 1]
                >0: 比预期好 (正惊奇)
                <0: 比预期差 (负惊奇)
            uncertainty: 环境不确定性估计, [0, 1]
            surprise: 惊奇度 (感官输入与预测的差异), [0, 1]

        返回:
            包含三种调质当前水平的字典
        """
        self.update_count += 1

        # ── 多巴胺: 由奖励预测误差驱动 ──
        # 使用 tanh 将 RPE 映射到 [-1, 1] 范围
        rpe_clipped = np.tanh(reward_prediction_error * DA_RPE_SCALE)
        da_target = 0.5 + 0.5 * rpe_clipped  # 映射到 [0, 1]
        # 平滑更新 (EMA, α=0.3)
        self.dopamine = 0.7 * self.dopamine + 0.3 * da_target

        # ── 去甲肾上腺素: 由不确定性驱动 ──
        ne_target = np.clip(uncertainty * NE_UNC_SCALE, 0.0, 1.0)
        # 高不确定性时 NE 升高更快, 低不确定性时衰减
        if uncertainty > 0.6:
            self.norepinephrine = 0.6 * self.norepinephrine + 0.4 * ne_target
        else:
            self.norepinephrine = 0.8 * self.norepinephrine + 0.2 * ne_target

        # ── 乙酰胆碱: 由惊奇度驱动 ──
        ach_target = np.clip(surprise * ACH_SURP_SCALE, 0.0, 1.0)
        self.acetylcholine = 0.6 * self.acetylcholine + 0.4 * ach_target

        # ── 自然衰减 (所有调质缓慢回归基线) ──
        self._apply_decay()

        # 记录历史
        self._record_history()

        return {
            "dopamine": round(self.dopamine, 4),
            "norepinephrine": round(self.norepinephrine, 4),
            "acetylcholine": round(self.acetylcholine, 4),
        }

    def _apply_decay(self):
        """所有调质向默认水平衰减 (模拟再摄取/酶解)"""
        self.dopamine = (
            NM_DECAY_RATE * self.dopamine
            + (1 - NM_DECAY_RATE) * DEFAULT_NM_LEVEL
        )
        self.norepinephrine = (
            NM_DECAY_RATE * self.norepinephrine
            + (1 - NM_DECAY_RATE) * DEFAULT_NM_LEVEL
        )
        self.acetylcholine = (
            NM_DECAY_RATE * self.acetylcholine
            + (1 - NM_DECAY_RATE) * DEFAULT_NM_LEVEL
        )

    def _record_history(self):
        """记录历史 (最多100步)"""
        max_history = 100
        self.da_history.append(self.dopamine)
        self.ne_history.append(self.norepinephrine)
        self.ach_history.append(self.acetylcholine)
        if len(self.da_history) > max_history:
            self.da_history = self.da_history[-max_history:]
            self.ne_history = self.ne_history[-max_history:]
            self.ach_history = self.ach_history[-max_history:]

    def get_explore_exploit_ratio(self) -> float:
        """
        返回探索/利用比率。

        计算逻辑 (神经科学依据):
        - 多巴胺高 + 去甲肾上腺素低 → 利用 (exploitation)
        - 多巴胺低 + 去甲肾上腺素高 → 探索 (exploration)
        - 乙酰胆碱调节探索的随机性

        返回值: [0, 1]
            0.0 = 纯探索 (随机行动)
            0.5 = 平衡
            1.0 = 纯利用 (贪婪选择)
        """
        # 利用倾向: DA高 → 利用; NE高 → 探索 (反向)
        exploit_lever = self.dopamine
        explore_lever = self.norepinephrine

        # 乙酰胆碱调节: ACh高 → 探索时更精确 (有针对性探索)
        # ACh低 → 探索时更随机
        ach_modifier = 1.0 - 0.3 * self.acetylcholine  # [0.7, 1.0]

        # 核心公式: exploit偏向 vs explore偏向
        total = exploit_lever + explore_lever * ach_modifier
        if total < 0.001:
            return 0.5

        ratio = exploit_lever / total

        # 钳制在 [0.05, 0.95] 避免极端
        return float(np.clip(ratio, 0.05, 0.95))

    def get_sensory_precision_modifier(self) -> float:
        """
        返回感官精度调节因子。

        计算逻辑:
        - 乙酰胆碱高 → 提高感官精度 (信噪比↑)
        - 去甲肾上腺素高 → 窄化注意 → 提高相关通道精度
        - 多巴胺适中 → 维持正常精度

        返回值: float, 以1.0为基准
            > 1.0: 提高精度 (更相信感官输入)
            < 1.0: 降低精度 (更依赖先验)
        """
        # 乙酰胆碱主导感官精度
        ach_effect = 1.0 + 0.8 * (self.acetylcholine - DEFAULT_NM_LEVEL)

        # 去甲肾上腺素辅助 (高NE → 聚焦 → 有效精度提升)
        ne_effect = 1.0 + 0.3 * (self.norepinephrine - DEFAULT_NM_LEVEL)

        # 多巴胺微调 (极高DA可能过度乐观, 极低DA可能过度悲观)
        da_deviation = self.dopamine - DEFAULT_NM_LEVEL
        da_effect = 1.0 - 0.1 * abs(da_deviation) * np.sign(da_deviation)

        modifier = ach_effect * ne_effect * da_effect

        # 钳制在 [0.5, 2.0]
        return float(np.clip(modifier, 0.5, 2.0))

    def get_state(self) -> Dict[str, Any]:
        """获取完整系统状态"""
        return {
            "dopamine": round(self.dopamine, 4),
            "norepinephrine": round(self.norepinephrine, 4),
            "acetylcholine": round(self.acetylcholine, 4),
            "explore_exploit_ratio": round(self.get_explore_exploit_ratio(), 4),
            "sensory_precision_modifier": round(
                self.get_sensory_precision_modifier(), 4
            ),
            "update_count": self.update_count,
        }


# ═══════════════════════════════════════════════════════════════════════
# 异稳态调节器
# ═══════════════════════════════════════════════════════════════════════

class HomeostaticRegulator:
    """
    异稳态调节器 — 智能体的"自主神经系统"。
    
    工作模式:
    NORMAL → 正常分配, 监控趋势
    STRESS → 削减非核心, 优先关键任务
    RECOVERY → 逐步恢复, 避免振荡
    CRITICAL → 紧急模式, 最小化资源消耗
    IDLE → 利用空闲进行维护 (记忆巩固/模式发现)
    BURST → 短时超频处理紧急任务
    """

    def __init__(self):
        # 四种内部资源
        self.resources: Dict[ResourceType, ResourceBudget] = {
            ResourceType.COMPUTE: ResourceBudget(ResourceType.COMPUTE, 
                                                  total_capacity=100000),  # tokens
            ResourceType.MEMORY: ResourceBudget(ResourceType.MEMORY,
                                                 total_capacity=128000),  # tokens
            ResourceType.TIME: ResourceBudget(ResourceType.TIME,
                                               total_capacity=60.0),      # seconds per turn
            ResourceType.QUALITY: ResourceBudget(ResourceType.QUALITY,
                                                  total_capacity=1.0),     # 0-1 scale
        }
        
        self.current_mode: SystemMode = SystemMode.NORMAL
        self.mode_history: List[Tuple[SystemMode, float]] = []
        
        # PID 控制参数
        self.Kp = 0.5   # 比例增益
        self.Ki = 0.1   # 积分增益
        self.Kd = 0.05  # 微分增益
        
        # 累积误差 (用于积分项)
        self.cumulative_error: Dict[ResourceType, float] = {
            rt: 0.0 for rt in ResourceType
        }
        
        # 上次误差 (用于微分项)
        self.last_error: Dict[ResourceType, float] = {
            rt: 0.0 for rt in ResourceType
        }

        # 神经调质系统 (P0: 调质三件套)
        self.neuromodulators: NeuromodulatorSystem = NeuromodulatorSystem()

        # 累积统计 (用于传递给调质系统)
        self._total_reward_prediction_error: float = 0.0
        self._total_surprise: float = 0.0
        self._surprise_count: int = 0

    def consume(self, resource_type: ResourceType, amount: float) -> bool:
        """
        消耗资源。
        
        返回: 是否成功 (资源充足)
        """
        budget = self.resources[resource_type]
        
        if amount > budget.available:
            return False
        
        budget.current_usage += amount
        budget.usage_history.append(budget.usage_ratio)
        if len(budget.usage_history) > 100:
            budget.usage_history = budget.usage_history[-100:]
        
        return True

    def release(self, resource_type: ResourceType, amount: float):
        """释放资源"""
        budget = self.resources[resource_type]
        budget.current_usage = max(0, budget.current_usage - amount)

    def predict_and_adjust(self) -> Dict[str, Any]:
        """
        异稳态核心: 预测 → 调整 → 预防。
        
        在每个决策周期:
        1. 预测未来资源需求
        2. 如果预测到不足 → 提前调整
        3. 调整系统模式
        """
        predictions = {}
        adjustments = {}
        
        for rt, budget in self.resources.items():
            predicted = budget.predict_demand()
            predictions[rt.value] = round(predicted, 3)
            
            # PID 调节
            current = budget.usage_ratio
            target = 0.5  # 理想使用率 50%
            error = current - target
            
            # PID 计算
            P = self.Kp * error
            I = self.Ki * self.cumulative_error[rt]
            D = self.Kd * (error - self.last_error[rt])
            adjustment = P + I + D
            
            self.cumulative_error[rt] += error
            self.last_error[rt] = error
            
            # 应用调节
            if adjustment > 0:  # 使用率过高 → 增加预留
                budget.reserve_ratio = min(0.5, budget.reserve_ratio + adjustment * 0.1)
            else:  # 使用率低 → 释放预留
                budget.reserve_ratio = max(0.1, budget.reserve_ratio + adjustment * 0.1)
            
            adjustments[rt.value] = {
                "adjustment": round(adjustment, 3),
                "new_reserve": round(budget.reserve_ratio, 3),
                "predicted_need": round(budget.predicted_need, 3),
            }

        # 更新系统模式
        self._update_mode()
        
        return {
            "predictions": predictions,
            "adjustments": adjustments,
            "mode": self.current_mode.value,
        }

    def _update_mode(self):
        """根据资源状态更新系统模式"""
        statuses = [b.status for b in self.resources.values()]
        
        if "critical" in statuses:
            new_mode = SystemMode.CRITICAL
        elif "stress" in statuses:
            new_mode = SystemMode.STRESS
        elif all(s == "normal" for s in statuses):
            # 检查是否空闲
            avg_usage = np.mean([b.usage_ratio for b in self.resources.values()])
            if avg_usage < 0.15:
                new_mode = SystemMode.IDLE
            else:
                new_mode = SystemMode.NORMAL
        else:
            new_mode = SystemMode.NORMAL
        
        if new_mode != self.current_mode:
            self.mode_history.append((self.current_mode, time.time()))
            if len(self.mode_history) > 50:
                self.mode_history = self.mode_history[-50:]
            self.current_mode = new_mode

    def get_action_policy(self) -> Dict[str, Any]:
        """
        根据当前模式返回行动策略。
        
        不同模式下的行为:
        NORMAL:  全部功能可用
        STRESS:  削减30%非关键任务
        CRITICAL: 只保留核心功能
        IDLE:    执行维护任务 (记忆巩固、模式学习)
        """
        policies = {
            SystemMode.NORMAL: {
                "max_parallel_tasks": 5,
                "temperature": 1.0,
                "quality_threshold": 0.5,
                "allow_exploration": True,
                "allow_maintenance": False,
            },
            SystemMode.STRESS: {
                "max_parallel_tasks": 3,
                "temperature": 0.7,
                "quality_threshold": 0.4,
                "allow_exploration": False,
                "allow_maintenance": False,
            },
            SystemMode.CRITICAL: {
                "max_parallel_tasks": 1,
                "temperature": 0.3,
                "quality_threshold": 0.3,
                "allow_exploration": False,
                "allow_maintenance": False,
            },
            SystemMode.IDLE: {
                "max_parallel_tasks": 8,
                "temperature": 2.0,
                "quality_threshold": 0.6,
                "allow_exploration": True,
                "allow_maintenance": True,
            },
            SystemMode.BURST: {
                "max_parallel_tasks": 10,
                "temperature": 0.5,
                "quality_threshold": 0.7,
                "allow_exploration": False,
                "allow_maintenance": False,
            },
        }
        
        return {
            "mode": self.current_mode.value,
            "policy": policies.get(self.current_mode, policies[SystemMode.NORMAL]),
            "resource_status": {
                rt.value: {"usage": round(b.usage_ratio, 3), "status": b.status}
                for rt, b in self.resources.items()
            },
        }

    def should_run_maintenance(self) -> bool:
        """是否应该执行维护任务 (记忆巩固/模式学习)"""
        return self.current_mode == SystemMode.IDLE

    def stress_level(self) -> float:
        """整体应激水平 (0-1)"""
        usage_ratios = [b.usage_ratio for b in self.resources.values()]
        return float(np.mean(usage_ratios))

    def update_neuromodulators(
        self,
        reward_prediction_error: float = 0.0,
        reward: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        更新神经调质系统。

        从内稳态状态推导 uncertainty 和 surprise，结合外部 RPE。

        参数:
            reward_prediction_error: 外部传入的奖励预测误差
            reward: 可选的实际奖励值 (用于计算内部 RPE)

        返回:
            调质状态字典
        """
        # 从资源压力推导 uncertainty
        uncertainty = self.stress_level()

        # 从预测误差推导 surprise
        avg_prediction_error = 0.0
        n = 0
        for budget in self.resources.values():
            if budget.prediction_errors:
                avg_prediction_error += abs(budget.prediction_errors[-1])
                n += 1
        surprise = avg_prediction_error / max(n, 1)

        # 确保 surprise 在合理范围
        surprise = np.clip(surprise, 0.0, 1.0)

        return self.neuromodulators.update(
            reward_prediction_error=reward_prediction_error,
            uncertainty=uncertainty,
            surprise=surprise,
        )

    def get_workspace_params(self) -> Dict[str, Any]:
        """
        返回工作空间参数 (内稳态→工作空间调制)。

        根据当前系统模式调整工作空间的容量和阈值:
        ├── NORMAL:  容量=5, 阈值=0.5  (标准)
        ├── STRESS:  容量=3, 阈值=0.7  (缩小, 只让高显著性通过)
        ├── CRITICAL: 容量=1, 阈值=0.85 (最小, 仅最高优先级)
        ├── IDLE:    容量=8, 阈值=0.2  (扩大, 允许更多信息进入)
        ├── BURST:   容量=10,阈值=0.4  (最大容量, 中低阈值)
        └── RECOVERY:容量=4, 阈值=0.55 (逐步恢复)

        返回:
            {
                "capacity": int,        # 工作空间槽位数
                "threshold": float,     # 进入工作空间的最低显著性
                "decay_rate": float,    # 表征衰减率
                "mode": str,           # 当前模式
            }
        """
        params_map = {
            SystemMode.NORMAL: {
                "capacity": 5,
                "threshold": 0.5,
                "decay_rate": 0.9,
            },
            SystemMode.STRESS: {
                "capacity": 3,
                "threshold": 0.7,
                "decay_rate": 0.85,
            },
            SystemMode.CRITICAL: {
                "capacity": 1,
                "threshold": 0.85,
                "decay_rate": 0.95,
            },
            SystemMode.IDLE: {
                "capacity": 8,
                "threshold": 0.2,
                "decay_rate": 0.7,
            },
            SystemMode.BURST: {
                "capacity": 10,
                "threshold": 0.4,
                "decay_rate": 0.8,
            },
            SystemMode.RECOVERY: {
                "capacity": 4,
                "threshold": 0.55,
                "decay_rate": 0.85,
            },
        }

        base = params_map.get(self.current_mode, params_map[SystemMode.NORMAL])

        # 神经调质微调
        nm = self.neuromodulators
        explore_ratio = nm.get_explore_exploit_ratio()
        precision_mod = nm.get_sensory_precision_modifier()

        # 探索倾向高 → 略微降低阈值 (让更多新信息进入)
        # 精度高 → 略微提高阈值 (更选择性)
        threshold_mod = (1.0 - explore_ratio) * 0.05 - (precision_mod - 1.0) * 0.1

        return {
            "capacity": base["capacity"],
            "threshold": round(
                np.clip(base["threshold"] + threshold_mod, 0.1, 0.95), 4
            ),
            "decay_rate": base["decay_rate"],
            "mode": self.current_mode.value,
            "neuromodulator_influence": {
                "explore_exploit_ratio": round(explore_ratio, 4),
                "sensory_precision": round(precision_mod, 4),
                "threshold_adjustment": round(threshold_mod, 4),
            },
        }


# ═══════════════════════════════════════════════════════════════════════
# 边缘效用递减调度器
# ═══════════════════════════════════════════════════════════════════════

class MarginalUtilityScheduler:
    """
    基于边际效用递减的资源调度。
    
    经济原理:
    每增加一单位资源带来的效用递减
    → 应该将资源分配给边际效用最高的任务
    
    数学:
    MU = ΔU/ΔR → 随着R增加，MU递减
    最优分配: MU₁ = MU₂ = ... = MUₙ (等边际原则)
    """

    def __init__(self, homeostat: HomeostaticRegulator):
        self.homeostat = homeostat
        self.task_utilities: Dict[str, float] = {}  # task → expected utility

    def register_task(self, task_id: str, expected_utility: float):
        """注册任务及其期望效用"""
        self.task_utilities[task_id] = expected_utility

    def schedule(self, available_compute: float) -> List[str]:
        """
        边际效用递减调度。
        
        贪心近似: 按效用/成本比降序选择任务，
        直到资源耗尽。
        """
        if not self.task_utilities:
            return []
        
        # 假设每个任务成本 ≈ 1 单位
        sorted_tasks = sorted(self.task_utilities.items(), 
                              key=lambda x: x[1], reverse=True)
        
        scheduled = []
        remaining = available_compute
        
        for task_id, utility in sorted_tasks:
            if remaining >= 1.0 and utility > 0.1:  # 最低效用阈值
                scheduled.append(task_id)
                remaining -= 1.0
        
        # 清理已完成任务
        for tid in scheduled:
            self.task_utilities.pop(tid, None)
        
        return scheduled
