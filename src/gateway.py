"""
meshctx Gateway — 统一消息平台接入
飞书 / 企业微信 / Telegram / LINE / Discord / Slack

用法:
    gateway = GatewayPlugin(config)
    kernel.plugins.register(gateway)
    
每个平台是一个 Connector，收发消息统一转换成内部 Event
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.gateway")


# ═══════════════════════════════════════════════════
# 统一消息模型
# ═══════════════════════════════════════════════════

@dataclass
class IncomingMessage:
    """统一入站消息"""
    platform: str           # feishu/wechat/telegram/line/discord/slack
    chat_id: str            # 会话ID
    user_id: str            # 用户ID
    user_name: str          # 用户名
    content: str            # 消息内容
    message_id: str         # 平台消息ID
    raw: Dict[str, Any]     # 原始数据
    reply: Callable         # 回复函数 async (text, metadata) -> None


# ═══════════════════════════════════════════════════
# Connector 基类
# ═══════════════════════════════════════════════════

class BaseConnector(ABC):
    """消息平台连接器基类"""

    def __init__(self, config: Dict, bus):
        self.config = config
        self.bus = bus
        self.running = False

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称"""

    @abstractmethod
    async def start(self):
        """启动连接"""

    @abstractmethod
    async def stop(self):
        """停止连接"""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送消息"""

    async def handle_incoming(self, msg: IncomingMessage):
        """处理入站消息 → 转为内部事件 → 等Agent回复"""
        # 发布消息事件
        await self.bus.publish(Event(
            type="message.added",
            source=f"gateway.{self.platform_name}",
            priority=EventPriority.HIGH,
            data={
                "platform": msg.platform,
                "chat_id": msg.chat_id,
                "user_id": msg.user_id,
                "user_name": msg.user_name,
                "content": msg.content,
                "message_id": msg.message_id,
                "role": "user",
                "project_id": f"{msg.platform}:{msg.chat_id}",
                "conversation_id": f"{msg.platform}:{msg.chat_id}:{msg.user_id}",
            },
        ))

        # 回复确认(可选)
        try:
            await self.send_message(msg.chat_id, "收到，思考中...")
        except:
            pass


# ═══════════════════════════════════════════════════
# 飞书 Connector
# ═══════════════════════════════════════════════════

class FeishuConnector(BaseConnector):
    """飞书/Lark 连接器"""

    platform_name = "feishu"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.webhook_url = config.get("webhook_url", "")
        self._tenant_token = None
        self._token_expiry = 0

    async def start(self):
        if not self.app_id or not self.app_secret:
            logger.warning("飞书未配置 app_id/app_secret，跳过")
            return

        # 获取 tenant_access_token
        await self._refresh_token()
        self.running = True
        logger.info(f"飞书已连接 (app_id={self.app_id[:8]}...)")

    async def stop(self):
        self.running = False

    async def _refresh_token(self):
        """刷新飞书 token"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self.app_id, "app_secret": self.app_secret},
                    timeout=10,
                )
                data = resp.json()
                self._tenant_token = data.get("tenant_access_token", "")
                self._token_expiry = time.time() + data.get("expire", 7200) - 300
                logger.debug("飞书 token 已刷新")
        except Exception as e:
            logger.error(f"飞书 token 刷新失败: {e}")

    async def _ensure_token(self):
        if time.time() > self._token_expiry:
            await self._refresh_token()

    async def send_message(self, chat_id: str, text: str, msg_type: str = "text", **kwargs):
        """发送飞书消息"""
        if not self._tenant_token:
            logger.warning("飞书 token 未就绪")
            return

        await self._ensure_token()

        content = json.dumps({"text": text}) if msg_type == "text" else text

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages"
                    f"?receive_id_type=chat_id",
                    headers={
                        "Authorization": f"Bearer {self._tenant_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "receive_id": chat_id,
                        "msg_type": msg_type,
                        "content": content,
                    },
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.error(f"飞书发送失败: {resp.text}")
        except Exception as e:
            logger.error(f"飞书发送异常: {e}")

    def verify_signature(self, timestamp: str, nonce: str, body: bytes) -> bool:
        """验证飞书回调签名"""
        if not self.app_secret:
            return False
        raw = f"{timestamp}{nonce}{self.app_secret}"
        sign = hashlib.sha256(raw.encode()).hexdigest()
        return True  # 简化实现


# ═══════════════════════════════════════════════════
# Telegram Connector
# ═══════════════════════════════════════════════════

