"""
meshctx v3.80 — API Discovery Engine (API发现引擎)

自动扫描+文档化所有API端点, 生成OpenAPI/测试用例
"""
import ast, os, json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class APIEndpoint:
    path: str; method: str; handler: str; params: List[str]
    response_model: str=""; description: str=""

class APIDiscoveryEngine:
    def __init__(self, source_dir: Optional[str]=None):
        self._dir = Path(source_dir) if source_dir else Path("src")
        self._endpoints: List[APIEndpoint]=[]
    
    def scan(self) -> List[APIEndpoint]:
        for f in self._dir.rglob("*.py"):
            if "__pycache__" in str(f): continue
            try:
                tree = ast.parse(f.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        for dec in node.decorator_list:
                            if isinstance(dec, ast.Call) and hasattr(dec.func,'attr'):
                                method = dec.func.attr
                                if method in ('get','post','put','delete','patch'):
                                    path = dec.args[0].value if dec.args else ""
                                    params = [a.arg for a in node.args.args[1:]]  # skip self
                                    self._endpoints.append(APIEndpoint(
                                        path=path, method=method.upper(), handler=node.name,
                                        params=params))
            except: pass
        return self._endpoints
    
    def generate_openapi(self, title: str="MeshCtx API") -> Dict:
        paths = defaultdict(dict)
        for ep in self._endpoints:
            paths[ep.path][ep.method.lower()] = {"operationId": ep.handler, "parameters": [
                {"name": p, "in": "query", "schema": {"type": "string"}} for p in ep.params
            ], "responses": {"200": {"description": "Success"}}}
        return {"openapi": "3.0.0", "info": {"title": title, "version": "1.0"}, "paths": dict(paths)}

    def get_stats(self) -> Dict:
        methods = defaultdict(int)
        for ep in self._endpoints: methods[ep.method] += 1
        return {"endpoints": len(self._endpoints), "by_method": dict(methods)}

_discovery = None
def get_api_discovery(d=None):
    global _discovery
    if _discovery is None: _discovery = APIDiscoveryEngine(d)
    return _discovery
