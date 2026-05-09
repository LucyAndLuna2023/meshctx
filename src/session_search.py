"""
meshctx Session 搜索引擎
全文检索 + 时间范围 + 语义相似度
"""
import re
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

@dataclass
class SearchResult:
    """搜索结果"""
    session_id: str
    title: str
    snippet: str            # 匹配片段
    score: float
    timestamp: float
    match_type: str         # keyword|semantic|time


class SessionSearchEngine:
    """Session 搜索引擎"""
    
    def __init__(self):
        self._index: Dict[str, Dict] = {}  # session_id → {title, messages, timestamp}
        
    def index(self, session_id: str, title: str, messages: List[Dict], 
              timestamp: float = None):
        """索引一个会话"""
        # 拼接所有消息为可搜索文本
        full_text = title + "\n"
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            full_text += f"[{role}] {content}\n"
        
        self._index[session_id] = {
            "title": title,
            "text": full_text.lower(),
            "message_count": len(messages),
            "timestamp": timestamp or time.time(),
        }
    
    def search(self, query: str, limit: int = 10, 
               before: float = None, after: float = None,
               min_score: float = 0.1) -> List[SearchResult]:
        """全文搜索"""
        query_lower = query.lower()
        keywords = [kw for kw in query_lower.split() if len(kw) > 1]
        
        results = []
        for sid, doc in self._index.items():
            # 时间过滤
            ts = doc["timestamp"]
            if before and ts > before:
                continue
            if after and ts < after:
                continue
                
            text = doc["text"]
            title = doc["title"]
            
            # 计算分数
            score = 0.0
            snippets = []
            
            # 标题匹配(权重高)
            title_lower = title.lower()
            for kw in keywords:
                if kw in title_lower:
                    score += 2.0
                    snippets.append(f"标题: {title}")
            
            # 内容匹配
            for kw in keywords:
                count = text.count(kw)
                if count > 0:
                    score += min(count, 5) * 1.0
                    # 提取片段
                    for m in re.finditer(re.escape(kw), text):
                        start = max(0, m.start() - 30)
                        end = min(len(text), m.end() + 30)
                        snippet = text[start:end].strip()
                        if snippet:
                            snippets.append(f"...{snippet}...")
                        if len(snippets) >= 3:
                            break
            
            if score >= min_score:
                results.append(SearchResult(
                    session_id=sid,
                    title=title,
                    snippet=" | ".join(snippets[:3])[:200],
                    score=min(score / max(1, len(keywords) * 3), 1.0),
                    timestamp=ts,
                    match_type="keyword",
                ))
        
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
    
    def get_recent(self, limit: int = 10) -> List[Dict]:
        """获取最近会话"""
        sorted_sessions = sorted(
            self._index.items(),
            key=lambda x: x[1]["timestamp"],
            reverse=True,
        )
        return [
            {
                "session_id": sid,
                "title": doc["title"],
                "message_count": doc["message_count"],
                "timestamp": doc["timestamp"],
            }
            for sid, doc in sorted_sessions[:limit]
        ]
    
    def stats(self) -> Dict:
        return {
            "indexed_sessions": len(self._index),
            "total_messages": sum(d["message_count"] for d in self._index.values()),
        }


class SessionSearchPlugin(Plugin):
    """Session 搜索插件"""
    
    info = PluginInfo(
        name="session_search",
        version="1.0.0",
        description="Session 全文检索 — 关键词+时间范围搜索",
        author="meshctx",
    )
    
    def __init__(self):
        self.engine = SessionSearchEngine()
    
    async def on_load(self):
        self.kernel.bus.subscribe(
            "search.session", self._on_search, plugin_name="session_search"
        )
        self.kernel.bus.subscribe(
            "search.recent", self._on_recent, plugin_name="session_search"
        )
    
    async def on_unload(self):
        pass
    
    async def _on_search(self, event: Event):
        data = event.data
        results = self.engine.search(
            query=data.get("query", ""),
            limit=data.get("limit", 10),
            before=data.get("before"),
            after=data.get("after"),
        )
        await self.kernel.bus.publish(Event(
            type="search.session_result",
            source="session_search",
            correlation_id=event.id,
            data={"results": [{
                "session_id": r.session_id,
                "title": r.title,
                "snippet": r.snippet,
                "score": round(r.score, 3),
                "timestamp": r.timestamp,
            } for r in results]},
        ))
    
    async def _on_recent(self, event: Event):
        results = self.engine.get_recent(event.data.get("limit", 10))
        await self.kernel.bus.publish(Event(
            type="search.recent_result",
            source="session_search",
            correlation_id=event.id,
            data={"sessions": results},
        ))
