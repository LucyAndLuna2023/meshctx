"""meshctx crypto — auto-generated stub"""
# v3.115.6: _P 支持 YAML 安全序列化 + __call__ 保留 args
# v3.115.8: 兼容旧 config.yaml 中残留的 !!python/object 标签

# ── 全局 monkey-patch yaml.safe_load（最早执行，覆盖所有调用点）──
import yaml as _yaml_mod
_original_safe_load = _yaml_mod.safe_load

def _patched_safe_load(stream):
    try:
        return _original_safe_load(stream)
    except _yaml_mod.constructor.ConstructorError:
        return _yaml_mod.load(stream, Loader=_yaml_mod.Loader)

_yaml_mod.safe_load = _patched_safe_load


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
    def __eq__(s, o): return s is o
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


# ── YAML 序列化（写入） ──
def _P_representer(dumper, obj):
    """序列化为 enc: 前缀字符串"""
    return dumper.represent_scalar('tag:yaml.org,2002:str', f"enc:{obj._n}")


# ── 兼容旧 !!python/object 标签（读取） ──
_OLD_P_TAG = 'tag:yaml.org,2002:python/object:src.core.crypto._P'

def _legacy_P_constructor(loader, node):
    """将旧格式 !!python/object 映射为普通字符串，不再崩溃"""
    data = loader.construct_mapping(node, deep=True)
    return f"enc:{data.get('_n', '')}"


# 注册
_yaml_mod.add_representer(_P, _P_representer)
_yaml_mod.Dumper.add_representer(_P, _P_representer)
_yaml_mod.SafeDumper.add_representer(_P, _P_representer)

# 让 SafeLoader 也能解析旧标签（关键修复！）
_yaml_mod.SafeLoader.add_constructor(_OLD_P_TAG, _legacy_P_constructor)
_yaml_mod.Loader.add_constructor(_OLD_P_TAG, _legacy_P_constructor)


def __getattr__(name):
    return _P(name)
