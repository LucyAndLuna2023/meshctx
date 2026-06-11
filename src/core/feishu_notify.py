"""Feishu Notifier — 开源版 (stub)"""
class FeishuNotifier:
    def __init__(self, *a, **kw): pass
    def send(self, *a, **kw) -> bool: 
        import logging
        logging.getLogger("meshctx").info("Feishu notifier stub — install meshctx-core")
        return True
    def stats(self): return {}
