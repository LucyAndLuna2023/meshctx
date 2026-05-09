# meshctx Windows 打包配置
# pip install pyinstaller && pyinstaller meshctx.spec

# -*- mode: python ; coding: utf-8 -*-
import sys, os
from pathlib import Path

_here = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in dir() else os.getcwd()

block_cipher = None

a = Analysis(
    ['src/cli.py'],
    pathex=[_here],
    binaries=[],
    datas=[
        ('meshctx.yaml', '.'),
        ('src/core/*.py', 'src/core'),
        ('src/*.py', 'src'),
    ],
    hiddenimports=[
        'src.core.kernel',
        'src.core.memory_hierarchy',
        'src.core.metacognition',
        'src.core.orchestrator',
        'src.config',
        'src.model_registry',
        'src.skill_manager',
        'src.gateway',
        'src.cron',
        'src.session_search',
        'src.mcp_server',
        'src.tts',
        'src.browser_tool',
        'src.memory_engine',
        'src.models',
        'src.llm_extractor',
        'src.vector_store',
        'src.cross_platform_engine',
        'src.plugin_system',
        'src.main',
        'src.web_ui',
        'yaml',
        'openai',
        'httpx',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'pandas', 'scipy',
        'notebook', 'jupyter', 'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='meshctx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # CLI应用
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='docs/assets/logo.png' if Path('docs/assets/logo.png').exists() else None,
)
