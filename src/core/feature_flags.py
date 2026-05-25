"""Feature Flag Manager — v3.12"""
import json, logging
from pathlib import Path
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class FeatureFlags:
    _DEFAULTS = {"auto_backup": True, "strict_mode": False, "experimental": False,
                 "voice_enabled": False, "web_search": True, "swarm_mode": False}
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".meshctx"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._flags = dict(self._DEFAULTS); self._load()
    def _load(self):
        f = self.config_dir / "features.json"
        if f.exists():
            try: self._flags.update(json.loads(f.read_text()))
            except: pass
    def _save(self):
        (self.config_dir / "features.json").write_text(json.dumps(self._flags, indent=2))
    def enable(self, name: str) -> bool:
        if name in self._flags: self._flags[name] = True; self._save(); return True
        return False
    def disable(self, name: str) -> bool:
        if name in self._flags: self._flags[name] = False; self._save(); return True
        return False
    def is_enabled(self, name: str) -> bool: return self._flags.get(name, False)
    def list_all(self) -> Dict: return dict(self._flags)
    def get_stats(self) -> Dict:
        enabled = sum(1 for v in self._flags.values() if v)
        return {"total": len(self._flags), "enabled": enabled, "flags": self._flags}

_flags: Optional[FeatureFlags] = None
def get_feature_flags() -> FeatureFlags:
    global _flags
    if _flags is None: _flags = FeatureFlags()
    return _flags
