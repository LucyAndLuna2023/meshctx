# -*- mode: python ; coding: utf-8 -*-
"""
meshctx Desktop — All-in-One 桌面客户端 PyInstaller 打包
Windows/macOS 双平台 .exe
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
        ('logo.png', '.'),
        ('logo.ico', '.'),
        ('logo.icns', '.'),
        ('version_info.txt', '.'),
        ('meshctx.yaml', '.'),
        ('src/__init__.py', 'src'),
        ('src/core/__init__.py', 'src/core'),
        ('src/core/*.py', 'src/core'),
        ('src/*.py', 'src'),
    ],
    hiddenimports=[
        # Core packages
        'src', 'src.core',
        # All src modules
        'src.config', 'src.model_registry', 'src.model_adapter',
        'src.skill_manager', 'src.gateway', 'src.cron',
        'src.session_search', 'src.mcp_server', 'src.tts',
        'src.browser_tool', 'src.memory_engine', 'src.models',
        'src.llm_extractor', 'src.vector_store', 'src.cross_platform_engine',
        'src.plugin_system', 'src.main', 'src.web_ui',
        'src.intent_parser', 'src.hermes_catalog', 'src.context_portal',
        'src.i18n', 'src.chat_tools', 'src.soul',
        # Core plugins
        'src.core.kernel', 'src.core.memory_hierarchy',
        'src.core.metacognition', 'src.core.orchestrator',
        'src.core.predictor', 'src.core.agent_loop',
        'src.core.performance', 'src.core.healer',
        'src.core.websocket_plugin', 'src.core.hotreload',
        'src.core.webhook',
        'src.core.free_energy', 'src.core.active_inference',
        'src.core.global_workspace', 'src.core.homeostasis',
        'src.core.brain_router', 'src.core.online_learning',
        'src.core.hybrid_reasoning', 'src.core.multi_agent',
        # Desktop deps
        'webview', 'webview.platforms', 'webview.js',
        'webview.guilib', 'webview.util',
        # Common deps
        'yaml', 'openai', 'httpx', 'fastapi', 'uvicorn',
        'pydantic', 'jinja2', 'Crypto', 'Crypto.Cipher',
        'Crypto.Cipher.AES', 'aiohttp', 'starlette',
        'anyio', 'sniffio', 'h11', 'websockets',
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

# ── Platform-specific settings ──────────────────────────────
if sys.platform == 'darwin':
    icon_file = None  # macOS EXE icon handled by BUNDLE
else:
    icon_file = 'logo.ico'

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name='meshctx-desktop',
    debug=False,
    strip=False,
    upx=(sys.platform != 'darwin'),  # upx not recommended on macOS
    console=True,   # 显示终端窗口以便看到启动日志/错误
    icon=icon_file,
    version='version_info.txt',
)

# ── macOS .app bundle (BUNDLE) ──────────────────────────────
# BUNDLE is macOS-specific; EXE is used on Windows.
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='meshctx-desktop.app',
        icon='logo.icns',
        bundle_identifier='com.meshctx.desktop',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': '1.6.0',
            'CFBundleVersion': '1.6.0',
        },
        version='version_info.txt',
    )
