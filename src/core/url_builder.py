"""URL Builder — v3.28"""
import logging
from urllib.parse import urlencode, urljoin, urlparse
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class URLBuilder:
    def build(self, base: str, path: str = "", params: Dict = None) -> str:
        url = urljoin(base, path)
        if params: url += "?" + urlencode({k:v for k,v in params.items() if v is not None})
        return url
    def parse(self, url: str) -> Dict:
        p = urlparse(url)
        qs = {}
        for kv in p.query.split("&"):
            if "=" in kv: k,v = kv.split("=",1); qs[k] = v
        return {"scheme":p.scheme, "host":p.hostname, "port":p.port, "path":p.path, "query":qs}
    def join(self, *parts: str) -> str: return "/".join(p.strip("/") for p in parts if p)
    def get_stats(self) -> Dict: return {"module":"url_builder"}

_builder: Optional[URLBuilder] = None
def get_url_builder() -> URLBuilder:
    global _builder
    if _builder is None: _builder = URLBuilder()
    return _builder
