"""Regex Tools — v3.29"""
import re, logging
from typing import Any, Dict, List, Optional, Tuple
logger = logging.getLogger(__name__)

class RegexTools:
    def findall(self, pattern: str, text: str) -> List[str]: return re.findall(pattern, text)
    def replace(self, pattern: str, repl: str, text: str) -> str: return re.sub(pattern, repl, text)
    def split(self, pattern: str, text: str) -> List[str]: return re.split(pattern, text)
    def extract_groups(self, pattern: str, text: str) -> List[Dict]:
        return [{k:v for k,v in m.groupdict().items()} if m.groupdict() else {"match": m.group(0)} for m in re.finditer(pattern, text)]
    def validate(self, pattern: str) -> Dict:
        try: re.compile(pattern); return {"valid": True}
        except re.error as e: return {"valid": False, "error": str(e)}
    def get_stats(self) -> Dict: return {"module":"regex_tools"}

_regex: Optional[RegexTools] = None
def get_regex_tools() -> RegexTools:
    global _regex
    if _regex is None: _regex = RegexTools()
    return _regex
