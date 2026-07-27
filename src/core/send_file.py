"""
meshctx SendFile — Send files to users through messaging platforms
Supports: Telegram, Feishu, Discord, Webhook, CLI
Uses environment variables for tokens. Graceful degradation with clear errors.
"""
import os
import json
import mimetypes
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# ── 路径遍历防护 ──
_ALLOWED_ROOTS = [
    os.path.realpath(os.path.expanduser("~/.meshctx")),
    os.path.realpath(os.path.expanduser("~/.hermes")),
    os.path.realpath("/tmp"),
]

def _safe_open_file(file_path: str, mode: str = "rb"):
    """安全打开文件 — 防止路径遍历攻击"""
    real = os.path.realpath(os.path.expanduser(file_path))
    if not any(real.startswith(root) for root in _ALLOWED_ROOTS):
        raise PermissionError(f"Path traversal blocked: {file_path}")
    return open(real, mode)

# Try to import requests for cleaner HTTP, fall back to stdlib
try:
    import requests as _requests
except ImportError:
    _requests = None


# ──────────────────────────────────────────────
#  Stdlib multipart form-data builder
# ──────────────────────────────────────────────

def _build_multipart_formdata(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body using stdlib email module.
    
    Args:
        fields: dict of {name: value} for text fields.
        files: dict of {name: (filename, file_bytes_or_path, content_type)} for file fields.
               If value is a string, treat as path and read it.
    
    Returns:
        (body_bytes, content_type_header_value)
    """
    msg = MIMEMultipart('form-data')
    
    for name, value in fields.items():
        part = MIMEText(str(value), 'plain', 'utf-8')
        part.add_header('Content-Disposition', 'form-data', name=name)
        msg.attach(part)
    
    for name, file_info in files.items():
        filename, file_data, content_type = file_info
        # Support passing a file path string
        if isinstance(file_data, str):
            with _safe_open_file(file_data) as f:
                file_data = f.read()
        part = MIMEBase(*content_type.split('/', 1))
        part.set_payload(file_data)
        encoders.encode_base64(part)  # safe transport encoding
        part.add_header('Content-Disposition', 'form-data', name=name, filename=filename)
        msg.attach(part)
    
    # The email module uses CRLF line endings by default
    body = msg.as_bytes()
    content_type = msg['Content-Type']  # includes boundary
    return body, content_type


# ──────────────────────────────────────────────
#  Platform senders
# ──────────────────────────────────────────────

def _send_file_cli(file_path: str, caption: Optional[str] = None) -> str:
    """Send file via CLI — print path and stats (always available)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    size = path.stat().st_size
    if size < 1024:
        size_str = f"{size} B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f} KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f} MB"
    print(f"\n{'=' * 50}")
    print(f"📎 File: {path.absolute()}")
    print(f"   Size: {size_str}")
    if caption:
        print(f"   Caption: {caption}")
    print(f"{'=' * 50}")
    return f"CLI: file ready at {path.absolute()}"


def _send_file_telegram(file_path: str, caption: Optional[str] = None, chat_id: Optional[str] = None) -> str:
    """Send file via Telegram Bot API (sendDocument)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID required — pass chat_id or set TELEGRAM_CHAT_ID env var")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError(f"File too large for Telegram (max 50 MB): {file_path}")

    url = f"https://api.telegram.org/bot{token}/sendDocument"

    if _requests is not None:
        with _safe_open_file(file_path) as f:
            files = {'document': (path.name, f)}
            data = {'chat_id': chat_id}
            if caption:
                data['caption'] = caption[:1024]
            resp = _requests.post(url, data=data, files=files, timeout=60)
            resp.raise_for_status()
            result = resp.json()
        if not result.get('ok'):
            raise RuntimeError(f"Telegram API error: {result.get('description', 'unknown')}")
        return f"Telegram: file sent to {chat_id}"

    # stdlib fallback using MIME multipart
    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    fields = {'chat_id': chat_id}
    if caption:
        fields['caption'] = caption[:1024]
    body, content_type = _build_multipart_formdata(
        fields=fields,
        files={'document': (path.name, file_path, mime_type)}
    )

    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    if not result.get('ok'):
        raise RuntimeError(f"Telegram API error: {result.get('description', 'unknown')}")
    return f"Telegram: file sent to {chat_id}"


def _send_file_feishu(file_path: str, caption: Optional[str] = None, chat_id: Optional[str] = None) -> str:
    """Send file via Feishu/Lark IM API (requires app credentials)."""
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    webhook = os.environ.get("FEISHU_WEBHOOK_URL")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not app_id or not app_secret:
        if webhook:
            raise ValueError(
                "Feishu webhook does not support file uploads. "
                "Set FEISHU_APP_ID and FEISHU_APP_SECRET for file sending."
            )
        raise ValueError("Feishu not configured: set FEISHU_APP_ID and FEISHU_APP_SECRET")

    # Step 1: Get tenant access token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    token_req = urllib.request.Request(
        token_url, data=token_data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token_result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Feishu auth HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    if token_result.get('code', -1) != 0:
        raise RuntimeError(f"Feishu auth error: {token_result.get('msg', 'unknown')}")
    access_token = token_result.get("tenant_access_token")
    if not access_token:
        raise RuntimeError("Feishu: no tenant_access_token in auth response")

    # Step 2: Upload file
    upload_url = "https://open.feishu.cn/open-apis/im/v1/files"
    file_name = path.name
    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

    if _requests is not None:
        with _safe_open_file(file_path) as f:
            resp = _requests.post(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}"},
                files={"file": (file_name, f, mime_type)},
                data={"file_type": "stream", "file_name": file_name},
                timeout=120
            )
            resp.raise_for_status()
            result = resp.json()
    else:
        body, content_type = _build_multipart_formdata(
            fields={"file_type": "stream", "file_name": file_name},
            files={"file": (file_name, file_path, mime_type)}
        )
        req = urllib.request.Request(upload_url, data=body)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', content_type)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Feishu upload HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    if result.get('code', -1) != 0:
        raise RuntimeError(f"Feishu upload error: {result.get('msg', 'unknown')}")
    file_key = result.get('data', {}).get('file_key')
    if not file_key:
        raise RuntimeError("Feishu: no file_key in upload response")

    # Step 3: Send message with file attachment
    recipient = chat_id or os.environ.get("FEISHU_CHAT_ID")
    if not recipient:
        raise ValueError("FEISHU_CHAT_ID required — pass chat_id or set FEISHU_CHAT_ID env var")

    msg_content = json.dumps({"file_key": file_key})
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    msg_payload = json.dumps({
        "receive_id": recipient,
        "msg_type": "file",
        "content": msg_content
    }).encode()

    msg_req = urllib.request.Request(
        msg_url, data=msg_payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(msg_req, timeout=10) as resp:
            msg_result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Feishu send HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    if msg_result.get('code', -1) != 0:
        raise RuntimeError(f"Feishu send error: {msg_result.get('msg', 'unknown')}")
    return f"Feishu: file sent to {recipient}"


def _send_file_discord(file_path: str, caption: Optional[str] = None) -> str:
    """Send file via Discord webhook."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL not set")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError(f"File too large for Discord (max 25 MB): {file_path}")

    if _requests is not None:
        with _safe_open_file(file_path) as f:
            files = {'file': (path.name, f)}
            data = {}
            if caption:
                data['content'] = caption
            resp = _requests.post(webhook_url, data=data, files=files, timeout=60)
            resp.raise_for_status()
        return "Discord: file sent via webhook"

    # stdlib fallback
    fields = {}
    if caption:
        fields['content'] = caption
    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    body, content_type = _build_multipart_formdata(
        fields=fields,
        files={'file': (path.name, file_path, mime_type)}
    )
    req = urllib.request.Request(webhook_url, data=body)
    req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()  # consume response
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Discord HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    return "Discord: file sent via webhook"


