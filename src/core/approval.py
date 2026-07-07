"""Approval Engine — 安全审批引擎

三级模式: manual(必须审批) / smart(智能判断) / off(跳过审批)
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalMode(str, Enum):
    MANUAL = "manual"
    SMART = "smart"
    OFF = "off"


@dataclass
class ApprovalResult:
    """审批检查结果"""
    requires_approval: bool = True
    reason: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    yolo_override: bool = False
    action: str = "prompt"  # "pass" | "prompt" | "block"

    def __post_init__(self):
        if not self.requires_approval:
            self.action = "pass"
        elif self.risk_level == RiskLevel.CRITICAL:
            self.action = "block"
        else:
            self.action = "prompt"


# ── 危险命令模式 ──
_DANGEROUS_PATTERNS: list[tuple[str, RiskLevel, str]] = [
    # 致命破坏
    (r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|-[a-zA-Z]*f[a-zA-Z]*r?)\s+/', RiskLevel.CRITICAL,
     "递归强制删除根目录"),
    (r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|-[a-zA-Z]*f[a-zA-Z]*r?)\s+\*', RiskLevel.CRITICAL,
     "递归强制删除通配"),
    (r'\bdd\s+if=.*of=/dev/', RiskLevel.CRITICAL,
     "直接写入块设备"),
    (r'\bmkfs\.', RiskLevel.CRITICAL,
     "格式化文件系统"),
    (r'>\s*/dev/sd[a-z]', RiskLevel.CRITICAL,
     "覆盖块设备"),

    # Git 危险操作
    (r'git\s+push\s+(-[a-zA-Z]*f|--force)', RiskLevel.HIGH,
     "Git force push"),
    (r'git\s+reset\s+--hard', RiskLevel.HIGH,
     "Git hard reset"),
    (r'git\s+clean\s+(-[a-zA-Z]*f|--force)', RiskLevel.MEDIUM,
     "Git force clean"),

    # 网络管道风险
    (r'curl\s+.*\|\s*(ba)?sh', RiskLevel.HIGH,
     "curl 管道到 shell"),
    (r'wget\s+.*\|\s*(ba)?sh', RiskLevel.HIGH,
     "wget 管道到 shell"),
    (r'curl\s+.*\|\s*bash', RiskLevel.HIGH,
     "curl 管道到 bash"),

    # 权限提升
    (r'\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*)?\s*777\b', RiskLevel.HIGH,
     "chmod 777"),
    (r'\bchmod\s+[ug]\+[s]\b', RiskLevel.MEDIUM,
     "setuid/setgid"),

    # 系统修改
    (r'\bsystemctl\s+disable\b', RiskLevel.MEDIUM,
     "禁用系统服务"),
    (r'\biptables\s+-F\b', RiskLevel.HIGH,
     "清空防火墙规则"),

    # Docker 风险
    (r'docker\s+rm\s+(-[a-zA-Z]*f|--force).*\$\s*\(', RiskLevel.HIGH,
     "Docker 强制删除容器"),
    (r'docker\s+system\s+prune\s+(-[a-zA-Z]*f|--force)', RiskLevel.HIGH,
     "Docker 系统强制清理"),
]

# ── 安全命令模式（白名单） ──
_SAFE_PATTERNS: list[str] = [
    r'^ls\b', r'^cat\b', r'^echo\b', r'^pwd\b', r'^whoami\b',
    r'^date\b', r'^uname\b', r'^git\s+status\b', r'^git\s+log\b',
    r'^git\s+diff\b', r'^git\s+branch\b', r'^python3?\s', r'^python\s',
    r'^pip3?\s+list\b', r'^pip3?\s+show\b', r'^pip3?\s+install\b',
    r'^pip\s+install\b', r'^which\b', r'^mkdir\b',
    r'^find\b', r'^head\b', r'^tail\b', r'^wc\b', r'^grep\b',
    r'^cp\b', r'^mv\b',
    r'^df\b', r'^du\b', r'^free\b', r'^ps\b', r'^top\b',
    r'^docker\s+ps\b', r'^docker\s+images\b', r'^docker\s+logs\b',
    r'^npm\s+list\b', r'^npm\s+view\b', r'^cargo\s+check\b',
]


class ApprovalEngine:
    """安全审批引擎

    Modes:
    - manual: 所有操作都需审批（最安全）
    - smart:  根据风险评估自动决定（推荐）
    - off:    跳过审批（不推荐）
    """

    mode: str
    yolo: bool

    def __init__(self, mode: str = "smart", yolo: bool = False):
        self.mode = mode
        self.yolo = yolo

    def set_mode(self, mode: str):
        """切换审批模式：manual / smart / off"""
        if mode in ("manual", "smart", "off"):
            self.mode = mode
        else:
            raise ValueError(f"Unknown mode: {mode}. Use manual/smart/off")

    def check(self, command: str, context: Optional[dict] = None) -> ApprovalResult:
        """检查命令是否需要审批

        Returns:
            ApprovalResult with requires_approval, reason, risk_level, action
        """
        # YOLO 模式：跳过一切
        if self.yolo:
            return ApprovalResult(requires_approval=False, reason="YOLO 活动 — 跳过审批", risk_level=RiskLevel.LOW, yolo_override=True)

        # off 模式：跳过一切
        if self.mode == "off":
            return ApprovalResult(requires_approval=False, reason="审批引擎已关闭", risk_level=RiskLevel.LOW)

        # 安全命令白名单 — 所有模式都放行
        for pat in _SAFE_PATTERNS:
            if re.search(pat, command, re.IGNORECASE):
                return ApprovalResult(requires_approval=False, reason="安全命令（白名单匹配）", risk_level=RiskLevel.LOW)

        # 危险命令检测
        for pat, level, reason_text in _DANGEROUS_PATTERNS:
            if re.search(pat, command, re.IGNORECASE):
                return ApprovalResult(requires_approval=True, reason=reason_text, risk_level=level)

        # 未识别命令
        if self.mode == "manual":
            return ApprovalResult(requires_approval=True, reason="Manual 模式 — 未识别命令需审批", risk_level=RiskLevel.MEDIUM)

        return ApprovalResult(requires_approval=False, reason="Smart 模式 — 未检测到危险", risk_level=RiskLevel.LOW)

    def request(self, command: str, reason: str = "") -> bool:
        """请求用户审批（同步/CLI模式）"""
        result = self.check(command)
        if not result.requires_approval:
            return True
        # 在真实环境中会弹出交互式审批 — stub 返回 False
        return False

    def stats(self) -> dict:
        """返回审批统计"""
        return {"mode": self.mode, "yolo": self.yolo}
