"""Error Code Registry — v3.18"""
import logging
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

CODES = {
    "E001": {"severity": "CRITICAL", "message": "Memory exhausted", "action": "Restart and free RAM"},
    "E002": {"severity": "ERROR", "message": "Config file corrupted", "action": "Restore from backup"},
    "E003": {"severity": "ERROR", "message": "Module not found", "action": "Check pip install"},
    "E004": {"severity": "WARNING", "message": "Rate limit approaching", "action": "Slow down requests"},
    "E005": {"severity": "WARNING", "message": "Disk space low", "action": "Clean old backups"},
    "E006": {"severity": "INFO", "message": "Auto-backup completed", "action": "None"},
    "W001": {"severity": "WARNING", "message": "Deprecated API called", "action": "Update to new endpoint"},
    "W002": {"severity": "WARNING", "message": "SSL certificate expiring", "action": "Renew certificate"},
}

class ErrorRegistry:
    def lookup(self, code: str) -> Optional[Dict]: return CODES.get(code.upper())
    def by_severity(self, level: str) -> Dict[str, Dict]:
        return {k:v for k,v in CODES.items() if v["severity"] == level.upper()}
    def suggest_action(self, error_message: str) -> str:
        msg = error_message.lower()
        if "memory" in msg: return CODES["E001"]["action"]
        if "module" in msg or "import" in msg: return CODES["E003"]["action"]
        if "disk" in msg or "space" in msg: return CODES["E005"]["action"]
        return "Check logs for details"
    def get_stats(self) -> Dict:
        return {"total_codes": len(CODES), "by_severity": {s: len(self.by_severity(s)) for s in ["CRITICAL","ERROR","WARNING","INFO"]}}

_registry: Optional[ErrorRegistry] = None
def get_error_registry() -> ErrorRegistry:
    global _registry
    if _registry is None: _registry = ErrorRegistry()
    return _registry
