"""
meshctx v3.96 — Notification Hub (多渠道通知中心)

功能:
  1) 多渠道: 飞书 / 邮件 / Webhook / ntfy
  2) 优先级路由: CRITICAL→全渠道 / HIGH→主渠道 / NORMAL/LOW→按规则
  3) 模板引擎: 预定义 + 自定义模板，支持变量渲染
  4) 静默时段: 按时间窗口抑制低优先级通知

设计模式: dataclass + 类 + 单例 (get_notification_hub / reset_notification_hub)
"""

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from enum import Enum
from string import Template
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.notification_hub")


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════

class NotificationChannel(str, Enum):
    """通知渠道"""
    FEISHU = "feishu"        # 飞书/Lark
    EMAIL = "email"          # 邮件
    WEBHOOK = "webhook"      # 通用 Webhook
    NTFY = "ntfy"            # ntfy.sh 推送


class NotificationPriority(str, Enum):
    """通知优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ChannelConfig:
    """渠道配置"""
    channel: NotificationChannel
    enabled: bool = True
    endpoint: str = ""                    # Webhook URL / ntfy server / SMTP host
    credentials: Dict[str, str] = field(default_factory=dict)  # {token, secret, username, password}
    max_retries: int = 3
    timeout_sec: float = 10.0
    extra_headers: Dict[str, str] = field(default_factory=dict)
    # 飞书专用
    feishu_secret: str = ""
    # 邮件专用
    smtp_port: int = 587
    smtp_use_tls: bool = True
    from_addr: str = ""
    to_addrs: List[str] = field(default_factory=list)
    # ntfy 专用
    ntfy_topic: str = ""
    ntfy_priority: int = 3               # 1-5, 默认3


@dataclass
class Notification:
    """通知消息"""
    title: str = ""
    body: str = ""
    priority: NotificationPriority = NotificationPriority.NORMAL
    channel: Optional[NotificationChannel] = None  # None = 自动路由
    template_name: str = ""
    template_vars: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """组合标题+正文"""
        if self.title and self.body:
            return f"{self.title}\n{self.body}"
        return self.title or self.body


@dataclass
class NotificationResult:
    """单渠道发送结果"""
    success: bool
    channel: NotificationChannel
    message_id: str = ""
    error: str = ""
    latency_sec: float = 0.0


@dataclass
class QuietHoursConfig:
    """静默时段配置"""
    enabled: bool = False
    start_time: dt_time = dt_time(22, 0)      # 22:00
    end_time: dt_time = dt_time(7, 0)          # 07:00 (跨夜)
    timezone: str = "Asia/Shanghai"
    # 静默期间仍允许发送的最低优先级 (NORMAL=除LOW外都发, HIGH=仅HIGH+CRITICAL, CRITICAL=仅CRITICAL)
    min_allowed_priority: NotificationPriority = NotificationPriority.HIGH


@dataclass
class NotificationStats:
    """通知统计"""
    total_sent: int = 0
    total_suppressed: int = 0
    total_failed: int = 0
    by_channel: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[str, int] = field(default_factory=dict)
    last_send_time: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# Template Engine
# ═══════════════════════════════════════════════════════════════════

# 预定义模板
DEFAULT_TEMPLATES: Dict[str, str] = {
    "alert": (
        "🚨 Alert: $title\n"
        "$body\n\n"
        "Time: $timestamp | Priority: $priority"
    ),
    "info": (
        "ℹ️ $title\n"
        "$body"
    ),
    "task_complete": (
        "✅ Task Complete: $title\n"
        "$body\n\n"
        "Duration: $duration | Status: $status"
    ),
    "task_failed": (
        "❌ Task Failed: $title\n"
        "$body\n\n"
        "Error: $error_info | Retries: $retries"
    ),
    "deploy": (
        "🚀 Deploy: $title\n"
        "$body\n\n"
        "Version: $version | Env: $env | By: $author"
    ),
    "health": (
        "🏥 Health Report\n"
        "Status: $status\n"
        "$body\n\n"
        "Uptime: $uptime | CPU: $cpu | Mem: $mem | Disk: $disk"
    ),
    "daily_summary": (
        "📊 Daily Summary\n"
        "$body\n\n"
        "Tasks: $tasks_done/$tasks_total | Errors: $errors | Date: $date"
    ),
    "simple": "$body",
}


class TemplateEngine:
    """
    v3.96 模板引擎 — 支持 $var / ${var} 语法，预定义 + 自定义模板
    """

    def __init__(self):
        self._templates: Dict[str, str] = dict(DEFAULT_TEMPLATES)

    def add_template(self, name: str, template: str) -> None:
        """注册自定义模板"""
        self._templates[name] = template
        logger.debug(f"Template registered: {name}")

    def remove_template(self, name: str) -> bool:
        """移除模板 (不允许移除预定义模板)"""
        if name in DEFAULT_TEMPLATES:
            logger.warning(f"Cannot remove builtin template: {name}")
            return False
        return self._templates.pop(name, None) is not None

    def list_templates(self) -> List[str]:
        """列出所有可用模板"""
        return sorted(self._templates.keys())

    def get_template(self, name: str) -> Optional[str]:
        """获取模板原始字符串"""
        return self._templates.get(name)

    def render(self, name: str, vars: Optional[Dict[str, str]] = None) -> str:
        """
        渲染模板

        Args:
            name: 模板名称
            vars: 模板变量字典

        Returns:
            渲染后的文本。若模板不存在，返回空字符串。
        """
        template_str = self._templates.get(name)
        if template_str is None:
            logger.warning(f"Template not found: {name}")
            return ""

        tpl = Template(template_str)
        safe_vars = vars or {}

        try:
            return tpl.safe_substitute(safe_vars)
        except Exception as e:
            logger.error(f"Template render error for '{name}': {e}")
            return template_str


# ═══════════════════════════════════════════════════════════════════
# Channel Senders
# ═══════════════════════════════════════════════════════════════════

def _send_feishu(config: ChannelConfig, notification: Notification) -> NotificationResult:
    """飞书 Webhook 发送器"""
    start = time.monotonic()
    try:
        url = config.endpoint
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": notification.title or "Notification"},
                    "template": _feishu_color(notification.priority),
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": notification.body or "(no content)",
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"Priority: {notification.priority.value} | {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(notification.timestamp))}",
                            }
                        ],
                    },
                ],
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", **config.extra_headers},
        )

        for attempt in range(config.max_retries):
            try:
                with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
                    body = json.loads(resp.read())
                    code = body.get("code", -1)
                    if code == 0:
                        latency = time.monotonic() - start
                        msg_id = body.get("data", {}).get("message_id", "")
                        return NotificationResult(
                            success=True, channel=NotificationChannel.FEISHU,
                            message_id=msg_id, latency_sec=latency,
                        )
                    else:
                        err_msg = body.get("msg", f"Feishu error code: {code}")
                        logger.warning(f"Feishu send attempt {attempt+1} failed: {err_msg}")
            except Exception as e:
                logger.warning(f"Feishu send attempt {attempt+1} error: {e}")
            if attempt < config.max_retries - 1:
                time.sleep(1)

        return NotificationResult(
            success=False, channel=NotificationChannel.FEISHU,
            error=f"Failed after {config.max_retries} retries",
            latency_sec=time.monotonic() - start,
        )
    except Exception as e:
        logger.error(f"Feishu send exception: {e}")
        return NotificationResult(
            success=False, channel=NotificationChannel.FEISHU,
            error=str(e), latency_sec=time.monotonic() - start,
        )


def _feishu_color(priority: NotificationPriority) -> str:
    """飞书卡片颜色映射"""
    return {
        NotificationPriority.CRITICAL: "red",
        NotificationPriority.HIGH: "orange",
        NotificationPriority.NORMAL: "blue",
        NotificationPriority.LOW: "grey",
    }.get(priority, "blue")


def _send_webhook(config: ChannelConfig, notification: Notification) -> NotificationResult:
    """通用 Webhook HTTP POST 发送器"""
    start = time.monotonic()
    try:
        payload = {
            "title": notification.title,
            "body": notification.body,
            "priority": notification.priority.value,
            "timestamp": notification.timestamp,
            "tags": notification.tags,
            "metadata": notification.metadata,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **config.extra_headers}

        for attempt in range(config.max_retries):
            try:
                req = urllib.request.Request(config.endpoint, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
                    resp.read()
                    return NotificationResult(
                        success=True, channel=NotificationChannel.WEBHOOK,
                        message_id=f"wh_{int(time.time()*1000)}",
                        latency_sec=time.monotonic() - start,
                    )
            except Exception as e:
                logger.warning(f"Webhook send attempt {attempt+1} error: {e}")
            if attempt < config.max_retries - 1:
                time.sleep(1)

        return NotificationResult(
            success=False, channel=NotificationChannel.WEBHOOK,
            error=f"Failed after {config.max_retries} retries",
            latency_sec=time.monotonic() - start,
        )
    except Exception as e:
        logger.error(f"Webhook send exception: {e}")
        return NotificationResult(
            success=False, channel=NotificationChannel.WEBHOOK,
            error=str(e), latency_sec=time.monotonic() - start,
        )


def _send_email(config: ChannelConfig, notification: Notification) -> NotificationResult:
    """邮件 SMTP 发送器"""
    start = time.monotonic()
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(
            notification.body or notification.title,
            "plain", "utf-8",
        )
        msg["Subject"] = notification.title or "MeshCtx Notification"
        msg["From"] = config.from_addr or config.credentials.get("username", "")
        msg["To"] = ", ".join(config.to_addrs)

        for attempt in range(config.max_retries):
            try:
                if config.smtp_use_tls:
                    server = smtplib.SMTP(config.endpoint, config.smtp_port, timeout=config.timeout_sec)
                    server.starttls()
                else:
                    server = smtplib.SMTP_SSL(config.endpoint, config.smtp_port, timeout=config.timeout_sec)

                username = config.credentials.get("username", "")
                password = config.credentials.get("password", "")
                if username:
                    server.login(username, password)

                server.sendmail(
                    config.from_addr or username,
                    config.to_addrs,
                    msg.as_string(),
                )
                server.quit()
                return NotificationResult(
                    success=True, channel=NotificationChannel.EMAIL,
                    message_id=f"mail_{int(time.time()*1000)}",
                    latency_sec=time.monotonic() - start,
                )
            except Exception as e:
                logger.warning(f"Email send attempt {attempt+1} error: {e}")
            if attempt < config.max_retries - 1:
                time.sleep(1)

        return NotificationResult(
            success=False, channel=NotificationChannel.EMAIL,
            error=f"Failed after {config.max_retries} retries",
            latency_sec=time.monotonic() - start,
        )
    except ImportError:
        return NotificationResult(
            success=False, channel=NotificationChannel.EMAIL,
            error="smtplib not available", latency_sec=time.monotonic() - start,
        )
    except Exception as e:
        logger.error(f"Email send exception: {e}")
        return NotificationResult(
            success=False, channel=NotificationChannel.EMAIL,
            error=str(e), latency_sec=time.monotonic() - start,
        )


def _send_ntfy(config: ChannelConfig, notification: Notification) -> NotificationResult:
    """ntfy.sh 推送发送器"""
    start = time.monotonic()
    try:
        topic = config.ntfy_topic
        if not topic:
            return NotificationResult(
                success=False, channel=NotificationChannel.NTFY,
                error="ntfy_topic not configured",
            )

        base_url = config.endpoint or "https://ntfy.sh"
        url = f"{base_url}/{topic}"

        headers = {
            "Title": notification.title or "Notification",
            "Priority": str(config.ntfy_priority),
            "Tags": ",".join(notification.tags) if notification.tags else "information_source",
            **config.extra_headers,
        }

        # ntfy 认证
        token = config.credentials.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        body_data = (notification.body or notification.title).encode("utf-8")

        for attempt in range(config.max_retries):
            try:
                req = urllib.request.Request(url, data=body_data, headers=headers)
                with urllib.request.urlopen(req, timeout=config.timeout_sec) as resp:
                    body = json.loads(resp.read())
                    return NotificationResult(
                        success=True, channel=NotificationChannel.NTFY,
                        message_id=body.get("id", f"ntfy_{int(time.time()*1000)}"),
                        latency_sec=time.monotonic() - start,
                    )
            except Exception as e:
                logger.warning(f"ntfy send attempt {attempt+1} error: {e}")
            if attempt < config.max_retries - 1:
                time.sleep(1)

        return NotificationResult(
            success=False, channel=NotificationChannel.NTFY,
            error=f"Failed after {config.max_retries} retries",
            latency_sec=time.monotonic() - start,
        )
    except Exception as e:
        logger.error(f"ntfy send exception: {e}")
        return NotificationResult(
            success=False, channel=NotificationChannel.NTFY,
            error=str(e), latency_sec=time.monotonic() - start,
        )


# 渠道发送器映射
CHANNEL_SENDERS: Dict[NotificationChannel, Callable] = {
    NotificationChannel.FEISHU: _send_feishu,
    NotificationChannel.WEBHOOK: _send_webhook,
    NotificationChannel.EMAIL: _send_email,
    NotificationChannel.NTFY: _send_ntfy,
}


# ═══════════════════════════════════════════════════════════════════
# NotificationHub
# ═══════════════════════════════════════════════════════════════════

class NotificationHub:
    """
    v3.96 Notification Hub — 多渠道通知中心

    功能:
      - 多渠道: 飞书 / 邮件 / Webhook / ntfy
      - 优先级路由: CRITICAL→全渠道 / HIGH→主渠道 / NORMAL→按配置 / LOW→单渠道
      - 模板引擎: 预定义 + 自定义模板
      - 静默时段: 按时间窗口抑制低优先级通知

    Usage:
        hub = get_notification_hub()
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
        ))
        hub.notify(Notification(
            title="Task Done",
            body="Build completed successfully",
            priority=NotificationPriority.NORMAL,
            template_name="task_complete",
            template_vars={"duration": "2m 30s", "status": "PASS"},
        ))
    """

    def __init__(self):
        # 渠道配置
        self._channels: Dict[NotificationChannel, ChannelConfig] = {}
        self._lock = threading.RLock()

        # 模板引擎
        self.templates = TemplateEngine()

        # 静默时段
        self._quiet_hours = QuietHoursConfig()

        # 优先级路由规则: 优先级 → 目标渠道列表
        self._routing_rules: Dict[NotificationPriority, List[NotificationChannel]] = {
            NotificationPriority.CRITICAL: [
                NotificationChannel.FEISHU,
                NotificationChannel.EMAIL,
                NotificationChannel.WEBHOOK,
                NotificationChannel.NTFY,
            ],
            NotificationPriority.HIGH: [
                NotificationChannel.FEISHU,
                NotificationChannel.EMAIL,
            ],
            NotificationPriority.NORMAL: [
                NotificationChannel.FEISHU,
            ],
            NotificationPriority.LOW: [
                NotificationChannel.EMAIL,
            ],
        }

        # 统计
        self._stats = NotificationStats()

        # 自定义钩子: 在发送前/后执行
        self._pre_send_hook: Optional[Callable[[Notification], Optional[Notification]]] = None
        self._post_send_hook: Optional[Callable[[Notification, List[NotificationResult]], None]] = None

    # ── Channel Configuration ─────────────────────────────────────

    def configure_channel(self, channel: NotificationChannel, config: ChannelConfig) -> None:
        """
        配置通知渠道

        Args:
            channel: 渠道类型
            config: 渠道配置
        """
        with self._lock:
            config.channel = channel
            self._channels[channel] = config
            logger.info(f"Channel configured: {channel.value} -> {config.endpoint}")

    def remove_channel(self, channel: NotificationChannel) -> bool:
        """移除渠道配置"""
        with self._lock:
            if channel in self._channels:
                del self._channels[channel]
                logger.info(f"Channel removed: {channel.value}")
                return True
            return False

    def get_channel_config(self, channel: NotificationChannel) -> Optional[ChannelConfig]:
        """获取渠道配置"""
        return self._channels.get(channel)

    def list_configured_channels(self) -> List[NotificationChannel]:
        """列出已配置的渠道"""
        return sorted(self._channels.keys(), key=lambda c: c.value)

    # ── Priority Routing ──────────────────────────────────────────

    def set_routing_rule(
        self, priority: NotificationPriority,
        channels: List[NotificationChannel],
    ) -> None:
        """
        设置优先级路由规则

        Args:
            priority: 通知优先级
            channels: 该优先级应发送到的渠道列表
        """
        with self._lock:
            self._routing_rules[priority] = list(channels)
            logger.debug(f"Routing rule set: {priority.value} -> {[c.value for c in channels]}")

    def get_routing_rule(self, priority: NotificationPriority) -> List[NotificationChannel]:
        """获取优先级路由规则"""
        return list(self._routing_rules.get(priority, []))

    def resolve_channels(self, notification: Notification) -> List[NotificationChannel]:
        """
        根据优先级解析目标渠道

        Logic:
          - 若 notification.channel 显式指定 → 仅该渠道
          - 否则按 priority 查路由表 → 仅返回已配置且启用的渠道

        Args:
            notification: 通知消息

        Returns:
            目标渠道列表
        """
        if notification.channel is not None:
            config = self._channels.get(notification.channel)
            if config and config.enabled:
                return [notification.channel]
            return []

        target_channels = self._routing_rules.get(
            notification.priority,
            [NotificationChannel.FEISHU],
        )

        return [
            ch for ch in target_channels
            if ch in self._channels and self._channels[ch].enabled
        ]

    # ── Quiet Hours (静默时段) ────────────────────────────────────

    def set_quiet_hours(self, config: QuietHoursConfig) -> None:
        """设置静默时段配置"""
        with self._lock:
            self._quiet_hours = config
            logger.info(
                f"Quiet hours set: {'enabled' if config.enabled else 'disabled'} "
                f"({config.start_time} - {config.end_time}, min={config.min_allowed_priority.value})"
            )

    def get_quiet_hours(self) -> QuietHoursConfig:
        """获取当前静默时段配置"""
        return self._quiet_hours

    def is_quiet_time(self, now: Optional[datetime] = None) -> bool:
        """
        检查当前是否处于静默时段

        Args:
            now: 参考时间 (默认当前时间)

        Returns:
            True if within quiet hours window
        """
        if not self._quiet_hours.enabled:
            return False

        dt = now or datetime.now()
        current = dt.time()
        start = self._quiet_hours.start_time
        end = self._quiet_hours.end_time

        # 跨夜窗口: e.g., 22:00 - 07:00
        if start > end:
            return current >= start or current < end
        else:
            # 同日窗口: e.g., 09:00 - 17:00
            return start <= current < end

    def _should_suppress(self, notification: Notification) -> bool:
        """
        判断通知是否应在静默时段被抑制

        Args:
            notification: 通知消息

        Returns:
            True if suppressed
        """
        if not self.is_quiet_time():
            return False

        # 检查优先级是否达到最低允许阈值
        priority_order = {
            NotificationPriority.LOW: 0,
            NotificationPriority.NORMAL: 1,
            NotificationPriority.HIGH: 2,
            NotificationPriority.CRITICAL: 3,
        }
        min_allowed = priority_order.get(self._quiet_hours.min_allowed_priority, 2)
        current = priority_order.get(notification.priority, 1)

        return current < min_allowed

    # ── Template Helpers ──────────────────────────────────────────

    def format_notification(self, notification: Notification) -> Tuple[str, str]:
        """
        根据模板渲染通知的标题和正文

        Returns:
            (rendered_title, rendered_body)
        """
        if notification.template_name:
            rendered = self.templates.render(
                notification.template_name,
                notification.template_vars,
            )
            # 使用渲染结果作为正文，标题不变
            title = notification.title or notification.template_name
            body = rendered or notification.body
        else:
            title = notification.title
            body = notification.body

        return title, body

    # ── Hooks ─────────────────────────────────────────────────────

    def set_pre_send_hook(
        self, hook: Optional[Callable[[Notification], Optional[Notification]]]
    ) -> None:
        """
        设置发送前钩子。返回 None 表示取消发送。

        Args:
            hook: (notification) → modified_notification or None
        """
        self._pre_send_hook = hook

    def set_post_send_hook(
        self, hook: Optional[Callable[[Notification, List[NotificationResult]], None]]
    ) -> None:
        """
        设置发送后钩子

        Args:
            hook: (notification, results) → None
        """
        self._post_send_hook = hook

    # ── Send ──────────────────────────────────────────────────────

    def send_to_channel(
        self, channel: NotificationChannel, notification: Notification,
    ) -> NotificationResult:
        """
        发送通知到指定渠道

        Args:
            channel: 目标渠道
            notification: 通知消息

        Returns:
            NotificationResult
        """
        config = self._channels.get(channel)
        if config is None:
            return NotificationResult(
                success=False, channel=channel,
                error=f"Channel not configured: {channel.value}",
            )

        if not config.enabled:
            return NotificationResult(
                success=False, channel=channel,
                error=f"Channel disabled: {channel.value}",
            )

        # Dynamically resolve sender from module-level dict (supports mocking)
        sender = CHANNEL_SENDERS.get(channel)
        if sender is None:
            return NotificationResult(
                success=False, channel=channel,
                error=f"No sender for channel: {channel.value}",
            )

        try:
            result = sender(config, notification)
            return result
        except Exception as e:
            logger.error(f"Send to {channel.value} failed: {e}")
            return NotificationResult(
                success=False, channel=channel, error=str(e),
            )

    def notify(self, notification: Notification) -> List[NotificationResult]:
        """
        发送通知 (主入口)

        流程:
          1) pre_send_hook 预处理
          2) 检查静默时段 → 抑制低优先级
          3) 解析目标渠道
          4) 模板渲染
          5) 逐渠道发送
          6) post_send_hook 后处理
          7) 更新统计

        Args:
            notification: 通知消息

        Returns:
            各渠道发送结果列表
        """
        start = time.monotonic()

        # Step 1: pre-send hook
        if self._pre_send_hook:
            result = self._pre_send_hook(notification)
            if result is None:
                with self._lock:
                    self._stats.total_suppressed += 1
                logger.debug("Notification suppressed by pre_send_hook")
                return []
            notification = result

        # Step 2: check quiet hours
        if self._should_suppress(notification):
            with self._lock:
                self._stats.total_suppressed += 1
            logger.debug(
                f"Notification suppressed by quiet hours: {notification.title} "
                f"(priority={notification.priority.value})"
            )
            return []

        # Step 3: resolve channels
        target_channels = self.resolve_channels(notification)
        if not target_channels:
            logger.warning(f"No enabled channels for notification: {notification.title}")
            return []

        # Step 4: template rendering
        title, body = self.format_notification(notification)
        resolved = Notification(
            title=title,
            body=body,
            priority=notification.priority,
            channel=notification.channel,
            template_name=notification.template_name,
            template_vars=notification.template_vars,
            timestamp=notification.timestamp,
            tags=notification.tags,
            metadata=notification.metadata,
        )

        # Step 5: send to each channel
        results: List[NotificationResult] = []
        for channel in target_channels:
            result = self.send_to_channel(channel, resolved)
            results.append(result)

        # Step 6: post-send hook
        if self._post_send_hook:
            try:
                self._post_send_hook(resolved, results)
            except Exception as e:
                logger.error(f"post_send_hook error: {e}")

        # Step 7: update stats
        with self._lock:
            for r in results:
                ch_key = r.channel.value
                self._stats.by_channel[ch_key] = self._stats.by_channel.get(ch_key, 0) + 1
                pri_key = notification.priority.value
                self._stats.by_priority[pri_key] = self._stats.by_priority.get(pri_key, 0) + 1
                if r.success:
                    self._stats.total_sent += 1
                else:
                    self._stats.total_failed += 1
            self._stats.last_send_time = time.time()

        elapsed = time.monotonic() - start
        logger.info(
            f"Notification sent: {notification.title[:50]} "
            f"→ {len(results)} channels, {sum(1 for r in results if r.success)} ok, "
            f"{elapsed:.3f}s"
        )

        return results

    def notify_simple(
        self, title: str, body: str = "",
        priority: NotificationPriority = NotificationPriority.NORMAL,
        channel: Optional[NotificationChannel] = None,
        template_name: str = "",
        template_vars: Optional[Dict[str, str]] = None,
    ) -> List[NotificationResult]:
        """
        快捷发送通知 (无需构造 Notification 对象)

        Args:
            title: 标题
            body: 正文
            priority: 优先级
            channel: 指定渠道 (None=自动路由)
            template_name: 模板名称
            template_vars: 模板变量

        Returns:
            各渠道发送结果列表
        """
        return self.notify(Notification(
            title=title,
            body=body,
            priority=priority,
            channel=channel,
            template_name=template_name,
            template_vars=template_vars or {},
        ))

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> NotificationStats:
        """获取通知统计信息"""
        with self._lock:
            return NotificationStats(
                total_sent=self._stats.total_sent,
                total_suppressed=self._stats.total_suppressed,
                total_failed=self._stats.total_failed,
                by_channel=dict(self._stats.by_channel),
                by_priority=dict(self._stats.by_priority),
                last_send_time=self._stats.last_send_time,
            )

    def reset_stats(self) -> None:
        """重置统计"""
        with self._lock:
            self._stats = NotificationStats()


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_notification_hub: Optional[NotificationHub] = None
_hub_lock = threading.Lock()


def get_notification_hub() -> NotificationHub:
    """获取 NotificationHub 单例"""
    global _notification_hub
    if _notification_hub is None:
        with _hub_lock:
            if _notification_hub is None:
                _notification_hub = NotificationHub()
                logger.info("NotificationHub singleton created")
    return _notification_hub


def reset_notification_hub() -> None:
    """重置 NotificationHub 单例 (测试用)"""
    global _notification_hub
    with _hub_lock:
        _notification_hub = NotificationHub()
        logger.info("NotificationHub singleton reset")
