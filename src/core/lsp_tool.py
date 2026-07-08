"""
Language Server Protocol Tool — Code Intelligence
==================================================
Real LSP client using JSON-RPC 2.0 over subprocess stdin/stdout.

Supported languages:
  - python    → pylsp (python-lsp-server)
  - typescript → typescript-language-server
  - rust      → rust-analyzer

Lifecycle: lsp_start → auto-initialize → didOpen → queries → lsp_stop → shutdown/exit
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
#  Language → server command mapping
# ────────────────────────────────────────────────

LANGUAGE_SERVERS: Dict[str, List[str]] = {
    "python": ["pylsp"],
    "typescript": ["typescript-language-server", "--stdio"],
    "rust": ["rust-analyzer"],
}

# File extensions that map to language for auto-detection
EXT_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".mjs": "typescript",
    ".cjs": "typescript",
    ".rs": "rust",
}

# ────────────────────────────────────────────────
#  JSON-RPC 2.0 message helpers
# ────────────────────────────────────────────────

def _jsonrpc_request(method: str, params: Any, req_id: int) -> bytes:
    """Build a JSON-RPC 2.0 request message with Content-Length framing."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }, ensure_ascii=False)
    return _frame(body)


def _jsonrpc_notification(method: str, params: Any) -> bytes:
    """Build a JSON-RPC 2.0 notification (no id)."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }, ensure_ascii=False)
    return _frame(body)


def _frame(body: str) -> bytes:
    """Wrap a JSON body with LSP Content-Length header."""
    encoded = body.encode("utf-8")
    header = f"Content-Length: {len(encoded)}\r\n\r\n"
    return header.encode("utf-8") + encoded


def _parse_message(data: bytes) -> Optional[Tuple[Optional[Dict], int]]:
    """
    Parse one LSP message from a byte buffer.
    Returns (parsed_dict_or_None, bytes_consumed) or None if incomplete/malformed.
    Handles Content-Length framing per LSP spec.
    """
    header_end = data.find(b"\r\n\r\n")
    if header_end == -1:
        return None  # header not complete

    header_text = data[:header_end].decode("utf-8", errors="replace")
    content_length = None
    for line in header_text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            break

    if content_length is None:
        logger.warning("LSP message without Content-Length header, discarding")
        # Try to recover: treat everything after header as body, up to a JSON boundary
        body_start = header_end + 4
        remaining = data[body_start:]
        # Find a complete JSON object
        try:
            body = remaining.decode("utf-8", errors="replace")
            decoder = json.JSONDecoder()
            obj, idx = decoder.raw_decode(body)
            return obj, body_start + idx
        except json.JSONDecodeError:
            return None

    body_start = header_end + 4
    if len(data) < body_start + content_length:
        return None  # body not complete

    body_bytes = data[body_start:body_start + content_length]
    body_text = body_bytes.decode("utf-8", errors="replace")
    try:
        obj = json.loads(body_text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to decode LSP body: {e}")
        # Advance past this malformed message
        return None, body_start + content_length

    if obj is None:
        return None, body_start + content_length
    return obj, body_start + content_length


# ────────────────────────────────────────────────
#  LSP Client — manages one language server
# ────────────────────────────────────────────────

@dataclass
class LSPClient:
    """Manages a single LSP server process and its JSON-RPC communication."""

    language: str
    root_path: str
    cmd: List[str]

    # Internal state
    process: Optional[subprocess.Popen] = None
    _request_id: int = field(default=0, init=False)
    _pending: Dict[int, threading.Event] = field(default_factory=dict, init=False)
    _responses: Dict[int, Any] = field(default_factory=dict, init=False)
    _diagnostics: Dict[str, List[Dict]] = field(default_factory=dict, init=False)
    _reader_thread: Optional[threading.Thread] = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _running: bool = field(default=False, init=False)
    _initialized: bool = field(default=False, init=False)
    _buffer: bytes = field(default=b"", init=False)
    _open_files: set = field(default_factory=set, init=False)

    def start(self, **kw) -> bool:
        """Spawn the LSP server and perform initialize handshake."""
        if self._running:
            logger.warning(f"LSP server for {self.language} already running")
            return True

        logger.info(f"Starting LSP server: {' '.join(self.cmd)} (root={self.root_path})")
        try:
            self.process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.root_path or os.getcwd(),
            )
        except FileNotFoundError:
            logger.error(f"LSP server binary not found: {self.cmd[0]!r}. "
                         f"Install it with: pip install python-lsp-server (python), "
                         f"npm i -g typescript-language-server (ts), "
                         f"rustup component add rust-analyzer (rust)")
            return False
        except Exception as e:
            logger.error(f"Failed to spawn LSP server: {e}")
            return False

        self._running = True
        self._buffer = b""

        # Start reader thread
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # Initialize handshake
        init_result = self._call("initialize", {
            "processId": os.getpid(),
            "rootUri": Path(self.root_path).resolve().as_uri(),
            "rootPath": self.root_path,
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "hover": {
                        "dynamicRegistration": True,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "publishDiagnostics": {"relatedInformation": True},
                    "synchronization": {
                        "dynamicRegistration": True,
                        "didSave": True,
                    },
                },
                "workspace": {
                    "configuration": True,
                },
            },
            "initializationOptions": {},
            "workspaceFolders": [
                {"uri": Path(self.root_path).resolve().as_uri(), "name": self.root_path}
            ],
            "trace": "off",
        }, timeout=15.0)

        if init_result is None:
            logger.error(f"LSP initialize timed out for {self.language}")
            self.stop()
            return False

        # Send initialized notification
        self._notify("initialized", {})
        self._initialized = True
        logger.info(f"LSP server for {self.language} initialized successfully")
        return True

    def stop(self, **kw) -> None:
        """Shutdown the LSP server gracefully."""
        if not self._running:
            return

        logger.info(f"Stopping LSP server for {self.language}")
        try:
            self._call("shutdown", {}, timeout=5.0)
            self._notify("exit", {})
        except Exception:
            pass

        self._running = False

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stderr:
                    self.process.stderr.close()
                self.process.wait(timeout=5.0)
            except (subprocess.TimeoutExpired, BrokenPipeError, OSError):
                try:
                    self.process.kill()
                    self.process.wait(timeout=3.0)
                except Exception:
                    pass

        self._initialized = False
        self._open_files.clear()
        self._diagnostics.clear()
        logger.info(f"LSP server for {self.language} stopped")

    def _ensure_open(self, file_path: str, **kw) -> None:
        """Send textDocument/didOpen if not already sent for this file."""
        if file_path in self._open_files:
            return
        abs_path = os.path.abspath(file_path)
        uri = Path(abs_path).resolve().as_uri()

        # Try to read file content for languageId
        language_id = _detect_language(abs_path)
        content = ""
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            pass

        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": content,
            },
        })
        self._open_files.add(file_path)

    def _file_uri(self, file_path: str, **kw) -> str:
        return Path(os.path.abspath(file_path)).resolve().as_uri()

    # ── Public query API ──

    def definition(self, file_path: str, line: int, col: int, **kw) -> List[Dict]:
        """Go-to-definition. Returns list of Location dicts."""
        self._ensure_open(file_path)
        result = self._call("textDocument/definition", {
            "textDocument": {"uri": self._file_uri(file_path)},
            "position": {"line": line, "character": col},
        }, timeout=10.0)
        return _normalize_locations(result)

    def references(self, file_path: str, line: int, col: int, **kw) -> List[Dict]:
        """Find references. Returns list of Location dicts."""
        self._ensure_open(file_path)
        result = self._call("textDocument/references", {
            "textDocument": {"uri": self._file_uri(file_path)},
            "position": {"line": line, "character": col},
            "context": {"includeDeclaration": True},
        }, timeout=10.0)
        return _normalize_locations(result)

    def hover(self, file_path: str, line: int, col: int, **kw) -> Optional[str]:
        """Hover info. Returns markdown/plaintext string or None."""
        self._ensure_open(file_path)
        result = self._call("textDocument/hover", {
            "textDocument": {"uri": self._file_uri(file_path)},
            "position": {"line": line, "character": col},
        }, timeout=10.0)

        if result is None:
            return None

        contents = result.get("contents")
        if contents is None:
            return None

        if isinstance(contents, str):
            return contents

        if isinstance(contents, dict):
            # MarkupContent: {kind: "markdown"|"plaintext", value: "..."}
            return contents.get("value", str(contents))

        if isinstance(contents, list):
            # List of MarkedString or MarkupContent
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("value", ""))
            return "\n\n".join(parts)

        return str(contents)

    def diagnostics(self, file_path: str, **kw) -> List[Dict]:
        """Get diagnostics (errors/warnings) for a file.
        Returns cached diagnostics from publishDiagnostics notifications.
        """
        uri = self._file_uri(file_path)
        return self._diagnostics.get(uri, [])

    # ── Internal communication ──

    def _next_id(self, **kw) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _call(self, method: str, params: Any, timeout: float = 10.0, **kw) -> Optional[Any]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._running or self.process is None or self.process.stdin is None:
            logger.warning(f"Cannot call {method}: server not running")
            return None

        req_id = self._next_id()
        event = threading.Event()
        with self._lock:
            self._pending[req_id] = event

        try:
            msg = _jsonrpc_request(method, params, req_id)
            with self._lock:
                try:
                    self.process.stdin.write(msg)
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError) as e:
                    logger.error(f"Write to LSP server failed: {e}")
                    return None

            if not event.wait(timeout=timeout):
                logger.warning(f"LSP request {method} (id={req_id}) timed out")
                with self._lock:
                    self._pending.pop(req_id, None)
                return None

            with self._lock:
                result = self._responses.pop(req_id, None)

            if result is not None and "error" in result:
                err = result["error"]
                logger.warning(f"LSP error from {method}: {err.get('message', str(err))}")
                return None

            return result.get("result") if result else None

        finally:
            with self._lock:
                self._pending.pop(req_id, None)
                self._responses.pop(req_id, None)

    def _notify(self, method: str, params: Any, **kw) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._running or self.process is None or self.process.stdin is None:
            return
        try:
            msg = _jsonrpc_notification(method, params)
            with self._lock:
                self.process.stdin.write(msg)
                self.process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning(f"Notify {method} failed: {e}")

    def _reader_loop(self, **kw) -> None:
        """Background thread that reads JSON-RPC messages from the server stdout."""
        assert self.process and self.process.stdout
        while self._running:
            try:
                # Read in chunks
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    # Process exited
                    logger.info(f"LSP server {self.language} stdout closed")
                    self._running = False
                    break

                with self._lock:
                    self._buffer += chunk

                # Parse as many complete messages as possible
                while True:
                    parsed = _parse_message(self._buffer)
                    if parsed is None:
                        break
                    msg, consumed = parsed
                    if consumed > 0:
                        with self._lock:
                            self._buffer = self._buffer[consumed:]
                    else:
                        # Couldn't parse, just keep buffering
                        break

                    if msg is None:
                        continue

                    self._handle_message(msg)

            except (OSError, ValueError) as e:
                logger.error(f"LSP reader error for {self.language}: {e}")
                self._running = False
                break
            except Exception:
                logger.exception(f"Unexpected error in LSP reader for {self.language}")
                self._running = False
                break

    def _handle_message(self, msg: Dict, **kw) -> None:
        """Dispatch a received JSON-RPC message."""
        if "method" in msg:
            # Server → client notification or request
            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "textDocument/publishDiagnostics":
                uri = params.get("uri", "")
                diags = params.get("diagnostics", [])
                with self._lock:
                    self._diagnostics[uri] = diags
                logger.debug(f"Received {len(diags)} diagnostics for {uri}")

            elif method == "window/logMessage":
                level = params.get("type", 4)
                message = params.get("message", "")
                if level == 1:  # Error
                    logger.error(f"LSP [{self.language}]: {message}")
                elif level == 2:  # Warning
                    logger.warning(f"LSP [{self.language}]: {message}")
                else:
                    logger.info(f"LSP [{self.language}]: {message}")

            elif method == "window/showMessage":
                logger.info(f"LSP showMessage [{self.language}]: {params.get('message', '')}")

            elif method == "client/registerCapability":
                # Acknowledge silently
                pass

            else:
                logger.debug(f"Unhandled LSP notification: {method}")

            # If it's a request (has id), respond with null to avoid hang
            if "id" in msg:
                req_id = msg["id"]
                self._notify_cancel(req_id)

        elif "id" in msg:
            # Response to one of our requests
            req_id = msg["id"]
            with self._lock:
                self._responses[req_id] = msg
                event = self._pending.get(req_id)
                if event:
                    event.set()

    def _notify_cancel(self, req_id: Any, **kw) -> None:
        """Respond to an unsupported server request."""
        resp_body = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": None,
        })
        framed = _frame(resp_body)
        try:
            if self.process and self.process.stdin:
                with self._lock:
                    self.process.stdin.write(framed)
                    self.process.stdin.flush()
        except Exception:
            pass


# ────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────

def _detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return EXT_TO_LANGUAGE.get(suffix, "plaintext")


def _normalize_locations(result: Any) -> List[Dict]:
    """Convert various LSP location result shapes to a uniform list of dicts."""
    if result is None:
        return []
    if isinstance(result, list):
        out = []
        for loc in result:
            if isinstance(loc, dict):
                uri = loc.get("uri", "")
                rng = loc.get("range", {})
                start = rng.get("start", {})
                out.append({
                    "uri": uri,
                    "file": _uri_to_path(uri),
                    "line": start.get("line", 0),
                    "col": start.get("character", 0),
                    "range": rng,
                })
        return out
    if isinstance(result, dict):
        uri = result.get("uri", "")
        rng = result.get("range", {})
        start = rng.get("start", {})
        return [{
            "uri": uri,
            "file": _uri_to_path(uri),
            "line": start.get("line", 0),
            "col": start.get("character", 0),
            "range": rng,
        }]
    return []


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a local filesystem path."""
    if uri.startswith("file://"):
        # file:///path or file://host/path
        path_part = uri[7:]  # remove "file://"
        # On WSL/Linux, file path starts with /
        if path_part.startswith("/"):
            return path_part
        # file://host/path → /host/path (rare)
        return "/" + path_part
    return uri


