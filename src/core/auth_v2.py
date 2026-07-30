"""
meshctx v2 认证模块 — API Key + Session 双通道
替换 main.py 中 L376-L453 的旧认证代码

设计:
- 管理员通过 Web UI 密码登录 → session cookie → 全部权限
- 外部用户/Agent 通过 Authorization: Bearer <key> → 按权限访问
- 白名单路径无需认证 (health, login, static, docs)
"""

import os
import hashlib
import secrets
import time
import yaml
from pathlib import Path
from typing import Dict, Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
import logging
logger = logging.getLogger(__name__)

# ── 配置加载 ────────────────────────────────────────────

_AUTH_PASSWORD=os.environ.get("MESHCTX_PASSWORD", "")
_AUTH_SECRET=os.environ.get("MESHCTX_SECRET", secrets.token_hex(32))
# 安全修复: 默认启用认证，除非显式禁用
_AUTH_ENABLED = os.environ.get("MESHCTX_AUTH_DISABLED", "").lower() not in ("1", "true", "yes")
if not _AUTH_PASSWORD and _AUTH_ENABLED:
    logger.warning("MESHCTX_PASSWORD 未设置，认证已启用但无密码！请设置 MESHCTX_PASSWORD 或 MESHCTX_AUTH_DISABLED=1 禁用认证")

# API Key 存储路径
_API_KEYS_PATH = Path.home() / ".meshctx" / "api_keys.yaml"

# 白名单 — 无需认证
_AUTH_WHITELIST = {
    "/", "/health", "/api/health", "/api/version",
    "/api/auth/login", "/api/auth/logout", "/ui/login",
    "/favicon.ico", "/install.sh", "/install.bat",
    "/dashboard/live", "/docs", "/openapi.json", "/redoc",
}
_AUTH_WHITELIST_PREFIXES = ("/static/", "/ws/")

# ── API Key 存储 ─────────────────────────────────────────

def _load_api_keys() -> Dict:
    """加载 API Keys，返回 {key_hash: {name, permissions, created_at}}"""
    if _API_KEYS_PATH.exists():
        with open(_API_KEYS_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

def _save_api_keys(keys: Dict):
    """持久化 API Keys"""
    _API_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_API_KEYS_PATH, "w") as f:
        yaml.dump(keys, f, allow_unicode=True, default_flow_style=False)

# 启动时加载
_api_keys = _load_api_keys()

# ── 密码哈希 ─────────────────────────────────────────────

def _hash_session() -> str:
    return hashlib.sha256(f"{_AUTH_PASSWORD}:{_AUTH_SECRET}".encode()).hexdigest()

def _hash_api_key(key: str) -> str:
    """对 API key 做单向哈希存储"""
    return hashlib.sha256(key.encode()).hexdigest()

# ── 权限检查 ─────────────────────────────────────────────

# 权限 → 路径前缀映射
_PERMISSION_ROUTES = {
    "sandbox":    ["/api/sandbox/"],
    "file:read":  ["/api/file/read", "/api/file/list", "/api/file/tree"],
    "file:write": ["/api/file/write", "/api/file/delete", "/api/file/move",
                   "/api/file/mkdir", "/api/file/upload"],
    "api":        ["/api/"],  # 通用 API（providers, config 等）
}

def _check_permission(permissions: list, path: str) -> bool:
    """检查是否有权限访问该路径"""
    for perm in permissions:
        for prefix in _PERMISSION_ROUTES.get(perm, []):
            if path.startswith(prefix):
                return True
    return False

# ── 认证中间件 ───────────────────────────────────────────

def _is_public(path: str) -> bool:
    """判断路径是否为公开访问"""
    if path in _AUTH_WHITELIST:
        return True
    for prefix in _AUTH_WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True
    return False

async def _authenticate(request: Request):
    """
    认证请求，返回 (identity, is_admin)
    - API Key: identity = key_name, is_admin = False
    - Session: identity = "admin", is_admin = True
    - 未认证: 返回 None
    """
    # 1. 先检查 Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        key_hash = _hash_api_key(token)
        key_info = _api_keys.get(key_hash)
        if key_info:
            return key_info["name"], False  # API key 用户，非管理员

    # 2. 再检查 session cookie
    session = request.cookies.get("meshctx_session", "")
    if session and session == _hash_session():
        return "admin", True  # 管理员

    return None, False


async def auth_middleware_v2(request: Request, call_next):
    """统一认证中间件 — 替换旧 auth_middleware"""
    path = request.url.path

    # 公开路径直接放行
    if _is_public(path):
        return await call_next(request)

    if not _AUTH_ENABLED:
        return await call_next(request)

    identity, is_admin = await _authenticate(request)

    if identity is None:
        # 未认证 — API 返回 401，UI 重定向到登录
        if path.startswith("/api/"):
            return JSONResponse({"detail": "请提供 API Key 或登录"}, status_code=401)
        return RedirectResponse(url=f"/ui/login?next={path}", status_code=302)

    # 管理员全通
    if is_admin:
        request.state.identity = "admin"
        request.state.is_admin = True
        return await call_next(request)

    # API Key 用户 — 权限检查
    key_hash = _hash_api_key(request.headers.get("Authorization", "")[7:].strip())
    key_info = _api_keys.get(key_hash, {})
    permissions = key_info.get("permissions", [])

    if not _check_permission(permissions, path):
        return JSONResponse(
            {"detail": f"权限不足，你的权限: {permissions}"}, status_code=403
        )

    request.state.identity = identity
    request.state.is_admin = False
    return await call_next(request)


