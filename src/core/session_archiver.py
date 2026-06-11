"""会话归档 — 开源版"""
import logging
logger = logging.getLogger("meshctx")

class SessionArchiver:
    def __init__(self, *a, **kw): pass
    def init_session(self, version: str): 
        logger.info(f"Session archiver stub (v{version})")
    def archive(self, *a, **kw): pass
    def get_session(self, *a, **kw): return None

_archiver = SessionArchiver()
def get_archiver(): return _archiver
