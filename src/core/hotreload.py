"""配置热加载 — 开源版"""
import os, time, logging, threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("meshctx.hotreload")

class ConfigWatcher:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, config_path: str = None, **kw):
        if config_path is None:
            config_path = os.path.expanduser("~/.meshctx/config.yaml")
        self.path = Path(config_path)
        self._mtime = 0
        self._callbacks: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 2
    
    def on_change(self, callback: Callable, **kw):
        self._callbacks.append(callback)
    
    def start(self, **kw):
        if self._running: return
        self._mtime = self._get_mtime()
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("ConfigWatcher started")
    
    def stop(self): self._running = False
    
    def _get_mtime(self, **kw) -> float:
        try: return self.path.stat().st_mtime if self.path.exists() else 0
        except: return 0
    
    def _watch_loop(self, **kw):
        while self._running:
            time.sleep(self._interval)
            try:
                current = self._get_mtime()
                if current > self._mtime:
                    self._mtime = current
                    for cb in self._callbacks:
                        try: cb()
                        except Exception as e: logger.error(f"Hot reload callback failed: {e}")
            except Exception:
                logger.debug("Hot reload watcher loop interrupted (non-critical)")

class APIKeyFailover:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """API Key 故障转移 — 开源版"""
    def __init__(self, *a, **kw): 
        self.active_key = None
        self.pool = []
        self._running = False
    
    def get_key(self) -> Optional[str]: 
        return self.active_key
    
    def rotate(self):
        if len(self.pool) > 1:
            current = self.pool.index(self.active_key) if self.active_key in self.pool else -1
            self.active_key = self.pool[(current + 1) % len(self.pool)]
            return self.active_key
        return None
    def start(self):
        self._running = True
    def stop(self):
        self._running = False

class MemoryBackup:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """记忆备份 — 开源版"""
    def __init__(self, backup_dir: str = "~/.meshctx/backups", **kw):
        self.backup_dir = os.path.expanduser(backup_dir)
        self._running = False
    def start(self):
        self._running = True
    def stop(self):
        self._running = False
    def backup(self): return True

