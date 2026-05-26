"""Embedded KV Store — v3.24"""
import json, logging, time, shelve
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class KVStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path.home() / ".meshctx" / "kv.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Any] = {}
    
    def set(self, key: str, value: Any, ttl: int = 0) -> bool:
        entry = {"value": value, "expires_at": time.time() + ttl if ttl > 0 else 0, "set_at": time.time()}
        self._cache[key] = entry
        with shelve.open(str(self.path)) as db: db[key] = entry
        return True
    
    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            e = self._cache[key]
            if e["expires_at"] == 0 or e["expires_at"] > time.time(): return e["value"]
            del self._cache[key]
        with shelve.open(str(self.path)) as db:
            if key in db:
                e = db[key]
                if e["expires_at"] == 0 or e["expires_at"] > time.time(): return e["value"]
        return None
    
    def delete(self, key: str) -> bool:
        self._cache.pop(key, None)
        with shelve.open(str(self.path)) as db:
            if key in db: del db[key]; return True
        return False
    
    def keys(self) -> List[str]:
        with shelve.open(str(self.path)) as db: return list(db.keys())
    
    def get_stats(self) -> Dict:
        with shelve.open(str(self.path)) as db: return {"total_keys": len(db), "cached": len(self._cache)}

_store: Optional[KVStore] = None
def get_kv_store() -> KVStore:
    global _store
    if _store is None: _store = KVStore()
    return _store
