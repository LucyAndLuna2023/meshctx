"""对话存储 — 开源版"""
import os, json, time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

def _conv_data_dir() -> str:
    """Profile感知的对话存储路径。优先 MESHCTX_HOME，回退 ~/.meshctx。"""
    base = os.environ.get("MESHCTX_HOME", str(Path.home() / ".meshctx"))
    return os.path.join(base, "conversations")

DATA_DIR = _conv_data_dir()

@dataclass
class Conversation:
    id: str = ""
    title: str = ""
    model: str = ""
    messages: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    
    @property
    def message_count(self) -> int:
        return len(self.messages)
    
    def to_dict(self):
        return {"id": self.id, "title": self.title, "model": self.model,
                "messages": self.messages, "message_count": self.message_count,
                "created_at": self.created_at}
    
    def add_message(self, role: str, content: str, **kw):
        self.messages.append({"role": role, "content": content, "time": time.time()})
    
    def add(self, role: str, content: str, **kw):
        """Alias for add_message."""
        return self.add_message(role, content, **kw)
    
    def save(self):
        """Persist conversation to disk."""
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, f"{self.id}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    @classmethod
    def list_all(cls, **kw):
        import os, json
        convs = []
        d = DATA_DIR
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith('.json'):
                    try:
                        with open(os.path.join(d, f)) as fh:
                            data = json.load(fh)
                        convs.append({"id": data.get("id", f[:-5]), "title": data.get("title", ""), "model": data.get("model", ""), "created_at": data.get("created_at", 0)})
                    except Exception:
                        pass
        return convs

    @classmethod
    def browse_meta(cls, limit=50, offset=0, search="", **kw):
        all_conv = cls.list_all()
        if search:
            all_conv = [c for c in all_conv if search.lower() in c.get("title","").lower()]
        return all_conv[offset:offset+limit]

    @classmethod
    def load(cls, conv_id, **kw):
        import os, json
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            return cls(id=d["id"], title=d["title"], model=d.get("model", ""), messages=d.get("messages", []))
        return None

    @classmethod
    def stats(cls, **kw):
        all_c = cls.list_all()
        return {"total_conversations": len(all_c), "storage_path": DATA_DIR}

    @classmethod
    def delete_all(cls, **kw):
        """清空所有对话"""
        import os, shutil
        d = DATA_DIR
        count = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith('.json'):
                    try:
                        os.remove(os.path.join(d, f))
                        count += 1
                    except OSError:
                        pass
        return count

    @classmethod
    def prune(cls, older_than_days: int = 30, **kw):
        """删除 older_than_days 之前的旧对话，返回删除数和释放的磁盘空间"""
        import os
        cutoff = time.time() - older_than_days * 86400
        d = DATA_DIR
        deleted = 0
        freed_bytes = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith('.json'):
                    fp = os.path.join(d, f)
                    try:
                        mtime = os.path.getmtime(fp)
                        if mtime < cutoff:
                            size = os.path.getsize(fp)
                            os.remove(fp)
                            deleted += 1
                            freed_bytes += size
                    except OSError:
                        pass
        return {"deleted": deleted, "freed_bytes": freed_bytes}

    @classmethod
    def delete(cls, conv_id, **kw):
        """删除单个对话"""
        import os
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    @classmethod
    def rename(cls, conv_id, new_title, **kw):
        """重命名对话"""
        import os, json
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            d["title"] = new_title
            with open(path, "w") as f:
                json.dump(d, f, ensure_ascii=False)
            return True
        return False

def get_or_create(conv_id: str = None) -> Conversation:
    if conv_id:
        path = os.path.join(DATA_DIR, f"{conv_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
                return Conversation(id=d["id"], title=d["title"], model=d.get("model", ""), messages=d.get("messages", []))
    return Conversation(id=conv_id or str(time.time()), title="New Chat")
get_conversation_store = get_or_create
