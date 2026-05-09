"""
meshctx v1.0 性能层 — Streaming + Tiered Cache

性能目标:
- 上下文组装延迟: < 50ms
- 记忆检索延迟: < 10ms  
- 首次响应时间: < 500ms (端到端)

三层缓存:
  L1: 进程内存 (热点数据, LRU)
  L2: 文件缓存 (跨进程共享)
  L3: 分布式 (可选 Redis/MinIO)
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

from .kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.performance")


# ═══════════════════════════════════════════════════════════
# L1 内存缓存 (进程内, 最快)
# ═══════════════════════════════════════════════════════════

@dataclass
class CacheEntry:
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: float = 300  # 5分钟默认TTL


class L1MemoryCache:
    """
    L1 缓存: 进程内存 LRU
    
    容量: 1000条目
    淘汰策略: LRU + TTL
    """
    
    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            
            # TTL过期
            if time.time() - entry.created_at > entry.ttl:
                del self._cache[key]
                self._misses += 1
                return None
            
            # LRU: 移到末尾
            self._cache.move_to_end(key)
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._hits += 1
            
            return entry.value
    
    def set(self, key: str, value: Any, ttl: float = 300):
        """设置缓存"""
        with self._lock:
            # 容量控制
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)  # 淘汰最旧的
            
            self._cache[key] = CacheEntry(
                key=key, value=value, ttl=ttl
            )
            self._cache.move_to_end(key)
    
    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
    
    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0
    
    def stats(self) -> Dict:
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
        }


# ═══════════════════════════════════════════════════════════
# L2 文件缓存 (跨进程)
# ═══════════════════════════════════════════════════════════

class L2FileCache:
    """
    L2 缓存: 文件系统
    
    用于跨进程共享的持久缓存。
    适合: 嵌入向量、编译后的Skill、会话摘要
    """
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.path.expanduser("~/.meshctx/cache/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _key_to_path(self, key: str) -> Path:
        h = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{h[:2]}/{h}.json"
    
    def get(self, key: str, max_age: float = 3600) -> Optional[Any]:
        """读取缓存"""
        path = self._key_to_path(key)
        if not path.exists():
            return None
        
        # 检查过期
        mtime = path.stat().st_mtime
        if time.time() - mtime > max_age:
            return None
        
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            return None
    
    def set(self, key: str, value: Any):
        """写入缓存"""
        path = self._key_to_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            json.dump(value, f)
    
    def delete(self, key: str):
        path = self._key_to_path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    
    def clear(self):
        """清除所有缓存"""
        import shutil
        try:
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except:
            pass
    
    def stats(self) -> Dict:
        file_count = 0
        total_size = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.rglob("*.json"):
                file_count += 1
                total_size += f.stat().st_size
        return {
            "files": file_count,
            "size_mb": round(total_size / (1024 * 1024), 2),
        }


# ═══════════════════════════════════════════════════════════
# 流式响应生成器
# ═══════════════════════════════════════════════════════════

class StreamGenerator:
    """
    流式响应生成器
    
    支持:
    - SSE (Server-Sent Events) 格式
    - 渐进式上下文组装
    - token级别的流式输出
    """
    
    async def stream_response(self, content: str,
                              chunk_size: int = 50,
                              delay: float = 0.01) -> AsyncGenerator[str, None]:
        """流式输出内容"""
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
            await asyncio.sleep(delay)
        
        yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
    
    async def stream_events(self, events: List[Dict]) -> AsyncGenerator[str, None]:
        """流式发布事件"""
        for ev in events:
            yield f"event: {ev.get('type', 'message')}\n"
            yield f"data: {json.dumps(ev.get('data', {}))}\n\n"
    
    def wrap_response(self, text: str, streaming: bool = False) -> Dict:
        """包装响应"""
        return {
            "content": text,
            "streaming": streaming,
            "timestamp": time.time(),
        }


# ═══════════════════════════════════════════════════════════
# 性能监控器
# ═══════════════════════════════════════════════════════════

class PerformanceMonitor:
    """性能监控"""
    
    def __init__(self):
        self._latencies: Dict[str, List[float]] = {
            "context_assembly": [],
            "memory_retrieval": [],
            "decision": [],
            "action": [],
            "total_response": [],
        }
        self._max_samples = 100
    
    def record(self, operation: str, latency_ms: float):
        if operation in self._latencies:
            self._latencies[operation].append(latency_ms)
            if len(self._latencies[operation]) > self._max_samples:
                self._latencies[operation] = self._latencies[operation][-self._max_samples:]
    
    def get_stats(self) -> Dict:
        stats = {}
        for op, latencies in self._latencies.items():
            if latencies:
                import statistics
                stats[op] = {
                    "avg_ms": round(statistics.mean(latencies), 2),
                    "p50_ms": round(statistics.median(latencies), 2),
                    "p95_ms": round(
                        sorted(latencies)[int(len(latencies) * 0.95)], 2
                    ) if len(latencies) >= 20 else 0,
                    "samples": len(latencies),
                }
        return stats


# ═══════════════════════════════════════════════════════════
# 性能插件
# ═══════════════════════════════════════════════════════════

class PerformancePlugin(Plugin):
    """
    性能优化插件
    
    功能:
    - L1/L2分级缓存
    - 流式响应支持
    - 性能监控
    """
    
    info = PluginInfo(
        name="performance",
        version="1.0.0",
        description="性能优化 — 分层缓存+流式响应+延迟监控",
        author="meshctx",
    )
    
    def __init__(self):
        self.l1_cache = L1MemoryCache(max_size=1000)
        self.l2_cache = L2FileCache()
        self.streamer = StreamGenerator()
        self.monitor = PerformanceMonitor()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def on_load(self):
        bus = self.kernel.bus
        
        bus.subscribe("cache.get", self._on_cache_get,
                      plugin_name="performance")
        bus.subscribe("cache.set", self._on_cache_set,
                      plugin_name="performance")
        bus.subscribe("perf.report", self._on_perf_report,
                      plugin_name="performance")
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("性能插件已加载 (L1+L2缓存 + 流式 + 监控)")
    
    async def on_unload(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("性能插件已卸载")
    
    async def _on_cache_get(self, event: Event):
        key = event.data.get("key", "")
        level = event.data.get("level", "l1")
        
        start = time.time()
        
        if level == "l1":
            value = self.l1_cache.get(key)
        else:
            value = self.l2_cache.get(key)
        
        latency = (time.time() - start) * 1000
        
        await self.kernel.bus.publish(Event(
            type="cache.result",
            source="performance",
            correlation_id=event.id,
            data={"key": key, "hit": value is not None, "value": value, "latency_ms": latency},
        ))
    
    async def _on_cache_set(self, event: Event):
        key = event.data.get("key", "")
        value = event.data.get("value")
        level = event.data.get("level", "l1")
        ttl = event.data.get("ttl", 300)
        
        if level == "l1":
            self.l1_cache.set(key, value, ttl)
        else:
            self.l2_cache.set(key, value)
    
    async def _on_perf_report(self, event: Event):
        await self.kernel.bus.publish(Event(
            type="perf.report_result",
            source="performance",
            correlation_id=event.id,
            data={
                "l1_cache": self.l1_cache.stats(),
                "l2_cache": self.l2_cache.stats(),
                "latencies": self.monitor.get_stats(),
            },
        ))
    
    async def _cleanup_loop(self):
        """定期清理过期缓存"""
        while True:
            try:
                await asyncio.sleep(600)  # 10分钟
                # L2清理30天以上的缓存
                for f in self.l2_cache.cache_dir.rglob("*.json"):
                    if time.time() - f.stat().st_mtime > 86400 * 30:
                        try:
                            f.unlink()
                        except:
                            pass
            except asyncio.CancelledError:
                break
    
    def generate_report(self) -> Dict:
        return {
            "l1_cache": self.l1_cache.stats(),
            "l2_cache": self.l2_cache.stats(),
            "latencies": self.monitor.get_stats(),
        }
