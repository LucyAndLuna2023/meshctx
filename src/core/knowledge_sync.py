"""
meshctx v3.51 — Cross-Agent Knowledge Sync (跨Agent知识同步)

问题: 多profile独立运行，各自学习，知识孤岛
方案: 共享知识库 — 一个Profile的发现自动同步到相关Profile

架构:
  Knowledge Bus → 发布/订阅模式
  Profile A学会"Windows NSIS Var语法" → 自动推送到Profile B (开发)
  Profile B遇到"远程部署超时" → Profile A获得解决方案

同步策略:
  - 实时推送: 高价值发现(安全/错误修复)
  - 定时批量: 通用知识(最佳实践/模式)
  - 按需拉取: 特定领域查询
"""
import json
import logging
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.knowledge_sync")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class SyncPriority(Enum):
    """同步优先级"""
    CRITICAL = 0    # 安全漏洞/崩溃修复 → 立即推送所有Profile
    HIGH = 1        # 重要发现/错误模式 → 推送相关Profile
    MEDIUM = 2      # 通用知识/最佳实践 → 定时批量
    LOW = 3         # 提示/建议 → 按需拉取


class KnowledgeDomain(Enum):
    """知识领域"""
    DEVELOPMENT = "dev"       # 开发/代码
    DEPLOYMENT = "deploy"     # 部署/运维
    SECURITY = "security"     # 安全
    TESTING = "testing"       # 测试
    PERFORMANCE = "perf"      # 性能
    DEBUGGING = "debug"       # 调试
    GENERAL = "general"       # 通用


@dataclass
class KnowledgeItem:
    """知识条目"""
    id: str = field(default_factory=lambda: f"ki-{int(time.time()*1000)}")
    source_profile: str = ""         # 来源Profile
    domain: KnowledgeDomain = KnowledgeDomain.GENERAL
    priority: SyncPriority = SyncPriority.MEDIUM
    title: str = ""
    content: str = ""
    solution: str = ""               # 解决方案
    tags: List[str] = field(default_factory=list)
    context: str = ""                # 触发上下文
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0            # 过期时间(0=永不过期)
    view_count: int = 0
    helpful_count: int = 0
    
    def mark_helpful(self):
        self.helpful_count += 1
    
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at
    
    def to_summary(self) -> str:
        return f"[{self.domain.value}] {self.title}: {self.content[:80]}"


@dataclass
class ProfileInfo:
    """Profile信息"""
    name: str = ""
    domains: List[KnowledgeDomain] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    last_sync: float = 0
    knowledge_count: int = 0


# ═══════════════════════════════════════════════════════════
# Knowledge Bus — 发布/订阅
# ═══════════════════════════════════════════════════════════

