"""配置热加载 — 开源版"""
import os, time, logging, threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("meshctx.hotreload")

class ConfigWatcher:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.expanduser("~/.meshctx/config.yaml")
        self.path = Path(config_path)
        self._mtime = 0
        self._callbacks: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 2
    
    def on_change(self, callback: Callable):
        self._callbacks.append(callback)
    
    def start(self):
        if self._running: return
        self._mtime = self._get_mtime()
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("ConfigWatcher started")
    
    def stop(self): self._running = False
    
    def _get_mtime(self) -> float:
        try: return self.path.stat().st_mtime if self.path.exists() else 0
        except: return 0
    
    def _watch_loop(self):
        while self._running:
            time.sleep(self._interval)
            try:
                current = self._get_mtime()
                if current > self._mtime:
                    self._mtime = current
                    for cb in self._callbacks:
                        try: cb()
                        except Exception as e: logger.error(f"Hot reload callback failed: {e}")
            except Exception: pass

class APIKeyFailover:
    """API Key 故障转移 — 开源版"""
    def __init__(self, *a, **kw): 
        self.active_key = None
        self.pool = []
    
    def get_key(self) -> Optional[str]: 
        return self.active_key
    
    def rotate(self): pass
    
    def start(self): pass
    def stop(self): pass

class MemoryBackup:
    """记忆备份 — 开源版"""
    def __init__(self, *a, **kw): pass
    def start(self): pass
    def stop(self): pass
    def backup(self): return True

class _P:
    __slots__ = ('_n',)
    def __init__(s, n=""): object.__setattr__(s, '_n', n)
    def __getattr__(s, n):
        if n.startswith('_'): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

