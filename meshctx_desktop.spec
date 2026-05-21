# -*- mode: python ; coding: utf-8 -*-
"""MeshCtx Desktop — PyInstaller spec v2.41 FULL"""
import sys, os
from PyInstaller.utils.hooks import collect_submodules
_here = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in dir() else os.getcwd()
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
        ('src/core/*.py', 'src/core'),
        ('src/*.py', 'src'),
        ('plugins/registry.json', 'plugins'),
    ],
    hiddenimports=collect_submodules('src.core') + collect_submodules('src') + [
        # Desktop deps
        'webview', 'webview.platforms', 'webview.js',
        'webview.guilib', 'webview.util',
        # Common deps
        'yaml', 'openai', 'httpx', 'fastapi', 'uvicorn',
        'pydantic', 'jinja2', 'Crypto', 'Crypto.Cipher',
        'Crypto.Cipher.AES', 'aiohttp', 'starlette',
        'anyio', 'sniffio', 'h11', 'websockets', 'psutil',
        'numpy', 'aiofiles', 'packaging',
    ],
    hookspath=[],
    excludes=['tkinter','matplotlib','pandas','scipy','jupyter','IPython','PyQt5','PyQt6','PySide2','PySide6','wx'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='meshctx-desktop', debug=False, strip=False, upx=True,
    console=True, icon='logo.ico', version='version_info.txt')

if sys.platform == 'darwin':
    app = BUNDLE(exe, name='meshctx-desktop.app', icon='logo.icns',
        bundle_identifier='com.meshctx.desktop',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': '2.49.0',
            'CFBundleVersion': '2.49.0',
        }, version='version_info.txt')
