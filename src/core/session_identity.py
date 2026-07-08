"""meshctx Session Identity — real implementation (v3.115.16)"""
import uuid, time, hashlib
from typing import Optional

class SessionIdentity:
    """Track and validate session identity across restarts."""
    
    def __init__(self, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.created_at = time.time()
        self._fingerprint = self._compute_fingerprint()
    
    def _compute_fingerprint(self) -> str:
        data = f"{self.session_id}:{self.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def validate(self, fingerprint: str) -> bool:
        return fingerprint == self._fingerprint
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "fingerprint": self._fingerprint,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SessionIdentity':
        s = cls(session_id=data.get("session_id"))
        s.created_at = data.get("created_at", time.time())
        s._fingerprint = data.get("fingerprint", "")
        return s

_active_session: Optional[SessionIdentity] = None

def get_session() -> SessionIdentity:
    global _active_session
    if _active_session is None:
        _active_session = SessionIdentity()
    return _active_session