# ── Web UI 登录页 ─────────────────────────────────────────

LOGIN_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>MeshCtx Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:40px;width:360px;text-align:center}
h1{color:#e0e4f0;margin-bottom:8px}
p{color:#8090b0;font-size:14px;margin-bottom:24px}
input{width:100%;padding:12px;border:1px solid rgba(255,255,255,0.12);border-radius:8px;background:rgba(0,0,0,0.3);color:#e0e4f0;font-size:16px;margin-bottom:16px;outline:none}
input:focus{border-color:#6c5ce7}
button{width:100%;padding:12px;background:linear-gradient(135deg,#6c5ce7,#5a4bd1);border:none;border-radius:8px;color:#fff;font-size:16px;cursor:pointer}
.error{color:#f85149;font-size:13px;margin-top:8px;display:none}
</style></head><body>
<div class="card">
<h1>🔐 MeshCtx</h1><p>请输入管理密码</p>
<form onsubmit="login(event)">
<input type="password" id="pw" placeholder="密码" autofocus>
<button type="submit">登 录</button>
<div class="error" id="err">密码错误</div>
</form>
</div>
<script>
async function login(e){e.preventDefault();
var pw=document.getElementById('pw').value;
var r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
if(r.ok){location.href='""" + "/ui/chat" + """'}else{document.getElementById('err').style.display='block'}}
</script></div></body></html>"""


# ── API 路由 ─────────────────────────────────────────────

def register_auth_routes(app):
    """注册认证相关路由（需要在 main.py 中调用）"""

    @app.get("/ui/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return HTMLResponse(content=LOGIN_HTML)

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        try: body = await request.json()
        except Exception:
            logger.debug("auth error", exc_info=True)
            raise HTTPException(400)
        password = body.get("password", "")
        if password == _AUTH_PASSWORD:
            resp = JSONResponse({"status": "ok", "role": "admin"})
            resp.set_cookie("meshctx_session", _hash_session(),
                          httponly=True, max_age=86400, samesite="lax")
            return resp
        raise HTTPException(401, "密码错误")

    @app.post("/api/auth/logout")
    async def auth_logout():
        resp = JSONResponse({"status": "ok"})
        resp.delete_cookie("meshctx_session")
        return resp

    # ── API Key 管理（仅管理员）───────────────────────────

    def _require_admin(request: Request):
        """验证管理员身份"""
        session = request.cookies.get("meshctx_session", "")
        if not session or session != _hash_session():
            raise HTTPException(403, "仅管理员可管理 API Keys")

    @app.get("/api/auth/keys")
    async def list_keys(request: Request):
        """列出所有 API Keys（不返回原始 key）"""
        _require_admin(request)
        keys = _load_api_keys()
        result = {}
        for kh, info in keys.items():
            result[kh[:12]] = {  # 只返回哈希前缀作为 ID
                "name": info.get("name", ""),
                "permissions": info.get("permissions", []),
                "created_at": info.get("created_at", ""),
            }
        return {"keys": result}

    @app.post("/api/auth/keys")
    async def create_key(request: Request):
        """创建新 API Key → 返回完整 key（仅此一次）"""
        _require_admin(request)
        try: body = await request.json()
        except Exception:
            logger.debug("auth error", exc_info=True)
            raise HTTPException(400)

        name = body.get("name", "unnamed")
        permissions = body.get("permissions", ["api"])

        # 验证权限名
        valid_perms = set(_PERMISSION_ROUTES.keys())
        for p in permissions:
            if p not in valid_perms:
                raise HTTPException(400, f"无效权限: {p}，可选: {list(valid_perms)}")

        # 生成 key
        raw_key = "mctx-" + secrets.token_hex(24)  # mctx- + 48 hex chars
        key_hash = _hash_api_key(raw_key)

        keys = _load_api_keys()
        keys[key_hash] = {
            "name": name,
            "permissions": permissions,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_api_keys(keys)

        # 刷新内存缓存
        global _api_keys
        _api_keys = keys

        logger.info(f"🔑 创建 API Key: {name} (权限: {permissions})")
        return {
            "status": "ok",
            "key": raw_key,       # ⚠️ 仅此一次返回完整 key
            "name": name,
            "permissions": permissions,
            "usage": f'curl -H "Authorization: Bearer {raw_key}" http://...',
        }

    @app.delete("/api/auth/keys/{key_prefix}")
    async def revoke_key(request: Request, key_prefix: str):
        """撤销 API Key（传入 key 的前12位哈希前缀）"""
        _require_admin(request)
        keys = _load_api_keys()

        # 按前缀匹配
        matched = [kh for kh in keys if kh.startswith(key_prefix)]
        if not matched:
            raise HTTPException(404, "未找到该 Key")

        name = keys[matched[0]]["name"]
        del keys[matched[0]]
        _save_api_keys(keys)

        global _api_keys
        _api_keys = keys

        logger.info(f"🔑 撤销 API Key: {name}")
        return {"status": "ok", "revoked": name}


# ── 启动日志 ─────────────────────────────────────────────

if _AUTH_ENABLED:
    key_count = len(_api_keys)
    logger.info(f"🔐 认证已启用 — 管理员密码 + {key_count} 个 API Key")
else:
    logger.warning("⚠️ 未设置 MESHCTX_PASSWORD，认证已禁用")
