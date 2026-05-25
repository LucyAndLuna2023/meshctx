"""Hot Reload Watcher — v3.07"""
import time, logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

class HotReload:
    def __init__(self, watch_dir: Optional[Path] = None):
        self.watch_dir = watch_dir or Path.cwd()
        self._files: Dict[str, float] = {}
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._running = False
    
    def watch(self, pattern: str, callback: Callable):
        self._callbacks[pattern].append(callback)
        # Scan initial state
        for f in self.watch_dir.rglob(pattern):
            try: self._files[str(f)] = f.stat().st_mtime
            except: pass
    
    def check(self) -> List[str]:
        changed = []
        for pattern, callbacks in self._callbacks.items():
            for f in self.watch_dir.rglob(pattern):
                key = str(f)
                try:
                    mtime = f.stat().st_mtime
                    if key not in self._files:
                        self._files[key] = mtime; changed.append(key)
                    elif mtime > self._files[key]:
                        self._files[key] = mtime; changed.append(key)
                        for cb in callbacks:
                            try: cb(key)
                            except: pass
                except: pass
        return changed
    
    def get_stats(self) -> Dict:
        return {"watched_patterns": list(self._callbacks.keys()),
                "tracked_files": len(self._files), "running": self._running}

_reloader: Optional[HotReload] = None
def get_hot_reload() -> HotReload:
    global _reloader
    if _reloader is None: _reloader = HotReload()
    return _reloader
