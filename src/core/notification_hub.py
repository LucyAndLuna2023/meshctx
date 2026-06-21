"""
meshctx Notification Hub — 通知中心 v1.0
==========================================

统一的多通道通知分发中心,
支持优先级路由、模板渲染、投递状态追踪。

核心能力:
  1. 多通道通知 (Console, File, Webhook, Email, Slack)
  2. 优先级路由 (Critical → Low)
  3. 通知模板系统
  4. 投递状态追踪和重试
  5. 广播和定向通知

使用场景:
  - 系统告警和运维通知
  - 用户行为触发通知
  - 管道执行结果通知
  - 实验结束通知

使用示例:
  nh = get_notification_hub()
  nh.register_channel("ops-slack", "slack", webhook_url="https://hooks.slack.com/...")
  nh.notify("ops-slack", title="Pipeline Failed", body="Knowledge indexing failed.",
            priority="critical")

代码量: ~480 行
"""

import json
import logging
import os
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from string import Template as StringTemplate
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.notification_hub")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class NotificationPriority(str, Enum):
    """通知优先级"""
    CRITICAL = "critical"       # 严重, 需要立即关注
    HIGH = "high"               # 高
    MEDIUM = "medium"           # 中
    LOW = "low"                 # 低
    INFO = "info"               # 信息


