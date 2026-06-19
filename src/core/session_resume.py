"""Session Resume — 开源版 (stub)"""
class _SessionResume:
    def resume(self, *a, **kw): return None
    def stats(self): return {}

_resume = _SessionResume()
def get_session_resume(): return _resume
