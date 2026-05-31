"""
meshctx v3.48 — Subconscious Observer Engine (潜意识观察引擎)

解决AI Agent根本性架构缺陷:
- 问题: 所有Agent(含Hermes/meshctx自身)天生被动→等指令
- 社区方案: GitHub Hermes #553 Subconscious Observer + #5712 True Autonomy
- 实现: 后台daemon → 跨session观察 → 模式发现 → 主动注入上下文

三通道观察:
  1. Internal: session历史→模式识别→未完成任务→知识gap
  2. External: 竞品动态→社区热点→技术趋势→安全告警  
  3. Systemic: 错误复发→性能退化→依赖过期→测试覆盖下降

注入机制: Predictor预加载→当前session上下文→nudge提示(不打断)
"""
import asyncio
import json
import logging
import os
import time
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.subconscious")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class NudgePriority(Enum):
    """提示优先级"""
    CRITICAL = 0    # 红色: 安全/崩溃/数据丢失
    HIGH = 1        # 橙色: 重要但非紧急
    MEDIUM = 2      # 黄色: 建议优化
    LOW = 3         # 蓝色: 信息参考
    INSIGHT = 4     # 绿色: 模式发现


class NudgeSource(Enum):
    """提示来源"""
    INTERNAL = "internal"       # session模式发现
    EXTERNAL = "external"       # 竞品/社区/趋势
    SYSTEMIC = "systemic"       # 错误/性能/安全
    MEMORY = "memory"           # 知识图谱发现
    PREDICTIVE = "predictive"   # 时间模式预测


@dataclass
class Nudge:
    """潜意识提示 — 主动注入给当前Agent的上下文"""
    id: str = field(default_factory=lambda: f"nudge-{int(time.time()*1000)}")
    priority: NudgePriority = NudgePriority.MEDIUM
    source: NudgeSource = NudgeSource.INTERNAL
    title: str = ""
    detail: str = ""
    action: str = ""            # 建议的操作
    relevance: float = 0.5      # 与当前上下文的相关度 0-1
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0     # 过期时间
    was_acknowledged: bool = False
    
    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at
    
    def to_context(self) -> str:
        """转为可注入Agent上下文的文本"""
        emoji = {NudgePriority.CRITICAL: "🚨", NudgePriority.HIGH: "⚠️",
                 NudgePriority.MEDIUM: "💡", NudgePriority.LOW: "ℹ️",
                 NudgePriority.INSIGHT: "🔍"}.get(self.priority, "")
        return f"{emoji} [{self.source.value}] {self.title}\n   {self.detail}\n   → {self.action}"


@dataclass
class SessionSnapshot:
    """Session快照 — 用于跨session分析"""
    session_id: str
    profile: str
    started_at: float
    ended_at: float = 0
    message_count: int = 0
    tool_calls: int = 0
    errors: int = 0
    topics: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)
    unfinished_tasks: List[str] = field(default_factory=list)
    model_used: str = ""
    token_count: int = 0


# ═══════════════════════════════════════════════════════════
# Observer Core
# ═══════════════════════════════════════════════════════════

