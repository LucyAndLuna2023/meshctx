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
