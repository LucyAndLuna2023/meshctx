"""
meshctx Canonical Stub Proxy (v3.115.16)
Single _P class replacing 61 scattered duplicates across core/.

Usage:
    from ._stub import _P, stub_module
    __getattr__ = lambda name: _P(name)   # module-level proxy

Architecture:
    - _P is a "black hole" proxy — any attribute access returns another _P
    - This allows public repo modules to compile without private core dependencies
    - Real implementations in meshctx-core override these stubs at runtime
    - v3.115.16: consolidated from 61 copies into this single definition
"""
import logging

logger = logging.getLogger("meshctx.stub")


class _P:
    """Canonical stub proxy — consolidated from 61 scattered definitions.
    
    All attribute accesses, calls, and comparisons return another _P instance.
    This allows the public repo to define module interfaces without the private
    implementation, while still being importable and type-checkable.
    """
    __slots__ = ('_n', '_d')
    
    def __init__(s, n=""):
        object.__setattr__(s, '_n', n)
        object.__setattr__(s, '_d', {})
    
    def __getattr__(s, n, **kw):
        if n in s._d:
            return s._d[n]
        if n.startswith("__"):
            raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    
    def __setattr__(s, n, v):
        s._d[n] = v
    
    def __delattr__(s, n, **kw):
        if n in s._d:
            del s._d[n]
    
    def __call__(s, *a, **k):
        logger.warning(f"Stub called: {s._n or 'anonymous'}() — SHELL module, real impl in meshctx-core")
        return _P(f"{s._n}()" if s._n else "call")
    
    def __bool__(s):
        return True
    
    def __len__(s):
        return 1
    
    def __iter__(s):
        yield _P("item")
        yield _P("item")
    
    def __getitem__(s, k):
        return _P(f"{s._n}[{k}]")
    
    def __contains__(s, i):
        return False  # v3.115.16: was True — security fix
    
    def __eq__(s, o):
        return NotImplemented  # v3.115.16: was True — security fix, falls back to identity
    
    def __ne__(s, o):
        return False
    
    def __hash__(s):
        return 0
    
    def __int__(s):
        return 0
    
    def __float__(s):
        return 0.0
    
    def __str__(s):
        return ""
    
    def __repr__(s):
        return f"_P({s._n!r})" if s._n else "_P()"
    
    def __truediv__(s, o):
        return _P(f"{s._n}/{o}")
    
    def __rtruediv__(s, o):
        return _P(f"{o}/{s._n}")
    
    def __lt__(s, o):
        return True
    
    def __le__(s, o):
        return True
    
    def __gt__(s, o):
        return True
    
    def __ge__(s, o):
        return True
    
    def __enter__(s):
        return s
    
    def __exit__(s, *a):
        pass
    
    async def __aenter__(s):
        return s
    
    async def __aexit__(s, *a):
        pass
    
    def __await__(s, **kw):
        async def _aw():
            return s
        return _aw().__await__()
    
    def __neg__(s):
        return _P(f"-{s._n}")
    
    def __add__(s, o):
        return _P(f"{s._n}+")
    
    def __sub__(s, o):
        return _P(f"{s._n}-")
    
    def __mul__(s, o):
        return _P(f"{s._n}*")


def stub_module(name: str = None):
    """Create a module-level __getattr__ stub exporter.
    
    Usage:
        __getattr__ = stub_module(__name__)
    """
    def _module_getattr(attr_name):
        return _P(f"{name}.{attr_name}" if name else attr_name)
    return _module_getattr
