"""Session Resume — 开源版 (stub)"""
import logging

logger = logging.getLogger("meshctx.session_resume")

class _SessionResume:
    def resume(self, *a, **kw): return None
    def stats(self): return {}
    def detect_previous_session(self):
        """检测是否存在上次会话存档"""
        return None  # 开源版不实现自动恢复
    def restore(self, session_id):
        """恢复指定会话"""
        return {"context_continuity": 0, "items_restored": {"decisions": 0, "rules": 0}, "resume_time_ms": 0}
    def apply_to_kernel(self, kernel):
        """将会话上下文注入内核"""
        return []

_resume = _SessionResume()
def get_session_resume(): return _resume

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