# ────────────────────────────────────────────────
#  Global registry — multiple servers per session
# ────────────────────────────────────────────────

_registry: Dict[str, LSPClient] = {}
_registry_lock = threading.Lock()


def lsp_start(language: str, root_path: str) -> Dict[str, Any]:
    """
    Start an LSP server for the given language.

    Args:
        language: 'python', 'typescript', or 'rust'
        root_path: Project root directory for the language server

    Returns:
        dict with keys: 'ok' (bool), 'message' (str), 'language' (str)
    """
    language = language.lower().strip()

    if language not in LANGUAGE_SERVERS:
        return {
            "ok": False,
            "message": f"Unsupported language: {language!r}. "
                       f"Supported: {list(LANGUAGE_SERVERS.keys())}",
            "language": language,
        }

    with _registry_lock:
        # Stop existing server for this language if running
        if language in _registry:
            old = _registry[language]
            if old._running:
                old.stop()
            del _registry[language]

        cmd = LANGUAGE_SERVERS[language]
        client = LSPClient(language=language, root_path=root_path, cmd=list(cmd))

        if not client.start():
            return {
                "ok": False,
                "message": f"Failed to start LSP server for {language}. "
                           f"Ensure the server binary is installed (e.g., {cmd[0]}).",
                "language": language,
            }

        _registry[language] = client
        return {
            "ok": True,
            "message": f"LSP server for {language} started (root={root_path})",
            "language": language,
        }


