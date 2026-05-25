"""Command Alias & Shortcut System — v3.05"""
import json, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ALIASES = {
    "d": "deploy", "t": "test", "b": "build", "s": "status",
    "l": "logs", "r": "restart", "up": "update", "c": "chat",
    "init": "agent init", "backup": "backup run", "scan": "plugin scan",
    "health": "heal cycle", "bench": "benchmark run",
}

class AliasManager:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".meshctx"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._aliases: Dict[str, str] = {}
        self._load()
    
    def _load(self):
        af = self.config_dir / "aliases.json"
        if af.exists():
            try: self._aliases = json.loads(af.read_text())
            except: pass
        if not self._aliases:
            self._aliases = dict(DEFAULT_ALIASES)
            self._save()
    
    def _save(self):
        (self.config_dir / "aliases.json").write_text(json.dumps(self._aliases, indent=2))
    
    def add(self, alias: str, command: str) -> Dict:
        self._aliases[alias] = command; self._save()
        return {"success": True, "alias": alias, "command": command}
    
    def remove(self, alias: str) -> Dict:
        if alias in DEFAULT_ALIASES: return {"success": False, "error": "不能删除内置别名"}
        if alias in self._aliases: del self._aliases[alias]; self._save()
        return {"success": True}
    
    def resolve(self, alias: str) -> Optional[str]:
        return self._aliases.get(alias)
    
    def list_all(self) -> Dict[str, str]: return dict(self._aliases)
    def get_stats(self) -> Dict:
        return {"total": len(self._aliases), "builtin": len(DEFAULT_ALIASES),
                "custom": len(self._aliases) - len([k for k in self._aliases if k in DEFAULT_ALIASES])}

_mgr: Optional[AliasManager] = None
def get_alias_manager() -> AliasManager:
    global _mgr
    if _mgr is None: _mgr = AliasManager()
    return _mgr
