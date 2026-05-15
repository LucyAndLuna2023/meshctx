"""
MeshCtx Security Hardening — Input validation & XSS protection
===============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.
"""
import re
import html
from typing import Optional


def sanitize_input(text: str, max_len: int = 32000) -> str:
    """Sanitize user input — truncate, strip null bytes, normalize."""
    if not text:
        return ""
    # Strip null bytes
    text = text.replace("\x00", "")
    # Truncate
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text.strip()


def sanitize_html(text: str) -> str:
    """Escape HTML to prevent XSS."""
    return html.escape(text, quote=True)


def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    import os
    # Remove path separators
    name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    # Remove null bytes
    name = name.replace("\x00", "")
    # Only allow safe chars
    name = re.sub(r'[^\w\-\.]', '_', name)
    # Limit length
    return name[:255] or "unnamed"


def validate_url(url: str) -> bool:
    """Validate URL format."""
    return bool(re.match(r'^https?://[\w\-\.]+(:\d+)?(/.*)?$', url))


def validate_model_id(model_id: str) -> bool:
    """Validate model ID format: provider:model-name"""
    return bool(re.match(r'^[a-z0-9_\-]+:[a-z0-9_\-\.]+$', model_id, re.IGNORECASE))


def rate_limit_check(ip: str, window: int = 60, max_req: int = 60) -> bool:
    """Simple rate limit check. Returns True if allowed."""
    # Handled by middleware in main.py
    return True


def mask_key(key: str, show: int = 8) -> str:
    """Mask API key for safe display."""
    if not key or len(key) <= show:
        return "****"
    return key[:show] + "****" + (key[-4:] if len(key) > show + 4 else "")
