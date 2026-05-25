"""Text Diff & Merge Engine — v3.15"""
import difflib, logging
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class DiffEngine:
    def diff(self, old: str, new: str, context_lines: int = 3) -> str:
        d = difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="old", tofile="new", n=context_lines)
        return "".join(d)
    
    def merge(self, base: str, ours: str, theirs: str) -> Dict:
        """三方合并"""
        result = []; conflicts = 0
        matcher = difflib.SequenceMatcher(None, ours.splitlines(), theirs.splitlines())
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal': result.extend(ours.splitlines()[i1:i2])
            elif tag == 'replace':
                result.append(f"<<<<<<< OURS"); result.extend(ours.splitlines()[i1:i2])
                result.append("======="); result.extend(theirs.splitlines()[j1:j2])
                result.append(f">>>>>>> THEIRS"); conflicts += 1
            elif tag == 'delete': result.extend([f"-{l}" for l in ours.splitlines()[i1:i2]]); conflicts += 1
            elif tag == 'insert': result.extend([f"+{l}" for l in theirs.splitlines()[j1:j2]])
        return {"merged": "\n".join(result), "conflicts": conflicts, "resolved": conflicts == 0}
    
    def similarity(self, a: str, b: str) -> float:
        return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)
    
    def get_stats(self) -> Dict: return {"engine": "difflib", "supports": ["diff","merge","similarity"]}

_diff: Optional[DiffEngine] = None
def get_diff_engine() -> DiffEngine:
    global _diff
    if _diff is None: _diff = DiffEngine()
    return _diff
