"""meshctx Semantic Index — real implementation (v3.115.16)"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import math
import re


@dataclass
class SemanticEntry:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    _ngrams: Optional[Set[str]] = None
    
    def ngrams(self) -> Set[str]:
        if self._ngrams is None:
            words = re.findall(r'\w+', self.text.lower())
            self._ngrams = set()
            for w in words:
                self._ngrams.add(w)
                for i in range(len(w) - 1):
                    self._ngrams.add(w[i:i+2])
                if len(w) > 2:
                    self._ngrams.add(w[:3])
        return self._ngrams

@dataclass
class SemanticSearchResult:
    entry: SemanticEntry
    score: float
    matched_terms: List[str] = field(default_factory=list)

class SemanticIndex:
    """Keyword + n-gram inverted index with TF scoring."""
    
    def __init__(self):
        self.entries: Dict[str, SemanticEntry] = {}
        self._inverted: Dict[str, Set[str]] = defaultdict(set)
        self._doc_freq: Dict[str, int] = defaultdict(int)
        self._doc_count = 0
    
    def add(self, id: str, text: str, metadata: dict = None) -> SemanticEntry:
        entry = SemanticEntry(id=id, text=text, metadata=metadata or {})
        self.entries[id] = entry
        self._doc_count += 1
        
        for ngram in entry.ngrams():
            self._inverted[ngram].add(id)
            self._doc_freq[ngram] += 1
        
        return entry
    
    def remove(self, id: str):
        entry = self.entries.pop(id, None)
        if entry:
            self._doc_count -= 1
            for ngram in entry.ngrams():
                self._inverted[ngram].discard(id)
                self._doc_freq[ngram] = max(0, self._doc_freq[ngram] - 1)
    
    def search(self, query: str, top_k: int = 10, threshold: float = 0.0) -> List[SemanticSearchResult]:
        query_ngrams = set()
        for w in re.findall(r'\w+', query.lower()):
            query_ngrams.add(w)
            for i in range(len(w) - 1):
                query_ngrams.add(w[i:i+2])
        
        if not query_ngrams:
            return []
        
        scores: Dict[str, float] = defaultdict(float)
        matched: Dict[str, List[str]] = defaultdict(list)
        
        for ng in query_ngrams:
            idf = math.log((self._doc_count + 1) / (self._doc_freq.get(ng, 0) + 1)) + 1
            for doc_id in self._inverted.get(ng, set()):
                scores[doc_id] += idf
                matched[doc_id].append(ng)
        
        results = []
        for doc_id, score in sorted(scores.items(), key=lambda x: -x[1]):
            if score < threshold:
                continue
            results.append(SemanticSearchResult(
                entry=self.entries[doc_id],
                score=score,
                matched_terms=matched[doc_id][:5]
            ))
            if len(results) >= top_k:
                break
        
        return results
    
    def __len__(self):
        return len(self.entries)
    
    def stats(self) -> dict:
        return {
            "documents": self._doc_count,
            "terms": len(self._inverted),
            "avg_doc_terms": sum(len(e.ngrams()) for e in self.entries.values()) / max(1, self._doc_count),
        }