def lsp_stop(language: str) -> Dict[str, Any]:
    """
    Stop the LSP server for the given language.

    Args:
        language: 'python', 'typescript', or 'rust'

    Returns:
        dict with 'ok' and 'message'
    """
    language = language.lower().strip()

    with _registry_lock:
        client = _registry.pop(language, None)
        if client is None:
            return {"ok": False, "message": f"No running LSP server for {language!r}"}

        client.stop()
        return {"ok": True, "message": f"LSP server for {language} stopped"}


def _get_client_for_file(file_path: str) -> Tuple[Optional[LSPClient], str]:
    """Get the LSP client for the language implied by file_path."""
    language = _detect_language(file_path)
    with _registry_lock:
        client = _registry.get(language)
    return client, language


def lsp_definition(file_path: str, line: int, col: int) -> Dict[str, Any]:
    """
    Go to definition.

    Args:
        file_path: Absolute path to the source file
        line: 0-indexed line number
        col: 0-indexed character/column number

    Returns:
        dict with 'ok', 'locations' (list of {file, line, col, uri, range})
    """
    client, language = _get_client_for_file(file_path)
    if client is None or not client._running:
        msg = f"No running LSP server for language {language!r}. Call lsp_start first."
        logger.warning(msg)
        return {"ok": False, "message": msg, "locations": []}

    locations = client.definition(file_path, line, col)
    return {
        "ok": True,
        "locations": locations,
        "count": len(locations),
    }


