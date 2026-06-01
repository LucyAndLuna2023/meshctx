"""v3.96 Notification Hub tests"""
import time
import urllib.error
from datetime import datetime, time as dt_time
from unittest.mock import patch, MagicMock

import pytest

from src.core.notification_hub import (
    NotificationHub,
    Notification,
    NotificationResult,
    NotificationChannel,
    NotificationPriority,
    ChannelConfig,
    QuietHoursConfig,
    NotificationStats,
    TemplateEngine,
    DEFAULT_TEMPLATES,
    CHANNEL_SENDERS,
    get_notification_hub,
    reset_notification_hub,
    _send_feishu,
    _send_webhook,
    _send_ntfy,
    _feishu_color,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def hub():
    """Fresh NotificationHub with no channels"""
    h = NotificationHub()
    return h


@pytest.fixture
def configured_hub(hub):
    """Hub with all 4 channels pre-configured (mocked endpoints)"""
    hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
        channel=NotificationChannel.FEISHU,
        endpoint="https://open.feishu.cn/open-apis/bot/v2/hook/mock",
    ))
    hub.configure_channel(NotificationChannel.EMAIL, ChannelConfig(
        channel=NotificationChannel.EMAIL,
        endpoint="smtp.example.com",
        credentials={"username": "test@example.com", "password": "secret"},
        from_addr="test@example.com",
        to_addrs=["admin@example.com"],
    ))
    hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
        channel=NotificationChannel.WEBHOOK,
        endpoint="https://hooks.example.com/notify",
    ))
    hub.configure_channel(NotificationChannel.NTFY, ChannelConfig(
        channel=NotificationChannel.NTFY,
        endpoint="https://ntfy.sh",
        ntfy_topic="meshctx-test",
    ))
    return hub


@pytest.fixture
def basic_notification():
    """Basic normal-priority notification"""
    return Notification(
        title="Test Notification",
        body="This is a test message",
        priority=NotificationPriority.NORMAL,
    )


@pytest.fixture
def critical_notification():
    """Critical notification"""
    return Notification(
        title="CRITICAL: Server Down",
        body="Production server is unreachable",
        priority=NotificationPriority.CRITICAL,
    )


@pytest.fixture
def low_priority_notification():
    """Low priority notification"""
    return Notification(
        title="Daily Digest",
        body="Here's your daily summary...",
        priority=NotificationPriority.LOW,
    )


# ═══════════════════════════════════════════════════════════════════
# Helper: create a mock sender for a channel
# ═══════════════════════════════════════════════════════════════════

def _mock_sender_for_channel(channel: NotificationChannel, message_id: str = "mock_msg"):
    """Return a mock sender function that returns success."""
    def _sender(config, notification):
        return NotificationResult(
            success=True, channel=channel,
            message_id=message_id, latency_sec=0.01,
        )
    return _sender


# ═══════════════════════════════════════════════════════════════════
# Test: Channel Configuration (TC1-TC4)
# ═══════════════════════════════════════════════════════════════════

class TestChannelConfiguration:
    """渠道配置测试"""

    def test_configure_and_list_channels(self, hub):
        """TC1: 配置渠道后可列出"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/abc",
        ))
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://hooks.example.com",
        ))

        channels = hub.list_configured_channels()
        assert NotificationChannel.FEISHU in channels
        assert NotificationChannel.WEBHOOK in channels
        assert len(channels) == 2

    def test_remove_channel(self, hub):
        """TC2: 移除渠道"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/abc",
        ))
        assert hub.remove_channel(NotificationChannel.FEISHU) is True
        assert hub.remove_channel(NotificationChannel.FEISHU) is False
        assert hub.list_configured_channels() == []

    def test_get_channel_config(self, hub):
        """TC3: 获取渠道配置"""
        config = ChannelConfig(
            channel=NotificationChannel.NTFY,
            endpoint="https://ntfy.sh",
            ntfy_topic="alerts",
        )
        hub.configure_channel(NotificationChannel.NTFY, config)
        retrieved = hub.get_channel_config(NotificationChannel.NTFY)
        assert retrieved is not None
        assert retrieved.endpoint == "https://ntfy.sh"
        assert retrieved.ntfy_topic == "alerts"

    def test_get_unconfigured_channel_returns_none(self, hub):
        """TC4: 未配置的渠道返回 None"""
        assert hub.get_channel_config(NotificationChannel.NTFY) is None


