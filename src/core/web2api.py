"""
meshctx v3.86 — Web-to-API Proxy (网页大模型→OpenAI兼容API)

将闭源网页大模型(如Gemini Web)转为标准OpenAI API。
零依赖，单文件，支持Cookie认证+SSE流式。
"""
import json, time, logging, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Iterator
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("meshctx.web2api")

@dataclass
class WebAPIConfig:
    name: str = ""; base_url: str = ""; api_style: str = "openai"
    auth_type: str = "cookie"; cookie: str = ""; model: str = ""
    
@dataclass
class ProxyRequest:
    model: str; messages: List[Dict]; stream: bool = False
    max_tokens: int = 2048; temperature: float = 0.7

@dataclass
class ProxyResponse:
    content: str; model: str; tokens: int = 0; finish: str = "stop"

class Web2APIProxy:
    """Web→API代理引擎"""
    
    def __init__(self):
        self._providers: Dict[str, WebAPIConfig] = {}
        self._stats = {"requests": 0, "tokens": 0, "errors": 0}
    
    def add_provider(self, name: str, config: WebAPIConfig):
        self._providers[name] = config
    
    def chat(self, provider: str, req: ProxyRequest) -> ProxyResponse:
        if provider not in self._providers:
            raise ValueError(f"Unknown provider: {provider}")
        
        config = self._providers[provider]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MeshCtx-Web2API/3.86"
        }
        if config.auth_type == "cookie" and config.cookie:
            headers["Cookie"] = config.cookie
        
        body = {
            "model": req.model or config.model,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "stream": req.stream
        }
        
        try:
            http_req = Request(config.base_url, data=json.dumps(body).encode(), 
                              headers=headers, method="POST")
            with urlopen(http_req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                tokens = data.get("usage", {}).get("total_tokens", 0)
                self._stats["requests"] += 1
                self._stats["tokens"] += tokens
                return ProxyResponse(content=content, model=req.model, tokens=tokens)
        except URLError as e:
            self._stats["errors"] += 1
            logger.error(f"Web2API error: {e}")
            return ProxyResponse(content=f"ERROR: {e}", model=req.model, finish="error")
    
    def chat_stream(self, provider: str, req: ProxyRequest) -> Iterator[str]:
        req.stream = True
        response = self.chat(provider, req)
        if response.finish == "error":
            yield f"data: {json.dumps({'error': response.content})}\n\n"
        else:
            for chunk in response.content.split():
                yield f"data: {json.dumps({'choices':[{'delta':{'content':chunk+' '}}]})}\n\n"
            yield "data: [DONE]\n\n"
    
    def list_providers(self) -> List[str]:
        return list(self._providers.keys())
    
    def get_stats(self) -> Dict:
        return dict(self._stats)

def get_web2api():
    global _web2api
    if _web2api is None:
        _web2api = Web2APIProxy()
    return _web2api

_web2api = None