def lsp_references(file_path: str, line: int, col: int) -> Dict[str, Any]:
    """
    Find all references to the symbol at the given position.

    Args:
        file_path: Absolute path to the source file
        line: 0-indexed line number
        col: 0-indexed character/column number

    Returns:
        dict with 'ok', 'locations' (list of {file, line, col, uri, range})
    """
    client, language = _get_client_for_file(file_path)
    if client is None or not client._running:
        msg = f"No running LSP server for language {language!r}. Call lsp_start first."
        logger.warning(msg)
        return {"ok": False, "message": msg, "locations": []}

    locations = client.references(file_path, line, col)
    return {
        "ok": True,
        "locations": locations,
        "count": len(locations),
    }


def lsp_hover(file_path: str, line: int, col: int) -> Dict[str, Any]:
    """
    Get hover information (type info, documentation) at a position.

    Args:
        file_path: Absolute path to the source file
        line: 0-indexed line number
        col: 0-indexed character/column number

    Returns:
        dict with 'ok', 'contents' (str or None)
    """
    client, language = _get_client_for_file(file_path)
    if client is None or not client._running:
        msg = f"No running LSP server for language {language!r}. Call lsp_start first."
        logger.warning(msg)
        return {"ok": False, "message": msg, "contents": None}

    contents = client.hover(file_path, line, col)
    return {
        "ok": True,
        "contents": contents,
    }


