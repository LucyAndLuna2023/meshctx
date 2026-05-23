# -*- mode: python ; coding: utf-8 -*-
"""MeshCtx Desktop — PyInstaller spec v2.41 FULL"""
import sys, os
from PyInstaller.utils.hooks import collect_submodules
_here = os.path.dirname(os.path.abspath(SPECPATH)) if 'SPECPATH' in globals() else os.path.dirname(os.path.abspath(__file__))
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
        # 显式列出所有核心模块 (防PyInstaller try/except漏掉)
        'src.core.metacognition', 'src.core.memory_hierarchy',
        'src.core.orchestrator', 'src.core.predictor', 'src.core.agent_loop',
        'src.core.performance', 'src.core.healer', 'src.core.kernel',
        'src.core.websocket_plugin', 'src.core.free_energy', 'src.core.active_inference',
        'src.core.global_workspace', 'src.core.homeostasis', 'src.core.hybrid_reasoning',
        'src.core.super_brain', 'src.core.sandbox', 'src.core.project_indexer',
        'src.core.online_learning', 'src.core.platform_fs', 'src.core.crypto',
        'src.core.feishu_notify', 'src.core.win_admin', 'src.core.model_compare',
        'src.core.conversation_store', 'src.core.code_reviewer', 'src.core.agent_monitor',
        'src.core.plugin_autoload', 'src.core.agent_tasks', 'src.core.realtime_push',
        'src.core.auto_update', 'src.core.multi_notify', 'src.core.versioned_memory',
        'src.core.workspace_manager', 'src.core.telegram_router', 'src.core.principle_extractor',
        'src.core.pre_action_check', 'src.core.action_gate', 'src.core.attention_decay',
        'src.core.cognitive_health', 'src.core.learn_loop', 'src.core.profile_manager',
        'src.core.approval', 'src.core.secret_scanner', 'src.core.progressive_context',
        'src.core.session_identity', 'src.core.llm_quality', 'src.core.acp_server',
        'src.core.checkpoint', 'src.core.image_gen', 'src.core.credential_pool',
        'src.core.usage_insights', 'src.core.gateway_connectors', 'src.core.human_memory',
        'src.core.autonomous_engine', 'src.core.diff_preview', 'src.core.task_progress',
        'src.core.sdb_framework', 'src.core.self_modify', 'src.core.brain_validator',
        'src.core.gateway_llm', 'src.core.unified_loop', 'src.core.attractor_reasoner',
        'src.core.dashboard', 'src.core.auto_healer', 'src.core.performance_optimizer',
        'src.core.hotreload', 'src.core.plugin_manifest', 'src.core.session_archiver',
        'src.core.hooks_engine', 'src.core.agent_teams', 'src.core.augmented_memory',
        'src.core.cache', 'src.core.context_compressor', 'src.core.voice_io',
        'src.core.watchdog', 'src.core.webhook', 'src.core.memory_v2',
        'src.core.memory_engine', 'src.core.cross_platform_engine',
        # v2.50-v2.76 新模块
        'src.core.knowledge_transfer', 'src.core.breakthrough_memory',
        'src.core.predictive_precompute', 'src.core.auto_tuner',
        'src.core.agent_benchmark', 'src.core.smart_router',
        'src.core.autonomous_bugfix', 'src.core.regression_shield',
        'src.core.memory_health', 'src.core.plugin_market',
        'src.core.error_learner', 'src.core.goal_decomposer',
        'src.core.backup_vault', 'src.core.version_guard',
        'src.core.context_restorer', 'src.core.self_updater',
        'src.core.prompt_shield', 'src.core.cross_validator',
        'src.core.behavior_monitor', 'src.core.workflow_engine',
        'src.core.info_geo_router',
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
    console=True, icon='logo.ico',
    version=os.path.join(_here, 'version_info.txt'))

if sys.platform == 'darwin':
    app = BUNDLE(exe, name='meshctx-desktop.app', icon='logo.icns',
        bundle_identifier='com.meshctx.desktop',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': '2.76.0',
            'CFBundleVersion': '2.76.0',
        }, version=os.path.join(_here, 'version_info.txt'))