def _send_file_webhook(file_path: str, caption: Optional[str] = None, webhook_url: Optional[str] = None) -> str:
    """Send file via generic webhook URL."""
    url = webhook_url or os.environ.get("WEBHOOK_URL")
    if not url:
        raise ValueError("WEBHOOK_URL not set — pass webhook_url or set WEBHOOK_URL env var")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if _requests is not None:
        with _safe_open_file(file_path) as f:
            files = {'file': (path.name, f)}
            data = {}
            if caption:
                data['caption'] = caption
            resp = _requests.post(url, data=data, files=files, timeout=60)
            resp.raise_for_status()
        return f"Webhook: file sent to {url[:50]}..."

    # stdlib fallback
    fields = {}
    if caption:
        fields['caption'] = caption
    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    body, content_type = _build_multipart_formdata(
        fields=fields,
        files={'file': (path.name, file_path, mime_type)}
    )
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Webhook HTTP {e.code}: {e.read().decode(errors='replace')}") from e

    return f"Webhook: file sent to {url[:50]}..."


# ──────────────────────────────────────────────
#  Platform registry (auto-detection order)
# ──────────────────────────────────────────────

_PLATFORM_SENDERS = [
    ("telegram", _send_file_telegram),
    ("feishu", _send_file_feishu),
    ("discord", _send_file_discord),
    ("webhook", _send_file_webhook),
    ("cli", _send_file_cli),
]

