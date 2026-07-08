"""meshctx Action Gate — real implementation (v3.115.16)"""
import logging
from typing import Callable, Dict, Any
logger = logging.getLogger("meshctx.gate")

class ActionGate:
    """Gate sensitive actions behind approval checks."""
    def __init__(self):
        self._rules: Dict[str, Callable[[Dict], bool]] = {}
        self._require_approval = set()
    
    def protect(self, action: str, rule: Callable[[Dict], bool] = None, require_approval: bool = True):
        if require_approval:
            self._require_approval.add(action)
        if rule:
            self._rules[action] = rule
    
    def can_execute(self, action: str, context: dict = None) -> bool:
        if action in self._require_approval:
            return context.get("approved", False) if context else False
        rule = self._rules.get(action)
        return rule(context) if rule else True
    
    def list_protected(self) -> list:
        return sorted(self._require_approval)

_gate = ActionGate()
_gate.protect("write_file")
_gate.protect("remote_exec")
_gate.protect("delete_project")

def get_action_gate() -> ActionGate:
    return _gate
