"""
meshctx v1.0 自愈引擎 — Self-Healing Engine

核心能力:
- 插件健康监控 (心跳检测)
- 自动恢复 (重启失败插件)
- 熔断器 (连续失败自动隔离)
- 降级策略 (核心功能优先保证)
- 告警通知 (关键事件推送)

这是 meshctx 实现真正 24/7 自主运行的关键。
"""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .kernel import Event, EventPriority, Plugin, PluginInfo, PluginState

logger = logging.getLogger("meshctx.healer")


# ═══════════════════════════════════════════════════════════
# 错误分类系统
# ═══════════════════════════════════════════════════════════

class ErrorClass(Enum):
    """错误分类: transient(瞬态) vs permanent(永久)"""
    TRANSIENT = "transient"       # 可自动恢复 (网络抖动、资源暂时不足)
    PERMANENT = "permanent"       # 需要人工介入 (配置错误、权限缺失)
    UNKNOWN = "unknown"           # 待分类


@dataclass
class ErrorPattern:
    """学习的错误模式"""
    signature: str = ""                 # 错误签名 (关键词hash)
    error_class: ErrorClass = ErrorClass.UNKNOWN
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    auto_recover_success: int = 0       # 自动恢复成功次数
    auto_recover_attempts: int = 0      # 自动恢复尝试次数
    auto_recover_rate: float = 0.0      # 自动恢复成功率
    notify_needed: bool = False         # 是否需要通知人工


class ErrorLearner:
    """
    错误学习器 — 从自我修复中学习
    
    功能:
    - 记录错误模式 → 改进预测
    - transient vs permanent 自动分类
    - 自动恢复成功率追踪
    - 向HealerPlugin提供改进建议
    """
    
    def __init__(self):
        self._patterns: Dict[str, ErrorPattern] = {}
        self._history: deque = deque(maxlen=1000)
        
        # transient 关键词 — 可自动恢复
        self._transient_keywords = {
            "timeout", "connection", "reset", "refused", "unreachable",
            "temporarily", "retry", "throttl", "rate_limit", "too_many",
            "overflow", "busy", "unavailable", "interrupted", "timed out",
            "econnreset", "econnrefused", "eagain", "would block",
        }
        
        # permanent 关键词 — 需要人工介入
        self._permanent_keywords = {
            "permission", "denied", "forbidden", "unauthorized", "invalid",
            "not found", "not exist", "cannot find", "misconfig",
            "no such", "doesn't exist", "does not exist", "missing",
            "syntax error", "illegal", "disabled", "deprecated",
        }
        
        # config
        self.min_samples_for_classification = 3
        self.min_recover_rate_for_auto = 0.5   # 成功率≥50%继续自动修复
        
    def classify(self, error_msg: str) -> ErrorClass:
        """自动分类错误"""
        error_lower = error_msg.lower()
        
        # 检查permanent关键词
        for kw in self._permanent_keywords:
            if kw in error_lower:
                return ErrorClass.PERMANENT
        
        # 检查transient关键词
        for kw in self._transient_keywords:
            if kw in error_lower:
                return ErrorClass.TRANSIENT
        
        return ErrorClass.UNKNOWN
    
    def _make_signature(self, error_msg: str) -> str:
        """从错误消息提取签名"""
        error_lower = error_msg.lower().strip()
        # 取前50个字符作为签名
        return error_lower[:50]
    
    def record(self, plugin: str, error_msg: str, auto_recover_success: Optional[bool] = None) -> ErrorClass:
        """记录错误并返回分类"""
        error_class = self.classify(error_msg)
        signature = self._make_signature(error_msg)
        
        now = time.time()
        if signature not in self._patterns:
            self._patterns[signature] = ErrorPattern(
                signature=signature,
                error_class=error_class,
                first_seen=now,
            )
        
        pattern = self._patterns[signature]
        pattern.count += 1
        pattern.last_seen = now
        
        # 更新error_class (如果积累足够样本)
        if pattern.count >= self.min_samples_for_classification:
            pattern.error_class = error_class
        
        # 记录恢复结果
        if auto_recover_success is not None:
            pattern.auto_recover_attempts += 1
            if auto_recover_success:
                pattern.auto_recover_success += 1
            pattern.auto_recover_rate = (
                pattern.auto_recover_success / max(1, pattern.auto_recover_attempts)
            )
            pattern.notify_needed = pattern.auto_recover_rate < self.min_recover_rate_for_auto
        
        # 加入历史
        self._history.append({
            "timestamp": now,
            "plugin": plugin,
            "error": error_msg,
            "class": error_class.value,
            "auto_recover_success": auto_recover_success,
        })
        
        return error_class
    
    def should_auto_recover(self, error_msg: str) -> bool:
        """是否应该自动恢复"""
        error_class = self.classify(error_msg)
        if error_class == ErrorClass.PERMANENT:
            return False
        
        signature = self._make_signature(error_msg)
        pattern = self._patterns.get(signature)
        
        if pattern and pattern.notify_needed:
            return False
        
        if pattern and pattern.auto_recover_attempts >= 5:
            return pattern.auto_recover_rate >= self.min_recover_rate_for_auto
        
        return True  # 新错误默认尝试自动恢复
    
    def get_known_patterns(self, top_k: int = 20) -> List[Dict]:
        """获取已知错误模式"""
        sorted_patterns = sorted(
            self._patterns.values(),
            key=lambda p: p.count,
            reverse=True,
        )
        return [
            {
                "signature": p.signature,
                "error_class": p.error_class.value,
                "count": p.count,
                "auto_recover_rate": round(p.auto_recover_rate, 2),
                "notify_needed": p.notify_needed,
                "last_seen": p.last_seen,
            }
            for p in sorted_patterns[:top_k]
        ]
    
    def get_stats(self) -> Dict:
        """获取学习统计"""
        total = len(self._patterns)
        transient = sum(1 for p in self._patterns.values() if p.error_class == ErrorClass.TRANSIENT)
        permanent = sum(1 for p in self._patterns.values() if p.error_class == ErrorClass.PERMANENT)
        unknown = sum(1 for p in self._patterns.values() if p.error_class == ErrorClass.UNKNOWN)
        return {
            "total_patterns": total,
            "transient": transient,
            "permanent": permanent,
            "unknown": unknown,
            "history_size": len(self._history),
            "recent": list(self._history)[-5:] if self._history else [],
        }


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"      # 部分功能降级
    UNSTABLE = "unstable"      # 故障恢复中
    CRITICAL = "critical"      # 核心功能异常