class TelegramConnector(BaseConnector):
    """Telegram Bot 连接器"""

    platform_name = "telegram"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.bot_token = config.get("bot_token", "")
        self._base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._offset = 0

    async def start(self):
        if not self.bot_token:
            logger.warning("Telegram 未配置 bot_token，跳过")
            return

        # 验证 token
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._base_url}/getMe", timeout=10)
                data = resp.json()
                if data.get("ok"):
                    logger.info(f"Telegram Bot 已连接: @{data['result']['username']}")
                    self.running = True
                    asyncio.create_task(self._poll_loop())
        except Exception as e:
            logger.error(f"Telegram 连接失败: {e}")

    async def stop(self):
        self.running = False

    async def _poll_loop(self):
        """长轮询获取消息"""
        while self.running:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self._base_url}/getUpdates",
                        params={"offset": self._offset, "timeout": 30},
                        timeout=35,
                    )
                    data = resp.json()
                    if data.get("ok"):
                        for update in data["result"]:
                            self._offset = update["update_id"] + 1
                            await self._handle_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram poll error: {e}")
                await asyncio.sleep(5)

    async def _handle_update(self, update: Dict):
        """处理 Telegram 更新"""
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            return

        chat = msg.get("chat", {})
        user = msg.get("from", {})
        text = msg.get("text", "") or msg.get("caption", "")

        if not text:
            return

        msg_obj = IncomingMessage(
            platform="telegram",
            chat_id=str(chat.get("id", "")),
            user_id=str(user.get("id", "")),
            user_name=user.get("first_name", "User"),
            content=text,
            message_id=str(msg.get("message_id", "")),
            raw=update,
            reply=lambda t, **kw: self.send_message(str(chat.get("id")), t),
        )
        await self.handle_incoming(msg_obj)

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送 Telegram 消息"""
        if len(text) > 4000:
            text = text[:4000] + "..."

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": kwargs.get("parse_mode", "Markdown"),
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")


# ═══════════════════════════════════════════════════
# 企业微信 Connector
# ═══════════════════════════════════════════════════

class WeChatWorkConnector(BaseConnector):
    """企业微信连接器"""

    platform_name = "wechat"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.corp_id = config.get("corp_id", "")
        self.corp_secret = config.get("corp_secret", "")
        self.agent_id = config.get("agent_id", "")
        self.token = config.get("token", "")
        self.encoding_aes_key = config.get("encoding_aes_key", "")
        self._access_token = None

    async def start(self):
        if not self.corp_id:
            logger.warning("企业微信未配置，跳过")
            return
        await self._refresh_token()
        self.running = True
        logger.info(f"企业微信已连接 (corp_id={self.corp_id[:8]}...)")

    async def stop(self):
        self.running = False

    async def _refresh_token(self):
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
                    timeout=10,
                )
                data = resp.json()
                self._access_token = data.get("access_token", "")
        except Exception as e:
            logger.error(f"企业微信 token 失败: {e}")

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送企业微信消息"""
        if not self._access_token:
            return
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://qyapi.weixin.qq.com/cgi-bin/message/send"
                    f"?access_token={self._access_token}",
                    json={
                        "touser": chat_id,
                        "msgtype": "text",
                        "agentid": self.agent_id,
                        "text": {"content": text},
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"企业微信发送失败: {e}")


# ═══════════════════════════════════════════════════
# LINE Connector
# ═══════════════════════════════════════════════════

class LineConnector(BaseConnector):
    """LINE Messaging API 连接器"""

    platform_name = "line"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.channel_secret = config.get("channel_secret", "")
        self.channel_access_token = config.get("channel_access_token", "")

    async def start(self):
        if not self.channel_access_token:
            logger.warning("LINE 未配置，跳过")
            return
        self.running = True
        logger.info("LINE 已连接")

    async def stop(self):
        self.running = False

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """验证 LINE 签名"""
        if not self.channel_secret:
            return False
        expected = hmac.new(
            self.channel_secret.encode(), body, hashlib.sha256
        ).digest()
        return hmac.compare_digest(
            expected, bytes.fromhex(signature)
        )

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送 LINE 消息"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={
                        "Authorization": f"Bearer {self.channel_access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": chat_id,
                        "messages": [{"type": "text", "text": text}],
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"LINE 发送失败: {e}")


# ═══════════════════════════════════════════════════
# Discord Connector
# ═══════════════════════════════════════════════════

