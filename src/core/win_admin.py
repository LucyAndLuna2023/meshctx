"""Windows Admin — 开源版 (stub)"""

class _P:
    """Lazy proxy placeholder for Linux stub"""
    def __init__(s, n=""):
        object.__setattr__(s, "_n", n)
        object.__setattr__(s, "_d", {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v):
        s._d[n] = v
    def __call__(s, *a, **k):
        return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s):
        yield _P("item"); yield _P("item")
    def __getitem__(s, k):
        return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __int__(s): return 0
    def __repr__(s): return s._n or "_WinAdminStub"

class _WinAdmin:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def elevate(self, *a, **kw): return False
    def is_admin(self) -> bool: return False
    def stats(self): return {}

_admin = _WinAdmin()
def get_win_admin(): return _admin
