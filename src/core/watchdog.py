"""看门狗 — 开源版"""
import logging, threading, time
from pathlib import Path
logger = logging.getLogger("meshctx.watchdog")
HEARTBEAT_FILE = Path("/tmp/.meshctx_heartbeat")

class WatchdogDaemon:
    def __init__(self, *a, **kw): 
        self._running = False
        self._thread = None
        self._alerts = []
    
    def start(self, **kw):
        self._running = True
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        logger.info("Watchdog started (stub mode)")
    
    def _beat(self, **kw):
        while self._running:
            try:
                with open(HEARTBEAT_FILE, "w") as f:
                    f.write(str(time.time()))
            except Exception:
                pass  # 心跳文件写入失败不影响守护进程（磁盘满/权限），非关键路径
            time.sleep(5)
    
    def stop(self): self._running = False
    def stats(self): return {"uptime": 0}
    def get_status(self): return {"status": "ok", "uptime": 0, "alerts": len(self._alerts)}

_daemon = WatchdogDaemon()
def get_daemon(): return _daemon