# ═══════════════════════════════════════════════════════════════════
# Test: Priority Routing (TC5-TC9)
# ═══════════════════════════════════════════════════════════════════

class TestPriorityRouting:
    """优先级路由测试"""

    def test_critical_routes_to_all_channels(self, configured_hub, critical_notification):
        """TC5: CRITICAL 优先级路由到所有已配置渠道"""
        channels = configured_hub.resolve_channels(critical_notification)
        assert NotificationChannel.FEISHU in channels
        assert NotificationChannel.EMAIL in channels
        assert NotificationChannel.WEBHOOK in channels
        assert NotificationChannel.NTFY in channels
        assert len(channels) == 4

    def test_normal_routes_to_feishu_only(self, configured_hub, basic_notification):
        """TC6: NORMAL 优先级默认路由到飞书"""
        channels = configured_hub.resolve_channels(basic_notification)
        assert channels == [NotificationChannel.FEISHU]

    def test_explicit_channel_overrides_routing(self, configured_hub):
        """TC7: 显式指定渠道覆盖路由规则"""
        notification = Notification(
            title="Test",
            body="Explicit channel",
            priority=NotificationPriority.CRITICAL,
            channel=NotificationChannel.NTFY,
        )
        channels = configured_hub.resolve_channels(notification)
        assert channels == [NotificationChannel.NTFY]

    def test_custom_routing_rule(self, hub):
        """TC8: 自定义路由规则"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com/hook",
        ))
        hub.set_routing_rule(
            NotificationPriority.LOW,
            [NotificationChannel.WEBHOOK],
        )
        rule = hub.get_routing_rule(NotificationPriority.LOW)
        assert NotificationChannel.WEBHOOK in rule
        assert len(rule) == 1

    def test_disabled_channel_not_routed(self, hub):
        """TC9: 禁用的渠道不参与路由"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/abc",
            enabled=False,
        ))
        notification = Notification(
            title="Test",
            body="Should not route to disabled",
            priority=NotificationPriority.CRITICAL,
        )
        channels = hub.resolve_channels(notification)
        assert NotificationChannel.FEISHU not in channels


# ═══════════════════════════════════════════════════════════════════
# Test: Quiet Hours (TC10-TC15)
# ═══════════════════════════════════════════════════════════════════

