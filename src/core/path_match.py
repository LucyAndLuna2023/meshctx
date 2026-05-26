"""Path Matcher — v3.27"""
import fnmatch, logging
from pathlib import Path
from typing import Dict, List, Optional
logger = logging.getLogger(__name__)

class PathMatcher:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or Path.cwd()
    def match(self, patterns: List[str]) -> List[str]:
        results = []
        for pattern in patterns:
            for f in self.root.rglob(pattern):
                results.append(str(f.relative_to(self.root)))
        return sorted(set(results))[:100]
    def find_largest(self, pattern: str = "*", n: int = 5) -> List[Dict]:
        files = [(f, f.stat().st_size) for f in self.root.rglob(pattern) if f.is_file()]
        files.sort(key=lambda x: -x[1])
        return [{"path": str(f.relative_to(self.root)), "size_mb": round(s/1e6,2)} for f,s in files[:n]]
    def get_stats(self) -> Dict: return {"root": str(self.root)}

_matcher: Optional[PathMatcher] = None
def get_path_matcher() -> PathMatcher:
    global _matcher
    if _matcher is None: _matcher = PathMatcher()
    return _matcher