_PLATFORM_NAMES = [name for name, _ in _PLATFORM_SENDERS]


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────

def send_file(file_path: str, platform: str = "auto", caption: Optional[str] = None) -> str:
    """Send a file through available messaging platforms.

    In auto mode, platforms are tried in order: telegram, feishu, discord,
    webhook, cli.  The first successfully configured platform is used.
    If a platform raises a runtime error the next one is tried; CLI is the
    guaranteed fallback and always works (it prints the path to stdout).

    Args:
        file_path: Path to the file to send.
        platform: 'auto' (default) or a specific platform name:
                  'telegram', 'feishu', 'discord', 'webhook', 'cli'.
        caption: Optional caption / description for the file.

    Returns:
        Human-readable success message (e.g. "Telegram: file sent to 123456").

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        RuntimeError: If *platform* is 'auto' and every platform fails.
        ValueError: If *platform* is an unrecognised name.
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if platform == "auto":
        errors = []
        for plat_name, sender in _PLATFORM_SENDERS:
            try:
                return sender(file_path, caption=caption)
            except Exception as e:
                errors.append(f"{plat_name}: {e}")
        raise RuntimeError(
            "Failed to send file via any platform:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    # Specific platform
    plat_lower = platform.lower()
    for plat_name, sender in _PLATFORM_SENDERS:
        if plat_name == plat_lower:
            return sender(file_path, caption=caption)

    raise ValueError(
        f"Unknown platform: '{platform}'. "
        f"Available: {', '.join(_PLATFORM_NAMES)}"
    )


def send_file_to_channel(file_path: str, channel_id: str, caption: Optional[str] = None) -> str:
    """Send a file to a specific channel / chat.

    Tries Telegram first (using *channel_id* as the chat_id), then Feishu
    (using *channel_id* as the chat_id), then falls back to CLI.

    Required env vars:
        Telegram: TELEGRAM_BOT_TOKEN
        Feishu:   FEISHU_APP_ID + FEISHU_APP_SECRET

    Args:
        file_path: Path to the file to send.
        channel_id: Target channel / chat identifier.
        caption: Optional caption for the file.

    Returns:
        Human-readable success message.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        RuntimeError: If all delivery attempts fail.
    """
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    errors = []

    # ── Telegram ──
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        try:
            return _send_file_telegram(file_path, caption=caption, chat_id=channel_id)
        except Exception as e:
            errors.append(f"telegram: {e}")
    else:
        errors.append("telegram: TELEGRAM_BOT_TOKEN not set")

    # ── Feishu ──
    app_id = os.environ.get("FEISHU_APP_ID")
    if app_id:
        try:
            return _send_file_feishu(file_path, caption=caption, chat_id=channel_id)
        except Exception as e:
            errors.append(f"feishu: {e}")
    else:
        errors.append("feishu: FEISHU_APP_ID not set")

    # ── CLI (guaranteed) ──
    try:
        return _send_file_cli(file_path, caption=caption)
    except Exception as e:
        errors.append(f"cli: {e}")

    raise RuntimeError(
        f"Failed to send file to channel '{channel_id}':\n" +
        "\n".join(f"  - {e}" for e in errors)
    )
