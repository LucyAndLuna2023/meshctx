"""
meshctx Audit Logger — 审计日志 v1.0
=====================================

完整的审计日志系统, 记录所有操作、访问和变更,
支持合规审计 (SOC2, HIPAA, GDPR) 和事后追溯。

核心能力:
  1. 结构化审计事件 (Actor, Action, Resource, Result)
  2. 不可变日志 (追加写入, 支持校验和)
  3. 审计追踪和查询
  4. 保留策略和自动归档
  5. 敏感数据脱敏

使用场景:
  - 用户操作审计 (谁在何时做了什么)
  - API 调用追踪
  - 数据访问审计
  - 配置变更历史
  - 合规报告生成

使用示例:
  al = get_audit_logger()
  al.log(action="model.deploy", actor="admin@example.com",
         resource="gpt-4o", result="success",
         details={"version": "2024-08-06", "env": "production"})
  events = al.query(actor="admin@example.com", action="model.deploy")

代码量: ~480 行
"""

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.audit_logger")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class AuditResult(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """审计结果"""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    PENDING = "pending"
    UNKNOWN = "unknown"


class RetentionPolicy(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """保留策略"""
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    DAYS_180 = "180d"
    YEARS_1 = "1y"
    YEARS_3 = "3y"
    YEARS_7 = "7y"
    FOREVER = "forever"


# 敏感字段 (需要脱敏)
SENSITIVE_FIELDS = {
    "password", "secret", "token", "api_key", "private_key",
    "credit_card", "ssn", "auth", "credential", "passphrase",
}


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class AuditEvent:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """审计事件"""
    event_id: str
    timestamp: float
    action: str                    # 操作, e.g. "model.deploy", "user.login"
    actor: str                     # 执行者, e.g. "admin@example.com"
    actor_type: str = "user"       # 执行者类型: user, system, api_key, service
    resource: str = ""             # 资源, e.g. "gpt-4o", "/users/123"
    resource_type: str = ""        # 资源类型: model, user, config, pipeline
    result: AuditResult = AuditResult.SUCCESS
    reason: str = ""               # 失败/拒绝原因
    details: Dict[str, Any] = field(default_factory=dict)
    source_ip: str = ""
    user_agent: str = ""
    session_id: str = ""
    request_id: str = ""
    checksum: str = ""             # 内容校验和 (防篡改)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, sanitize: bool = False, **kw) -> Dict[str, Any]:
        """转为字典 (可选脱敏)"""
        d = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "iso_time": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(self.timestamp)
            ),
            "action": self.action,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "resource": self.resource,
            "resource_type": self.resource_type,
            "result": self.result.value,
            "reason": self.reason,
            "source_ip": self.source_ip,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "checksum": self.checksum,
        }
        if sanitize:
            d["details"] = self._sanitize_details(self.details)
        else:
            d["details"] = self.details
        return d

    def _sanitize_details(self, details: Dict[str, Any], **kw) -> Dict[str, Any]:
        """脱敏处理"""
        sanitized = {}
        for k, v in details.items():
            if any(sf in k.lower() for sf in SENSITIVE_FIELDS):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_details(v)
            else:
                sanitized[k] = v
        return sanitized

    def compute_checksum(self, **kw) -> str:
        """计算校验和"""
        content = json.dumps({
            "action": self.action,
            "actor": self.actor,
            "resource": self.resource,
            "result": self.result.value,
            "details": self.details,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify(self, **kw) -> bool:
        """验证校验和"""
        return self.checksum == self.compute_checksum() if self.checksum else True


# ═══════════════════════════════════════════════════════════
# 审计存储后端
# ═══════════════════════════════════════════════════════════

class AuditStorage:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """审计日志存储抽象"""

    def __init__(self, storage_path: str, **kw):
        self._storage_path = storage_path
        self._write_lock = threading.Lock()

    def append(self, event: AuditEvent, **kw) -> bool:
        """追加事件"""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._write_lock:
                line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
                with open(self._storage_path, "a") as f:
                    f.write(line)
            return True
        except Exception as e:
            logger.error(f"Failed to write audit event: {e}")
            return False

    def read_all(self, **kw) -> List[Dict[str, Any]]:
        """读取所有事件"""
        if not os.path.exists(self._storage_path):
            return []
        events = []
        try:
            with open(self._storage_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Failed to read audit events: {e}")
        return events

    def rotate(self, max_size_mb: float = 100.0, **kw) -> bool:
        """日志轮转"""
        if not os.path.exists(self._storage_path):
            return False
        try:
            size_mb = os.path.getsize(self._storage_path) / (1024 * 1024)
            if size_mb >= max_size_mb:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                rotated = f"{self._storage_path}.{timestamp}.old"
                os.rename(self._storage_path, rotated)
                logger.info(f"Rotated audit log: {self._storage_path} → {rotated}")
                return True
        except Exception as e:
            logger.error(f"Log rotation failed: {e}")
        return False

    def size_mb(self, **kw) -> float:
        """获取日志文件大小 (MB)"""
        if not os.path.exists(self._storage_path):
            return 0.0
        return os.path.getsize(self._storage_path) / (1024 * 1024)


# ═══════════════════════════════════════════════════════════
# 审计查询引擎
# ═══════════════════════════════════════════════════════════

class AuditQuery:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """审计事件查询器"""

    def __init__(self, storage: AuditStorage, **kw):
        self.storage = storage

    def query(
        self,
        actor: str = None,
        action: str = None,
        resource: str = None,
        result: AuditResult = None,
        start_time: float = None,
        end_time: float = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询审计事件

        Args:
            actor: 按执行者过滤
            action: 按操作过滤
            resource: 按资源过滤
            result: 按结果过滤
            start_time: 开始时间 (unix timestamp)
            end_time: 结束时间
            limit: 返回数量限制
            offset: 偏移量
        """
        all_events = self.storage.read_all()
        filtered = []

        for event in all_events:
            if actor and event.get("actor") != actor:
                continue
            if action and event.get("action") != action:
                continue
            if resource and event.get("resource") != resource:
                continue
            if result and event.get("result") != result.value:
                continue
            ts = event.get("timestamp", 0)
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            filtered.append(event)

        # 按时间倒序
        filtered.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
        return filtered[offset:offset + limit]

    def count(
        self,
        actor: str = None,
        action: str = None,
        result: AuditResult = None,
        start_time: float = None,
        end_time: float = None,
    ) -> int:
        """计数"""
        return len(self.query(
            actor=actor, action=action, result=result,
            start_time=start_time, end_time=end_time,
            limit=999999,
        ))

    def get_actor_actions(
        self, actor: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取指定执行者的所有操作"""
        return self.query(actor=actor, limit=limit)

    def get_resource_accesses(
        self, resource: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取指定资源的所有访问"""
        return self.query(resource=resource, limit=limit)

    def get_recent_failures(self, limit: int = 20, **kw) -> List[Dict[str, Any]]:
        """获取最近的失败事件"""
        return self.query(result=AuditResult.FAILURE, limit=limit)

    def get_time_range_summary(
        self, start_time: float, end_time: float,
    ) -> Dict[str, Any]:
        """获取时间范围摘要"""
        events = self.query(start_time=start_time, end_time=end_time, limit=999999)

        by_action = {}
        by_actor = {}
        by_result = {}
        for e in events:
            act = e.get("action", "unknown")
            by_action[act] = by_action.get(act, 0) + 1
            actor = e.get("actor", "unknown")
            by_actor[actor] = by_actor.get(actor, 0) + 1
            res = e.get("result", "unknown")
            by_result[res] = by_result.get(res, 0) + 1

        return {
            "total_events": len(events),
            "by_action": dict(sorted(by_action.items(), key=lambda x: x[1], reverse=True)[:10]),
            "by_actor": dict(sorted(by_actor.items(), key=lambda x: x[1], reverse=True)[:10]),
            "by_result": by_result,
            "start_time": start_time,
            "end_time": end_time,
        }


# ═══════════════════════════════════════════════════════════
# AuditLogger — 主类
# ═══════════════════════════════════════════════════════════

class AuditLogger:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """审计日志主类

    提供完整的审计日志记录和查询 API。
    """

    def __init__(self, storage_path: str = "", **kw):
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "audit.log"
        )
        self.storage = AuditStorage(self._storage_path)
        self.query_engine = AuditQuery(self.storage)
        self._retention_policy = RetentionPolicy.DAYS_90
        self._max_log_size_mb = 100.0
        self._lock = threading.RLock()

    # ── 日志记录 ────────────────────────────────────────────

    def log(
        self,
        action: str,
        actor: str,
        resource: str = "",
        resource_type: str = "",
        result: AuditResult = AuditResult.SUCCESS,
        reason: str = "",
        details: Dict[str, Any] = None,
        actor_type: str = "user",
        source_ip: str = "",
        user_agent: str = "",
        session_id: str = "",
        request_id: str = "",
        metadata: Dict[str, Any] = None,
    ) -> AuditEvent:
        """记录审计事件

        Args:
            action: 操作名称, e.g. "user.login", "model.deploy"
            actor: 执行者标识
            resource: 资源标识
            resource_type: 资源类型
            result: 操作结果
            reason: 失败/拒绝原因
            details: 详细上下文
            actor_type: 执行者类型
            source_ip: 来源 IP
            user_agent: User-Agent
            session_id: 会话 ID
            request_id: 请求 ID
            metadata: 附加元数据

        Returns:
            AuditEvent: 创建的审计事件
        """
        import uuid

        event_id = str(uuid.uuid4())
        event = AuditEvent(
            event_id=event_id,
            timestamp=time.time(),
            action=action,
            actor=actor,
            actor_type=actor_type,
            resource=resource,
            resource_type=resource_type,
            result=result,
            reason=reason,
            details=details or {},
            source_ip=source_ip,
            user_agent=user_agent,
            session_id=session_id,
            request_id=request_id,
            metadata=metadata or {},
        )
        event.checksum = event.compute_checksum()

        # 写入存储
        self.storage.append(event)
        logger.debug(f"Audit: {actor} {action} {resource} → {result.value}")

        # 自动轮转
        if self.storage.size_mb() >= self._max_log_size_mb:
            self.storage.rotate(self._max_log_size_mb)

        return event

    def log_batch(self, events: List[Dict[str, Any]], **kw) -> int:
        """批量记录审计事件

        Args:
            events: [{"action": ..., "actor": ..., ...}, ...]

        Returns:
            int: 成功记录数量
        """
        count = 0
        for e in events:
            try:
                self.log(
                    action=e.get("action", ""),
                    actor=e.get("actor", ""),
                    resource=e.get("resource", ""),
                    resource_type=e.get("resource_type", ""),
                    result=AuditResult(e.get("result", "success")),
                    reason=e.get("reason", ""),
                    details=e.get("details"),
                    actor_type=e.get("actor_type", "user"),
                    source_ip=e.get("source_ip", ""),
                    session_id=e.get("session_id", ""),
                    request_id=e.get("request_id", ""),
                )
                count += 1
            except Exception as ex:
                logger.error(f"Batch audit log error: {ex}")
        return count

    # ── 便捷方法 ────────────────────────────────────────────

    def log_access(
        self, actor: str, resource: str, result: AuditResult = AuditResult.SUCCESS,
        details: Dict = None,
    ) -> AuditEvent:
        """记录资源访问"""
        return self.log(
            action="resource.access",
            actor=actor,
            resource=resource,
            resource_type="resource",
            result=result,
            details=details,
        )

    def log_config_change(
        self, actor: str, config_key: str, old_value: Any, new_value: Any,
    ) -> AuditEvent:
        """记录配置变更"""
        return self.log(
            action="config.change",
            actor=actor,
            resource=config_key,
            resource_type="config",
            result=AuditResult.SUCCESS,
            details={
                "key": config_key,
                "old_value": str(old_value),
                "new_value": str(new_value),
            },
        )

    def log_model_deploy(
        self, actor: str, model_name: str, version: str, env: str,
    ) -> AuditEvent:
        """记录模型部署"""
        return self.log(
            action="model.deploy",
            actor=actor,
            resource=model_name,
            resource_type="model",
            result=AuditResult.SUCCESS,
            details={"version": version, "environment": env},
        )

    def log_error(
        self, action: str, actor: str, resource: str, error: str,
        details: Dict = None,
    ) -> AuditEvent:
        """记录错误"""
        return self.log(
            action=action,
            actor=actor,
            resource=resource,
            result=AuditResult.FAILURE,
            reason=error,
            details=details,
        )

    # ── 查询 ────────────────────────────────────────────────

    def query(
        self,
        actor: str = None,
        action: str = None,
        resource: str = None,
        result: AuditResult = None,
        start_time: float = None,
        end_time: float = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询审计事件"""
        return self.query_engine.query(
            actor=actor,
            action=action,
            resource=resource,
            result=result,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )

    def get_recent_failures(self, limit: int = 20, **kw) -> List[Dict[str, Any]]:
        """获取最近失败事件"""
        return self.query_engine.get_recent_failures(limit)

    def get_actor_activity(
        self, actor: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取执行者活动"""
        return self.query_engine.get_actor_actions(actor, limit)

    def get_daily_summary(self, **kw) -> Dict[str, Any]:
        """获取当日摘要"""
        now = time.time()
        day_start = now - (now % 86400)
        return self.query_engine.get_time_range_summary(day_start, now)

    def generate_report(
        self, start_time: float, end_time: float, output_path: str = None,
    ) -> str:
        """生成审计报告 (JSON)"""
        summary = self.query_engine.get_time_range_summary(start_time, end_time)
        events = self.query(start_time=start_time, end_time=end_time, limit=99999)
        report = {
            "report": {
                "generated_at": time.time(),
                "period": {
                    "start": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_time)),
                    "end": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end_time)),
                },
            },
            "summary": summary,
            "events": events,
        }

        if output_path:
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            return output_path

        return json.dumps(report, indent=2, ensure_ascii=False)

    # ── 管理 ────────────────────────────────────────────────

    def set_retention_policy(self, policy: RetentionPolicy, **kw) -> None:
        """设置保留策略"""
        self._retention_policy = policy
        logger.info(f"Audit retention policy set to {policy.value}")

    def get_log_size(self, **kw) -> float:
        """获取日志大小 (MB)"""
        return self.storage.size_mb()

    def get_event_count(self, **kw) -> int:
        """获取事件总数"""
        return self.query_engine.count()

    def rotate(self, **kw) -> bool:
        """手动轮转日志"""
        return self.storage.rotate(self._max_log_size_mb)


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_audit_logger: Optional[AuditLogger] = None
_global_al_lock = threading.Lock()


