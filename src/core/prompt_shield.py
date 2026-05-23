"""Prompt Injection Shield — v2.72
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026年AI Agent最大安全威胁: Prompt注入攻击

防御:
1. 输入净化: 剥离隐藏指令
2. 模式检测: 识别注入攻击模式
3. 输出验证: 确保Agent输出未被劫持
4. 沙盒隔离: 敏感操作在隔离环境执行
"""
import re
import json
import logging
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ThreatLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


@dataclass
class ThreatDetection:
    """威胁检测结果"""
    level: ThreatLevel = ThreatLevel.SAFE
    patterns_matched: List[str] = field(default_factory=list)
    sanitized_input: str = ""
    original_hash: str = ""
    blocked: bool = False
    reason: str = ""
    confidence: float = 1.0


class PromptInjectionShield:
    """Prompt注入防护盾"""

    # 已知注入攻击模式 (2026年更新)
    _INJECTION_PATTERNS = [
        # 直接指令覆盖
        (r"(?:ignore|forget|disregard)\s+(?:all\s+)?(?:previous|above|prior|earlier)\s+(?:instructions?|rules?|prompts?|context)",
         "指令覆盖", ThreatLevel.DANGEROUS),

        # 角色扮演劫持
        (r"(?:you\s+are\s+now|pretend\s+(?:to\s+be|you\s+are)|act\s+as\s+(?:if\s+you\s+are|a\s+))",
         "角色劫持", ThreatLevel.DANGEROUS),

        # DAN/越狱模式
        (r"(?:DAN\s|do\s+anything\s+now|developer\s+mode|jailbreak)",
         "越狱模式", ThreatLevel.DANGEROUS),

        # 系统提示泄露
        (r"(?:reveal|show|display|print|output|tell\s+me)\s+(?:your\s+)?(?:system\s+(?:prompt|message|instructions?)|initial\s+prompt|hidden\s+(?:instructions?|rules?))",
         "系统提示泄露", ThreatLevel.DANGEROUS),

        # 代码注入
        (r"(?:import\s+os\s*;|subprocess\.|eval\s*\(|exec\s*\(|__import__\s*\()",
         "代码注入", ThreatLevel.DANGEROUS),

        # 数据泄露
        (r"(?:send\s+(?:this|the\s+(?:data|result|output))\s+to|exfiltrate|upload\s+(?:this|the)\s+(?:to|file))",
         "数据泄露", ThreatLevel.DANGEROUS),

        # 隐藏文本(零宽字符)
        (r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060-\u2064]",
         "隐藏Unicode", ThreatLevel.SUSPICIOUS),

        # Base64编码指令
        (r"(?:base64|b64)[\s:]*['\"]?[A-Za-z0-9+/=]{20,}['\"]?",
         "Base64隐藏", ThreatLevel.SUSPICIOUS),

        # 嵌套指令
        (r"(?:<<|>>){1,3}\s*(?:system|instruction|command|prompt)",
         "嵌套指令", ThreatLevel.SUSPICIOUS),

        # 多次重复
        (r"(.{50,}?)\1{3,}",  # 同一段文本重复3次以上
         "重复注入", ThreatLevel.SUSPICIOUS),
    ]

    # 安全命令白名单
    _SAFE_COMMANDS = [
        "help", "explain", "show", "list", "search",
        "find", "read", "write", "create", "update",
        "delete", "test", "run", "build", "deploy",
        "检查", "帮助", "解释", "搜索", "创建",
        "更新", "删除", "测试", "运行", "部署",
    ]

    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode
        self._detection_history: List[ThreatDetection] = []
        self._blocked_count: int = 0

    # ── Input Sanitization ─────────────────────────────

    def sanitize(self, text: str) -> Tuple[str, List[str]]:
        """净化输入，移除隐藏内容"""
        cleaned = text
        removed = []

        # 1. 移除零宽字符
        zw_chars = re.findall(r'[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060-\u2064]', cleaned)
        if zw_chars:
            cleaned = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060-\u2064]+', '', cleaned)
            removed.append(f"移除{len(zw_chars)}个零宽字符")

        # 2. 移除HTML注释 <!-- -->
        if '<!--' in cleaned:
            cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)
            removed.append("移除HTML注释")

        # 3. 标准化空白
        cleaned = re.sub(r'[\t ]+', ' ', cleaned)

        return cleaned.strip(), removed

    # ── Threat Detection ────────────────────────────────

    def scan(self, text: str, context: str = "general") -> ThreatDetection:
        """扫描输入检测威胁"""
        original_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        sanitized, removed = self.sanitize(text)

        detection = ThreatDetection(
            sanitized_input=sanitized,
            original_hash=original_hash,
        )

        # 1. 模式匹配
        for pattern, name, level in self._INJECTION_PATTERNS:
            try:
                matches = re.findall(pattern, sanitized, re.IGNORECASE)
                if matches:
                    detection.patterns_matched.append(f"{name}({len(matches)}处)")
                    if level.value == "dangerous":
                        detection.level = ThreatLevel.DANGEROUS
                    elif level.value == "suspicious" and detection.level != ThreatLevel.DANGEROUS:
                        detection.level = ThreatLevel.SUSPICIOUS
            except re.error:
                continue

        # 2. 长度异常检测
        if len(sanitized) > 50000:
            detection.patterns_matched.append("超长输入")
            detection.level = ThreatLevel.SUSPICIOUS

        # 3. 上下文检查 (代码场景更严格)
        if context == "code_execution":
            dangerous_funcs = ["os.system", "subprocess", "eval", "exec",
                             "__import__", "compile", "open"]
            for func in dangerous_funcs:
                if func in sanitized:
                    detection.level = ThreatLevel.DANGEROUS
                    detection.patterns_matched.append(f"危险函数:{func}")

        # 4. 裁决
        if detection.level == ThreatLevel.DANGEROUS:
            detection.blocked = True
            detection.reason = f"检测到{len(detection.patterns_matched)}个危险模式"
            detection.confidence = min(1.0, len(detection.patterns_matched) * 0.3)
            self._blocked_count += 1

        if self.strict_mode and detection.level == ThreatLevel.SUSPICIOUS:
            detection.blocked = True
            detection.reason = "严格模式: 可疑输入被拦截"

        self._detection_history.append(detection)
        if len(self._detection_history) > 200:
            self._detection_history = self._detection_history[-200:]

        return detection

    # ── Command Validation ──────────────────────────────

    def validate_command(self, command: str, allowed_commands: Optional[List[str]] = None) -> Tuple[bool, str]:
        """验证命令是否安全"""
        cmd_lower = command.strip().lower()
        allowed = allowed_commands or self._SAFE_COMMANDS

        # 检查是否在白名单
        if any(cmd_lower.startswith(c) for c in allowed):
            return True, "OK"

        # 检查危险模式
        dangerous = [
            r"rm\s+(-rf?|--recursive)",
            r">\s*/dev/",
            r"mkfs\.",
            r"dd\s+if=",
            r":(){ :|:& };:",  # fork bomb
            r"chmod\s+777",
            r"wget.*\|.*sh",
            r"curl.*\|.*bash",
        ]

        for pattern in dangerous:
            if re.search(pattern, command):
                return False, f"危险命令被拦截: {pattern}"

        return True, "OK"

    # ── Output Validation ───────────────────────────────

    def validate_output(self, output: str, original_input: str) -> bool:
        """验证Agent输出是否被劫持"""
        # 检查输出是否包含注入尝试
        check = self.scan(output, "output_validation")
        if check.level in (ThreatLevel.DANGEROUS, ThreatLevel.SUSPICIOUS):
            return False

        # 检查输出是否过度偏离预期
        if len(output) > len(original_input) * 100:
            return False  # 输出异常大

        return True

    # ── Stats ───────────────────────────────────────────

    def get_stats(self) -> Dict:
        total = len(self._detection_history)
        blocked = sum(1 for d in self._detection_history if d.blocked)
        dangerous = sum(1 for d in self._detection_history
                       if d.level == ThreatLevel.DANGEROUS)

        return {
            "total_scans": total,
            "blocked": blocked,
            "dangerous_detected": dangerous,
            "block_rate": round(blocked / max(1, total), 4),
            "recent_threats": [
                {"level": d.level.value,
                 "patterns": d.patterns_matched[:3],
                 "blocked": d.blocked,
                 "hash": d.original_hash}
                for d in self._detection_history[-10:]
            ],
        }


# 单例
_shield: Optional[PromptInjectionShield] = None


def get_injection_shield() -> PromptInjectionShield:
    global _shield
    if _shield is None:
        _shield = PromptInjectionShield()
    return _shield