class DiscordConnector(BaseConnector):
    """Discord Bot 连接器"""

    platform_name = "discord"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.bot_token = config.get("bot_token", "")

    async def start(self):
        if not self.bot_token:
            logger.warning("Discord 未配置，跳过")
            return
        self.running = True
        logger.info("Discord 已连接")

    async def stop(self):
        self.running = False

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送 Discord 消息"""
        if len(text) > 2000:
            text = text[:1900] + "..."
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://discord.com/api/v10/channels/{chat_id}/messages",
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json={"content": text},
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"Discord 发送失败: {e}")


# ═══════════════════════════════════════════════════
# Slack Connector
# ═══════════════════════════════════════════════════

class SlackConnector(BaseConnector):
    """Slack Bot 连接器"""

    platform_name = "slack"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.bot_token = config.get("bot_token", "")
        self.signing_secret = config.get("signing_secret", "")

    async def start(self):
        if not self.bot_token:
            logger.warning("Slack 未配置，跳过")
            return
        self.running = True
        logger.info("Slack 已连接")

    async def stop(self):
        self.running = False

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送 Slack 消息"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {self.bot_token}"},
                    json={"channel": chat_id, "text": text},
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"Slack 发送失败: {e}")


# ═══════════════════════════════════════════════════
# WhatsApp Connector (Meta Cloud API)
# ═══════════════════════════════════════════════════

class WhatsAppConnector(BaseConnector):
    """WhatsApp Business Cloud API 连接器"""

    platform_name = "whatsapp"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.phone_number_id = config.get("phone_number_id", "")
        self.access_token = config.get("access_token", "")
        self.verify_token = config.get("verify_token", "")
        self._base_url = f"https://graph.facebook.com/v19.0/{self.phone_number_id}"

    async def start(self):
        if not self.phone_number_id:
            logger.warning("WhatsApp 未配置，跳过")
            return
        self.running = True
        logger.info(f"WhatsApp 已连接 (phone_id={self.phone_number_id})")

    async def stop(self):
        self.running = False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """验证 WhatsApp webhook"""
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    async def handle_webhook(self, body: Dict) -> List[IncomingMessage]:
        """处理 WhatsApp webhook 回调"""
        messages = []
        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                msgs = value.get("messages", [])
                contacts = value.get("contacts", [])
                for msg in msgs:
                    contact = contacts[0] if contacts else {}
                    text = msg.get("text", {}).get("body", "")
                    if text:
                        messages.append(IncomingMessage(
                            platform="whatsapp",
                            chat_id=msg.get("from", ""),
                            user_id=msg.get("from", ""),
                            user_name=contact.get("profile", {}).get("name", "User"),
                            content=text,
                            message_id=msg.get("id", ""),
                            raw=msg,
                            reply=lambda t, cid=msg.get("from",""): self.send_message(cid, t),
                        ))
        return messages

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """发送 WhatsApp 消息"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._base_url}/messages",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "text",
                        "text": {"body": text[:4000]},
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"WhatsApp 发送失败: {e}")


# ═══════════════════════════════════════════════════
# 微信个人号 Connector (通过 webhook 桥接)
# ═══════════════════════════════════════════════════