class CircuitState(Enum):
    CLOSED = "closed"          # 正常
    OPEN = "open"              # 熔断
    HALF_OPEN = "half_open"    # 测试恢复


@dataclass
class PluginHealth:
    """插件健康状态"""
    name: str
    status: HealthStatus = HealthStatus.HEALTHY
    last_heartbeat: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    total_restarts: int = 0
    last_error: Optional[str] = None
    circuit_state: CircuitState = CircuitState.CLOSED
    restart_count: int = 0
    max_restarts: int = 5
    crash_count: int = 0                 # 崩溃次数
    last_crash_time: float = 0.0         # 最后崩溃时间
    periodic_ping_ok: bool = True        # 周期性ping状态
    ping_failures: int = 0               # ping失败计数


@dataclass
class HealthEvent:
    """健康事件"""
    timestamp: float = field(default_factory=time.time)
    plugin: str = ""
    event_type: str = ""        # heartbeat/failure/recovery/restart
    detail: str = ""
    severity: int = 0           # 0=info, 1=warn, 2=error, 3=critical


class SelfHealingEngine:
    """
    自愈引擎
    
    监控→检测→诊断→修复→验证 闭环
    """
    
    def __init__(self):
        self._plugin_health: Dict[str, PluginHealth] = {}
        self._event_history: deque = deque(maxlen=500)
        self._repair_actions: Dict[str, List[str]] = defaultdict(list)
        
        # 错误学习器
        self._error_learner = ErrorLearner()
        
        # 配置
        self.heartbeat_interval = 30      # 30秒心跳
        self.failure_threshold = 3        # 连续3次失败触发恢复
        self.circuit_threshold = 5        # 5次失败熔断
        self.circuit_timeout = 60         # 60秒后尝试半开
        self.max_restarts = 5             # 最多重启5次
        self.restart_delay = 1.0          # 重启延迟(秒)
        self.max_crash_restarts = 3       # 连续崩溃最多重启3次
        
        # 降级策略: 各插件重要性
        self._critical_plugins = {"memory", "kernel"}
        self._important_plugins = {"metacognition", "agent_loop"}
        self._optional_plugins = {"predictor", "performance"}
        
        # 恢复策略
        self._recovery_strategies = {
            "restart": self._try_restart,
            "reload": self._try_reload,
            "isolate": self._isolate_plugin,
            "degrade": self._degrade_mode,
        }
    
    def register_plugin(self, name: str, critical: bool = False):
        """注册插件监控"""
        self._plugin_health[name] = PluginHealth(name=name)
        if critical:
            self._critical_plugins.add(name)
    
    def heartbeat(self, name: str) -> bool:
        """接收心跳"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        health.last_heartbeat = time.time()
        
        # 半开状态恢复
        if health.circuit_state == CircuitState.HALF_OPEN:
            health.circuit_state = CircuitState.CLOSED
            health.consecutive_failures = 0
            self._log_event(name, "recovery", "熔断器恢复: 半开→关闭")
        
        return True
    
    def report_failure(self, name: str, error: str) -> bool:
        """报告失败"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        health.consecutive_failures += 1
        health.last_error = error
        
        # 使用ErrorLearner分类和记录
        error_class = self._error_learner.record(name, error)
        
        # 熔断判断
        if health.consecutive_failures >= self.circuit_threshold:
            if health.circuit_state != CircuitState.OPEN:
                health.circuit_state = CircuitState.OPEN
                self._log_event(name, "circuit_open", 
                              f"熔断器打开: 连续{health.consecutive_failures}次失败 ({error_class.value})")
                return True  # 需要隔离
        
        # 恢复触发
        if health.consecutive_failures >= self.failure_threshold:
            severity = 2 if name in self._critical_plugins else 1
            self._log_event(name, "failure_threshold",
                          f"连续失败{health.consecutive_failures}次, 触发恢复 ({error_class.value})",
                          severity=severity)
            return True  # 需要恢复
        
        return False
    
    def report_crash(self, name: str, error: str) -> bool:
        """报告插件崩溃 — 使用重启策略"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        health.crash_count += 1
        health.last_crash_time = time.time()
        health.last_error = error
        health.consecutive_failures += 1
        
        # 记录到错误学习器
        self._error_learner.record(name, error)
        
        # 检查是否超过最大崩溃重启次数
        if health.crash_count > self.max_crash_restarts:
            self._log_event(name, "crash_limit",
                          f"崩溃次数{health.crash_count}超过限制{self.max_crash_restarts}, 需要隔离",
                          severity=2)
            return False  # 不再自动重启，需要隔离
        
        self._log_event(name, "crash",
                      f"第{health.crash_count}次崩溃: {error}",
                      severity=2)
        return True  # 可以重启
    
    def periodic_ping(self, name: str) -> bool:
        """周期性健康检查ping"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        now = time.time()
        elapsed = now - health.last_heartbeat
        
        if elapsed > self.heartbeat_interval * 2:
            health.ping_failures += 1
            health.periodic_ping_ok = False
            self._log_event(name, "ping_fail",
                          f"心跳超时({elapsed:.0f}s), ping失败#{health.ping_failures}",
                          severity=1)
            return False
        else:
            health.ping_failures = 0
            health.periodic_ping_ok = True
            return True
    
    def get_status_aggregation(self) -> Dict:
        """状态聚合 — 返回各插件状态汇总"""
        now = time.time()
        total = len(self._plugin_health)
        healthy = 0
        degraded = 0
        unstable = 0
        critical = 0
        crashed = 0
        
        for name, h in self._plugin_health.items():
            if h.circuit_state == CircuitState.OPEN:
                critical += 1
            elif h.crash_count > self.max_crash_restarts:
                crashed += 1
                critical += 1
            elif h.consecutive_failures >= self.failure_threshold:
                unstable += 1
            elif now - h.last_heartbeat > self.heartbeat_interval * 3:
                degraded += 1
            else:
                healthy += 1
        
        return {
            "total": total,
            "healthy": healthy,
            "degraded": degraded,
            "unstable": unstable,
            "critical": critical,
            "crashed": crashed,
            "health_pct": round(healthy / max(1, total) * 100, 1),
        }
    
    def should_restart(self, name: str) -> bool:
        """判断是否应该重启"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        return (health.consecutive_failures >= self.failure_threshold and
                health.restart_count < health.max_restarts)
    
    def should_isolate(self, name: str) -> bool:
        """判断是否应该隔离"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        return (health.circuit_state == CircuitState.OPEN or
                health.restart_count >= health.max_restarts)
    
    async def heal(self, name: str, kernel) -> bool:
        """执行自愈"""
        health = self._plugin_health.get(name)
        if not health:
            return False
        
        # 关键插件优先重启
        if name in self._critical_plugins:
            success = await self._recovery_strategies["restart"](name, kernel)
            if success:
                return True
            # 关键插件重启失败 → 降级模式
            await self._recovery_strategies["degrade"](name, kernel)
            return False
        
        # 重要插件: 重启→重载→隔离
        if name in self._important_plugins:
            if self.should_restart(name):
                return await self._recovery_strategies["restart"](name, kernel)
            elif self.should_isolate(name):
                return await self._recovery_strategies["isolate"](name, kernel)
            return await self._recovery_strategies["reload"](name, kernel)
        
        # 可选插件: 直接隔离
        return await self._recovery_strategies["isolate"](name, kernel)
    
    async def _try_restart(self, name: str, kernel) -> bool:
        """尝试重启插件"""
        health = self._plugin_health[name]
        health.restart_count += 1
        health.total_restarts += 1
        
        self._log_event(name, "restart", f"第{health.restart_count}次重启")
        
        # 卸载
        try:
            await kernel.plugins.unload(name)
        except:
            pass
        
        await asyncio.sleep(self.restart_delay)
        
        # 重新加载
        try:
            success = await kernel.plugins.load(name)
            if success:
                health.consecutive_failures = 0
                health.circuit_state = CircuitState.CLOSED
                health.restart_count = 0
                health.crash_count = 0  # 重置崩溃计数
                self._log_event(name, "recovery", "重启成功")
                return True
        except Exception as e:
            self._log_event(name, "restart_failed", str(e), severity=2)
        
        return False
    
    async def _try_reload(self, name: str, kernel) -> bool:
        """尝试重载(不卸载,重置状态)"""
        plugin = kernel.plugins.get(name)
        if not plugin:
            return False
        
        try:
            # 暂停→恢复
            await plugin.on_pause()
            await asyncio.sleep(0.5)
            await plugin.on_resume()
            self._plugin_health[name].consecutive_failures = 0
            self._log_event(name, "reload", "重载成功")
            return True
        except Exception as e:
            return False
    
    async def _isolate_plugin(self, name: str, kernel) -> bool:
        """隔离故障插件"""
        try:
            await kernel.plugins.unload(name)
            self._log_event(name, "isolated", "插件已隔离", severity=1)
            return True
        except:
            return False
    
    async def _degrade_mode(self, name: str, kernel) -> bool:
        """进入降级模式"""
        self._log_event(name, "degraded", "系统进入降级模式", severity=3)
        
        # 发布降级事件
        await kernel.bus.publish(Event(
            type="system.degraded",
            source="healer",
            priority=EventPriority.CRITICAL,
            data={
                "failed_plugin": name,
                "mode": "degraded",
                "timestamp": time.time(),
            },
        ))
        
        return True
    
    def get_system_health(self) -> Dict[str, Any]:
        """获取整体健康状态"""
        now = time.time()
        plugin_statuses = {}
        
        for name, h in self._plugin_health.items():
            heartbeat_age = now - h.last_heartbeat
            
            if h.circuit_state == CircuitState.OPEN:
                status = HealthStatus.CRITICAL.value
            elif h.crash_count > self.max_crash_restarts:
                status = HealthStatus.CRITICAL.value
            elif h.consecutive_failures >= self.failure_threshold:
                status = HealthStatus.UNSTABLE.value
            elif heartbeat_age > self.heartbeat_interval * 3:
                status = HealthStatus.DEGRADED.value
            else:
                status = HealthStatus.HEALTHY.value
            
            plugin_statuses[name] = {
                "status": status,
                "heartbeat_age": round(heartbeat_age, 1),
                "failures": h.consecutive_failures,
                "restarts": h.total_restarts,
                "circuit": h.circuit_state.value,
                "crashes": h.crash_count,
                "ping_ok": h.periodic_ping_ok,
            }
        
        # 整体状态
        critical_failed = any(
            p["status"] != "healthy"
            for n, p in plugin_statuses.items()
            if n in self._critical_plugins
        )
        
        overall = (HealthStatus.CRITICAL.value if critical_failed
                   else HealthStatus.DEGRADED.value
                   if any(p["status"] == "degraded" for p in plugin_statuses.values())
                   else HealthStatus.HEALTHY.value)
        
        return {
            "overall": overall,
            "plugins": plugin_statuses,
            "aggregation": self.get_status_aggregation(),
            "error_learner": self._error_learner.get_stats(),
            "recent_events": [
                {"time": e.timestamp, "plugin": e.plugin,
                 "type": e.event_type, "detail": e.detail}
                for e in list(self._event_history)[-10:]
            ],
        }
    
    def _log_event(self, plugin: str, event_type: str, detail: str, severity: int = 0):
        event = HealthEvent(
            plugin=plugin,
            event_type=event_type,
            detail=detail,
            severity=severity,
        )
        self._event_history.append(event)
        
        level = {0: logging.INFO, 1: logging.WARNING, 
                 2: logging.ERROR, 3: logging.CRITICAL}.get(severity, logging.INFO)
        logger.log(level, f"[{plugin}] {event_type}: {detail}")