class TestQuietHours:
    """静默时段测试"""

    def test_quiet_hours_disabled_by_default(self, hub):
        """TC10: 默认静默时段关闭"""
        assert not hub.is_quiet_time()

    def test_quiet_hours_active_during_window(self, hub):
        """TC11: 静默时段窗口内处于激活状态"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(22, 0),
            end_time=dt_time(7, 0),
            min_allowed_priority=NotificationPriority.HIGH,
        )
        hub.set_quiet_hours(config)

        # 23:00 should be in quiet hours
        test_dt = datetime(2026, 6, 1, 23, 0, 0)
        assert hub.is_quiet_time(now=test_dt) is True

    def test_quiet_hours_not_active_outside_window(self, hub):
        """TC12: 静默时段窗口外不抑制"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(22, 0),
            end_time=dt_time(7, 0),
        )
        hub.set_quiet_hours(config)

        # 12:00 noon should NOT be in quiet hours
        test_dt = datetime(2026, 6, 1, 12, 0, 0)
        assert hub.is_quiet_time(now=test_dt) is False

    def test_quiet_hours_suppresses_low_priority(self, hub):
        """TC13: 静默时段抑制低优先级通知"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(22, 0),
            end_time=dt_time(7, 0),
            min_allowed_priority=NotificationPriority.HIGH,
        )
        hub.set_quiet_hours(config)

        notification = Notification(
            title="Low pri",
            body="Should be suppressed",
            priority=NotificationPriority.LOW,
        )

        test_dt = datetime(2026, 6, 1, 23, 0, 0)
        with patch.object(hub, 'is_quiet_time', return_value=True):
            assert hub._should_suppress(notification) is True

    def test_quiet_hours_allows_critical(self, hub):
        """TC14: 静默时段仍允许 CRITICAL 通知"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(22, 0),
            end_time=dt_time(7, 0),
            min_allowed_priority=NotificationPriority.HIGH,
        )
        hub.set_quiet_hours(config)

        notification = Notification(
            title="CRITICAL",
            body="Urgent",
            priority=NotificationPriority.CRITICAL,
        )

        with patch.object(hub, 'is_quiet_time', return_value=True):
            assert hub._should_suppress(notification) is False

    def test_quiet_hours_same_day_window(self, hub):
        """TC15: 同日窗口正确判断 (e.g., 09:00-17:00)"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(9, 0),
            end_time=dt_time(17, 0),
        )
        hub.set_quiet_hours(config)

        # 12:00 during window
        assert hub.is_quiet_time(now=datetime(2026, 6, 1, 12, 0, 0)) is True
        # 18:00 after window
        assert hub.is_quiet_time(now=datetime(2026, 6, 1, 18, 0, 0)) is False
        # 08:00 before window
        assert hub.is_quiet_time(now=datetime(2026, 6, 1, 8, 0, 0)) is False


# ═══════════════════════════════════════════════════════════════════
# Test: Template Engine (TC16-TC23)
# ═══════════════════════════════════════════════════════════════════

class TestTemplateEngine:
    """模板引擎测试"""

    def test_builtin_templates_exist(self):
        """TC16: 预定义模板存在"""
        engine = TemplateEngine()
        templates = engine.list_templates()
        assert "alert" in templates
        assert "info" in templates
        assert "task_complete" in templates
        assert "task_failed" in templates
        assert "deploy" in templates
        assert "health" in templates
        assert "daily_summary" in templates
        assert "simple" in templates

    def test_render_alert_template(self):
        """TC17: 渲染 alert 模板"""
        engine = TemplateEngine()
        result = engine.render("alert", {
            "title": "Server Down",
            "body": "CPU at 100%",
            "timestamp": "2026-06-01 22:00",
            "priority": "CRITICAL",
        })
        assert "🚨 Alert: Server Down" in result
        assert "CPU at 100%" in result
        assert "Priority: CRITICAL" in result

    def test_render_task_complete_template(self):
        """TC18: 渲染 task_complete 模板"""
        engine = TemplateEngine()
        result = engine.render("task_complete", {
            "title": "Build #42",
            "body": "All tests passed",
            "duration": "3m 15s",
            "status": "PASS",
        })
        assert "✅ Task Complete: Build #42" in result
        assert "Duration: 3m 15s" in result
        assert "Status: PASS" in result

    def test_add_custom_template(self):
        """TC19: 添加自定义模板"""
        engine = TemplateEngine()
        engine.add_template("my_alert", "!!! $msg - $level !!!")
        result = engine.render("my_alert", {"msg": "Fire", "level": "HIGH"})
        assert result == "!!! Fire - HIGH !!!"

    def test_missing_template_returns_empty(self):
        """TC20: 不存在的模板返回空字符串"""
        engine = TemplateEngine()
        result = engine.render("nonexistent", {})
        assert result == ""

    def test_safe_substitute_missing_vars(self):
        """TC21: safe_substitute 保留未提供变量的占位符"""
        engine = TemplateEngine()
        result = engine.render("simple", {})  # $body without vars
        # safe_substitute leaves $body as-is
        assert "$body" in result

    def test_cannot_remove_builtin_template(self):
        """TC22: 不能移除预定义模板"""
        engine = TemplateEngine()
        assert engine.remove_template("alert") is False
        assert "alert" in engine.list_templates()

    def test_can_remove_custom_template(self):
        """TC23: 可以移除自定义模板"""
        engine = TemplateEngine()
        engine.add_template("custom", "test")
        assert engine.remove_template("custom") is True
        assert "custom" not in engine.list_templates()


# ═══════════════════════════════════════════════════════════════════
# Test: Notification Dataclass (TC24-TC27)
# ═══════════════════════════════════════════════════════════════════

class TestNotificationDataclass:
    """Notification 数据类测试"""

    def test_full_text_with_title_and_body(self):
        """TC24: full_text 组合标题+正文"""
        n = Notification(title="Title", body="Body text")
        assert n.full_text == "Title\nBody text"

    def test_full_text_title_only(self):
        """TC25: 仅标题"""
        n = Notification(title="Title")
        assert n.full_text == "Title"

    def test_full_text_body_only(self):
        """TC26: 仅正文"""
        n = Notification(body="Body only")
        assert n.full_text == "Body only"

    def test_default_priority_is_normal(self):
        """TC27: 默认优先级为 NORMAL"""
        n = Notification(title="Test", body="Hello")
        assert n.priority == NotificationPriority.NORMAL


# ═══════════════════════════════════════════════════════════════════
# Test: Send to Channel (TC28-TC30)
# ═══════════════════════════════════════════════════════════════════

class TestSendToChannel:
    """渠道发送测试"""

    def test_send_to_unconfigured_channel_fails(self, hub, basic_notification):
        """TC28: 发送到未配置渠道返回失败"""
        result = hub.send_to_channel(NotificationChannel.WEBHOOK, basic_notification)
        assert result.success is False
        assert "not configured" in result.error.lower()

    def test_send_to_disabled_channel_fails(self, hub, basic_notification):
        """TC29: 发送到禁用渠道返回失败"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com",
            enabled=False,
        ))
        result = hub.send_to_channel(NotificationChannel.WEBHOOK, basic_notification)
        assert result.success is False
        assert "disabled" in result.error.lower()

    def test_send_to_channel_calls_sender(self, hub, basic_notification):
        """TC30: 发送调用正确的 sender 函数 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com/hook",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.WEBHOOK,
            message_id="wh_mock", latency_sec=0.01,
        ))

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.WEBHOOK: mock_sender}):
            result = hub.send_to_channel(NotificationChannel.WEBHOOK, basic_notification)

        assert result.success is True
        assert result.message_id == "wh_mock"
        mock_sender.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# Test: Notify (main entry) (TC31-TC35)
# ═══════════════════════════════════════════════════════════════════

class TestNotify:
    """notify 主入口测试"""

    def test_notify_with_no_channels_returns_empty(self, hub, basic_notification):
        """TC31: 无配置渠道时返回空列表"""
        results = hub.notify(basic_notification)
        assert results == []

    def test_notify_sends_to_routed_channels(self, hub, basic_notification):
        """TC32: notify 按优先级路由发送 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/mock",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.FEISHU,
            message_id="fs_msg", latency_sec=0.05,
        ))

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.FEISHU: mock_sender}):
            results = hub.notify(basic_notification)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].channel == NotificationChannel.FEISHU

    def test_quiet_hours_suppresses_notify(self, hub, low_priority_notification):
        """TC33: 静默时段抑制 notify"""
        config = QuietHoursConfig(
            enabled=True,
            start_time=dt_time(22, 0),
            end_time=dt_time(7, 0),
            min_allowed_priority=NotificationPriority.HIGH,
        )
        hub.set_quiet_hours(config)
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/mock",
        ))

        with patch.object(hub, 'is_quiet_time', return_value=True):
            results = hub.notify(low_priority_notification)
        assert results == []
        stats = hub.stats()
        assert stats.total_suppressed >= 1

    def test_pre_send_hook_can_suppress(self, hub, basic_notification):
        """TC34: pre_send_hook 可取消发送"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/mock",
        ))
        hub.set_pre_send_hook(lambda n: None)  # cancel all
        results = hub.notify(basic_notification)
        assert results == []
        stats = hub.stats()
        assert stats.total_suppressed == 1

    def test_notify_simple(self, hub):
        """TC35: notify_simple 快捷方法 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com/hook",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.WEBHOOK,
            message_id="simple_ok",
        ))

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.WEBHOOK: mock_sender}):
            results = hub.notify_simple(
                title="Quick note",
                body="Hello world",
                priority=NotificationPriority.HIGH,
                channel=NotificationChannel.WEBHOOK,
            )

        assert len(results) == 1
        assert results[0].success is True


