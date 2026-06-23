"""
meshctx Session 全文搜索引擎 — SQLite FTS5
对标 Hermes session_search: 持久化索引 + BM25排序 + 片段高亮 + 时间过滤
"""
import os, re, time, sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

@dataclass
class SearchResult:
    session_id: str; title: str; snippet: str
    score: float; timestamp: float; match_type: str

class FTS5SessionSearch:
    """SQLite FTS5 全文搜索引擎"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.expanduser("~/.meshctx/sessions.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()
    
    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                timestamp REAL NOT NULL,
                message_count INTEGER DEFAULT 0,
                project_id TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                title, content, tokenize='unicode61'
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(timestamp);
        """)
        self._conn.commit()
    
    def index(self, session_id: str, title: str, messages: List[Dict],
              timestamp: float = None, project_id: str = None):
        """索引会话"""
        ts = timestamp or time.time()
        content = "\n".join(
            f"[{m.get('role','')}] {m.get('content','')}" 
            for m in messages
        )
        
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions(id,title,timestamp,message_count,project_id) VALUES(?,?,?,?,?)",
            (session_id, title, ts, len(messages), project_id)
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions_fts(rowid,title,content) VALUES(?,?,?)",
            (session_id, title, content)
        )
        self._conn.commit()
    
    def search(self, query: str, limit: int = 10,
               before: float = None, after: float = None) -> List[SearchResult]:
        """BM25全文搜索"""
        # 转义FTS5特殊字符
        safe_query = query.replace('"', '""')
        
        sql = """
            SELECT s.id, s.title, s.timestamp, s.message_count,
                   snippet(sessions_fts, 1, '<b>', '</b>', '...', 32) as snip,
                   bm25(sessions_fts, 0.0, 1.0) as rank
            FROM sessions_fts
            JOIN sessions s ON s.id = sessions_fts.rowid
            WHERE sessions_fts MATCH ?
        """
        params = [f'"{safe_query}"']
        
        if before:
            sql += " AND s.timestamp <= ?"
            params.append(before)
        if after:
            sql += " AND s.timestamp >= ?"
            params.append(after)
        
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        
        rows = self._conn.execute(sql, params).fetchall()
        
        results = []
        for row in rows:
            sid, title, ts, msg_count, snip, rank = row
            # BM25分数归一化
            score = min(1.0, max(0.1, 1.0 / (1.0 + abs(rank))))
            
            results.append(SearchResult(
                session_id=sid, title=title,
                snippet=snip or title,
                score=round(score, 3),
                timestamp=ts, match_type="fts5"
            ))
        
        return results
    
    def get_recent(self, limit: int = 10, project_id: str = None) -> List[Dict]:
        sql = "SELECT id,title,timestamp,message_count FROM sessions"
        params = []
        if project_id:
            sql += " WHERE project_id = ?"
            params.append(project_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        return [
            {"session_id":r[0],"title":r[1],"timestamp":r[2],"message_count":r[3]}
            for r in self._conn.execute(sql, params).fetchall()
        ]
    
    def delete(self, session_id: str):
        self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self._conn.execute("DELETE FROM sessions_fts WHERE rowid=?", (session_id,))
        self._conn.commit()
    
    def stats(self) -> Dict:
        count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return {"indexed_sessions": count,
                "db_size": os.path.getsize(self._conn.execute("PRAGMA database_list").fetchone()[2]) if count else 0}


class SessionSearchPlugin(Plugin):
    info = PluginInfo(name="session_search", version="1.1.0",
        description="SQLite FTS5全文检索 — BM25排序+时间过滤+持久化", author="meshctx")
    
    def __init__(self):
        self.engine = FTS5SessionSearch()
    
    async def on_load(self):
        bus = self.kernel.bus
        bus.subscribe("search.session", self._on_search, plugin_name="session_search")
        bus.subscribe("search.recent", self._on_recent, plugin_name="session_search")
        bus.subscribe("search.index", self._on_index, plugin_name="session_search")
        bus.subscribe("message.added", self._on_message, plugin_name="session_search")
    
    async def on_unload(self): pass
    
    async def _on_search(self, event: Event):
        d = event.data
        results = self.engine.search(d.get("query",""), d.get("limit",10), d.get("before"), d.get("after"))
        await self.kernel.bus.publish(Event(type="search.session_result", source="session_search",
            correlation_id=event.id, data={"results":[{
                "session_id":r.session_id,"title":r.title,"snippet":r.snippet,
                "score":r.score,"timestamp":r.timestamp} for r in results]}))
    
    async def _on_recent(self, event: Event):
        results = self.engine.get_recent(event.data.get("limit",10), event.data.get("project_id"))
        await self.kernel.bus.publish(Event(type="search.recent_result", source="session_search",
            correlation_id=event.id, data={"sessions":results}))
    
    async def _on_index(self, event: Event):
        d = event.data
        self.engine.index(d["session_id"], d.get("title",""), d.get("messages",[]), d.get("timestamp"))
    
    async def _on_message(self, event: Event):
        d = event.data
        sid = d.get("conversation_id") or d.get("session_id")
        if sid:
            self.engine.index(sid, d.get("title",""), [{"role":d.get("role","user"),"content":d.get("content","")}], time.time())