# ═══════════════════════════════════════════════════════════
# 记忆自动压缩器
# ═══════════════════════════════════════════════════════════

class MemoryCompactor:
    """
    记忆自动压缩器
    
    L2→L3: 7天以上的短时记忆压缩到长时记忆
    L3→L4: 30天以上未访问的长时记忆归档
    L4 去重: 相似归档记忆自动合并
    """
    
    def __init__(self):
        self._compaction_count = 0
        self._last_compaction = 0.0
        self.compaction_interval = 3600  # 每小时运行一次
        
    async def compact(self, memory_store) -> Dict[str, int]:
        """
        执行记忆压缩
        
        Returns: {"l2_to_l3": N, "l3_to_l4": N, "deduped": N}
        """
        from .memory_hierarchy import MemoryLevel
        now = time.time()
        results = {"l2_to_l3": 0, "l3_to_l4": 0, "deduped": 0}
        
        # L2→L3: 超过7天的短时记忆
        l2_store = memory_store._stores.get(MemoryLevel.SHORT_TERM, {})
        to_promote = []
        for mid, item in list(l2_store.items()):
            age_days = (now - item.created_at) / 86400
            if age_days > 7 or item.access_count > 10:
                to_promote.append(mid)
        
        for mid in to_promote:
            item = l2_store.pop(mid, None)
            if item:
                item.level = MemoryLevel.LONG_TERM
                item.summary = memory_store._generate_summary(item)
                memory_store._stores[MemoryLevel.LONG_TERM][mid] = item
                results["l2_to_l3"] += 1
        
        # L3→L4: 超过30天未访问
        l3_store = memory_store._stores.get(MemoryLevel.LONG_TERM, {})
        to_archive = []
        for mid, item in list(l3_store.items()):
            idle_days = (now - item.last_accessed) / 86400
            if idle_days > 30:
                to_archive.append(mid)
        
        for mid in to_archive:
            item = l3_store.pop(mid, None)
            if item:
                item.level = MemoryLevel.ARCHIVAL
                memory_store._stores[MemoryLevel.ARCHIVAL][mid] = item
                results["l3_to_l4"] += 1
        
        # L4去重: 合并相似记忆
        l4_store = memory_store._stores.get(MemoryLevel.ARCHIVAL, {})
        deduped = self._deduplicate(l4_store)
        results["deduped"] = deduped
        
        self._compaction_count += 1
        self._last_compaction = now
        
        if sum(results.values()) > 0:
            logger.info(f"记忆压缩完成: {results}")
        
        return results
    
    def _deduplicate(self, store: dict) -> int:
        """去重合并相似记忆"""
        removed = 0
        keys_seen = {}
        
        for mid, item in list(store.items()):
            key = item.key.lower().strip()
            if key in keys_seen:
                # 合并: 保留更新的,更新重要性
                existing_id = keys_seen[key]
                existing = store.get(existing_id)
                if existing and item.last_accessed > existing.last_accessed:
                    del store[existing_id]
                    keys_seen[key] = mid
                    removed += 1
                else:
                    del store[mid]
                    removed += 1
            else:
                keys_seen[key] = mid
        
        return removed


