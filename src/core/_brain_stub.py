"""
MeshCtx Core Brain — Proprietary Module
=========================================
This is the compiled interface for the 13-region Super Brain Engine.

Source code is NOT included in this open-source distribution.
The proprietary core is distributed separately as:
  pip install meshctx-core

For commercial licensing: license@meshctx.com

Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.
"""

# All brain modules are loaded from the compiled meshctx_core package
# This stub ensures the open-source framework can reference them
# but the actual implementations are in the proprietary core.

import sys

_BRAIN_MODULES = [
    "super_brain",
    "brain_router",
    "free_energy",
    "active_inference",
    "global_workspace",
    "homeostasis",
    "metacognition",
    "hybrid_reasoning",
    "principle_extractor",
    "pre_action_check",
    "action_gate",
    "attention_decay",
]

_available = False

try:
    import meshctx_core
    _available = True
except ImportError:
    pass

if not _available:
    raise ImportError(
        "MeshCtx Core Brain is not installed.\n\n"
        "The Super Brain engine (13 brain regions) is proprietary and distributed separately.\n\n"
        "Install: pip install meshctx-core\n"
        "License: license@meshctx.com\n"
    )
else:
    # Re-export from compiled core
    for mod_name in _BRAIN_MODULES:
        try:
            mod = __import__(f"meshctx_core.{mod_name}", fromlist=["*"])
            for attr in dir(mod):
                if not attr.startswith("_"):
                    globals()[attr] = getattr(mod, attr)
        except ImportError:
            pass
