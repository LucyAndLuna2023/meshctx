"""JWT Token Manager — v3.22"""
import hashlib, hmac, json, time, logging
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class JWTManager:
    def __init__(self, secret: str = "meshctx-jwt-secret"):
        self.secret = secret; self._blacklist = set()
    
    def create(self, payload: Dict, expiry_seconds: int = 3600) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        payload["exp"] = int(time.time()) + expiry_seconds
        payload["iat"] = int(time.time())
        b64 = lambda d: __import__('base64').urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()
        msg = f"{b64(header)}.{b64(payload)}"
        sig = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{msg}.{sig}"
    
    def verify(self, token: str) -> Dict:
        try:
            if token in self._blacklist: return {"valid": False, "error": "token已失效"}
            parts = token.split(".")
            if len(parts) != 3: return {"valid": False, "error": "格式错误"}
            msg = f"{parts[0]}.{parts[1]}"
            expected = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(expected, parts[2]): return {"valid": False, "error": "签名无效"}
            from base64 import urlsafe_b64decode
            payload = json.loads(urlsafe_b64decode(parts[1] + "=="))
            if payload.get("exp", 0) < time.time(): return {"valid": False, "error": "已过期"}
            return {"valid": True, "payload": payload}
        except Exception as e: return {"valid": False, "error": str(e)}
    
    def revoke(self, token: str): self._blacklist.add(token)
    def get_stats(self) -> Dict: return {"blacklisted": len(self._blacklist)}

_jwt: Optional[JWTManager] = None
def get_jwt_manager() -> JWTManager:
    global _jwt
    if _jwt is None: _jwt = JWTManager()
    return _jwt
