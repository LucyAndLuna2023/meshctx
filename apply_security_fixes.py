#!/usr/bin/env python3
"""
安全加固一键脚本 — P1 修复
用法: python3 apply_security_fixes.py
"""
import re

FIXES = []

# ── Fix 1: CORS allow_headers 收紧 ──
def fix_cors():
    path = 'src/main.py'
    with open(path) as f: c = f.read()
    old = 'allow_headers=["*"]'
    new = 'allow_headers=["Authorization", "Content-Type", "X-Requested-With"]'
    if old in c:
        c = c.replace(old, new)
        with open(path, 'w') as f: f.write(c)
        return f'✅ CORS: {old} → {new}'
    return f'⚠️  CORS: pattern not found (may already be fixed)'

# ── Fix 2: Session cookie secure flag ──
def fix_cookie_secure():
    path = 'src/core/auth_v2.py'
    with open(path) as f: c = f.read()
    old = 'httponly=True, max_age=86400, samesite="lax"'
    new = 'httponly=True, secure=True, max_age=86400, samesite="lax"'
    if old in c and 'secure=True' not in c:
        c = c.replace(old, new)
        with open(path, 'w') as f: f.write(c)
        return f'✅ Cookie: added secure=True'
    return f'⚠️  Cookie: already has secure=True or pattern changed'

# ── Fix 3: Rate limiter sliding window ──
def fix_rate_limiter():
    path = 'src/main.py'
    with open(path) as f: c = f.read()
    old = '_rate_limits.clear()\n        _suspicious_ips.clear()'
    new = ('# Sliding window: remove entries older than 2x RATE_WINDOW\n'
           '        now_cleanup = time.time()\n'
           '        _rate_limits = {k: [t for t in v if now_cleanup - t < RATE_WINDOW * 2] for k, v in _rate_limits.items()}\n'
           '        _rate_limits = {k: v for k, v in _rate_limits.items() if v}\n'
           '        _suspicious_ips = {k: [t for t in v if now_cleanup - t < _SUSPICIOUS_WINDOW * 2] for k, v in _suspicious_ips.items()}\n'
           '        _suspicious_ips = {k: v for k, v in _suspicious_ips.items() if v}')
    if old in c:
        c = c.replace(old, new)
        with open(path, 'w') as f: f.write(c)
        return '✅ Rate limiter: .clear() → sliding window'
    return '⚠️  Rate limiter: pattern not found'

# ── Fix 4: _StubClass add warning ──
def fix_stub_class():
    path = 'src/core/__init__.py'
    with open(path) as f: c = f.read()
    if 'MESHCTX_STRICT' not in c and '_StubClass' in c:
        # Patch __getattr__ and __bool__ to warn
        old_getattr = 'def __getattr__(self, name):\n                return self'
        new_getattr = ('def __getattr__(self, name):\n'
                       '                import os, warnings\n'
                       '                if os.environ.get("MESHCTX_STRICT"):\n'
                       '                    raise ImportError(f"meshctx-core not installed, cannot access {name}")\n'
                       '                warnings.warn(f"meshctx stub accessed: {name}", RuntimeWarning, stacklevel=2)\n'
                       '                return self')
        if old_getattr in c:
            c = c.replace(old_getattr, new_getattr)
            with open(path, 'w') as f: f.write(c)
            return '✅ _StubClass: added MESHCTX_STRICT diagnostics'
        return '⚠️  _StubClass.__getattr__: pattern changed'
    return '⚠️  _StubClass: already patched'

# ── Run all ──
for name, func in [
    ('CORS', fix_cors),
    ('Cookie', fix_cookie_secure),
    ('Rate Limiter', fix_rate_limiter),
    ('_StubClass', fix_stub_class),
]:
    try:
        print(func())
    except Exception as e:
        print(f'❌ {name}: {e}')

print('\n👉 下一步: pytest tests/test_*.py -v')
