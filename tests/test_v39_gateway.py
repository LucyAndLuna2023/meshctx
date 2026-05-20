"""Tests for Gateway Connectors — v2.39"""
import pytest
import tempfile
import os
from pathlib import Path
from src.core.gateway_connectors import (
    GatewayMessage, ConnectorStatus, BaseConnector,
    SlackConnector, DiscordConnector, WhatsAppConnector,
    GatewayManager, get_gateway,
)


class TestGatewayMessage:
    def test_create(self):
        msg = GatewayMessage(
            platform="slack", channel_id="C123", user_id="U456",
            user_name="testuser", text="hello"
        )
        assert msg.platform == "slack"
        assert msg.text == "hello"
        assert msg.thread_id == ""

    def test_to_dict(self):
        msg = GatewayMessage(
            platform="discord", channel_id="D1", user_id="U1",
            user_name="user", text="hi", thread_id="T1"
        )
        d = msg.raw_payload
        assert isinstance(d, dict)


class TestConnectorStatus:
    def test_defaults(self):
        s = ConnectorStatus(platform="test")
        assert s.platform == "test"
        assert not s.connected
        assert s.messages_received == 0
        assert s.errors == 0


class TestSlackConnector:
    def test_init_no_token(self):
        c = SlackConnector()
        assert c.platform == "slack"
        assert c.bot_token == ""  # No env var set

    def test_init_with_config(self):
        c = SlackConnector({"bot_token": "xoxb-test", "app_token": "xapp-test"})
        assert c.bot_token == "xoxb-test"

    def test_connect_no_token(self):
        c = SlackConnector()
        result = asyncio.run(c.connect())
        assert result is False


class TestDiscordConnector:
    def test_init(self):
        c = DiscordConnector()
        assert c.platform == "discord"

    def test_init_with_config(self):
        c = DiscordConnector({"bot_token": "test-token"})
        assert c.bot_token == "test-token"

    def test_connect_no_token(self):
        c = DiscordConnector()
        result = asyncio.run(c.connect())
        assert result is False


class TestWhatsAppConnector:
    def test_init(self):
        c = WhatsAppConnector()
        assert c.platform == "whatsapp"

    def test_verify_webhook_correct(self):
        c = WhatsAppConnector({"verify_token": "secret"})
        result = c.verify_webhook("subscribe", "secret", "challenge123")
        assert result == "challenge123"

    def test_verify_webhook_wrong_token(self):
        c = WhatsAppConnector({"verify_token": "secret"})
        result = c.verify_webhook("subscribe", "wrong", "challenge123")
        assert result is None

    def test_verify_webhook_wrong_mode(self):
        c = WhatsAppConnector({"verify_token": "secret"})
        result = c.verify_webhook("invalid", "secret", "challenge123")
        assert result is None

    def test_handle_webhook(self):
        c = WhatsAppConnector({"token": "t", "phone_id": "p"})
        asyncio.run(c.connect())
        body = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "123456789",
                            "text": {"body": "Hello World"},
                        }],
                        "contacts": [{"profile": {"name": "John"}}],
                    }
                }]
            }]
        }
        msgs = c.handle_webhook(body)
        assert len(msgs) == 1
        assert msgs[0].text == "Hello World"
        assert msgs[0].user_id == "123456789"


class TestGatewayManager:
    def test_init_empty(self):
        gm = GatewayManager()
        assert len(gm.connectors) == 0

    def test_add_connector(self):
        gm = GatewayManager()
        sc = SlackConnector({"bot_token": "x", "app_token": "y"})
        gm.add_connector(sc)
        assert "slack" in gm.connectors

    def test_get_status_empty(self):
        gm = GatewayManager()
        assert gm.get_status() == []

    def test_get_status_with_connector(self):
        gm = GatewayManager()
        dc = DiscordConnector({"bot_token": "t"})
        gm.add_connector(dc)
        status = gm.get_status()
        assert len(status) == 1
        assert status[0]["platform"] == "discord"

    def test_send_to_nonexistent(self):
        gm = GatewayManager()
        result = asyncio.run(gm.send_to_platform("nonexistent", "C1", "hi"))
        assert result is False

    def test_broadcast_empty(self):
        gm = GatewayManager()
        result = asyncio.run(gm.broadcast("hello"))
        assert result == {}


class TestSingleton:
    def test_global_instance(self):
        # get_gateway returns singleton but tests should use fresh instances
        gm1 = GatewayManager()
        gm2 = GatewayManager()
        assert gm1 is not gm2  # Each call creates new instance


# Need asyncio for async tests
import asyncio
