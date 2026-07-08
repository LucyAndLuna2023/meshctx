"""meshctx web2api — v3.86 Web-to-API Proxy"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WebAPIConfig:
    name: str
    base_url: str = ""
    cookie: str = ""
    api_key: str = ""
    auth_type: str = "none"

    def __post_init__(self, **kw):
        if not self.auth_type or self.auth_type == "none":
            if self.cookie:
                self.auth_type = "cookie"
            elif self.api_key:
                self.auth_type = "bearer"


@dataclass
class ProxyRequest:
    model: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    stream: bool = False
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class ProxyResponse:
    content: str = ""
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"
    error: str = ""


class Web2APIProxy:
    """Proxy that wraps web-based AI APIs into a unified OpenAI-compatible interface."""

    def __init__(self, **kw):
        self._providers: Dict[str, WebAPIConfig] = {}
        self._request_count: int = 0
        self._error_count: int = 0

    def add_provider(self, name: str, config: WebAPIConfig, **kw):
        self._providers[name] = config

    def list_providers(self, **kw) -> List[str]:
        return list(self._providers.keys())

    def get_stats(self, **kw) -> Dict[str, Any]:
        return {
            "requests": self._request_count,
            "errors": self._error_count,
            "providers": len(self._providers),
        }

    def chat(self, provider_name: str, request: ProxyRequest, **kw) -> ProxyResponse:
        if provider_name not in self._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        self._request_count += 1
        # Stub: return empty response
        return ProxyResponse(
            content="This is a stub response from Web2API proxy.",
            model=request.model,
        )

    def chat_stream(self, provider_name: str, request: ProxyRequest, **kw):
        if provider_name not in self._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        self._request_count += 1
        # Stub: yield one chunk
        yield "This is a stub stream chunk from Web2API proxy."


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_web2api_instance: Optional[Web2APIProxy] = None


def get_web2api() -> Web2APIProxy:
    global _web2api_instance
    if _web2api_instance is None:
        _web2api_instance = Web2APIProxy()
    return _web2api_instance

from ._stub import _P