# ═══════════════════════════════════════════════════════════
# 自愈插件
# ═══════════════════════════════════════════════════════════

class HealerPlugin(Plugin):
    """
    自愈插件
    
    功能:
    - 插件心跳监控
    - 自动故障恢复
    - 熔断器
    - 记忆自动压缩
    """
    
    info = PluginInfo(
        name="healer",
        version="1.0.0",
        description="自愈引擎 — 健康监控+自动恢复+熔断+记忆压缩",
        author="meshctx",
    )
    
    def __init__(self):
        self.engine = SelfHealingEngine()
        self.compactor = MemoryCompactor()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._compact_task: Optional[asyncio.Task] = None
    
    async def on_load(self):
        bus = self.kernel.bus
        
        bus.subscribe("plugin.heartbeat", self._on_heartbeat,
                      plugin_name="healer")
        bus.subscribe("plugin.error", self._on_error,
                      plugin_name="healer")
        bus.subscribe("healer.report", self._on_report,
                      plugin_name="healer")
        bus.subscribe("healer.heal", self._on_heal_request,
                      plugin_name="healer")
        
        # 注册所有已加载插件
        for name in self.kernel.plugins.list_active():
            self.engine.register_plugin(name)
        
        # 启动心跳监控
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        # 启动记忆压缩
        self._compact_task = asyncio.create_task(self._compaction_loop())
        
        logger.info("自愈引擎已加载 (监控+恢复+熔断+压缩)")
    
    async def on_unload(self):
        for task in [self._heartbeat_task, self._compact_task]:
            if task:
                task.cancel()
        logger.info("自愈引擎已卸载")
    
    async def _on_heartbeat(self, event: Event):
        name = event.data.get("plugin", "")
        self.engine.heartbeat(name)
    
    async def _on_error(self, event: Event):
        name = event.data.get("plugin", "")
        error = event.data.get("error", "unknown")
        
        needs_healing = self.engine.report_failure(name, error)
        
        if needs_healing:
            await self._auto_heal(name)
    
    async def _on_heal_request(self, event: Event):
        name = event.data.get("plugin", "")
        if name:
            await self._auto_heal(name)
    
    async def _on_report(self, event: Event):
        health = self.engine.get_system_health()
        await self.kernel.bus.publish(Event(
            type="healer.report_result",
            source="healer",
            correlation_id=event.id,
            data=health,
        ))
    
    async def _auto_heal(self, name: str):
        """自动修复"""
        logger.warning(f"自愈引擎: 尝试修复 [{name}]")
        success = await self.engine.heal(name, self.kernel)
        
        # 发布修复结果
        await self.kernel.bus.publish(Event(
            type="healer.action",
            source="healer",
            data={
                "plugin": name,
                "action": "heal",
                "success": success,
                "health": self.engine.get_system_health(),
            },
        ))
    
    async def _heartbeat_loop(self):
        """定期检测所有插件心跳"""
        while True:
            try:
                await asyncio.sleep(self.engine.heartbeat_interval)
                
                # 向每个活跃插件发送心跳检测
                for name in self.kernel.plugins.list_active():
                    await self.kernel.bus.publish(Event(
                        type="plugin.heartbeat_check",
                        source="healer",
                        data={"plugin": name, "timestamp": time.time()},
                    ))
                    
                    # 检查超时
                    health = self.engine._plugin_health.get(name)
                    if health:
                        elapsed = time.time() - health.last_heartbeat
                        if elapsed > self.engine.heartbeat_interval * 3:
                            self.engine.report_failure(name, "heartbeat_timeout")
                            await self._auto_heal(name)
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳循环错误: {e}")
    
    async def _compaction_loop(self):
        """定期记忆压缩"""
        while True:
            try:
                await asyncio.sleep(self.compactor.compaction_interval)
                
                mem_plugin = self.kernel.plugins.get("memory")
                if mem_plugin and hasattr(mem_plugin, 'store'):
                    results = await self.compactor.compact(mem_plugin.store)
                    if sum(results.values()) > 0:
                        await self.kernel.bus.publish(Event(
                            type="memory.compacted",
                            source="healer",
                            data=results,
                        ))
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"压缩循环错误: {e}")
    
    def generate_report(self) -> Dict:
        return {
            "health": self.engine.get_system_health(),
            "compaction": {
                "count": self.compactor._compaction_count,
                "last": self.compactor._last_compaction,
            },
        }
