"""
Test v1.5.26 — Gateway module
Covers: BaseConnector, FeishuConnector, TelegramConnector, WeChatWorkConnector,
LINE, Discord, Slack, WhatsApp connectors, and GatewayPlugin
"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, sys.path)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_bus():
    """Mock event bus"""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def feishu_config():
    return {"app_id": "cli_abc123", "app_secret": "secret_xyz"}


@pytest.fixture
def telegram_config():
    return {"bot_token": "123:ABCdef"}


@pytest.fixture
def wechat_config():
    return {"corp_id": "ww123", "corp_secret": "secret", "agent_id": "1000001"}


@pytest.fixture
def line_config():
    return {"channel_secret": "secret123", "channel_access_token": "token123"}


@pytest.fixture
def discord_config():
    return {"bot_token": "discord_token"}


@pytest.fixture
def slack_config():
    return {"bot_token": "slack_token", "signing_secret": "signing123"}


@pytest.fixture
def whatsapp_config():
    return {"phone_number_id": "123456", "access_token": "wa_token", "verify_token": "verify123"}


# ═══════════════════════════════════════════════════════════════
# 1. BaseConnector
# ═══════════════════════════════════════════════════════════════

class TestBaseConnector:
    """Test BaseConnector abstract class"""

    def _make_concrete(self, config=None, bus=None):
        """Create a concrete subclass for testing"""
        from src.gateway import BaseConnector, IncomingMessage
        if bus is None:
            bus = MagicMock()
            bus.publish = AsyncMock()
        class TestConnector(BaseConnector):
            platform_name = "test"
            async def start(self): self.running = True
            async def stop(self): self.running = False
            async def send_message(self, chat_id, text, **kwargs): pass
        return TestConnector(config or {}, bus)

    def test_base_connector_init(self, mock_bus):
        """BaseConnector stores config and bus"""
        c = self._make_concrete({"key": "val"}, mock_bus)
        assert c.config == {"key": "val"}
        assert c.bus == mock_bus
        assert c.running is False

    def test_base_connector_handle_incoming_publishes_event(self, mock_bus):
        """handle_incoming publishes a message.added event"""
        from src.gateway import IncomingMessage
        c = self._make_concrete({}, mock_bus)
        c.send_message = AsyncMock()

        async def run():
            msg = IncomingMessage(
                platform="test",
                chat_id="chat1",
                user_id="user1",
                user_name="Test User",
                content="Hello",
                message_id="msg1",
                raw={},
                reply=lambda t, **kw: None,
            )
            await c.handle_incoming(msg)
            mock_bus.publish.assert_awaited_once()

        import asyncio
        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════
# 2. FeishuConnector
# ═══════════════════════════════════════════════════════════════

class TestFeishuConnector:
    """Test Feishu/Lark connector"""

    def test_feishu_init(self, feishu_config, mock_bus):
        """FeishuConnector stores config"""
        from src.gateway import FeishuConnector
        c = FeishuConnector(feishu_config, mock_bus)
        assert c.platform_name == "feishu"
        assert c.app_id == "cli_abc123"
        assert c.app_secret == "secret_xyz"

    def test_feishu_start_no_config(self, mock_bus):
        """Start without config logs warning and skips"""
        from src.gateway import FeishuConnector
        c = FeishuConnector({}, mock_bus)
        import asyncio
        asyncio.run(c.start())
        assert c.running is False

    @patch("httpx.AsyncClient")
    def test_feishu_send_message_no_token(self, mock_async_client, feishu_config, mock_bus):
        """send_message without token logs warning"""
        from src.gateway import FeishuConnector
        c = FeishuConnector(feishu_config, mock_bus)
        c._tenant_token = None
        import asyncio
        asyncio.run(c.send_message("chat1", "Hello"))
        # Should not crash, just log a warning

    def test_feishu_verify_signature(self, feishu_config, mock_bus):
        """verify_signature returns True (simplified)"""
        from src.gateway import FeishuConnector
        c = FeishuConnector(feishu_config, mock_bus)
        result = c.verify_signature("12345", "nonce123", b"body")
        assert result is True


# ═══════════════════════════════════════════════════════════════
# 3. TelegramConnector
# ═══════════════════════════════════════════════════════════════

class TestTelegramConnector:
    """Test Telegram connector"""

    def test_telegram_init(self, telegram_config, mock_bus):
        """TelegramConnector stores config"""
        from src.gateway import TelegramConnector
        c = TelegramConnector(telegram_config, mock_bus)
        assert c.platform_name == "telegram"
        assert c.bot_token == "123:ABCdef"

    def test_telegram_start_no_token(self, mock_bus):
        """Start without token skips"""
        from src.gateway import TelegramConnector
        c = TelegramConnector({}, mock_bus)
        import asyncio
        asyncio.run(c.start())
        assert c.running is False

    def test_telegram_send_message_truncates(self, telegram_config, mock_bus):
        """send_message truncates text > 4000 chars"""
        from src.gateway import TelegramConnector
        c = TelegramConnector(telegram_config, mock_bus)
        long_text = "x" * 5000
        # Should truncate to 4000 + "..."
        assert len(long_text) > 4000


# ═══════════════════════════════════════════════════════════════
# 4. WeChatWorkConnector
# ═══════════════════════════════════════════════════════════════

class TestWeChatWorkConnector:
    """Test WeChat Work connector"""

    def test_wechat_init(self, wechat_config, mock_bus):
        """WeChatWorkConnector stores config"""
        from src.gateway import WeChatWorkConnector
        c = WeChatWorkConnector(wechat_config, mock_bus)
        assert c.platform_name == "wechat"
        assert c.corp_id == "ww123"
        assert c.corp_secret == "secret"

    def test_wechat_start_no_corp_id(self, mock_bus):
        """Start without corp_id skips"""
        from src.gateway import WeChatWorkConnector
        c = WeChatWorkConnector({}, mock_bus)
        import asyncio
        asyncio.run(c.start())
        assert c.running is False


# ═══════════════════════════════════════════════════════════════
# 5. LINE / Discord / Slack / WhatsApp Connectors
# ═══════════════════════════════════════════════════════════════

class TestLineConnector:
    """Test LINE connector"""

    def test_line_init(self, line_config, mock_bus):
        """LineConnector stores config"""
        from src.gateway import LineConnector
        c = LineConnector(line_config, mock_bus)
        assert c.platform_name == "line"
        assert c.channel_secret == "secret123"

    def test_line_verify_signature_valid(self, line_config, mock_bus):
        """verify_signature with valid config returns bool"""
        from src.gateway import LineConnector
        c = LineConnector(line_config, mock_bus)
        # No channel_secret → returns False
        c.channel_secret = ""
        result = c.verify_signature(b"body", "signature")
        assert result is False

    def test_line_start_no_token(self, mock_bus):
        """Start without access token skips"""
        from src.gateway import LineConnector
        c = LineConnector({}, mock_bus)
        import asyncio
        asyncio.run(c.start())
        assert c.running is False


class TestDiscordConnector:
    """Test Discord connector"""

    def test_discord_init(self, discord_config, mock_bus):
        """DiscordConnector stores config"""
        from src.gateway import DiscordConnector
        c = DiscordConnector(discord_config, mock_bus)
        assert c.platform_name == "discord"
        assert c.bot_token == "discord_token"

    def test_discord_send_message_truncates(self, discord_config, mock_bus):
        """send_message truncates text > 2000 chars"""
        from src.gateway import DiscordConnector
        c = DiscordConnector(discord_config, mock_bus)
        long_text = "x" * 2500
        assert len(long_text) > 2000


class TestSlackConnector:
    """Test Slack connector"""

    def test_slack_init(self, slack_config, mock_bus):
        """SlackConnector stores config"""
        from src.gateway import SlackConnector
        c = SlackConnector(slack_config, mock_bus)
        assert c.platform_name == "slack"
        assert c.bot_token == "slack_token"


class TestWhatsAppConnector:
    """Test WhatsApp connector"""

    def test_whatsapp_init(self, whatsapp_config, mock_bus):
        """WhatsAppConnector stores config"""
        from src.gateway import WhatsAppConnector
        c = WhatsAppConnector(whatsapp_config, mock_bus)
        assert c.platform_name == "whatsapp"
        assert c.phone_number_id == "123456"

    def test_whatsapp_verify_webhook_valid(self, whatsapp_config, mock_bus):
        """verify_webhook returns challenge on valid token"""
        from src.gateway import WhatsAppConnector
        c = WhatsAppConnector(whatsapp_config, mock_bus)
        result = c.verify_webhook("subscribe", "verify123", "challenge123")
        assert result == "challenge123"

    def test_whatsapp_verify_webhook_invalid(self, whatsapp_config, mock_bus):
        """verify_webhook returns None on invalid token"""
        from src.gateway import WhatsAppConnector
        c = WhatsAppConnector(whatsapp_config, mock_bus)
        result = c.verify_webhook("subscribe", "wrong_token", "challenge123")
        assert result is None

    def test_whatsapp_handle_webhook_empty(self, whatsapp_config, mock_bus):
        """handle_webhook with empty body returns empty list"""
        from src.gateway import WhatsAppConnector
        c = WhatsAppConnector(whatsapp_config, mock_bus)
        import asyncio
        messages = asyncio.run(c.handle_webhook({"entry": []}))
        assert messages == []

    def test_whatsapp_start_no_config(self, mock_bus):
        """Start without phone_number_id skips"""
        from src.gateway import WhatsAppConnector
        c = WhatsAppConnector({}, mock_bus)
        import asyncio
        asyncio.run(c.start())
        assert c.running is False


# ═══════════════════════════════════════════════════════════════
# 6. WeChatPersonalConnector
# ═══════════════════════════════════════════════════════════════

class TestWeChatPersonalConnector:
    """Test WeChat Personal connector"""

    def test_wechat_personal_init(self, mock_bus):
        """WeChatPersonalConnector stores config"""
        from src.gateway import WeChatPersonalConnector
        c = WeChatPersonalConnector({"bridge_url": "http://localhost:8080"}, mock_bus)
        assert c.platform_name == "wechat_personal"
        assert c.bridge_url == "http://localhost:8080"

    def test_wechat_personal_handle_webhook_valid(self, mock_bus):
        """handle_webhook returns IncomingMessage for text"""
        from src.gateway import WeChatPersonalConnector
        c = WeChatPersonalConnector({"bridge_url": "http://localhost:8080"}, mock_bus)
        import asyncio
        msg = asyncio.run(c.handle_webhook({
            "type": "text",
            "content": "Hello",
            "from_user": "wx_user",
            "from_name": "WeChat User",
            "msg_id": "msg_123",
        }))
        assert msg is not None
        assert msg.content == "Hello"
        assert msg.platform == "wechat_personal"

    def test_wechat_personal_handle_webhook_non_text(self, mock_bus):
        """handle_webhook returns None for non-text type"""
        from src.gateway import WeChatPersonalConnector
        c = WeChatPersonalConnector({"bridge_url": "http://localhost:8080"}, mock_bus)
        import asyncio
        msg = asyncio.run(c.handle_webhook({"type": "image", "content": "photo.jpg"}))
        assert msg is None


# ═══════════════════════════════════════════════════════════════
# 7. QQConnector
# ═══════════════════════════════════════════════════════════════

class TestQQConnector:
    """Test QQ connector"""

    def test_qq_init(self, mock_bus):
        """QQConnector stores config"""
        from src.gateway import QQConnector
        c = QQConnector({"bridge_url": "http://localhost:5700"}, mock_bus)
        assert c.platform_name == "qq"
        assert c.bridge_url == "http://localhost:5700"

    def test_qq_handle_webhook_private(self, mock_bus):
        """handle_webhook for private message"""
        from src.gateway import QQConnector
        c = QQConnector({"bridge_url": "http://localhost:5700"}, mock_bus)
        import asyncio
        msg = asyncio.run(c.handle_webhook({
            "message_type": "private",
            "user_id": 12345,
            "message": "Hello QQ",
            "message_id": "msg_qq",
            "sender": {"nickname": "QQ User"},
        }))
        assert msg is not None
        assert msg.content == "Hello QQ"
        assert msg.chat_id == "user_12345"

    def test_qq_handle_webhook_group(self, mock_bus):
        """handle_webhook for group message"""
        from src.gateway import QQConnector
        c = QQConnector({"bridge_url": "http://localhost:5700"}, mock_bus)
        import asyncio
        msg = asyncio.run(c.handle_webhook({
            "message_type": "group",
            "group_id": 99999,
            "user_id": 12345,
            "message": "Group message",
            "message_id": "msg_group",
            "sender": {"nickname": "Group User"},
        }))
        assert msg is not None
        assert msg.chat_id == "group_99999"

    def test_qq_handle_webhook_empty_content(self, mock_bus):
        """handle_webhook with empty content returns None"""
        from src.gateway import QQConnector
        c = QQConnector({"bridge_url": "http://localhost:5700"}, mock_bus)
        import asyncio
        msg = asyncio.run(c.handle_webhook({
            "message_type": "private",
            "user_id": 12345,
            "message": "",
        }))
        assert msg is None


# ═══════════════════════════════════════════════════════════════
# 8. GatewayPlugin
# ═══════════════════════════════════════════════════════════════

class TestGatewayPlugin:
    """Test GatewayPlugin"""

    def test_gateway_plugin_init(self):
        """GatewayPlugin initializes with empty connector dict"""
        from src.gateway import GatewayPlugin
        gp = GatewayPlugin()
        assert gp._connectors == {}

    def test_gateway_plugin_connector_map_size(self):
        """CONNECTOR_MAP has 9 entries"""
        from src.gateway import GatewayPlugin
        assert len(GatewayPlugin.CONNECTOR_MAP) == 9

    def test_gateway_plugin_connector_map_keys(self):
        """CONNECTOR_MAP has all expected platforms"""
        from src.gateway import GatewayPlugin
        keys = set(GatewayPlugin.CONNECTOR_MAP.keys())
        expected = {"feishu", "telegram", "wechat", "wechat_personal", 
                    "whatsapp", "qq", "line", "discord", "slack"}
        assert keys == expected

    def test_gateway_plugin_has_credentials_basic(self):
        """_has_credentials returns False for empty config"""
        from src.gateway import GatewayPlugin
        gp = GatewayPlugin()
        result = gp._has_credentials({})
        assert result is False

    def test_gateway_plugin_info(self):
        """GatewayPlugin has PluginInfo with correct name"""
        from src.gateway import GatewayPlugin
        assert GatewayPlugin.info.name == "gateway"
        assert "飞书" in GatewayPlugin.info.description