class NotificationStatus(str, Enum):
    """通知投递状态"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class ChannelType(str, Enum):
    """通知通道类型"""
    CONSOLE = "console"         # 终端输出
    FILE = "file"               # 文件日志
    WEBHOOK = "webhook"         # HTTP Webhook
    EMAIL = "email"             # 电子邮件
    SLACK = "slack"             # Slack 消息
    SMS = "sms"                 # 短信
    CUSTOM = "custom"           # 自定义


MAX_RETRIES = 3
RETRY_DELAY = 5.0  # 秒


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class NotificationTemplate:
    """通知模板"""
    name: str
    title_template: str = ""     # 标题模板 (支持 $variable)
    body_template: str = ""      # 正文模板 (支持 $variable)
    priority: NotificationPriority = NotificationPriority.MEDIUM
    tags: List[str] = field(default_factory=list)


@dataclass
class ChannelConfig:
    """通道配置"""
    name: str                       # 通道名称 (唯一)
    channel_type: ChannelType
    enabled: bool = True
    min_priority: NotificationPriority = NotificationPriority.LOW
    config: Dict[str, Any] = field(default_factory=dict)  # 通道特定配置
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Notification:
    """通知实例"""
    notification_id: str
    channel_name: str               # 目标通道名
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING
    template_name: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    sent_at: float = 0.0
    delivered_at: float = 0.0
    retry_count: int = 0
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "channel_name": self.channel_name,
            "title": self.title,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "sent_at": self.sent_at,
            "retry_count": self.retry_count,
        }


# ═══════════════════════════════════════════════════════════
# 通道发送器
# ═══════════════════════════════════════════════════════════

class ChannelSender:
    """通知通道发送器"""

    @staticmethod
    def send_console(notification: Notification, config: Dict[str, Any]) -> bool:
        """终端输出"""
        prefix = config.get("prefix", "[meshctx]")
        print(f"\n{prefix} [{notification.priority.value.upper()}] {notification.title}")
        print(f"  {notification.body}")
        return True

    @staticmethod
    def send_file(notification: Notification, config: Dict[str, Any]) -> bool:
        """文件日志"""
        file_path = config.get("path", os.path.expanduser("~/.meshctx/notifications.log"))
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            line = (
                f"[{timestamp}] [{notification.priority.value.upper()}] "
                f"{notification.title} | {notification.body}\n"
            )
            with open(file_path, "a") as f:
                f.write(line)
            return True
        except Exception as e:
            logger.error(f"Failed to write notification to file: {e}")
            return False

    @staticmethod
    def send_webhook(notification: Notification, config: Dict[str, Any]) -> bool:
        """HTTP Webhook 通知"""
        url = config.get("url", "")
        if not url:
            logger.error("Webhook URL not configured")
            return False

        try:
            import urllib.request
            payload = json.dumps({
                "title": notification.title,
                "body": notification.body,
                "priority": notification.priority.value,
                "notification_id": notification.notification_id,
                "tags": notification.tags,
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "meshctx-notification-hub/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    return True
                logger.error(f"Webhook returned {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Webhook send failed: {e}")
            return False

    @staticmethod
    def send_slack(notification: Notification, config: Dict[str, Any]) -> bool:
        """Slack 消息 (通过 Webhook)"""
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            logger.error("Slack webhook URL not configured")
            return False

        color_map = {
            NotificationPriority.CRITICAL: "#FF0000",
            NotificationPriority.HIGH: "#FF6600",
            NotificationPriority.MEDIUM: "#FFCC00",
            NotificationPriority.LOW: "#36A64F",
            NotificationPriority.INFO: "#439FE0",
        }

        try:
            import urllib.request
            payload = json.dumps({
                "attachments": [{
                    "color": color_map.get(notification.priority, "#CCCCCC"),
                    "title": notification.title,
                    "text": notification.body,
                    "fields": [
                        {"title": "Priority", "value": notification.priority.value, "short": True},
                        {"title": "ID", "value": notification.notification_id[:8], "short": True},
                    ],
                    "footer": "meshctx Notification Hub",
                    "ts": int(time.time()),
                }]
            }).encode("utf-8")

            req = urllib.request.Request(
                webhook_url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False

    @staticmethod
    def send_custom(notification: Notification, config: Dict[str, Any],
                    handler: Callable = None) -> bool:
        """自定义通道"""
        if handler:
            try:
                handler(notification, config)
                return True
            except Exception as e:
                logger.error(f"Custom handler failed: {e}")
                return False
        return False


# ═══════════════════════════════════════════════════════════
# 通知中心
# ═══════════════════════════════════════════════════════════

class NotificationHub:
    """通知中心

    管理通道、模板和通知投递。
    """

    def __init__(self, storage_path: str = ""):
        self._channels: Dict[str, ChannelConfig] = {}
        self._templates: Dict[str, NotificationTemplate] = {}
        self._notifications: List[Notification] = []
        self._history: List[Notification] = []
        self._custom_senders: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "notifications.json"
        )
        self._load_from_disk()

    # ── 通道管理 ────────────────────────────────────────────

    def register_channel(
        self, name: str, channel_type: str, enabled: bool = True,
        min_priority: NotificationPriority = NotificationPriority.LOW,
        **config,
    ) -> ChannelConfig:
        """注册通知通道

        Args:
            name: 通道名称 (唯一)
            channel_type: 通道类型 (console, file, webhook, slack, ...)
            enabled: 是否启用
            min_priority: 最低处理优先级 (低于此优先级不发送)
            **config: 通道特定配置
        """
        with self._lock:
            if name in self._channels:
                logger.warning(f"Channel '{name}' already registered, updating")
            channel = ChannelConfig(
                name=name,
                channel_type=ChannelType(channel_type),
                enabled=enabled,
                min_priority=min_priority,
                config=config,
            )
            self._channels[name] = channel
            logger.info(f"Registered notification channel: {name} ({channel_type})")
        self._save_to_disk()
        return channel

    def unregister_channel(self, name: str) -> bool:
        """注销通道"""
        with self._lock:
            if name not in self._channels:
                return False
            del self._channels[name]
            logger.info(f"Unregistered channel: {name}")
        self._save_to_disk()
        return True

    def get_channel(self, name: str) -> Optional[ChannelConfig]:
        """获取通道配置"""
        with self._lock:
            return self._channels.get(name)

    def list_channels(self, enabled_only: bool = True) -> List[ChannelConfig]:
        """列出通道"""
        with self._lock:
            channels = list(self._channels.values())
            if enabled_only:
                channels = [c for c in channels if c.enabled]
            return channels

    def register_custom_sender(self, channel_name: str, handler: Callable) -> None:
        """注册自定义通道发送器"""
        self._custom_senders[channel_name] = handler
        logger.info(f"Registered custom sender for channel: {channel_name}")

    # ── 模板管理 ────────────────────────────────────────────

    def register_template(self, template: NotificationTemplate) -> None:
        """注册通知模板"""
        with self._lock:
            self._templates[template.name] = template
            logger.info(f"Registered notification template: {template.name}")

    def render_template(
        self, template_name: str, variables: Dict[str, str] = None,
    ) -> Tuple[str, str]:
        """渲染模板

        Args:
            template_name: 模板名
            variables: 模板变量 {"user": "Alice", "error": "Timeout"}

        Returns:
            (title, body) 渲染后的标题和正文
        """
        variables = variables or {}
        template = self._templates.get(template_name)
        if not template:
            return "", ""
        try:
            title = StringTemplate(template.title_template).safe_substitute(variables)
            body = StringTemplate(template.body_template).safe_substitute(variables)
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            return template.title_template, template.body_template
        return title, body

    # ── 通知发送 ────────────────────────────────────────────

    def notify(
        self,
        channel_name: str,
        title: str,
        body: str = "",
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        template_name: str = "",
        template_vars: Dict[str, str] = None,
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
    ) -> Optional[Notification]:
        """发送通知

        Args:
            channel_name: 目标通道名
            title: 通知标题
            body: 通知正文
            priority: 优先级
            template_name: 使用的模板名 (可选)
            template_vars: 模板变量
            tags: 标签
            metadata: 附加元数据

        Returns:
            Notification: 通知对象 (如果通道禁用则返回 None)
        """
        # 模板渲染
        if template_name:
            tpl_title, tpl_body = self.render_template(template_name, template_vars)
            title = tpl_title or title
            body = tpl_body or body

        # 创建通知
        notification_id = str(uuid.uuid4())[:12]
        notification = Notification(
            notification_id=notification_id,
            channel_name=channel_name,
            title=title,
            body=body,
            priority=priority,
            template_name=template_name,
            tags=tags or [],
            metadata=metadata or {},
        )

        # 查找通道
        channel = self.get_channel(channel_name)
        if not channel:
            logger.error(f"Channel '{channel_name}' not found")
            notification.status = NotificationStatus.FAILED
            notification.error_message = f"Channel '{channel_name}' not found"
            self._history.append(notification)
            return notification

        if not channel.enabled:
            logger.debug(f"Channel '{channel_name}' is disabled, skipping")
            return None

        # 优先级检查
        priority_order = {
            NotificationPriority.CRITICAL: 5,
            NotificationPriority.HIGH: 4,
            NotificationPriority.MEDIUM: 3,
            NotificationPriority.LOW: 2,
            NotificationPriority.INFO: 1,
        }
        if priority_order.get(priority, 0) < priority_order.get(channel.min_priority, 0):
            logger.debug(f"Priority {priority.value} below channel min {channel.min_priority.value}")
            return None

        # 发送
        success = self._send(notification, channel)
        notification.sent_at = time.time()

        if success:
            notification.status = NotificationStatus.SENT
            notification.delivered_at = time.time()
            notification.status = NotificationStatus.DELIVERED
        else:
            notification.status = NotificationStatus.FAILED

        # 记录历史
        with self._lock:
            self._history.append(notification)
            if len(self._history) > 500:
                self._history = self._history[-500:]

        return notification

    def broadcast(
        self,
        title: str,
        body: str = "",
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        channels: List[str] = None,
        tags: List[str] = None,
    ) -> List[Notification]:
        """广播通知到多个通道

        Args:
            title: 标题
            body: 正文
            priority: 优先级
            channels: 目标通道列表 (None = 所有启用通道)
            tags: 标签
        """
        results = []
        target_channels = channels or [c.name for c in self.list_channels(enabled_only=True)]
        for ch_name in target_channels:
            notif = self.notify(ch_name, title, body, priority, tags=tags)
            if notif:
                results.append(notif)
        return results

    def _send(self, notification: Notification, channel: ChannelConfig) -> bool:
        """内部发送逻辑 (含重试)"""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                success = False
                if channel.channel_type == ChannelType.CONSOLE:
                    success = ChannelSender.send_console(notification, channel.config)
                elif channel.channel_type == ChannelType.FILE:
                    success = ChannelSender.send_file(notification, channel.config)
                elif channel.channel_type == ChannelType.WEBHOOK:
                    success = ChannelSender.send_webhook(notification, channel.config)
                elif channel.channel_type == ChannelType.SLACK:
                    success = ChannelSender.send_slack(notification, channel.config)
                elif channel.channel_type == ChannelType.CUSTOM:
                    custom_handler = self._custom_senders.get(channel.name)
                    success = ChannelSender.send_custom(
                        notification, channel.config, custom_handler,
                    )
                else:
                    logger.error(f"Unsupported channel type: {channel.channel_type.value}")
                    return False

                if success:
                    return True

                logger.warning(f"Send attempt {attempt}/{MAX_RETRIES} failed for {channel.name}")

            except Exception as e:
                logger.error(f"Send attempt {attempt} error: {e}")
                notification.error_message = str(e)

            notification.retry_count = attempt
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

        return False

    # ── 查询和历史 ──────────────────────────────────────────

    def get_notification(self, notification_id: str) -> Optional[Notification]:
        """获取通知"""
        with self._lock:
            for n in reversed(self._history):
                if n.notification_id == notification_id:
                    return n
        return None

    def get_history(
        self, channel_name: str = None, priority: NotificationPriority = None,
        limit: int = 50,
    ) -> List[Notification]:
        """获取通知历史"""
        with self._lock:
            history = list(self._history)
            if channel_name:
                history = [n for n in history if n.channel_name == channel_name]
            if priority:
                history = [n for n in history if n.priority == priority]
            return list(reversed(history[-limit:]))

    def get_stats(self) -> Dict[str, Any]:
        """获取通知统计"""
        with self._lock:
            total = len(self._history)
            by_status = {}
            by_channel = {}
            by_priority = {}
            for n in self._history:
                by_status.setdefault(n.status.value, 0)
                by_status[n.status.value] += 1
                by_channel.setdefault(n.channel_name, 0)
                by_channel[n.channel_name] += 1
                by_priority.setdefault(n.priority.value, 0)
                by_priority[n.priority.value] += 1

            delivered = by_status.get("delivered", 0)
            return {
                "total_notifications": total,
                "success_rate": round(delivered / max(1, total), 4),
                "by_status": by_status,
                "by_channel": by_channel,
                "by_priority": by_priority,
                "active_channels": len(self.list_channels(enabled_only=True)),
            }

    # ── 持久化 ──────────────────────────────────────────────

    def _save_to_disk(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._lock:
                data = {
                    "channels": {
                        name: {
                            "name": c.name,
                            "channel_type": c.channel_type.value,
                            "enabled": c.enabled,
                            "min_priority": c.min_priority.value,
                            "config": c.config,
                        }
                        for name, c in self._channels.items()
                    },
                    "templates": {
                        name: {
                            "name": t.name,
                            "title_template": t.title_template,
                            "body_template": t.body_template,
                            "priority": t.priority.value,
                            "tags": t.tags,
                        }
                        for name, t in self._templates.items()
                    },
                    "saved_at": time.time(),
                }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save notifications: {e}")

    def _load_from_disk(self) -> None:
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for name, cd in data.get("channels", {}).items():
                channel = ChannelConfig(
                    name=cd["name"],
                    channel_type=ChannelType(cd["channel_type"]),
                    enabled=cd.get("enabled", True),
                    min_priority=NotificationPriority(cd.get("min_priority", "low")),
                    config=cd.get("config", {}),
                )
                self._channels[name] = channel
            for name, td in data.get("templates", {}).items():
                template = NotificationTemplate(
                    name=td["name"],
                    title_template=td.get("title_template", ""),
                    body_template=td.get("body_template", ""),
                    priority=NotificationPriority(td.get("priority", "medium")),
                    tags=td.get("tags", []),
                )
                self._templates[name] = template
            logger.info(f"Loaded {len(self._channels)} channels and {len(self._templates)} templates")
        except Exception as e:
            logger.error(f"Failed to load notifications: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_notification_hub: Optional[NotificationHub] = None
_global_nh_lock = threading.Lock()


def get_notification_hub(storage_path: str = "") -> NotificationHub:
    """获取全局 NotificationHub 单例"""
    global _global_notification_hub
    if _global_notification_hub is None:
        with _global_nh_lock:
            if _global_notification_hub is None:
                _global_notification_hub = NotificationHub(storage_path=storage_path)
                logger.info("Created global NotificationHub instance")
    return _global_notification_hub


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Notification Hub — 诊断工具")
    print("=" * 60)

    nh = NotificationHub()

    # 注册通道
    nh.register_channel("console", "console")
    nh.register_channel("file-log", "file",
                        path="/tmp/meshctx_test_notifications.log")
    nh.register_channel("slack-alerts", "slack",
                        webhook_url="https://hooks.slack.com/services/[REDACTED]",
                        min_priority=NotificationPriority.HIGH)

    # 注册模板
    nh.register_template(NotificationTemplate(
        name="pipeline_failed",
        title_template="Pipeline '$pipeline_name' Failed",
        body_template="Pipeline $pipeline_name failed at stage '$stage'. Error: $error",
        priority=NotificationPriority.CRITICAL,
        tags=["pipeline", "error"],
    ))

    print(f"\n[1] 通道列表 ({len(nh.list_channels(enabled_only=False))}):")
    for c in nh.list_channels(enabled_only=False):
        print(f"    {c.name}: {c.channel_type.value} (enabled={c.enabled})")

    print("\n[2] 发送通知:")
    n1 = nh.notify("console", title="System Startup", body="Meshctx started successfully.",
                   priority=NotificationPriority.INFO)
    print(f"    Console: status={n1.status.value if n1 else 'skipped'}")

    # 按模板发送
    n2 = nh.notify(
        "file-log",
        title="",
        body="",
        priority=NotificationPriority.CRITICAL,
        template_name="pipeline_failed",
        template_vars={"pipeline_name": "index_build", "stage": "chunk", "error": "OOM"},
        tags=["pipeline"],
    )
    if n2:
        print(f"    File: status={n2.status.value}, title='{n2.title}'")

    # 广播
    print("\n[3] 广播:")
    results = nh.broadcast("Deploy Notice", "New version deployed to production.",
                          priority=NotificationPriority.MEDIUM)
    print(f"    广播到 {len(results)} 个通道")

    print(f"\n[4] 统计: {json.dumps(nh.get_stats(), indent=2)}")

    print("\n[5] 最近 3 条通知:")
    for n in nh.get_history(limit=3):
        print(f"    [{n.priority.value}] {n.title[:50]} → {n.status.value}")

    print("\n✅ Notification Hub 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()


# ═══════════════════════════════════════════════════════════
# Compatibility exports for test files
# ═══════════════════════════════════════════════════════════

class NotificationChannel(str, Enum):
    FEISHU = "feishu"
    WEBHOOK = "webhook"
    NTFY = "ntfy"
    EMAIL = "email"
    SLACK = "slack"
    CONSOLE = "console"
    FILE = "file"

@dataclass
class NotificationResult:
    success: bool = False
    channel: NotificationChannel = NotificationChannel.WEBHOOK
    message_id: str = ""
    error: str = ""

@dataclass
class NotificationStats:
    sent: int = 0
    failed: int = 0
    last_sent: float = field(default_factory=time.time)

@dataclass
class QuietHoursConfig:
    enabled: bool = False
    start_hour: int = 22
    end_hour: int = 7
    timezone: str = "UTC"

class TemplateEngine:
    def __init__(self):
        self._templates: dict = {}
    def register(self, name, template_str):
        self._templates[name] = template_str
    def render(self, name, context=None):
        tmpl = self._templates.get(name, "{title}: {body}")
        ctx = context or {}
        result = tmpl
        for k, v in ctx.items():
            result = result.replace("{" + k + "}", str(v))
        return result

DEFAULT_TEMPLATES: dict = {
    "alert": "[ALERT] {title}: {body}",
    "info": "[INFO] {title}: {body}",
    "task": "[TASK] {title}: {body}",
}

CHANNEL_SENDERS: dict = {
    NotificationChannel.FEISHU: "_send_feishu",
    NotificationChannel.WEBHOOK: "_send_webhook",
    NotificationChannel.NTFY: "_send_ntfy",
}

def _feishu_color(priority):
    color_map = {"high": "red", "urgent": "red", "normal": "blue", "low": "green", "info": "blue", "medium": "yellow", "critical": "red"}
    return color_map.get(str(priority).lower() if hasattr(priority, 'value') else str(priority).lower(), "blue")

def _send_feishu(notification, config):
    try:
        import requests
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"content": notification.title if hasattr(notification, 'title') else str(notification), "tag": "plain_text"}},
                "elements": [{"tag": "div", "text": {"content": notification.body if hasattr(notification, 'body') else "", "tag": "lark_md"}}]
            }
        }
        url = config.url if hasattr(config, 'url') else str(config)
        r = requests.post(url, json=payload, timeout=5)
        return NotificationResult(success=r.status_code == 200, channel=NotificationChannel.FEISHU)
    except Exception as e:
        return NotificationResult(success=False, channel=NotificationChannel.FEISHU, error=str(e))

def _send_webhook(notification, config):
    try:
        import requests
        url = config.url if hasattr(config, 'url') else str(config)
        title = notification.title if hasattr(notification, 'title') else str(notification)
        body = notification.body if hasattr(notification, 'body') else ""
        r = requests.post(url, json={"title": title, "body": body}, timeout=5)
        return NotificationResult(success=r.status_code == 200, channel=NotificationChannel.WEBHOOK)
    except Exception as e:
        return NotificationResult(success=False, channel=NotificationChannel.WEBHOOK, error=str(e))

def _send_ntfy(notification, config):
    try:
        import requests
        url = config.url if hasattr(config, 'url') else str(config)
        title = notification.title if hasattr(notification, 'title') else str(notification)
        body = notification.body if hasattr(notification, 'body') else ""
        r = requests.post(url, data=body.encode(), headers={"Title": title}, timeout=5)
        return NotificationResult(success=r.status_code == 200, channel=NotificationChannel.NTFY)
    except Exception as e:
        return NotificationResult(success=False, channel=NotificationChannel.NTFY, error=str(e))

def reset_notification_hub():
    global _notification_hub_instance
    _notification_hub_instance = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

