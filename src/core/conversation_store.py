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

def get_or_create(conv_id: str = None) -> Conversation:
    if conv_id:
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
                return Conversation(id=d["id"], title=d["title"], messages=d.get("messages", []))
    return Conversation(id=conv_id or str(time.time()), title="New Chat")
get_conversation_store = get_or_create
