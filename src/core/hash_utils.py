"""Hash Utilities — v3.31"""
import hashlib, logging
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class HashUtils:
    def md5(self, data: str) -> str: return hashlib.md5(data.encode()).hexdigest()
    def sha256(self, data: str) -> str: return hashlib.sha256(data.encode()).hexdigest()
    def file_hash(self, path: Path, algo: str = "sha256") -> str:
        h = getattr(hashlib, algo)()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""): h.update(chunk)
        return h.hexdigest()
    def short(self, data: str, length: int = 8) -> str: return self.sha256(data)[:length]
    def hash_dict(self, d: Dict) -> str:
        import json; return self.sha256(json.dumps(d, sort_keys=True))
    def get_stats(self) -> Dict: return {"algorithms": ["md5","sha256"], "module":"hash_utils"}

_hasher: Optional[HashUtils] = None
def get_hash_utils() -> HashUtils:
    global _hasher
    if _hasher is None: _hasher = HashUtils()
    return _hasher