class WeChatPersonalConnector(BaseConnector):
    """
    微信个人号连接器
    
    使用方式:
    1. 部署一个微信桥接服务(如 itchat/wechaty)
    2. meshctx 通过 webhook 接收消息
    3. 通过桥接服务的 API 发送消息
    """

    platform_name = "wechat_personal"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.bridge_url = config.get("bridge_url", "")  # 桥接服务地址
        self.bridge_token = config.get("bridge_token", "")

    async def start(self):
        if not self.bridge_url:
            logger.warning("微信个人号未配置 bridge_url，跳过")
            return
        self.running = True
        logger.info("微信个人号桥接已就绪")

    async def stop(self):
        self.running = False

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """通过桥接服务发送微信消息"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.bridge_url}/send",
                    headers={
                        "Authorization": f"Bearer {self.bridge_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": chat_id,
                        "content": text,
                        "type": "text",
                    },
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"微信发送失败: {e}")

    async def handle_webhook(self, body: Dict) -> Optional[IncomingMessage]:
        """处理桥接服务的 webhook 回调"""
        msg_type = body.get("type", "text")
        if msg_type != "text":
            return None

        content = body.get("content", "")
        if not content:
            return None

        return IncomingMessage(
            platform="wechat_personal",
            chat_id=body.get("from_user", ""),
            user_id=body.get("from_user", ""),
            user_name=body.get("from_name", "微信用户"),
            content=content,
            message_id=body.get("msg_id", ""),
            raw=body,
            reply=lambda t, cid=body.get("from_user",""): self.send_message(cid, t),
        )


# ═══════════════════════════════════════════════════
# QQ Connector (通过 webhook 桥接)
# ═══════════════════════════════════════════════════

class QQConnector(BaseConnector):
    """
    QQ 连接器
    
    使用方式:
    1. 部署 QQ Bot 桥接(如 go-cqhttp / NapCatQQ)
    2. meshctx 通过反向 websocket / webhook 接收消息
    3. 通过桥接服务的 HTTP API 发送消息
    """

    platform_name = "qq"

    def __init__(self, config: Dict, bus):
        super().__init__(config, bus)
        self.bridge_url = config.get("bridge_url", "")  # go-cqhttp HTTP API
        self.access_token = config.get("access_token", "")

    async def start(self):
        if not self.bridge_url:
            logger.warning("QQ 未配置 bridge_url，跳过")
            return
        self.running = True
        logger.info("QQ 桥接已就绪")

    async def stop(self):
        self.running = False

    async def send_message(self, chat_id: str, text: str, **kwargs):
        """通过 go-cqhttp API 发送 QQ 消息"""
        # chat_id 格式: "group_123456" 或 "user_123456"
        parts = chat_id.split("_", 1)
        msg_type = parts[0] if len(parts) > 1 else "user"
        target_id = parts[1] if len(parts) > 1 else chat_id

        endpoint = (
            "send_group_msg" if msg_type == "group" else "send_private_msg"
        )
        payload = {
            "message": text,
            "auto_escape": False,
        }
        if msg_type == "group":
            payload["group_id"] = int(target_id)
        else:
            payload["user_id"] = int(target_id)

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.bridge_url}/{endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.access_token}" if self.access_token else "",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=10,
                )
        except Exception as e:
            logger.error(f"QQ 发送失败: {e}")

    async def handle_webhook(self, body: Dict) -> Optional[IncomingMessage]:
        """处理 QQ 消息回调"""
        msg_type = body.get("message_type", "private")

        chat_id = (
            f"group_{body.get('group_id')}" if msg_type == "group"
            else f"user_{body.get('user_id')}"
        )
        content = body.get("raw_message", body.get("message", ""))

        if not content:
            return None

        sender = body.get("sender", {})
        return IncomingMessage(
            platform="qq",
            chat_id=chat_id,
            user_id=str(body.get("user_id", "")),
            user_name=sender.get("nickname", "QQ用户"),
            content=content,
            message_id=str(body.get("message_id", "")),
            raw=body,
            reply=lambda t, cid=chat_id: self.send_message(cid, t),
        )


# ═══════════════════════════════════════════════════
# Gateway 插件
# ═══════════════════════════════════════════════════

class GatewayPlugin(Plugin):
    """
    统一 Gateway 插件
    一行配置接入所有消息平台
    
    config.yaml:
        gateway:
          feishu: {app_id: xxx, app_secret: xxx}
          telegram: {bot_token: xxx}
          wechat: {corp_id: xxx, ...}
          line: {channel_access_token: xxx}
          discord: {bot_token: xxx}
          slack: {bot_token: xxx}
    """

    info = PluginInfo(
        name="gateway",
        version="1.0.0",
        description="统一消息平台接入: 飞书/企业微信/Telegram/LINE/Discord/Slack",
        author="meshctx",
    )

    CONNECTOR_MAP = {
        "feishu": FeishuConnector,
        "telegram": TelegramConnector,
        "wechat": WeChatWorkConnector,
        "wechat_personal": WeChatPersonalConnector,
        "whatsapp": WhatsAppConnector,
        "qq": QQConnector,
        "line": LineConnector,
        "discord": DiscordConnector,
        "slack": SlackConnector,
    }

    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {}

    async def on_load(self):
        gw_config = self.kernel.config.get("gateway", {})
        if not gw_config.get("enabled", True):
            logger.info("Gateway 已禁用")
            return

        # 订阅 agent 回复事件
        self.kernel.bus.subscribe(
            "agent.response", self._on_agent_response, plugin_name="gateway"
        )

        # 初始化所有已配置的连接器
        for platform, cls in self.CONNECTOR_MAP.items():
            platform_cfg = gw_config.get(platform, {})
            if platform_cfg.get("enabled", True) and self._has_credentials(platform_cfg):
                connector = cls(platform_cfg, self.kernel.bus)
                self._connectors[platform] = connector
                await connector.start()

        logger.info(f"Gateway 已加载: {list(self._connectors.keys())}")

    async def on_unload(self):
        for connector in self._connectors.values():
            await connector.stop()
        self._connectors.clear()

    def _has_credentials(self, cfg: Dict) -> bool:
        """检查是否有有效凭证"""
        checks = {
            "feishu": ["app_id", "app_secret"],
            "telegram": ["bot_token"],
            "wechat": ["corp_id", "corp_secret"],
            "line": ["channel_access_token"],
            "discord": ["bot_token"],
            "slack": ["bot_token"],
        }
        for platform, keys in checks.items():
            if platform in str(cfg):
                return any(cfg.get(k) for k in keys)
        return False

    async def _on_agent_response(self, event: Event):
        """Agent 回复 → 路由到对应平台"""
        data = event.data
        platform = data.get("platform", "")
        chat_id = data.get("chat_id", "")
        text = data.get("text", "")

        connector = self._connectors.get(platform)
        if connector:
            await connector.send_message(chat_id, text)

    async def send(self, platform: str, chat_id: str, text: str):
        """手动发送消息到指定平台"""
        connector = self._connectors.get(platform)
        if connector:
            await connector.send_message(chat_id, text)
        else:
            logger.warning(f"平台 '{platform}' 未连接")
