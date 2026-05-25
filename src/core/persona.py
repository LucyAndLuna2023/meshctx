"""Agent Persona Manager — v2.96"""
import json, logging, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class Persona:
    name: str; description: str; tone: str = "professional"
    verbosity: int = 5; creativity: float = 0.5
    safety_level: str = "high"; expertise: List[str] = field(default_factory=list)
    custom_prompt: str = ""

class PersonaManager:
    _BUILTIN = {
        "coder": Persona("coder","Expert software engineer","precise",3,0.3,"high",["code","architecture"]),
        "reviewer": Persona("reviewer","Code review specialist","critical",7,0.2,"high",["review","security"]),
        "teacher": Persona("teacher","Patient educator","friendly",8,0.6,"high",["explain","tutorial"]),
        "architect": Persona("architect","System architect","visionary",5,0.8,"high",["design","scalability"]),
        "devops": Persona("devops","Infrastructure expert","direct",3,0.4,"high",["deploy","monitor"]),
    }
    def __init__(self): self._active = "coder"; self._custom: Dict[str,Persona] = {}
    def activate(self, name: str) -> Persona:
        p = self._custom.get(name) or self._BUILTIN.get(name)
        if p: self._active = name; return p
        return self._BUILTIN["coder"]
    def create(self, name: str, desc: str, **kw) -> Persona:
        p = Persona(name=name, description=desc, **kw); self._custom[name] = p; return p
    def list_all(self) -> List[Dict]: 
        return [{"name":n,"desc":p.description,"tone":p.tone} for n,p in {**self._BUILTIN,**self._custom}.items()]
    def get_stats(self) -> Dict:
        return {"active": self._active, "builtin": len(self._BUILTIN), "custom": len(self._custom)}

_mgr: Optional[PersonaManager] = None
def get_persona_manager() -> PersonaManager:
    global _mgr
    if _mgr is None: _mgr = PersonaManager()
    return _mgr
