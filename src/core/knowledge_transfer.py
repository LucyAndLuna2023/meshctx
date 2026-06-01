"""
meshctx v3.75 — Knowledge Transfer Engine (知识迁移引擎)

跨项目/跨领域知识迁移: A项目学到的→应用到B项目
"""
import logging, time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.knowledge_transfer")

@dataclass
class TransferRecord:
    source: str; target: str; concept: str; success: bool=False
    timestamp: float=field(default_factory=time.time)

class KnowledgeTransferEngine:
    def __init__(self):
        self._records: deque=deque(maxlen=100)
        self._transfer_map: Dict[str,List[str]]={}
    
    def learn(self, source_project: str, concept: str, details: str):
        if source_project not in self._transfer_map:
            self._transfer_map[source_project] = []
        self._transfer_map[source_project].append(concept)
    
    def suggest(self, target_project: str, limit: int=5) -> List[str]:
        suggestions = []
        for source, concepts in self._transfer_map.items():
            if source != target_project:
                for c in concepts[-3:]:
                    suggestions.append(f"From [{source}]: {c}")
        return suggestions[:limit]
    
    def transfer(self, source: str, target: str, concept: str, success: bool=True):
        self._records.append(TransferRecord(source=source, target=target, concept=concept, success=success))
    
    def get_stats(self) -> Dict:
        return {"projects": len(self._transfer_map), "transfers": len(self._records),
                "success_rate": f"{sum(1 for r in self._records if r.success)/max(1,len(self._records))*100:.0f}%"}

_kt = None
def get_knowledge_transfer():
    global _kt
    if _kt is None: _kt = KnowledgeTransferEngine()
    return _kt

# Backward compat
def get_knowledge_engine():
    return get_knowledge_transfer()
