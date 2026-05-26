"""String Formatter — v3.30"""
import json, logging, textwrap
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class StringFormatter:
    def truncate(self, s: str, max_len: int = 80, suffix: str = "..."): return s[:max_len-len(suffix)]+suffix if len(s)>max_len else s
    def slugify(self, s: str) -> str: return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")
    def title_case(self, s: str) -> str: return " ".join(w.capitalize() for w in s.split())
    def line_wrap(self, s: str, width: int = 80) -> str: return "\n".join(textwrap.wrap(s, width))
    def indent(self, s: str, spaces: int = 4) -> str: return textwrap.indent(s, " "*spaces)
    def pretty_json(self, obj: Any) -> str: return json.dumps(obj, indent=2, ensure_ascii=False)
    def get_stats(self) -> Dict: return {"module":"string_formatter"}

_formatter: Optional[StringFormatter] = None
def get_string_formatter() -> StringFormatter:
    global _formatter
    if _formatter is None: _formatter = StringFormatter()
    return _formatter
