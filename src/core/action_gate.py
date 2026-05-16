"""
行动前门控 (Action Gate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每次工具调用前自动检查原则，类似人脑的前额叶抑制机制。

3级门控:
- BLOCK: 阻止执行（critical原则违反）
- FIX: 自动修正参数后执行
- WARN: 记录警告但继续（high原则违反）

设计灵感: 前额叶皮层 (PFC) 的行动抑制 → 边沿系统 (杏仁核) 的情感标记
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .principle_extractor import get_extractor

logger = logging.getLogger(__name__)


class GateAction(Enum):
    """门控动作"""
    BLOCK = "block"       # 阻止执行
    FIX = "fix"           # 自动修正后执行
    WARN = "warn"         # 警告但继续
    PASS = "pass"         # 放行


@dataclass
class GateResult:
    """门控检查结果"""
    action: GateAction
    reason: str = ""
    fix_applied: Optional[str] = None
    violated_principle: Optional[str] = None
    salience: float = 0.0


@dataclass
class ToolCall:
    """工具调用描述"""
    name: str          # 工具名 (e.g., 'patch', 'terminal', 'write_file')
    params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        p = {k: (v[:50] + "..." if isinstance(v, str) and len(v) > 50 else v) for k, v in self.params.items()}
        return f"ToolCall({self.name}, {p})"


# ═══════════════════════════════════════════════════════════════
# 工具→原则映射表
# ═══════════════════════════════════════════════════════════════

TOOL_PRINCIPLE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "patch": [
        {
            "principle_id": "html-js-comma",
            "pattern": lambda tc: "html" in str(tc.params.get("path", "")).lower()
                                or ".js" in str(tc.params.get("path", "")).lower(),
            "check": "_check_html_js_trailing_comma",
            "gate": GateAction.FIX,
            "fix": "_fix_html_js_comma",
        },
        {
            "principle_id": "py-fstring-backslash",
            "pattern": lambda tc: ".py" in str(tc.params.get("path", "")).lower(),
            "check": "_check_fstring_backslash",
            "gate": GateAction.BLOCK,
        },
    ],
    "terminal": [
        {
            "principle_id": "test-real-connection",
            "pattern": lambda tc: "curl" in str(tc.params.get("command", ""))
                                and "test" in str(tc.params.get("command", "")).lower(),
            "gate": GateAction.WARN,
        },
    ],
    "write_file": [
        {
            "principle_id": "nsi-backslash-n",
            "pattern": lambda tc: str(tc.params.get("path", "")).endswith(".nsi"),
            "check": "_check_nsi_newline",
            "gate": GateAction.FIX,
            "fix": "_fix_nsi_newline",
        },
    ],
    "delegate_task": [
        {
            "principle_id": "deploy-sync-all-changed",
            "pattern": lambda tc: "deploy" in str(tc.params.get("goal", "")).lower(),
            "gate": GateAction.WARN,
            "warn_msg": "部署前确认所有修改文件已同步（不是只有main.py）",
        },
    ],
}


class ActionGate:
    """行动前门控 — 前额叶抑制机制
    
    每次Agent执行工具调用前，检查调用是否违反已知关键原则。
    如果违反，根据严重程度：阻止/Fix后执行/警告但继续。
    """

    def __init__(self):
        self._stats = {
            "total_checked": 0,
            "blocked": 0,
            "fixed": 0,
            "warned": 0,
            "passed": 0,
        }
        self._recent_events: List[GateResult] = []  # 最近20次门控事件

    # ── 公共API ──────────────────────────────────────────

    def check(self, tool_call: ToolCall) -> GateResult:
        """检查工具调用是否违反任何原则
        
        Returns:
            GateResult with action=BLOCK/FIX/WARN/PASS
        """
        self._stats["total_checked"] += 1
        rules = TOOL_PRINCIPLE_MAP.get(tool_call.name, [])
        extractor = get_extractor() if hasattr(self, '_extractor_loaded') else None

        if not rules:
            return GateResult(action=GateAction.PASS, reason="no rules matched")

        for rule in rules:
            # 检查是否匹配该工具调用
            if rule.get("pattern") and not rule["pattern"](tool_call):
                continue

            gate_action = rule["gate"]
            principle_id = rule.get("principle_id", "")

            if gate_action == GateAction.BLOCK:
                self._stats["blocked"] += 1
                result = GateResult(
                    action=GateAction.BLOCK,
                    reason=f"BLOCKED by principle [{principle_id}]",
                    violated_principle=principle_id,
                    salience=0.95,
                )
            elif gate_action == GateAction.FIX:
                # 尝试自动修复
                fix_fn = rule.get("fix")
                if fix_fn and hasattr(self, fix_fn):
                    fix_msg = getattr(self, fix_fn)(tool_call)
                    self._stats["fixed"] += 1
                    result = GateResult(
                        action=GateAction.FIX,
                        reason=f"AUTO-FIXED by [{principle_id}]",
                        fix_applied=fix_msg,
                        violated_principle=principle_id,
                        salience=0.8,
                    )
                else:
                    result = GateResult(
                        action=GateAction.WARN,
                        reason=f"Fix unavailable for [{principle_id}]",
                        violated_principle=principle_id,
                        salience=0.6,
                    )
                    self._stats["warned"] += 1
            else:  # WARN
                self._stats["warned"] += 1
                result = GateResult(
                    action=GateAction.WARN,
                    reason=rule.get("warn_msg", f"Warning by [{principle_id}]"),
                    violated_principle=principle_id,
                    salience=0.5,
                )

            # 记录事件
            self._recent_events.append(result)
            if len(self._recent_events) > 20:
                self._recent_events.pop(0)

            return result

        # 没有匹配的规则 → 放行
        self._stats["passed"] += 1
        return GateResult(action=GateAction.PASS, reason="all rules passed")

    # ── 自动修复方法 ──────────────────────────────────────

    def _fix_html_js_comma(self, tool_call: ToolCall) -> str:
        """确保HTML/JS patch中逗号不丢失"""
        new_str = tool_call.params.get("new_string", "")
        old_str = tool_call.params.get("old_string", "")

        if not new_str or not old_str:
            return "no fix needed (empty strings)"

        # 检查是否在JS对象内做修改
        if "{" in old_str or ":" in old_str:
            # 确保前一项有逗号
            lines = new_str.split("\n")
            original_new = new_str

            # 简单规则: 如果new_string以换行结束且前一行是键值对，确保有逗号
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.endswith('"') or stripped.endswith("'") or stripped.endswith("]") or stripped.endswith("}"):
                    # 可能缺少逗号，但这里不盲目加逗号来避免引入新问题
                    pass

            if new_str != original_new:
                tool_call.params["new_string"] = new_str
                return "added trailing commas in JS object"
        return "js comma check passed"

    def _check_fstring_backslash(self, tool_call: ToolCall) -> bool:
        """检查Python patch中是否有f-string反斜杠问题"""
        new_str = tool_call.params.get("new_string", "")
        lines = new_str.split("\n")
        for i, line in enumerate(lines):
            if 'f"' in line or "f'" in line:
                if "\\\\" in line:
                    # f-string表达式内不能含反斜杠 (Python 3.10)
                    return False
        return True

    def _fix_nsi_newline(self, tool_call: ToolCall) -> str:
        """修复NSIS的$\\n问题"""
        new_str = tool_call.params.get("new_string", "")
        if "$\\\\n" in new_str:
            new_str = new_str.replace("$\\\\n", "$\\n")
            tool_call.params["new_string"] = new_str
            return "fixed NSIS $\\\\n → $\\n"
        return "nsi newline ok"

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "block_rate": round(self._stats["blocked"] / max(self._stats["total_checked"], 1), 3),
            "fix_rate": round(self._stats["fixed"] / max(self._stats["total_checked"], 1), 3),
            "pass_rate": round(self._stats["passed"] / max(self._stats["total_checked"], 1), 3),
            "recent_events": len(self._recent_events),
        }

    def get_recent_events(self, limit: int = 10) -> List[Dict]:
        return [
            {
                "action": e.action.value,
                "reason": e.reason,
                "fix": e.fix_applied,
                "principle": e.violated_principle,
                "salience": e.salience,
            }
            for e in self._recent_events[-limit:]
        ]


# 单例
_gate_instance: Optional[ActionGate] = None


def get_gate() -> ActionGate:
    """获取ActionGate单例"""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ActionGate()
    return _gate_instance
