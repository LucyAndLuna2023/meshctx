# -*- mode: python ; coding: utf-8 -*-
"""MeshCtx Desktop — PyInstaller spec v2.41 FULL"""
import sys, os
_here = os.getcwd()
if 'SPECPATH' in dir():
    for _cand in (os.path.abspath(SPECPATH), os.path.dirname(os.path.abspath(SPECPATH))):
        if os.path.isdir(os.path.join(_cand, 'src', 'core')):
            _here = _cand
            break

# ═══════════════ 闭源核心/顶层模块枚举 (004 审计, 2026-08-23) ═══════════════
# 根因: collect_submodules 在 CI 隔离子进程静默返回 0, 且 spec 显式列表过期(幽灵条目+漏新增模块)
# → 发布 244/287 不完整包。修复: 构建期从磁盘递归枚举 src/core/*.py (确定性, 杜绝两类坑)。
def _enumerate_core_modules(base):
    core_dir = os.path.join(base, 'src', 'core')
    mods = []
    if os.path.isdir(core_dir):
        for root, _dirs, files in os.walk(core_dir):
            for fn in sorted(files):
                if fn.endswith('.py') and fn != '__init__.py':
                    rel = os.path.relpath(os.path.join(root, fn), core_dir)
                    mods.append('src.core.' + rel[:-3].replace(os.sep, '.'))
    return sorted(mods)

def _enumerate_src_modules(base):
    src_dir = os.path.join(base, 'src')
    mods = []
    if os.path.isdir(src_dir):
        for fn in sorted(os.listdir(src_dir)):
            if fn.endswith('.py') and fn != '__init__.py':
                mods.append('src.' + fn[:-3])
    return sorted(mods)

_core_mods = _enumerate_core_modules(_here)
_src_mods = _enumerate_src_modules(_here)
if not _core_mods:
    raise SystemExit("FAIL: src/core 无模块 — 闭源核心未落地, 禁止发布 stub 资产")
block_cipher = None

a = Analysis(
    ['meshctx_desktop.py'],
    pathex=[_here, os.path.join(_here, 'src')],
    binaries=[],
    datas=[
        ('logo.png', '.'), ('logo.ico', '.'), ('logo.icns', '.'),
        ('version_info.txt', '.'), ('meshctx.yaml', '.'),
        ('src/__init__.py', 'src'),
        ('src/core/__init__.py', 'src/core'),
        ('src/*.py', 'src'),
        ('src/i18n_translations.json', 'src'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('plugins/registry.json', 'plugins'),
    ],
    hiddenimports=_core_mods + _src_mods + [
        # Desktop deps
        'webview', 'webview.platforms', 'webview.js',
        'webview.guilib', 'webview.util',
        # Common deps
        'yaml', 'openai', 'httpx', 'fastapi', 'uvicorn',
        'fastapi.middleware', 'fastapi.middleware.cors',
        'fastapi.staticfiles', 'fastapi.responses',
        'fastapi.routing', 'fastapi.requests',
        'pydantic', 'jinja2', 'Crypto', 'Crypto.Cipher',
        'Crypto.Cipher.AES', 'aiohttp', 'starlette',
        'anyio', 'sniffio', 'h11', 'websockets', 'psutil',
        'starlette.middleware', 'starlette.middleware.gzip',
        'starlette.responses',
        'numpy', 'aiofiles', 'packaging',
        'cryptography', 'cryptography.fernet',
    ],
    hookspath=[],
    excludes=['torch','tensorflow','sklearn','keras','onnxruntime','torchvision','torchaudio','xgboost','lightgbm','numba','cupy'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='meshctx-desktop', debug=False, strip=False, upx=False,
    console=True, icon='logo.ico',
    version='version_info.txt')

if sys.platform == 'darwin':
    app = BUNDLE(exe, name='meshctx-desktop.app', icon='logo.icns',
        bundle_identifier='com.meshctx.desktop',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': '3.120.5',
            'CFBundleVersion': '3.120.5',
        }, version='version_info.txt')
