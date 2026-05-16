# -*- mode: python ; coding: utf-8 -*-
"""
MeshCtx Desktop — PyInstaller spec v2.15.4
pip install pyinstaller && pyinstaller meshctx_desktop.spec
"""
import sys, os
from pathlib import Path

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
    hiddenimports=[
        'src', 'src.core',
        'src.config', 'src.model_registry', 'src.model_adapter',
        'src.skill_manager', 'src.gateway', 'src.cron',
        'src.session_search', 'src.mcp_server', 'src.tts',
        'src.browser_tool', 'src.memory_engine', 'src.models',
        'src.llm_extractor', 'src.vector_store', 'src.cross_platform_engine',
        'src.plugin_system', 'src.main', 'src.web_ui',
        'src.intent_parser', 'src.hermes_catalog', 'src.context_portal',
        'src.i18n', 'src.chat_tools', 'src.soul',
        # Core plugins (original)
        'src.core.kernel', 'src.core.memory_hierarchy',
        'src.core.metacognition', 'src.core.orchestrator',
        'src.core.predictor', 'src.core.agent_loop',
        'src.core.performance', 'src.core.healer',
        'src.core.websocket_plugin', 'src.core.hotreload',
        'src.core.webhook',
        # Brain modules
        'src.core.free_energy', 'src.core.active_inference',
        'src.core.global_workspace', 'src.core.homeostasis',
        'src.core.brain_router', 'src.core.online_learning',
        'src.core.hybrid_reasoning', 'src.core.multi_agent',
        'src.core.super_brain',
        # v2.7-v2.15 NEW MODULES
        'src.core.sandbox', 'src.core.project_indexer',
        'src.core.feishu_notify', 'src.core.win_admin',
        'src.core.model_compare', 'src.core.conversation_store',
        'src.core.code_reviewer', 'src.core.agent_monitor',
        'src.core.cache', 'src.core.security',
        'src.core.agent_tasks', 'src.core.plugin_autoload',
        'src.core.realtime_push', 'src.core.auto_update',
        'src.core.multi_notify', 'src.core.versioned_memory',
        'src.core.workspace_manager',
        'src.core.platform_fs', 'src.core.crypto',
        'src.core.plugin_manifest',
        # Desktop deps
        'webview', 'webview.platforms', 'webview.js',
        'webview.guilib', 'webview.util',
        # Common deps
        'yaml', 'openai', 'httpx', 'fastapi', 'uvicorn',
        'pydantic', 'jinja2', 'Crypto', 'Crypto.Cipher',
        'Crypto.Cipher.AES', 'aiohttp', 'starlette',
        'anyio', 'sniffio', 'h11', 'websockets', 'psutil',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'pandas', 'scipy',
        'notebook', 'jupyter', 'IPython', 'PyQt5',
        'PyQt6', 'PySide2', 'PySide6', 'wx',
    ],
    win_no_prefer_redirects=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == 'darwin':
    icon_file = None
else:
    icon_file = 'logo.ico'

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name='meshctx-desktop',
    debug=False, strip=False,
    upx=(sys.platform != 'darwin'),
    console=True,
    icon=icon_file,
    version='version_info.txt',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='meshctx-desktop.app',
        icon='logo.icns',
        bundle_identifier='com.meshctx.desktop',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': '2.15.4',
            'CFBundleVersion': '2.15.4',
        },
        version='version_info.txt',
    )
