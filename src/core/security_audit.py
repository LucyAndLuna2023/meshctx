"""
meshctx v3.54 — Security Audit Engine (安全审计引擎)

功能:
  1. 命令注入检测: shell/OS命令注入模式识别
  2. 敏感信息泄露: API key/密码/Token模式匹配
  3. 权限提升检测: sudo/管理员操作审计
  4. 数据外泄检测: 可疑网络连接/文件传输
  5. 审计报告: 定期安全状态汇总
"""
import logging, re, time, json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("meshctx.security_audit")

class Severity(Enum):
    CRITICAL="critical"; HIGH="high"; MEDIUM="medium"; LOW="low"; INFO="info"

@dataclass
class SecurityEvent:
    id: str=field(default_factory=lambda: f"sec-{int(time.time()*1000)}")
    severity: Severity=Severity.INFO
    category: str=""
    description: str=""
    source: str=""
    timestamp: float=field(default_factory=time.time)
    resolved: bool=False

class SecurityAuditEngine:
    def __init__(self):
        self._events: deque=deque(maxlen=200)
        self._stats={"scanned":0,"flagged":0,"critical":0}
        self._patterns={
            "cmd_injection": [r'[;|&`$]\s*(rm\s+-rf|shutdown|reboot|wget|curl)',r'eval\s*\(',r'exec\s*\(',r'__import__\s*\(',r'subprocess\.'],
            "credential_leak": [r'(api[_-]?key|apikey|token|password|secret)\s*[:=]\s*["\'][A-Za-z0-9_\-]{8,}',r'sk-[A-Za-z0-9]{20,}',r'ghp_[A-Za-z0-9]{20,}',r'Bearer\s+[A-Za-z0-9\-_\.]{20,}'],
            "privilege_escalation": [r'sudo\s+',r'chmod\s+777',r'chown\s+root',r'systemctl\s+stop',r'passwd\s'],
            "data_exfil": [r'nc\s+.*\d{1,5}',r'scp\s+.*@.*:',r'rsync\s+.*:',r'base64\s+-d.*\|.*sh'],
            "dependency_risk": [r'pip\s+install.*--user',r'npm\s+install\s+-g',r'gem\s+install'],
        }
    
    def scan(self, text: str, source: str="unknown") -> List[SecurityEvent]:
        events = []
        self._stats["scanned"] += 1
        
        for category, patterns in self._patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for m in matches:
                    if category == "cmd_injection":
                        sev = Severity.CRITICAL
                    elif category == "credential_leak":
                        sev = Severity.HIGH
                    elif category == "privilege_escalation":
                        sev = Severity.HIGH
                    else:
                        sev = Severity.MEDIUM
                    
                    event = SecurityEvent(severity=sev, category=category,
                        description=f"Pattern '{pattern[:50]}' matched: ...{m.group()[max(0,len(m.group())-40):]}",
                        source=source)
                    events.append(event)
                    self._events.append(event)
        
        if events:
            self._stats["flagged"] += 1
            self._stats["critical"] += sum(1 for e in events if e.severity==Severity.CRITICAL)
        
        return events
    
    def audit_command(self, cmd: str, context: str="") -> List[SecurityEvent]:
        """审计shell命令"""
        events = []
        dangerous = [
            (r'rm\s+-rf\s+/', Severity.CRITICAL, "Recursive root delete"),
            (r'>\s*/dev/sda', Severity.CRITICAL, "Raw disk write"),
            (r'chmod\s+777\s+/', Severity.HIGH, "World-writable system dir"),
            (r'git\s+push\s+--force', Severity.MEDIUM, "Force push"),
            (r'docker\s+rm\s+-f', Severity.MEDIUM, "Force remove container"),
            (r'DROP\s+TABLE|DELETE\s+FROM', Severity.CRITICAL, "Database destruction"),
        ]
        for pattern, sev, desc in dangerous:
            if re.search(pattern, cmd, re.IGNORECASE):
                events.append(SecurityEvent(severity=sev, category="dangerous_cmd",
                    description=f"{desc}: {cmd[:80]}", source=context))
                self._events.append(events[-1])
        return events
    
    def get_report(self) -> Dict[str,Any]:
        recent = list(self._events)[-20:]
        return {
            "stats": dict(self._stats),
            "recent_events": len(recent),
            "by_severity": {s.value:sum(1 for e in recent if e.severity==s) for s in Severity},
            "unresolved": sum(1 for e in recent if not e.resolved),
            "latest": [{"sev":e.severity.value,"cat":e.category,"desc":e.description[:80]} for e in recent[-5:]],
        }

_audit_engine = None
def get_security_engine(): 
    global _audit_engine
    if _audit_engine is None: _audit_engine = SecurityAuditEngine()
    return _audit_engine
