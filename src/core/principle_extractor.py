"""meshctx Principle Extractor — real implementation (v3.115.16)"""
import re
from collections import Counter
from typing import List, Dict

class PrincipleExtractor:
    """Extract governing principles and patterns from text corpora."""
    
    def __init__(self):
        self._patterns = []
    
    def extract(self, texts: List[str]) -> List[Dict]:
        """Extract common patterns from a list of texts."""
        # Extract imperative statements (should/must/always/never)
        principles = []
        for text in texts:
            for sent in re.split(r'[.!?\n]', text):
                sent = sent.strip()
                if not sent: continue
                lower = sent.lower()
                if any(kw in lower for kw in ['should', 'must', 'always', 'never', '重要', '必须']):
                    principles.append({"text": sent[:200], "type": "imperative"})
                elif any(kw in lower for kw in ['rule', 'principle', 'pattern', '规则']):
                    principles.append({"text": sent[:200], "type": "declarative"})
        
        # Deduplicate by similarity
        seen = set()
        unique = []
        for p in principles:
            key = p["text"][:50].lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        
        self._patterns = unique
        return unique
    
    def stats(self) -> dict:
        return {"patterns_extracted": len(self._patterns)}

def get_extractor() -> PrincipleExtractor:
    return PrincipleExtractor()
