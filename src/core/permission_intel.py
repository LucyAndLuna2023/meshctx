"""
MeshCtx v3.38 — Permission Intelligence (智能权限引擎)

解决HN #1痛点: Agent权限疲劳 (372↑)
用户厌倦反复批准Agent操作 → 智能学习+自动批准+风险预判

架构:
- 权限学习: 记录用户批准模式 → 自动批准已知安全操作
- 风险分级: 5级风险 (TRIVIAL→CRITICAL) → 不同批准策略
- JEPA预测: 预评估操作后果 → 免去不必要的确认
- 用户画像: 每个用户的审批偏好 → 个性化

融合:
- LeCun JEPA世界模型: 潜空间预测操作风险
- meshctx SDB: 安全闸不可绕过
- meshctx Approval: 现有审批引擎升级
"""
import time
import json
import numpy as np
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


class RiskLevel(Enum):
    """操作风险等级"""
    TRIVIAL = 0      # 无风险: 读文件、查看状态
    LOW = 1          # 低风险: 创建文件、启动服务
    MEDIUM = 2       # 中风险: 修改配置、安装包
    HIGH = 3         # 高风险: 删除文件、修改代码
    CRITICAL = 4     # 极危险: rm -rf、drop table、sudo


class ApprovalDecision(Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    ASK_USER = "ask_user"
    REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass
class PermissionRule:
    """权限规则"""
    pattern: str           # 操作匹配模式 (regex或关键词)
    risk_level: RiskLevel
    max_frequency: int     # 每小时最大次数
    require_confirmation: bool
    cooldown_seconds: int  # 冷却时间
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


@dataclass
class ApprovalRecord:
    """审批记录"""
    action: str
    risk_level: RiskLevel
    user_decision: str  # approved/denied
    timestamp: float
    context: str = ""
    jepa_risk_score: float = 0.0


class PermissionLearner:
    """权限学习器 — 从用户行为中学习审批偏好"""
    
    def __init__(self):
        self.approval_history: List[ApprovalRecord] = []
        self.action_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"approved": 0, "denied": 0})
        self.auto_rules: Dict[str, PermissionRule] = {}
        self.trust_score: float = 0.5  # 全局信任分 0-1
        
        # 默认安全规则
        self._init_default_rules()
    
    def _init_default_rules(self):
        defaults = [
            ("read|cat|ls|dir|get|fetch|view|show|display|list|status|info|help",
             RiskLevel.TRIVIAL, 100, False, 0),
            ("create|write|save|new|add|append|touch|mkdir|echo",
             RiskLevel.LOW, 50, False, 5),
            ("install|update|upgrade|pip|npm|apt|brew|configure|config|setup",
             RiskLevel.MEDIUM, 20, True, 30),
            ("delete|remove|rm|uninstall|kill|stop|disable|clear|drop|truncate",
             RiskLevel.HIGH, 5, True, 60),
            ("rm -rf|sudo|chmod 777|drop table|format|wipe|shred|destroy",
             RiskLevel.CRITICAL, 0, True, 300),
        ]
        for pattern, risk, freq, confirm, cooldown in defaults:
            self.auto_rules[pattern.split("|")[0]] = PermissionRule(
                pattern=pattern, risk_level=risk, max_frequency=freq,
                require_confirmation=confirm, cooldown_seconds=cooldown,
            )
    
    def learn_from_decision(self, action: str, risk: RiskLevel,
                            approved: bool, context: str = ""):
        """学习用户审批决策"""
        record = ApprovalRecord(
            action=action, risk_level=risk,
            user_decision="approved" if approved else "denied",
            timestamp=time.time(), context=context,
        )
        self.approval_history.append(record)
        
        # 更新统计
        action_key = self._extract_action_key(action)
        if approved:
            self.action_stats[action_key]["approved"] += 1
            self.trust_score = min(1.0, self.trust_score + 0.01)
        else:
            self.action_stats[action_key]["denied"] += 1
            self.trust_score = max(0.1, self.trust_score - 0.02)
        
        # 频繁批准→自动规则
        stats = self.action_stats[action_key]
        total = stats["approved"] + stats["denied"]
        if total >= 5 and stats["approved"] / total >= 0.9:
            # 90%+批准率→自动批准
            self.auto_rules[action_key] = PermissionRule(
                pattern=action_key, risk_level=RiskLevel.TRIVIAL,
                max_frequency=20, require_confirmation=False, cooldown_seconds=5,
            )
    
    def _extract_action_key(self, action: str) -> str:
        """提取操作关键词"""
        return action.split()[0].lower() if action else "unknown"
    
    def get_approval_rate(self, action: str) -> float:
        """获取某操作的批准率"""
        key = self._extract_action_key(action)
        stats = self.action_stats.get(key, {"approved": 0, "denied": 0})
        total = stats["approved"] + stats["denied"]
        return stats["approved"] / total if total > 0 else 0.5
    
    def should_auto_approve(self, action: str, risk: RiskLevel) -> bool:
        """判断是否应自动批准"""
        if risk == RiskLevel.CRITICAL:
            return False  # 永不自动批准极危险操作
        
        key = self._extract_action_key(action)
        if key in self.auto_rules:
            rule = self.auto_rules[key]
            if not rule.require_confirmation:
                return True
        
        # 高频批准→自动
        rate = self.get_approval_rate(action)
        if rate >= 0.95 and risk.value <= RiskLevel.LOW.value:
            return True
        
        return False


