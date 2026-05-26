"""Content Type Detector — v3.23"""
import logging, re
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

MIME_TYPES = {
    "py":"text/x-python","js":"text/javascript","ts":"text/typescript","json":"application/json",
    "yaml":"text/yaml","yml":"text/yaml","md":"text/markdown","html":"text/html","css":"text/css",
    "txt":"text/plain","csv":"text/csv","xml":"text/xml","toml":"text/toml","ini":"text/ini",
    "png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","gif":"image/gif","svg":"image/svg+xml",
    "pdf":"application/pdf","zip":"application/zip","tar":"application/tar","gz":"application/gzip",
    "sh":"text/x-shellscript","bat":"text/x-bat","ps1":"text/x-powershell",
}

class ContentTypeDetector:
    def from_extension(self, path: str) -> str: return MIME_TYPES.get(Path(path).suffix.lstrip(".").lower(), "application/octet-stream")
    def from_content(self, content: str) -> str:
        if content.startswith("{"): return "application/json"
        if content.startswith("<"): return "text/html" if "<html" in content[:100].lower() else "text/xml"
        if content.startswith("#!"): return "text/x-shellscript"
        if content.startswith("---"): return "text/yaml"
        return "text/plain"
    def is_text(self, mime: str) -> bool: return mime.startswith("text/") or mime in ("application/json","application/xml","application/javascript")
    def detect(self, path: str, content: str = "") -> Dict:
        mime = self.from_content(content) if content else self.from_extension(path)
        return {"path": path, "mime": mime, "is_text": self.is_text(mime)}
    def get_stats(self) -> Dict: return {"known_types": len(MIME_TYPES)}

_detector: Optional[ContentTypeDetector] = None
def get_content_detector() -> ContentTypeDetector:
    global _detector
    if _detector is None: _detector = ContentTypeDetector()
    return _detector
