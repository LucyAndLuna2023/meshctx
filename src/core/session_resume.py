"""
meshctx v3.71 — Session Resume Engine (会话恢复引擎)

会话中断后秒级恢复全部上下文
"""
import logging, time, json, os
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.session_resume")

@dataclass
class SessionState:
    id: str; profile: str=""; messages: int=0; tools_called: int=0
    last_action: str=""; last_model: str=""; checkpoint: float=field(default_factory=time.time)

class SessionResumeEngine:
    def __init__(self, storage: Optional[Path]=None):
        self._storage = storage or (Path.home()/".meshctx"/"sessions")
        self._storage.mkdir(parents=True, exist_ok=True)
        self._active: Dict[str,SessionState]={}
    
    def save(self, session_id: str, state: Dict) -> bool:
        try:
            s = SessionState(**{k:state.get(k,"") for k in ["id","profile","messages","tools_called","last_action","last_model"]})
            s.id = session_id
            self._active[session_id] = s
            with open(self._storage/f"{session_id}.json","w") as f:
                json.dump({"id":s.id,"profile":s.profile,"messages":s.messages,
                    "tools_called":s.tools_called,"last_action":s.last_action,
                    "last_model":s.last_model,"checkpoint":s.checkpoint}, f)
            return True
        except Exception as e:
            logger.error(f"Save failed: {e}"); return False
    
    def resume(self, session_id: str) -> Optional[Dict]:
        f = self._storage/f"{session_id}.json"
        if not f.exists(): return None
        try:
            with open(f) as fh: return json.load(fh)
        except: return None
    
    def list_recent(self, n: int=5) -> List[Dict]:
        files = sorted(self._storage.glob("*.json"), key=lambda f:f.stat().st_mtime, reverse=True)[:n]
        results = []
        for f in files:
            try:
                with open(f) as fh: results.append(json.load(fh))
            except: pass
        return results
    
    def get_stats(self) -> Dict:
        return {"sessions": len(list(self._storage.glob("*.json"))),
                "active": len(self._active)}

_engine = None
def get_session_resume(path=None):
    global _engine
    if _engine is None: _engine = SessionResumeEngine(path)
    return _engine