class KnowledgeBus:
    """
    知识总线
    
    发布/订阅模式:
    - Profile发布知识条目
    - 其他Profile根据领域/标签订阅
    - 优先级决定推送时机
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._items: Dict[str, KnowledgeItem] = {}
        self._profiles: Dict[str, ProfileInfo] = {}
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._domain_index: Dict[KnowledgeDomain, List[str]] = defaultdict(list)
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._lock = threading.RLock()
        
        # 持久化存储
        self._storage_path = storage_path or (Path.home() / ".meshctx" / "knowledge_bus.json")
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._load()
        logger.info(f"KnowledgeBus initialized ({len(self._items)} items, {len(self._profiles)} profiles)")
    
    def _load(self):
        """从磁盘加载"""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)
            
            for item_data in data.get("items", []):
                try:
                    item = KnowledgeItem(**item_data)
                    # Convert string to enum for domain/priority
                    if isinstance(getattr(item, 'domain', None), str):
                        try: item.domain = KnowledgeDomain(item.domain)
                        except: pass
                    if isinstance(getattr(item, 'priority', None), str):
                        try: item.priority = SyncPriority(item.priority)
                        except: pass
                    self._items[item.id] = item
                    self._index_item(item)
                except:
                    continue
            
            for profile_data in data.get("profiles", []):
                try:
                    # Convert string domains back to enum
                    if 'domains' in profile_data:
                        profile_data['domains'] = [
                            KnowledgeDomain(d) if isinstance(d, str) else d
                            for d in profile_data['domains']
                        ]
                    profile = ProfileInfo(**profile_data)
                    self._profiles[profile.name] = profile
                except:
                    continue
        except Exception as e:
            logger.error(f"Failed to load knowledge bus: {e}")
    
    def _save(self):
        """持久化到磁盘"""
        try:
            data = {
                "items": [
                    {
                        "id": item.id,
                        "source_profile": item.source_profile,
                        "domain": (item.domain.value if hasattr(item.domain, "value") else item.domain),
                        "priority": (item.priority.value if hasattr(item.priority, "value") else item.priority),
                        "title": item.title,
                        "content": item.content,
                        "solution": item.solution,
                        "tags": item.tags,
                        "context": item.context,
                        "created_at": item.created_at,
                        "expires_at": item.expires_at,
                        "view_count": item.view_count,
                        "helpful_count": item.helpful_count,
                    }
                    for item in self._items.values()
                ],
                "profiles": [
                    {
                        "name": p.name,
                        "domains": [(d.value if hasattr(d, "value") else d) for d in p.domains],
                        "tags": p.tags,
                        "last_sync": p.last_sync,
                        "knowledge_count": p.knowledge_count,
                    }
                    for p in self._profiles.values()
                ],
            }
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save knowledge bus: {e}")
    
    def _index_item(self, item: KnowledgeItem):
        """索引知识条目"""
        domain = item.domain
        if isinstance(domain, str):
            domain = KnowledgeDomain(domain)
        self._domain_index[domain].append(item.id)
        for tag in item.tags:
            self._tag_index[tag.lower()].append(item.id)
    
    # ═══ 发布 ═══
    
    def publish(self, item: KnowledgeItem) -> str:
        """发布知识条目"""
        with self._lock:
            self._items[item.id] = item
            self._index_item(item)
            
            # 更新Profile统计
            if item.source_profile:
                profile = self._profiles.get(item.source_profile)
                if profile:
                    profile.knowledge_count += 1
                    profile.last_sync = time.time()
            
            self._save()
            
            # 通知订阅者
            self._notify(item)
            
            logger.info(f"Published: {item.to_summary()}")
            return item.id
    
    def _notify(self, item: KnowledgeItem):
        """通知相关订阅者"""
        notified = set()
        
        # 按领域通知
        for sub_profile in self._get_relevant_profiles(item):
            if sub_profile.name not in notified:
                notified.add(sub_profile.name)
                for callback in self._subscribers.get(sub_profile.name, []):
                    try:
                        callback(item)
                    except Exception as e:
                        logger.error(f"Subscriber callback failed: {e}")
    
    def _get_relevant_profiles(self, item: KnowledgeItem) -> List[ProfileInfo]:
        """获取相关Profile"""
        relevant = []
        for profile in self._profiles.values():
            if profile.name == item.source_profile:
                continue
            # 领域匹配
            if item.domain in profile.domains or KnowledgeDomain.GENERAL in profile.domains:
                relevant.append(profile)
                continue
            # 标签匹配
            if any(t.lower() in [tt.lower() for tt in profile.tags] for t in item.tags):
                relevant.append(profile)
        
        return relevant
    
    # ═══ 订阅 ═══
    
    def subscribe(self, profile_name: str, callback: Callable):
        """订阅知识更新"""
        with self._lock:
            self._subscribers[profile_name].append(callback)
            if profile_name not in self._profiles:
                self._profiles[profile_name] = ProfileInfo(name=profile_name)
    
    def register_profile(self, profile: ProfileInfo):
        """注册Profile"""
        with self._lock:
            self._profiles[profile.name] = profile
            self._save()
    
    # ═══ 查询 ═══
    
    def query(self, 
              domain: Optional[KnowledgeDomain] = None,
              tags: Optional[List[str]] = None,
              priority: Optional[SyncPriority] = None,
              limit: int = 20,
              exclude_profile: Optional[str] = None,
              sort_by_helpful: bool = True) -> List[KnowledgeItem]:
        """查询知识"""
        candidates = set()
        
        # 按领域
        if domain:
            domain_key = KnowledgeDomain(domain) if isinstance(domain, str) else domain
            if domain_key in self._domain_index:
                candidates.update(self._domain_index[domain_key])
        else:
            candidates.update(self._items.keys())
        
        # 按标签过滤
        if tags:
            tag_ids = set()
            for tag in tags:
                tag_ids.update(self._tag_index.get(tag.lower(), []))
            if domain:  # 交集
                candidates &= tag_ids
            else:
                candidates = tag_ids
        
        # 获取items
        items = []
        for item_id in candidates:
            item = self._items.get(item_id)
            if item is None:
                continue
            if item.is_expired():
                continue
            if exclude_profile and item.source_profile == exclude_profile:
                continue
            if priority and item.priority != priority:
                continue
            items.append(item)
        
        # 排序
        if sort_by_helpful:
            items.sort(key=lambda i: ((i.priority.value if hasattr(i.priority, "value") else i.priority), -i.helpful_count, -i.created_at))
        else:
            items.sort(key=lambda i: ((i.priority.value if hasattr(i.priority, "value") else i.priority), -i.created_at))
        
        return items[:limit]
    
    def search(self, query: str, limit: int = 10) -> List[KnowledgeItem]:
        """全文搜索"""
        q = query.lower()
        results = []
        for item in self._items.values():
            score = 0
            if q in item.title.lower():
                score += 10
            if q in item.content.lower():
                score += 5
            if q in item.solution.lower():
                score += 3
            if any(q in tag.lower() for tag in item.tags):
                score += 2
            if score > 0:
                results.append((score, item))
        
        results.sort(key=lambda x: -x[0])
        return [item for _, item in results[:limit]]
    
    def get_for_profile(self, profile_name: str, limit: int = 10) -> List[KnowledgeItem]:
        """获取对特定Profile有用的知识"""
        profile = self._profiles.get(profile_name)
        if not profile:
            return []
        
        items = []
        for item in self._items.values():
            if item.source_profile == profile_name:
                continue
            if item.domain in profile.domains or any(
                tag.lower() in [t.lower() for t in profile.tags] 
                for tag in item.tags
            ):
                items.append(item)
        
        items.sort(key=lambda i: ((i.priority.value if hasattr(i.priority, "value") else i.priority), -i.created_at))
        return items[:limit]
    
    def mark_helpful(self, item_id: str) -> bool:
        """标记为有用"""
        with self._lock:
            item = self._items.get(item_id)
            if item:
                item.mark_helpful()
                self._save()
                return True
        return False
    
    def cleanup_expired(self) -> int:
        """清理过期条目"""
        with self._lock:
            expired = [iid for iid, item in self._items.items() if item.is_expired()]
            for iid in expired:
                del self._items[iid]
            if expired:
                self._save()
            return len(expired)
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_items": len(self._items),
            "total_profiles": len(self._profiles),
            "by_domain": {(d.value if hasattr(d,"value") else d): len(ids) for d, ids in self._domain_index.items()},
            "by_priority": {
                p.name: sum(1 for i in self._items.values() if i.priority == p)
                for p in SyncPriority
            },
            "top_tags": sorted(
                [(tag, len(ids)) for tag, ids in self._tag_index.items()],
                key=lambda x: -x[1]
            )[:10],
            "active_profiles": [p.name for p in self._profiles.values() if p.knowledge_count > 0],
        }


# ═══════════════════════════════════════════════════════════
# 跨Agent同步协调器
# ═══════════════════════════════════════════════════════════

class CrossAgentSyncEngine:
    """
    跨Agent知识同步引擎
    
    自动化知识流转:
    1. 监听Feedback Loop → 提取可复用知识
    2. 发布到KnowledgeBus
    3. 推送至相关Profile
    4. 收集反馈→优化相关性
    """
    
    def __init__(self, knowledge_bus: Optional[KnowledgeBus] = None):
        self.bus = knowledge_bus or KnowledgeBus()
        self._sync_history: deque = deque(maxlen=100)
    
    def learn_from_error(self, profile_name: str, error_type: str, 
                         error_message: str, solution: str) -> KnowledgeItem:
        """从错误中学习"""
        # 错误类型→知识领域
        domain_map = {
            "PERMISSION": KnowledgeDomain.SECURITY,
            "TIMEOUT": KnowledgeDomain.PERFORMANCE,
            "NETWORK": KnowledgeDomain.DEPLOYMENT,
            "NOT_FOUND": KnowledgeDomain.DEPLOYMENT,
            "MEMORY": KnowledgeDomain.PERFORMANCE,
            "SYNTAX": KnowledgeDomain.DEVELOPMENT,
        }
        domain = domain_map.get(error_type, KnowledgeDomain.DEBUGGING)
        
        priority_map = {
            "PERMISSION": SyncPriority.CRITICAL,
            "MEMORY": SyncPriority.HIGH,
            "NETWORK": SyncPriority.HIGH,
        }
        priority = priority_map.get(error_type, SyncPriority.MEDIUM)
        
        item = KnowledgeItem(
            source_profile=profile_name,
            domain=domain,
            priority=priority,
            title=f"{error_type}: {error_message[:60]}",
            content=error_message,
            solution=solution,
            tags=[error_type.lower(), profile_name],
            context=f"Auto-generated from error in {profile_name}",
        )
        
        self.bus.publish(item)
        self._sync_history.append(("learn_from_error", item.id))
        return item
    
    def learn_from_pattern(self, profile_name: str, pattern_name: str,
                           description: str, best_practice: str) -> KnowledgeItem:
        """从模式发现中学习"""
        item = KnowledgeItem(
            source_profile=profile_name,
            domain=KnowledgeDomain.GENERAL,
            priority=SyncPriority.MEDIUM,
            title=pattern_name,
            content=description,
            solution=best_practice,
            tags=["pattern", pattern_name.lower().replace(" ", "_"), profile_name],
            context=f"Pattern discovered in {profile_name}",
        )
        
        self.bus.publish(item)
        return item
    
    def sync_to_profile(self, target_profile: str, limit: int = 10) -> List[KnowledgeItem]:
        """同步知识到目标Profile"""
        items = self.bus.get_for_profile(target_profile, limit)
        
        for item in items:
            item.view_count += 1
        
        self._sync_history.append(("sync", target_profile, len(items)))
        return items
    
    def get_cross_agent_insights(self, profile_name: str) -> List[str]:
        """生成跨Agent洞察"""
        items = self.bus.get_for_profile(profile_name, 5)
        insights = []
        
        for item in items:
            insights.append(
                f"📡 [{item.source_profile}] {item.title}\n"
                f"   → {item.solution[:100]}"
            )
        
        return insights
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "bus": self.bus.get_stats(),
            "sync_count": len(self._sync_history),
            "last_syncs": list(self._sync_history)[-5:],
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_bus: Optional[KnowledgeBus] = None
_sync_engine: Optional[CrossAgentSyncEngine] = None


def get_knowledge_bus(storage_path: Optional[Path] = None) -> KnowledgeBus:
    global _bus
    if _bus is None:
        _bus = KnowledgeBus(storage_path)
    return _bus


def get_sync_engine() -> CrossAgentSyncEngine:
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = CrossAgentSyncEngine()
    return _sync_engine