def lsp_diagnostics(file_path: str) -> Dict[str, Any]:
    """
    Get diagnostics (errors, warnings, hints) for a file.

    Note: Diagnostics are delivered asynchronously by the LSP server
    via textDocument/publishDiagnostics notifications. You may need to
    wait briefly after opening/changing a file for diagnostics to arrive.

    Args:
        file_path: Absolute path to the source file

    Returns:
        dict with 'ok', 'diagnostics' (list of {range, severity, message, source, code})
    """
    client, language = _get_client_for_file(file_path)
    if client is None or not client._running:
        msg = f"No running LSP server for language {language!r}. Call lsp_start first."
        logger.warning(msg)
        return {"ok": False, "message": msg, "diagnostics": []}

    diags = client.diagnostics(file_path)
    return {
        "ok": True,
        "diagnostics": diags,
        "count": len(diags),
    }


# ────────────────────────────────────────────────
#  Module-level helpers
# ────────────────────────────────────────────────

def lsp_list_servers() -> Dict[str, bool]:
    """Return the status of all registered LSP servers."""
    with _registry_lock:
        return {lang: client._running for lang, client in _registry.items()}


def lsp_stop_all() -> Dict[str, Any]:
    """Stop all running LSP servers."""
    stopped = []
    with _registry_lock:
        for lang in list(_registry.keys()):
            client = _registry.pop(lang)
            client.stop()
            stopped.append(lang)
    return {
        "ok": True,
        "stopped": stopped,
        "message": f"Stopped {len(stopped)} LSP server(s): {stopped}" if stopped else "No servers were running",
    }


def detect_language(file_path: str) -> str:
    """Detect the programming language from a file path."""
    return _detect_language(file_path)


supported_languages = list(LANGUAGE_SERVERS.keys())