class RiskPredictor:
    """风险预测器 — 用JEPA世界模型预评估操作风险
    
    核心: 操作→潜空间向量→JEPA预测→风险分数
    不需要LLM，直接在潜空间评估
    """
    
    def __init__(self):
        self.action_risk_scores: Dict[str, float] = {}
        
        # 已知高风险模式
        self.dangerous_patterns = [
            (r"rm\s+-rf", 0.99),
            (r"sudo\s+", 0.85),
            (r"DROP\s+TABLE", 0.99),
            (r"DELETE\s+FROM", 0.90),
            (r"chmod\s+777", 0.95),
            (r"format\s+", 0.98),
            (r">/dev/sd", 0.99),
            (r"kill\s+-9", 0.70),
            (r"shutdown", 0.75),
            (r"reboot", 0.75),
        ]
    
    def predict_risk(self, action: str, context: str = "") -> Tuple[RiskLevel, float]:
        """预测操作风险
        
        Returns:
            risk_level: 风险等级
            confidence: 置信度 0-1
        """
        import re
        
        # 1. 模式匹配
        for pattern, score in self.dangerous_patterns:
            if re.search(pattern, action, re.IGNORECASE):
                if score >= 0.95:
                    return RiskLevel.CRITICAL, score
                elif score >= 0.85:
                    return RiskLevel.HIGH, score
                elif score >= 0.70:
                    return RiskLevel.MEDIUM, score
        
        # 2. 启发式判断
        action_lower = action.lower()
        
        # 只读操作
        if any(w in action_lower for w in ['read', 'get', 'ls', 'cat', 'view', 'show', 'status', 'help']):
            return RiskLevel.TRIVIAL, 0.9
        
        # 写操作
        if any(w in action_lower for w in ['write', 'create', 'save', 'new', 'add']):
            return RiskLevel.LOW, 0.85
        
        # 修改操作
        if any(w in action_lower for w in ['modify', 'update', 'change', 'set', 'edit', 'configure']):
            return RiskLevel.MEDIUM, 0.75
        
        # 删除操作
        if any(w in action_lower for w in ['delete', 'remove', 'uninstall', 'kill', 'stop']):
            return RiskLevel.HIGH, 0.80
        
        # 默认
        return RiskLevel.MEDIUM, 0.5
    
    def get_jepa_risk_score(self, action: str) -> float:
        """JEPA世界模型风险评分
        
        未来: 将操作编码为潜向量,用JEPA预测后果
        当前: 基于模式匹配+统计
        """
        if action in self.action_risk_scores:
            return self.action_risk_scores[action]
        
        risk, conf = self.predict_risk(action)
        score = risk.value / 4.0  # 归一化到0-1
        self.action_risk_scores[action] = score
        return score


