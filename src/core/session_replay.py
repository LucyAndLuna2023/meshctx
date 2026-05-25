"""Session Replay Engine — v3.11"""
import json, logging, time
from collections import deque
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class SessionReplay:
    def __init__(self, max_events=200):
        self._events: deque = deque(maxlen=max_events); self._recording = False
    
    def start(self): self._recording = True
    def stop(self): self._recording = False
    
    def record(self, event_type: str, data: Any):
        if self._recording:
            self._events.append({"t": time.time(), "type": event_type, "data": str(data)[:300]})
    
    def replay(self, n: int = 20) -> List[Dict]:
        return list(self._events)[-n:]
    
    def replay_timeline(self) -> str:
        lines = [f"[{e['t']:.0f}] {e['type']}: {e['data'][:80]}" for e in self._events]
        return "\n".join(lines[-30:])
    
    def get_stats(self) -> Dict:
        return {"events": len(self._events), "recording": self._recording,
                "types": len(set(e['type'] for e in self._events))}

_replay: Optional[SessionReplay] = None
def get_session_replay() -> SessionReplay:
    global _replay
    if _replay is None: _replay = SessionReplay()
    return _replay
