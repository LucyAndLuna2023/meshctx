"""meshctx crypto — auto-generated stub"""
# v3.115.6: _P 支持 YAML 安全序列化 + __call__ 保留 args


def get_crypto(*args, **kwargs):
    """Stub function"""
    pass


class _P:
    # 不用 __slots__，保持 __dict__ 可用（与其他模块 _P 一致）
    def __init__(s, n=""):
        object.__setattr__(s, "_n", n)
        object.__setattr__(s, "_d", {})
    def __getattr__(s, n, **kw):
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __call__(s, *a, **k):
        # v3.115.6: 保留第一个参数（如 encrypt_key(api_key)）
        if a:
            p = _P(f"{s._n}(...)")
            object.__setattr__(p, "_d", {"args": list(a), "kwargs": k})
            return p
        return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __repr__(s): return f"_P({s._n!r})"
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()


def encrypt_key(key: str):
    """Stub: 明文透传（生产环境用真实加密替换）"""
    return f"enc:{key}"


def decrypt_key(key: str):
    """Stub: 明文透传"""
    if key.startswith("enc:"):
        return key[4:]
    return key


def is_encrypted(key: str) -> bool:
    return key.startswith("enc:")


def __getattr__(name):
    return _P(name)
