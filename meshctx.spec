# meshctx Windows 打包配置 — 修复版 (parent package问题)
# pip install pyinstaller && pyinstaller meshctx.spec

# -*- mode: python ; coding: utf-8 -*-
import sys, os
from pathlib import Path

_here = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in dir() else os.getcwd()

block_cipher = None

a = Analysis(
    ['src/cli.py'],
    # 🔧 修复: 添加src/到搜索路径，确保 relative import 能找到parent package
    pathex=[_here, os.path.join(_here, 'src')],
    binaries=[],
    datas=[
        ('meshctx.yaml', '.'),
        # 🔧 修复: 显式包含__init__.py确保包结构完整
        ('src/__init__.py', 'src'),
        ('src/core/__init__.py', 'src/core'),
        ('src/core/*.py', 'src/core'),
        ('src/*.py', 'src'),
    ],
    hiddenimports=[
        # 🔧 修复: 关键! 显式声明src和src.core为包 (解决Windows "parent package" 错误)
        'src',
        'src.core',
        # Core 插件 — kernel + 所有v1.1模块
        'src.core.kernel',
        'src.core.memory_hierarchy',
        'src.core.metacognition',
        'src.core.orchestrator',
        'src.core.predictor',
        'src.core.agent_loop',
        'src.core.performance',
        'src.core.healer',
        'src.core.websocket_plugin',
        'src.core.hotreload',
        'src.core.webhook',
        # v1.1 脑启发模块
        'src.core.free_energy',
        'src.core.active_inference',
        'src.core.global_workspace',
        'src.core.homeostasis',
        # src 顶层模块 (全部列出)
        'src.config',
        'src.model_registry',
        'src.model_adapter',
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
        'src.intent_parser',
        'src.hermes_catalog',
        'src.context_portal',
        # 第三方依赖
        'yaml',
        'openai',
        'httpx',
        'fastapi',
        'uvicorn',
        'pydantic',
        'jinja2',
        'Crypto',
        'Crypto.Cipher',
        'Crypto.Cipher.AES',
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
    icon=None
)
