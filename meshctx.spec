# meshctx Windows 打包配置 — 修复版 (parent package问题)
# pip install pyinstaller && pyinstaller meshctx.spec

# -*- mode: python ; coding: utf-8 -*-
import sys, os
from pathlib import Path

_here = os.getcwd()
if 'SPECPATH' in dir():
    for _cand in (os.path.abspath(SPECPATH), os.path.dirname(os.path.abspath(SPECPATH))):
        if os.path.isdir(os.path.join(_cand, 'src', 'core')):
            _here = _cand
            break

# ═══════════════ 闭源核心模块枚举 (004 审计, 2026-08-23) ═══════════════
# 根因: collect_submodules('src.core') 在 CI 隔离子进程静默返回 0 → 发布 STUB 降级包。
# 修复: 构建期从磁盘递归枚举 src/core/*.py 生成显式 hiddenimports (确定性, 不依赖环境)。
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

_core_mods = _enumerate_core_modules(_here)
if not _core_mods:
    raise SystemExit("FAIL: src/core 无模块 — 闭源核心未落地, 禁止发布 stub 资产")

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
        ('src/*.py', 'src'),
        ('src/i18n_translations.json', 'src'),
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=_core_mods + [
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
        'fastapi.middleware', 'fastapi.middleware.cors',
        'fastapi.staticfiles', 'fastapi.responses',
        'uvicorn',
        'pydantic',
        'jinja2',
        'Crypto',
        'Crypto.Cipher',
        'Crypto.Cipher.AES',
        'cryptography',
        'cryptography.fernet',
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
    [],
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='meshctx',
)
