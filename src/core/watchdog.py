"""看门狗 — 开源版"""
import logging, threading, time
logger = logging.getLogger("meshctx.watchdog")
HEARTBEAT_FILE = "/tmp/.meshctx_heartbeat"

class WatchdogDaemon:
    def __init__(self, *a, **kw): 
        self._running = False
        self._thread = None
    
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        logger.info("Watchdog started (stub mode)")
    
    def _beat(self):
        while self._running:
            try:
                with open(HEARTBEAT_FILE, "w") as f:
                    f.write(str(time.time()))
            except: pass
            time.sleep(5)
    
    def stop(self): self._running = False
    def stats(self): return {"uptime": 0}

_daemon = WatchdogDaemon()
def get_daemon(): return _daemon
