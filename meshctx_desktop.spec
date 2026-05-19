# -*- mode: python ; coding: utf-8 -*-
"""MeshCtx Desktop — PyInstaller spec v2.29 MINIMAL"""
import sys, os
_here = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in dir() else os.getcwd()
block_cipher = None

a = Analysis(
    ['meshctx_desktop.py'],
    pathex=[_here, os.path.join(_here, 'src')],
    binaries=[],
    datas=[
        ('version_info.txt', '.'), ('meshctx.yaml', '.'),
        ('src/__init__.py', 'src'),
        ('src/core/__init__.py', 'src/core'),
        ('src/core/*.py', 'src/core'),
        ('src/*.py', 'src'),
    ],
    hiddenimports=[
        'src', 'src.core',
        'src.model_registry', 'src.main', 'src.web_ui', 'src.cli',
        'src.core.kernel', 'src.core.memory_hierarchy',
        'src.core.metacognition', 'src.core.orchestrator',
        'src.core.predictor', 'src.core.agent_loop',
        'src.core.performance', 'src.core.healer',
        'src.core.websocket_plugin',
        'yaml', 'openai', 'httpx', 'fastapi', 'uvicorn',
        'pydantic', 'jinja2', 'starlette',
        'anyio', 'sniffio', 'h11', 'websockets',
        'numpy', 'aiofiles',
        'webview', 'webview.platforms',
    ],
    hookspath=[],
    excludes=['tkinter','matplotlib','pandas','scipy','jupyter','IPython','PyQt5','PyQt6','PySide2','PySide6','wx'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='meshctx-desktop', debug=False, strip=False, upx=True,
    console=True, icon='logo.ico', version='version_info.txt')
