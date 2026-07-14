"""配置热加载 — 开源版"""
import os, time, logging, threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("meshctx.hotreload")

class ConfigWatcher:
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
    def status(self):
        return {"active_key": self.active_key[:8]+"***" if self.active_key else None, "pool_size": len(self.pool), "running": self._running}

class MemoryBackup:
    """记忆备份 — 开源版"""
    def __init__(self, backup_dir: str = "~/.meshctx/backups", **kw):
        self.backup_dir = os.path.expanduser(backup_dir)
        self._running = False
    def start(self):
        self._running = True
    def stop(self):
        self._running = False
    def backup(self, data=None, label=""):
        """创建备份 — 兼容开源/完整版"""
        import json, time
        os.makedirs(self.backup_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        name = label or ts
        path = os.path.join(self.backup_dir, f"{name}.json")
        try:
            with open(path, "w") as f:
                json.dump(data or {}, f, ensure_ascii=False, indent=2)
            return path
        except Exception:
            return None
    def restore(self, name=""):
        """恢复备份 — 兼容开源/完整版"""
        import json, glob
        if name:
            path = os.path.join(self.backup_dir, name if name.endswith('.json') else f"{name}.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        # 找最新备份
        files = sorted(glob.glob(os.path.join(self.backup_dir, "*.json")))
        if files:
            with open(files[-1]) as f:
                return json.load(f)
        return None
    def list_backups(self):
        """列出所有备份"""
        import glob
        os.makedirs(self.backup_dir, exist_ok=True)
        files = sorted(glob.glob(os.path.join(self.backup_dir, "*.json")))
        return [os.path.basename(f) for f in files]

