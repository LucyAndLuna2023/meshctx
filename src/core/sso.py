#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSO/SAML — Enterprise 单点登录 (OIDC 兼容骨架, 2026-08-28)

设计:
- MESHCTX_SSO_ISSUER / MESHCTX_SSO_CLIENT_ID / MESHCTX_SSO_CLIENT_SECRET 配置 OIDC IdP
- /api/sso/authorize: 重定向 IdP 授权
- /api/sso/callback: code 换 token → JWT 验证 → 返回用户身份
- 未配置 (自托管/开发): dev 模拟模式, 返回测试身份

JWT 验证: 纯标准库 (base64url + HMAC-SHA256), 无第三方依赖。
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("meshctx.sso")

SSO_ISSUER = os.environ.get("MESHCTX_SSO_ISSUER", "")       # 如 https://accounts.google.com
SSO_CLIENT_ID = os.environ.get("MESHCTX_SSO_CLIENT_ID", "")
SSO_CLIENT_SECRET = os.environ.get("MESHCTX_SSO_CLIENT_SECRET", "")
SSO_REDIRECT = os.environ.get("MESHCTX_SSO_REDIRECT", "/api/sso/callback")


def sso_enabled() -> bool:
    return bool(SSO_ISSUER and SSO_CLIENT_ID)


# ── JWT 工具 (标准库) ─────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def parse_jwt(token: str) -> Optional[Dict[str, Any]]:
    """解析并验证 JWT (HMAC-SHA256 签名, 支持 HS256)。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
        # 签名验证 (HS256, 用 client_secret 或 issuer 派生 key)
        if SSO_CLIENT_SECRET:
            signing_input = f"{parts[0]}.{parts[1]}".encode()
            expected = hmac.new(SSO_CLIENT_SECRET.encode(), signing_input,
                                hashlib.sha256).digest()
            actual = _b64url_decode(parts[2])
            if not hmac.compare_digest(expected, actual):
                logger.warning("JWT 签名不匹配")
                return None
        # 过期检查
        exp = payload.get("exp", 0)
        if exp and exp < time.time():
            logger.warning("JWT 已过期")
            return None
        return payload
    except Exception as e:
        logger.warning(f"JWT 解析失败: {e}")
        return None


def build_authorize_url(state: str) -> str:
    """构造 OIDC 授权 URL。"""
    qs = urlencode({
        "client_id": SSO_CLIENT_ID,
        "redirect_uri": SSO_REDIRECT,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    })
    return f"{SSO_ISSUER}/authorize?{qs}"


def exchange_code(code: str) -> Dict[str, Any]:
    """code 换 token (OIDC token endpoint)。"""
    import requests
    token_url = f"{SSO_ISSUER}/token"
    r = requests.post(token_url, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SSO_REDIRECT,
        "client_id": SSO_CLIENT_ID,
        "client_secret": SSO_CLIENT_SECRET,
    }, timeout=30)
    if r.status_code != 200:
        return {"error": f"token 交换失败: {r.text[:150]}"}
    return r.json()


def get_userinfo_from_token(token_data: Dict[str, Any]) -> Dict[str, Any]:
    """从 id_token 解析用户身份。"""
    id_token = token_data.get("id_token", "")
    payload = parse_jwt(id_token) if id_token else None
    if not payload:
        return {"error": "id_token 缺失或无效"}
    return {
        "sub": payload.get("sub", ""),
        "email": payload.get("email", ""),
        "name": payload.get("name", payload.get("email", "")),
        "verified": payload.get("email_verified", False),
    }


def sso_config() -> Dict[str, Any]:
    """SSO 配置状态 (公开)。"""
    return {
        "enabled": sso_enabled(),
        "issuer": SSO_ISSUER or "",
        "mode": "oidc" if sso_enabled() else "dev-simulated",
        "note": "配置 MESHCTX_SSO_ISSUER/CLIENT_ID/CLIENT_SECRET 启用真实 OIDC; 未配置为 dev 模拟",
    }