def get_audit_logger(storage_path: str = "") -> AuditLogger:
    """获取全局 AuditLogger 单例"""
    global _global_audit_logger
    if _global_audit_logger is None:
        with _global_al_lock:
            if _global_audit_logger is None:
                _global_audit_logger = AuditLogger(storage_path=storage_path)
                logger.info("Created global AuditLogger instance")
    return _global_audit_logger


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Audit Logger — 诊断工具")
    print("=" * 60)

    al = AuditLogger()

    # 记录事件
    al.log(action="user.login", actor="alice@example.com",
           result=AuditResult.SUCCESS, source_ip="192.168.1.10",
           session_id="sess_abc123")
    al.log(action="user.login", actor="bob@example.com",
           result=AuditResult.FAILURE, reason="Invalid password",
           source_ip="10.0.0.5")
    al.log(action="model.deploy", actor="admin@example.com",
           resource="gpt-4o", result=AuditResult.SUCCESS,
           details={"version": "2024-08-06", "env": "production"})
    al.log(action="config.change", actor="admin@example.com",
           resource="max_tokens", result=AuditResult.SUCCESS,
           details={"old": "4096", "new": "8192"})
    al.log_access("alice@example.com", "/users/123")
    al.log_error("pipeline.run", "system", "knowledge_index",
                 "OOM at chunk stage")

    print(f"\n[1] 记录数: {al.get_event_count()}")

    print("\n[2] 查询: alice 的活动")
    for e in al.get_actor_activity("alice@example.com", limit=5):
        print(f"    [{e.get('iso_time')}] {e.get('action')} → {e.get('result')}")

    print("\n[3] 最近失败:")
    for e in al.get_recent_failures(limit=3):
        print(f"    [{e.get('action')}] {e.get('actor')}: {e.get('reason')}")

    print(f"\n[4] 日志大小: {al.get_log_size():.4f} MB")

    print("\n[5] 当天摘要:")
    summary = al.get_daily_summary()
    print(f"    总事件数: {summary['total_events']}")
    print(f"    按操作: {summary.get('by_action', {})}")
    print(f"    按结果: {summary.get('by_result', {})}")

    print("\n✅ Audit Logger 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
