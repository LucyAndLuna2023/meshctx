"""对话存储 — 开源版"""
import os, json, time
from dataclasses import dataclass, field
from typing import Optional

DATA_DIR = os.path.expanduser("~/.meshctx/conversations")

@dataclass
class Conversation:
    id: str = ""
    title: str = ""
    messages: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self): return {"id": self.id, "title": self.title, "messages": self.messages}
    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content, "time": time.time()})
    @classmethod
    def list_all(cls):
        import os, json
        convs = []
        d = os.path.expanduser("~/.meshctx/conversations")
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith('.json'):
                    try:
                        with open(os.path.join(d, f)) as fh:
                            data = json.load(fh)
                        convs.append({"id": data.get("id", f[:-5]), "title": data.get("title", ""), "created_at": data.get("created_at", 0)})
                    except Exception:
                        pass
        return convs

    @classmethod
    def browse_meta(cls, limit=50, offset=0, search=""):
        all_conv = cls.list_all()
        if search:
            all_conv = [c for c in all_conv if search.lower() in c.get("title","").lower()]
        return all_conv[offset:offset+limit]

    @classmethod
    def load(cls, conv_id):
        import os, json
        path = os.path.expanduser(f"~/.meshctx/conversations/{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            return cls(id=d["id"], title=d["title"], messages=d.get("messages", []))
        return None

    @classmethod
    def stats(cls):
        all_c = cls.list_all()
        return {"total_conversations": len(all_c), "storage_path": "~/.meshctx/conversations"}

def get_or_create(conv_id: str = None) -> Conversation:
    if conv_id:
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
                return Conversation(id=d["id"], title=d["title"], messages=d.get("messages", []))
    return Conversation(id=conv_id or str(time.time()), title="New Chat")
get_conversation_store = get_or_create
