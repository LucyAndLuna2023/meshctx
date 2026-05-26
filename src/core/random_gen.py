"""Random Generator — v3.32"""
import logging, random, string, secrets, uuid
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class RandomGen:
    def string(self, length: int = 16, chars: str = None) -> str:
        return ''.join(secrets.choice(chars or string.ascii_letters+string.digits) for _ in range(length))
    def password(self, length: int = 20) -> str:
        return self.string(length, string.ascii_letters+string.digits+"!@#$%^&*")
    def token(self) -> str: return secrets.token_hex(32)
    def uuid4(self) -> str: return str(uuid.uuid4())
    def integer(self, a: int = 0, b: int = 100) -> int: return secrets.randbelow(b-a+1)+a
    def choice(self, items: List) -> Any: return secrets.choice(items) if items else None
    def get_stats(self) -> Dict: return {"module":"random_gen", "seedless": True}

_rand: Optional[RandomGen] = None
def get_random_gen() -> RandomGen:
    global _rand
    if _rand is None: _rand = RandomGen()
    return _rand
