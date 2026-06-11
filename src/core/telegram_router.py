"""Telegram Router — 开源版 (stub)"""
class _TelegramRouter:
    def start(self, *a, **kw): pass
    def route(self, *a, **kw): pass
    def stats(self): return {}

_router = _TelegramRouter()
def get_telegram_router(): return _router
