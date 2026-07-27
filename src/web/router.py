"""meshctx Web UI Router

Assembles all route modules into a single APIRouter.
Injected into the FastAPI app by web_ui.py at startup.

Modules:
  routes/v2.py  — v2 UI (2-entry + gear layout)
"""

from fastapi import APIRouter

from .routes.v2 import create_v2_routes


def create_ui_router(render_fn=None):
    """Create the unified UI router with all sub-routers included.

    Args:
        render_fn: _render(template_name, context, request) → HTMLResponse
                   Injected from web_ui.py to avoid circular imports.
                   If None (CLI/docs), router has no v2 routes.
    """
    router = APIRouter(prefix="/ui", tags=["Web UI"])

    if render_fn is not None:
        v2_router = create_v2_routes(render_fn)
        # Include v2 routes at /ui/... (prefix already set above)
        router.include_router(v2_router)

    return router