# ═══════════════════════════════════════════════════════════════════
# Test: Template Render in Notify (TC36)
# ═══════════════════════════════════════════════════════════════════

class TestTemplateNotify:
    """模板通知测试"""

    def test_notify_with_template_renders(self, hub):
        """TC36: 带模板的通知会自动渲染 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/mock",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.FEISHU,
            message_id="tpl_msg",
        ))

        notification = Notification(
            title="Build complete",
            body="Override body",
            priority=NotificationPriority.NORMAL,
            template_name="task_complete",
            template_vars={
                "title": "Build #99",
                "body": "All green",
                "duration": "1m",
                "status": "OK",
            },
        )

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.FEISHU: mock_sender}):
            results = hub.notify(notification)

        assert len(results) == 1
        # Verify the rendered template was sent
        call_args = mock_sender.call_args[0]
        sent_notification = call_args[1]
        assert sent_notification is not None
        sent_body = sent_notification.body
        assert "✅ Task Complete:" in sent_body
        assert "All green" in sent_body
        assert "Duration: 1m" in sent_body


# ═══════════════════════════════════════════════════════════════════
# Test: Stats (TC37-TC38)
# ═══════════════════════════════════════════════════════════════════

class TestStats:
    """统计测试"""

    def test_stats_accumulate(self, hub):
        """TC37: 统计正确累积 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.FEISHU, ChannelConfig(
            channel=NotificationChannel.FEISHU,
            endpoint="https://open.feishu.cn/hook/mock",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.FEISHU,
            message_id="stats_test",
        ))

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.FEISHU: mock_sender}):
            hub.notify(Notification(title="A", body="a", priority=NotificationPriority.NORMAL))
            hub.notify(Notification(title="B", body="b", priority=NotificationPriority.HIGH))

        stats = hub.stats()
        assert stats.total_sent == 2
        assert stats.total_failed == 0
        assert stats.by_channel.get("feishu", 0) >= 2
        assert stats.last_send_time > 0

    def test_reset_stats(self, hub):
        """TC38: 重置统计 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.WEBHOOK,
        ))

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.WEBHOOK: mock_sender}):
            hub.notify(Notification(
                title="T", body="b",
                channel=NotificationChannel.WEBHOOK,
            ))

        assert hub.stats().total_sent == 1
        hub.reset_stats()
        assert hub.stats().total_sent == 0


# ═══════════════════════════════════════════════════════════════════
# Test: Singleton (TC39-TC40)
# ═══════════════════════════════════════════════════════════════════

class TestSingleton:
    """单例模式测试"""

    def test_get_notification_hub_singleton(self):
        """TC39: get_notification_hub 返回单例"""
        reset_notification_hub()
        h1 = get_notification_hub()
        h2 = get_notification_hub()
        assert h1 is h2

    def test_reset_notification_hub_new_instance(self):
        """TC40: reset 后返回新实例"""
        reset_notification_hub()
        h1 = get_notification_hub()
        reset_notification_hub()
        h2 = get_notification_hub()
        assert h1 is not h2


# ═══════════════════════════════════════════════════════════════════
# Test: Feishu Color Mapping (TC41-TC44)
# ═══════════════════════════════════════════════════════════════════

class TestFeishuColor:
    """飞书颜色映射测试"""

    def test_critical_is_red(self):
        """TC41: CRITICAL → red"""
        assert _feishu_color(NotificationPriority.CRITICAL) == "red"

    def test_high_is_orange(self):
        """TC42: HIGH → orange"""
        assert _feishu_color(NotificationPriority.HIGH) == "orange"

    def test_normal_is_blue(self):
        """TC43: NORMAL → blue"""
        assert _feishu_color(NotificationPriority.NORMAL) == "blue"

    def test_low_is_grey(self):
        """TC44: LOW → grey"""
        assert _feishu_color(NotificationPriority.LOW) == "grey"


# ═══════════════════════════════════════════════════════════════════
# Test: Channel Senders (mocked) (TC45-TC48)
# ═══════════════════════════════════════════════════════════════════

class TestChannelSenders:
    """渠道发送器单元测试"""

    def test_webhook_sender_success(self, basic_notification):
        """TC45: webhook 发送器成功场景"""
        config = ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com/hook",
        )
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b"{}"
            result = _send_webhook(config, basic_notification)
            assert result.success is True
            assert result.channel == NotificationChannel.WEBHOOK
            assert result.latency_sec > 0

    def test_webhook_sender_connection_error(self, basic_notification):
        """TC46: webhook 发送器连接失败"""
        config = ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://invalid.example.com",
            max_retries=1,
        )
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = _send_webhook(config, basic_notification)
            assert result.success is False
            assert "Failed after" in result.error

    def test_ntfy_sender_missing_topic(self, basic_notification):
        """TC47: ntfy 缺少 topic 返回失败"""
        config = ChannelConfig(
            channel=NotificationChannel.NTFY,
            endpoint="https://ntfy.sh",
            ntfy_topic="",  # missing
        )
        result = _send_ntfy(config, basic_notification)
        assert result.success is False
        assert "ntfy_topic" in result.error.lower()

    def test_ntfy_sender_success(self, basic_notification):
        """TC48: ntfy 发送器成功场景"""
        config = ChannelConfig(
            channel=NotificationChannel.NTFY,
            endpoint="https://ntfy.sh",
            ntfy_topic="test-alerts",
        )
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = (
                b'{"id":"ntfy_msg_001","time":1717000000}'
            )
            result = _send_ntfy(config, basic_notification)
            assert result.success is True
            assert result.channel == NotificationChannel.NTFY
            assert result.message_id == "ntfy_msg_001"


# ═══════════════════════════════════════════════════════════════════
# Test: Post-send Hook (TC49)
# ═══════════════════════════════════════════════════════════════════

class TestPostSendHook:
    """发送后钩子测试"""

    def test_post_send_hook_called(self, hub):
        """TC49: post_send_hook 在发送后被调用 (patch CHANNEL_SENDERS)"""
        hub.configure_channel(NotificationChannel.WEBHOOK, ChannelConfig(
            channel=NotificationChannel.WEBHOOK,
            endpoint="https://example.com/hook",
        ))

        mock_sender = MagicMock(return_value=NotificationResult(
            success=True, channel=NotificationChannel.WEBHOOK,
            message_id="hook_msg",
        ))

        hook_data = []
        def post_hook(notification, results):
            hook_data.append((notification.title, len(results)))

        hub.set_post_send_hook(post_hook)

        notification = Notification(
            title="Test Notification",
            body="This is a test message",
            priority=NotificationPriority.NORMAL,
            channel=NotificationChannel.WEBHOOK,
        )

        with patch.dict("src.core.notification_hub.CHANNEL_SENDERS",
                        {NotificationChannel.WEBHOOK: mock_sender}):
            hub.notify(notification)

        assert len(hook_data) == 1
        assert hook_data[0][0] == "Test Notification"
        assert hook_data[0][1] == 1
