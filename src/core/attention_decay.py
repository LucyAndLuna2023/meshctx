"""
注意力衰减告警 (Attention Decay Alert)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
当Agent的上下文窗口接近极限时，关键原则容易被"掩埋"到
注意力视野之外。此模块监控上下文长度，在超出阈值时：
1. 提升关键原则的显著性(amygdala boost)
2. 向全局工作空间广播警告
3. 对action gate施加严格模式

设计灵感: 前扣带皮层(ACC)的冲突监测 + 蓝斑(LC)的去甲肾上腺素释放
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class AttentionLevel(Enum):
    """注意力层级 — 类比蓝斑的NE释放水平"""
    OPTIMAL = "optimal"          # < 50% 容量: 最佳注意力
    ENGAGED = "engaged"           # 50-65%: 需要聚焦
    STRESSED = "stressed"         # 65-80%: 开始衰减
    OVERLOADED = "overloaded"     # 80-90%: 严重衰减
    CRITICAL = "critical"         # > 90%: 临界，原则可能被掩埋


@dataclass
class AttentionSnapshot:
    """注意力快照"""
    level: AttentionLevel
    context_tokens: int
    context_limit: int
    fill_pct: float
    principle_boost: float       # 原则显著性提升系数 (1.0-3.0)
    timestamp: float = field(default_factory=time.time)


@dataclass
class PrincipleSalience:
    """原则显著性"""
    principle_id: str
    rule: str
    base_salience: float
    boosted_salience: float
    severity: str
    position_in_context: str      # "front" | "middle" | "buried"


class AttentionDecayMonitor:
    """注意力衰减监控器 — ACC+LC双核
    
    前扣带皮层(ACC): 检测注意力和期望之间的冲突
    蓝斑(LC): 根据冲突程度释放去甲肾上腺素(NE)来调整全局觉醒水平
    """

    # 阈值配置
    THRESHOLDS = {
        AttentionLevel.OPTIMAL: 0.0,     # < 50%
        AttentionLevel.ENGAGED: 0.50,     # 50-65%
        AttentionLevel.STRESSED: 0.65,    # 65-80%
        AttentionLevel.OVERLOADED: 0.80,  # 80-90%
        AttentionLevel.CRITICAL: 0.90,    # > 90%
    }

    # 不同注意力层级下的原则boost系数
    BOOST_FACTORS = {
        AttentionLevel.OPTIMAL: 1.0,
        AttentionLevel.ENGAGED: 1.3,
        AttentionLevel.STRESSED: 1.8,
        AttentionLevel.OVERLOADED: 2.5,
        AttentionLevel.CRITICAL: 3.0,
    }

    def __init__(self, context_limit: int = 16000):
        self.context_limit = context_limit
        self._level: AttentionLevel = AttentionLevel.OPTIMAL
        self._snapshots: List[AttentionSnapshot] = []
        self._alert_count: int = 0
        self._last_alert_time: float = 0

    # ── 核心API ──────────────────────────────────────────

    def assess(self, token_count: int) -> AttentionSnapshot:
        """评估当前上下文状态
        
        Args:
            token_count: 当前上下文token数
            
        Returns:
            AttentionSnapshot 包含注意力层级和原则boost系数
        """
        fill_pct = token_count / self.context_limit if self.context_limit > 0 else 0

        # 确定注意力层级
        if fill_pct >= 0.90:
            new_level = AttentionLevel.CRITICAL
        elif fill_pct >= 0.80:
            new_level = AttentionLevel.OVERLOADED
        elif fill_pct >= 0.65:
            new_level = AttentionLevel.STRESSED
        elif fill_pct >= 0.50:
            new_level = AttentionLevel.ENGAGED
        else:
            new_level = AttentionLevel.OPTIMAL

        # 层级变化 → 记录事件
        if new_level != self._level:
            self._level = new_level
            self._alert_count += 1
            self._last_alert_time = time.time()
            logger.warning(
                f"[ATTENTION] Level changed → {new_level.value} "
                f"(tokens={token_count}/{self.context_limit}, fill={fill_pct:.1%})"
            )

        boost = self.BOOST_FACTORS[self._level]
        snapshot = AttentionSnapshot(
            level=self._level,
            context_tokens=token_count,
            context_limit=self.context_limit,
            fill_pct=fill_pct,
            principle_boost=boost,
        )
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 50:
            self._snapshots.pop(0)

        return snapshot

    def get_boosted_principles(self, principles: List[Dict[str, Any]]) -> List[PrincipleSalience]:
        """获取boost后的原则显著性列表
        
        关键原则 (severity=critical) 按boost系数放大显著性。
        位置标记: front(前1/3) / middle(中1/3) / buried(后1/3, 被掩埋)
        """
        boost = self.BOOST_FACTORS[self._level]
        results = []

        for i, p in enumerate(principles):
            severity = p.get("severity", "low")
            base = p.get("salience", 0.5)

            if severity == "critical":
                boosted = min(base * boost, 1.0)
            elif severity == "high":
                boosted = base * (1 + (boost - 1) * 0.5)
            else:
                boosted = base

            # 位置标记: 假设原则均匀分布在上下文窗口
            total = len(principles)
            if total == 0:
                position = "front"
            elif i < total // 3:
                position = "front"
            elif i > total * 2 // 3:
                position = "buried"
            else:
                position = "middle"

            results.append(PrincipleSalience(
                principle_id=p.get("id", f"p{i}"),
                rule=p.get("rule", "")[:80],
                base_salience=base,
                boosted_salience=boosted,
                severity=severity,
                position_in_context=position,
            ))

        return results

    def generate_alert(self) -> Optional[Dict[str, Any]]:
        """生成注意力衰减告警消息
        
        当层级 >= STRESSED 时，生成结构化告警供Orient阶段注入。
        """
        if self._level in (AttentionLevel.OPTIMAL, AttentionLevel.ENGAGED):
            return None

        snap = self._snapshots[-1] if self._snapshots else None
        if not snap:
            return None

        return {
            "type": "attention_decay",
            "level": self._level.value,
            "fill_pct": snap.fill_pct,
            "tokens": snap.context_tokens,
            "limit": self.context_limit,
            "principle_boost": snap.principle_boost,
            "message": (
                f"⚠️ 上下文填充率 {snap.fill_pct:.0%} — "
                f"关键原则显著性提升至 {snap.principle_boost:.1f}x"
            ),
            "recommendation": (
                "建议压缩上下文或重启会话以防止原则被掩埋"
                if self._level == AttentionLevel.CRITICAL
                else "注意关键原则，它们在注意力窗口中权重降低"
            ),
        }

    # ── 统计 ──────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        return {
            "level": self._level.value,
            "context_limit": self.context_limit,
            "boost_factor": self.BOOST_FACTORS[self._level],
            "alert_count": self._alert_count,
            "last_alert_time": self._last_alert_time,
            "snapshot_count": len(self._snapshots),
            "latest_snapshot": {
                "fill_pct": self._snapshots[-1].fill_pct,
                "tokens": self._snapshots[-1].context_tokens,
            } if self._snapshots else None,
        }


# 单例
_monitor_instance: Optional[AttentionDecayMonitor] = None


def get_monitor(context_limit: int = 16000) -> AttentionDecayMonitor:
    """获取AttentionDecayMonitor单例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = AttentionDecayMonitor(context_limit=context_limit)
    return _monitor_instance
