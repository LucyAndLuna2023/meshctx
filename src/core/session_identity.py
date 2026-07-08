"""meshctx Session Identity — real implementation (v3.115.16)"""
import uuid, time, hashlib, json, os
from typing import Optional

class SessionIdentity:
    """Track and validate session identity across restarts."""
    
    def __init__(self, session_id: str = None, storage_dir: str = None, **kw):
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.storage_dir = storage_dir
        self.created_at = time.time()
        self._last_active = time.time()
        self._fingerprint = self._compute_fingerprint()
        self.preferences = kw.get('preferences', {})
        self.strategies = kw.get('strategies', [])
    
    def _compute_fingerprint(self) -> str:
        data = f"{self.session_id}:{self.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    @property
    def last_active(self):
        return self._last_active
    
    def validate(self, fingerprint: str) -> bool:
        return fingerprint == self._fingerprint
    
    def set_strategy_belief(self, strategy_name: str, belief: float):
        self.preferences[strategy_name] = belief
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id, "created_at": self.created_at,
            "fingerprint": self._fingerprint, "last_active": self._last_active,
            "preferences": self.preferences, "strategies": self.strategies,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SessionIdentity':
        s = cls(session_id=data.get("session_id"))
        s.created_at = data.get("created_at", time.time())
        s._last_active = data.get("last_active", time.time())
        s._fingerprint = data.get("fingerprint", "")
        s.preferences = data.get("preferences", {})
        s.strategies = data.get("strategies", [])
        return s
    
    def save(self):
        if self.storage_dir:
            os.makedirs(self.storage_dir, exist_ok=True)
            path = os.path.join(self.storage_dir, "session_identity.json")
            with open(path, 'w') as f:
                json.dump(self.to_dict(), f)
    
    @classmethod
    def load(cls, storage_dir: str) -> Optional['SessionIdentity']:
        path = os.path.join(storage_dir, "session_identity.json")
        if os.path.exists(path):
            with open(path) as f:
                return cls.from_dict(json.load(f))
        return None
    
    def touch(self):
        self.created_at = time.time()
        self._last_active = time.time()
        self._fingerprint = self._compute_fingerprint()
    
    def merge_from_learn_loop(self, beliefs: dict, habits: dict):
        self.preferences.update(beliefs)
        self.strategies.extend(habits.get('strategies', []))

_active_session: Optional[SessionIdentity] = None

def get_session() -> SessionIdentity:
    global _active_session
    if _active_session is None:
        _active_session = SessionIdentity()
    return _active_session