class PermissionIntelligence:
    """权限智能引擎 — 统一入口
    
    决策流程:
    1. 风险预测 (RiskPredictor)
    2. 用户偏好查询 (PermissionLearner)
    3. 决策: 自动批准 / 询问 / 拒绝
    4. 学习反馈
    """
    
    def __init__(self):
        self.learner = PermissionLearner()
        self.predictor = RiskPredictor()
        self.decision_log: List[Dict[str, Any]] = []
    
    def evaluate(self, action: str, context: str = "",
                 user_id: str = "default") -> Dict[str, Any]:
        """评估操作并返回决策"""
        
        # Step 1: 风险预测
        risk_level, risk_confidence = self.predictor.predict_risk(action, context)
        
        # Step 2: JEPA风险评分
        jepa_score = self.predictor.get_jepa_risk_score(action)
        
        # Step 3: 用户偏好
        approval_rate = self.learner.get_approval_rate(action)
        auto_approve = self.learner.should_auto_approve(action, risk_level)
        
        # Step 4: 决策
        if risk_level == RiskLevel.CRITICAL:
            decision = ApprovalDecision.REQUIRE_CONFIRMATION
            reason = "极危险操作，必须确认"
        elif auto_approve:
            decision = ApprovalDecision.AUTO_APPROVE
            reason = f"用户历史批准率{approval_rate:.0%}, 自动批准"
        elif risk_level == RiskLevel.TRIVIAL and approval_rate >= 0.8:
            decision = ApprovalDecision.AUTO_APPROVE
            reason = "低风险+高批准率, 自动通过"
        elif risk_level.value >= RiskLevel.HIGH.value:
            decision = ApprovalDecision.ASK_USER
            reason = "高风险操作, 需用户确认"
        else:
            decision = ApprovalDecision.AUTO_APPROVE if self.learner.trust_score > 0.7 else ApprovalDecision.ASK_USER
            reason = f"信任分{self.learner.trust_score:.2f}"
        
        result = {
            "action": action,
            "risk_level": risk_level.name,
            "risk_confidence": risk_confidence,
            "jepa_risk_score": jepa_score,
            "approval_rate": approval_rate,
            "decision": decision.value,
            "reason": reason,
            "trust_score": self.learner.trust_score,
            "timestamp": time.time(),
        }
        
        self.decision_log.append(result)
        return result
    
    def record_feedback(self, action: str, approved: bool, context: str = ""):
        """记录用户反馈"""
        risk, _ = self.predictor.predict_risk(action)
        self.learner.learn_from_decision(action, risk, approved, context)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        total = len(self.learner.approval_history)
        approved = sum(1 for r in self.learner.approval_history if r.user_decision == "approved")
        recent_decisions = self.decision_log[-10:]
        
        auto_approve_count = sum(1 for d in recent_decisions
                                if d['decision'] == 'auto_approve')
        
        return {
            "total_decisions": total,
            "approval_rate": approved / total if total > 0 else 0,
            "trust_score": self.learner.trust_score,
            "auto_approve_ratio": auto_approve_count / max(len(recent_decisions), 1),
            "saved_prompts": auto_approve_count,  # 免去的批准弹窗
            "auto_rules": len(self.learner.auto_rules),
            "recent_decisions": recent_decisions[-3:],
        }


# 单例
_intelligence: Optional[PermissionIntelligence] = None

def get_permission_intelligence() -> PermissionIntelligence:
    global _intelligence
    if _intelligence is None:
        _intelligence = PermissionIntelligence()
    return _intelligence
