"""meshctx v2 Routes — 2 Entry + Gear UI

Factory pattern: create_v2_routes(render_fn) → APIRouter
Routes live here, rendering lives in web_ui's _render().
No circular import — render_fn is injected at startup.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


def create_v2_routes(render_fn):
    """Create APIRouter with all v2 UI routes.
    
    Args:
        render_fn: _render(template_name, context, request) → HTMLResponse
    """
    router = APIRouter(tags=["Web UI v2"])

    # ── v2 首页: 2 入口 (Chat + Projects) + 齿轮 ──
    @router.get("/v2", response_class=HTMLResponse)
    @router.get("/home", response_class=HTMLResponse)
    async def dashboard_v2(request: Request):
        return render_fn("dashboard_v2.html",
                         {"request": request, "title": "meshctx"}, request)

    # ── v2 Chat 页 (带历史侧栏) ──
    @router.get("/v2/chat", response_class=HTMLResponse)
    async def chat_v2(request: Request):
        return render_fn("chat_v2.html",
                         {"request": request, "title": "Chat — meshctx"}, request)

    # ── v2 Projects 页 ──
    @router.get("/v2/projects", response_class=HTMLResponse)
    async def projects_v2(request: Request):
        return render_fn("projects_v2.html",
                         {"request": request, "title": "Projects — meshctx"}, request)

    # ── v2 设置面板 ──
    @router.get("/v2/settings", response_class=HTMLResponse)
    async def settings_v2(request: Request):
        return render_fn("settings_v2.html",
                         {"request": request, "title": "设置 — meshctx"}, request)

    # ── v2 开发者面板 ──
    @router.get("/v2/dev", response_class=HTMLResponse)
    async def dev_v2(request: Request):
        return render_fn("dev_v2.html",
                         {"request": request, "title": "开发者工具 — meshctx"}, request)

    return router