class SubconsciousObserver:
    """
    潜意识观察引擎

    后台常驻 → 周期扫描 → 三通道观察 → 模式发现 → Nudge生成
    每个周期: observe → analyze → generate → inject
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._nudges: List[Nudge] = []
        self._nudge_history: deque = deque(maxlen=200)
        self._sessions: Dict[str, SessionSnapshot] = {}
        self._patterns: Dict[str, Any] = {}
        self._last_scan: float = 0
        self._scan_interval: int = self.config.get("scan_interval", 300)  # 5min默认
        self._max_nudges: int = self.config.get("max_nudges", 5)
        self._enabled_channels = {
            "internal": self.config.get("internal", True),
            "external": self.config.get("external", True),
            "systemic": self.config.get("systemic", True),
            "memory": self.config.get("memory", True),
            "predictive": self.config.get("predictive", True),
        }
        
        # Session数据路径
        home = Path.home()
        self._session_dir = home / ".hermes" / "profiles"
        self._hermes_dir = home / ".hermes"
        
        # 模式检测阈值
        self._pattern_threshold = self.config.get("pattern_threshold", 3)
        
        logger.info(f"SubconsciousObserver initialized (scan_interval={self._scan_interval}s)")

    # ═══ 观察阶段: 三通道扫描 ═══

    def observe_internal(self) -> List[Nudge]:
        """
        通道1: 内部观察
        - 扫描最近session
        - 检测未完成任务
        - 发现重复错误
        - 识别跨session模式
        """
        nudges = []
        
        try:
            # 扫描session目录
            if not self._session_dir.exists():
                return nudges
            
            recent_sessions = []
            cutoff = time.time() - 86400  # 24小时内
            
            for profile_dir in self._session_dir.iterdir():
                if not profile_dir.is_dir():
                    continue
                sessions_dir = profile_dir / "sessions"
                if not sessions_dir.exists():
                    continue
                    
                for session_file in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                    stat = session_file.stat()
                    if stat.st_mtime < cutoff:
                        continue
                    try:
                        with open(session_file, 'r') as f:
                            data = json.load(f)
                        recent_sessions.append({
                            "file": str(session_file),
                            "profile": profile_dir.name,
                            "mtime": stat.st_mtime,
                            "data": data,
                        })
                    except:
                        continue
            
            # 分析最近sessions
            if len(recent_sessions) >= 2:
                # 检测重复出现的topic
                all_messages = []
                for s in recent_sessions:
                    msgs = s.get("data", {}).get("messages", [])
                    for m in msgs[-10:]:  # 最后10条
                        content = m.get("content", "")
                        if isinstance(content, str) and len(content) > 10:
                            all_messages.append(content.lower())
                
                # 模式: 连续3+ session提到同一主题
                topic_counts = defaultdict(int)
                topic_keywords = {
                    "bug": ["bug", "error", "crash", "failed", "broke"],
                    "deploy": ["deploy", "release", "push", "ship"],
                    "test": ["test", "pytest", "coverage", "pass"],
                    "security": ["security", "vuln", "exploit", "cve"],
                    "perf": ["slow", "performance", "timeout", "memory"],
                }
                
                for msg in all_messages:
                    for topic, keywords in topic_keywords.items():
                        if any(kw in msg for kw in keywords):
                            topic_counts[topic] += 1
                
                for topic, count in topic_counts.items():
                    if count >= self._pattern_threshold:
                        nudges.append(Nudge(
                            priority=NudgePriority.HIGH,
                            source=NudgeSource.INTERNAL,
                            title=f"Recurring theme: {topic}",
                            detail=f"Mentioned {count} times in recent {len(recent_sessions)} sessions",
                            action=f"Consider addressing {topic} systematically",
                            relevance=min(1.0, count / 10),
                            expires_at=time.time() + 86400,
                        ))
            
            # 检测未完成任务
            for s in recent_sessions[-5:]:
                msgs = s.get("data", {}).get("messages", [])
                for m in msgs[-3:]:
                    content = m.get("content", "")
                    if isinstance(content, str) and any(phrase in content.lower() for phrase in 
                        ["todo", "fix later", "need to", "remaining", "not done", "unfinished"]):
                        # 提取任务描述
                        snippet = content[:100]
                        nudges.append(Nudge(
                            priority=NudgePriority.MEDIUM,
                            source=NudgeSource.INTERNAL,
                            title="Unfinished task detected",
                            detail=f"Found in session: {snippet}...",
                            action="Review and complete pending work",
                            relevance=0.7,
                            expires_at=time.time() + 43200,
                        ))
                        break
                        
        except Exception as e:
            logger.error(f"Internal observer error: {e}")
        
        return nudges

    def observe_external(self) -> List[Nudge]:
        """
        通道2: 外部观察
        - 竞品GitHub动态
        - HackerNews AI相关话题
        - 安全漏洞披露
        - 依赖更新
        """
        nudges = []
        
        try:
            # 检查是否有竞品情报缓存
            intel_dir = Path.home() / ".meshctx" / "intel"
            if intel_dir.exists():
                for intel_file in sorted(intel_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                    try:
                        with open(intel_file, 'r') as f:
                            intel = json.load(f)
                        title = intel.get("title", "Unknown")
                        source = intel.get("source", "unknown")
                        if intel.get("priority", "").lower() in ("critical", "high"):
                            nudges.append(Nudge(
                                priority=NudgePriority.HIGH if intel.get("priority") == "critical" else NudgePriority.MEDIUM,
                                source=NudgeSource.EXTERNAL,
                                title=f"Intel: {title[:80]}",
                                detail=f"Source: {source} | Updated: {intel.get('updated', '?')}",
                                action=intel.get("action", "Review and assess impact"),
                                relevance=0.6,
                                expires_at=time.time() + 86400,
                            ))
                    except:
                        continue
            
            # 检查依赖过期 (requirements.txt)
            if Path("requirements.txt").exists():
                import subprocess
                try:
                    result = subprocess.run(
                        ["pip", "list", "--outdated", "--format=json"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        outdated = json.loads(result.stdout)
                        if len(outdated) > 5:
                            critical_deps = [d for d in outdated if d.get("name") in 
                                ("fastapi", "uvicorn", "pydantic", "numpy", "playwright")]
                            if critical_deps:
                                nudges.append(Nudge(
                                    priority=NudgePriority.MEDIUM,
                                    source=NudgeSource.EXTERNAL,
                                    title=f"{len(outdated)} packages outdated",
                                    detail=f"Critical: {', '.join(d['name'] for d in critical_deps[:3])}",
                                    action="Run: pip install --upgrade " + " ".join(d['name'] for d in critical_deps[:3]),
                                    relevance=0.5,
                                    expires_at=time.time() + 604800,
                                ))
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"External observer error: {e}")
        
        return nudges

    def observe_systemic(self) -> List[Nudge]:
        """
        通道3: 系统观察
        - 测试失败率趋势
        - 错误模式
        - 性能下降
        - 内存/磁盘
        """
        nudges = []
        
        try:
            # 检查pytest结果
            cache_dir = Path(".pytest_cache")
            if cache_dir.exists():
                last_failed = cache_dir / "v" / "cache" / "lastfailed"
                if last_failed.exists():
                    with open(last_failed, 'r') as f:
                        failed = json.load(f)
                    if len(failed) > 0:
                        nudges.append(Nudge(
                            priority=NudgePriority.HIGH if len(failed) > 5 else NudgePriority.MEDIUM,
                            source=NudgeSource.SYSTEMIC,
                            title=f"{len(failed)} tests failing",
                            detail=f"Last run failures: {', '.join(list(failed.keys())[:3])}...",
                            action="Run full test suite and fix failing tests",
                            relevance=0.8,
                            expires_at=time.time() + 43200,
                        ))
            
            # 检查错误日志
            log_file = Path("logs") / "meshctx.log"
            if log_file.exists():
                # 统计最近1小时的ERROR
                cutoff = datetime.now() - timedelta(hours=1)
                errors = []
                with open(log_file, 'r') as f:
                    for line in f:
                        if "ERROR" in line:
                            errors.append(line)
                
                if len(errors) > 10:
                    # 聚类错误类型
                    error_types = defaultdict(int)
                    for e in errors[-50:]:
                        for pattern in ["ModuleNotFoundError", "AttributeError", "KeyError", 
                                        "Timeout", "ConnectionError", "PermissionError"]:
                            if pattern in e:
                                error_types[pattern] += 1
                    
                    top_error = max(error_types, key=error_types.get) if error_types else "Unknown"
                    nudges.append(Nudge(
                        priority=NudgePriority.HIGH,
                        source=NudgeSource.SYSTEMIC,
                        title=f"{len(errors)} errors in last hour",
                        detail=f"Top error: {top_error} ({error_types[top_error]}x)",
                        action=f"Investigate and fix {top_error} pattern",
                        relevance=0.9,
                        expires_at=time.time() + 21600,
                    ))
                    
        except Exception as e:
            logger.error(f"Systemic observer error: {e}")
        
        return nudges

    def observe_memory(self) -> List[Nudge]:
        """
        通道4: 记忆观察
        - 知识图谱gap检测
        - 遗忘曲线预警
        - 跨session知识迁移机会
        """
        nudges = []
        
        try:
            # 检查知识图谱
            kg_file = Path.home() / ".meshctx" / "knowledge_graph.json"
            if kg_file.exists():
                with open(kg_file, 'r') as f:
                    kg = json.load(f)
                
                nodes = kg.get("nodes", [])
                edges = kg.get("edges", [])
                
                # 检测孤立节点(知识gap)
                connected_nodes = set()
                for e in edges:
                    connected_nodes.add(e.get("source", ""))
                    connected_nodes.add(e.get("target", ""))
                
                isolated = [n for n in nodes if n.get("id") not in connected_nodes]
                if len(isolated) > 3:
                    nudges.append(Nudge(
                        priority=NudgePriority.INSIGHT,
                        source=NudgeSource.MEMORY,
                        title=f"{len(isolated)} isolated knowledge nodes",
                        detail="Unconnected concepts may represent learning gaps",
                        action="Review knowledge graph for missing connections",
                        relevance=0.4,
                    ))
                
                # 检测最近新增节点(学习活跃度)
                recent_nodes = [n for n in nodes if n.get("created_at", 0) > time.time() - 86400]
                if len(recent_nodes) > 5:
                    nudges.append(Nudge(
                        priority=NudgePriority.INSIGHT,
                        source=NudgeSource.MEMORY,
                        title=f"Active learning: {len(recent_nodes)} new concepts in 24h",
                        detail=f"Recent: {', '.join(n.get('label','?') for n in recent_nodes[:3])}",
                        action="Knowledge graph is growing healthily",
                        relevance=0.3,
                    ))
                    
        except Exception as e:
            logger.error(f"Memory observer error: {e}")
        
        return nudges

    def observe_predictive(self) -> List[Nudge]:
        """
        通道5: 预测观察
        - 时间模式: 用户通常在何时做什么
        - 周期性任务提醒
        - 习惯形成检测
        """
        nudges = []
        
        try:
            # 简单的时间模式检测
            now = datetime.now()
            hour = now.hour
            weekday = now.weekday()
            
            # 基于时间的提醒模式
            time_patterns = {
                (9, 0): ("Morning standup", "Check yesterday's progress and plan today"),
                (12, 0): ("Midday check", "Review morning output, adjust priorities"),
                (17, 0): ("EOD wrap-up", "Commit changes, update CHANGELOG, push"),
                (23, 0): ("Daily report", "Send daily report to Feishu"),
            }
            
            for (target_hour, target_min), (title, action) in time_patterns.items():
                if hour == target_hour and 0 <= now.minute <= 30:
                    nudges.append(Nudge(
                        priority=NudgePriority.LOW,
                        source=NudgeSource.PREDICTIVE,
                        title=title,
                        detail=f"It's {now.strftime('%H:%M')} — time for a routine check",
                        action=action,
                        relevance=0.4,
                        expires_at=time.time() + 7200,
                    ))
                    break  # 只触发第一个匹配
            
            # 每周一提醒
            if weekday == 0 and 8 <= hour <= 10:
                nudges.append(Nudge(
                    priority=NudgePriority.LOW,
                    source=NudgeSource.PREDICTIVE,
                    title="Weekly planning",
                    detail="Monday morning — good time for weekly goals review",
                    action="Review sprint goals and update roadmap",
                    relevance=0.3,
                    expires_at=time.time() + 14400,
                ))
                
        except Exception as e:
            logger.error(f"Predictive observer error: {e}")
        
        return nudges

    # ═══ 分析阶段: 模式发现 ═══

    def analyze(self, all_nudges: List[Nudge]) -> List[Nudge]:
        """去重+优先级排序+过期清理"""
        # 清理过期
        self._nudges = [n for n in self._nudges if not n.is_expired()]
        
        # 去重(同title的只保留最新的)
        seen_titles = {n.title for n in self._nudges}
        filtered = []
        for n in all_nudges:
            if n.title not in seen_titles:
                seen_titles.add(n.title)
                filtered.append(n)
        
        # 按优先级排序
        filtered.sort(key=lambda n: (n.priority.value, -n.relevance))
        
        # 保留前N条
        return filtered[:self._max_nudges]

    # ═══ 注入阶段: 上下文注入 ═══

    def inject(self, nudges: List[Nudge]) -> str:
        """生成可注入Agent上下文的nudge文本"""
        if not nudges:
            return ""
        
        self._nudges.extend(nudges)
        self._nudge_history.extend(nudges)
        
        lines = ["\n## 🧠 Subconscious Observer (潜意识观察)", ""]
        
        priority_groups = defaultdict(list)
        for n in nudges:
            priority_groups[n.priority].append(n)
        
        for priority in [NudgePriority.CRITICAL, NudgePriority.HIGH, 
                        NudgePriority.MEDIUM, NudgePriority.LOW, NudgePriority.INSIGHT]:
            if priority in priority_groups:
                for n in priority_groups[priority]:
                    lines.append(n.to_context())
        
        lines.append(f"\n({len(nudges)} observations from {len(priority_groups)} priority levels)")
        return "\n".join(lines)

    # ═══ 主循环: 周期执行 ═══

    async def cycle(self) -> List[Nudge]:
        """执行一次完整的观察→分析→注入周期"""
        all_nudges = []
        
        # 并行观察
        channels = {
            "internal": self.observe_internal,
            "external": self.observe_external,
            "systemic": self.observe_systemic,
            "memory": self.observe_memory,
            "predictive": self.observe_predictive,
        }
        
        for channel_name, observer_fn in channels.items():
            if self._enabled_channels.get(channel_name, True):
                try:
                    # 在线程池中运行(避免阻塞事件循环)
                    loop = asyncio.get_event_loop()
                    nudges = await loop.run_in_executor(None, observer_fn)
                    all_nudges.extend(nudges)
                except Exception as e:
                    logger.error(f"Channel {channel_name} failed: {e}")
        
        # 分析+注入
        filtered = self.analyze(all_nudges)
        context = self.inject(filtered)
        
        self._last_scan = time.time()
        
        if filtered:
            logger.info(f"Cycle complete: {len(all_nudges)} raw → {len(filtered)} nudges")
        else:
            logger.debug(f"Cycle complete: {len(all_nudges)} raw → 0 nudges (all duplicate/expired)")
        
        return filtered

    def get_stats(self) -> Dict[str, Any]:
        """获取观察者统计"""
        return {
            "total_nudges_generated": len(self._nudge_history),
            "active_nudges": len(self._nudges),
            "last_scan": self._last_scan,
            "channels_enabled": self._enabled_channels,
            "scan_interval": self._scan_interval,
            "history_by_source": {
                source.value: sum(1 for n in self._nudge_history if n.source == source)
                for source in NudgeSource
            },
            "history_by_priority": {
                priority.name: sum(1 for n in self._nudge_history if n.priority == priority)
                for priority in NudgePriority
            },
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_observer: Optional[SubconsciousObserver] = None


def get_observer(config: Optional[Dict] = None) -> SubconsciousObserver:
    """获取全局观察者实例"""
    global _observer
    if _observer is None:
        _observer = SubconsciousObserver(config)
    return _observer
