"""
meshctx Web UI v2 — Modular Web Interface

v3.115.31: Refactored from 5693-line monolithic web_ui.py
- 2-entry layout (Chat + Projects) + Gear (Settings modal)
- Dev panel hidden behind Ctrl+Shift+D
- History moved to Chat sidebar
- Responsive CSS (mobile-first)
- All templates embedded in web_ui.py's _TEMPLATES dict for zero-config deployment

Imports from web_ui.py for backward compatibility:
    from src.web_ui import router, _TEMPLATES, _render
"""

# v2 routes are defined in web_ui.py alongside legacy routes
# This package provides the module structure and doc references
# Actual templates live in web_ui.py:TEMPLATES (DictLoader compatible)

from src.web_ui import router

__all__ = ["router"]
