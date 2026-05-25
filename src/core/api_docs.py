"""Endpoint Discovery & API Doc Generator — v3.04"""
import ast, json, logging, re, time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class APIDiscovery:
    """自动发现API端点并生成文档"""
    
    def __init__(self, source_file: Optional[Path] = None):
        self.source_file = source_file or Path("/home/administrator/meshctx-local/src/main.py")
        self._endpoints: List[Dict] = []
    
    def scan(self) -> List[Dict]:
        """扫描所有API端点"""
        if not self.source_file.exists():
            return []
        
        content = self.source_file.read_text(encoding="utf-8", errors="replace")
        
        # Find all @app.get/post/put/delete/websocket decorators
        patterns = [
            (r'@app\.(get|post|put|delete|websocket)\("([^"]+)"\)\s*\n\s*(?:async\s+)?def\s+(\w+)', "method", "path", "name"),
        ]
        
        endpoints = []
        for pattern, *groups in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                ep = {
                    "method": match.group(1).upper(),
                    "path": match.group(2),
                    "function": match.group(3),
                }
                
                # Try to find docstring
                func_start = match.end()
                doc_match = re.search(r'"""(.*?)"""', content[func_start:func_start+200], re.DOTALL)
                if doc_match:
                    ep["description"] = doc_match.group(1).strip().split("\n")[0]
                
                endpoints.append(ep)
        
        self._endpoints = endpoints
        return endpoints
    
    def generate_docs(self, format: str = "markdown") -> str:
        """生成API文档"""
        endpoints = self.scan()
        
        if format == "markdown":
            lines = ["# meshctx API Reference", f"", f"*Auto-generated: {time.strftime('%Y-%m-%d %H:%M')}*", f"", f"Total endpoints: {len(endpoints)}", ""]
            by_prefix = {}
            for ep in endpoints:
                prefix = "/".join(ep["path"].split("/")[:2])
                if prefix not in by_prefix: by_prefix[prefix] = []
                by_prefix[prefix].append(ep)
            
            for prefix, eps in sorted(by_prefix.items()):
                lines.append(f"## {prefix}")
                lines.append("")
                for ep in eps:
                    lines.append(f"### `{ep['method']} {ep['path']}`")
                    if ep.get("description"): lines.append(f"{ep['description']}")
                    lines.append("")
            
            return "\n".join(lines)
        
        return json.dumps(endpoints, indent=2)
    
    def get_stats(self) -> Dict:
        endpoints = self.scan()
        methods = {}
        for ep in endpoints:
            m = ep["method"]; methods[m] = methods.get(m, 0) + 1
        return {"total_endpoints": len(endpoints), "by_method": methods,
                "prefixes": len(set("/".join(ep["path"].split("/")[:2]) for ep in endpoints))}

_discovery: Optional[APIDiscovery] = None
def get_api_discovery() -> APIDiscovery:
    global _discovery
    if _discovery is None: _discovery = APIDiscovery()
    return _discovery
