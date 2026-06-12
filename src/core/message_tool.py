"""
meshctx Message — 统一多平台消息发送
对标: OpenClaw message tool
支持: CLI, Telegram, Discord, Feishu, WeCom, Slack, Email, SMS, Webhook
"""
import os, json, subprocess, urllib.request
from pathlib import Path
from typing import Optional

PLATFORM_HANDLERS = {}

def register_handler(platform: str, handler):
    """注册平台消息处理器"""
    PLATFORM_HANDLERS[platform] = handler

def message_send(platform: str, content: str, target: str = None, 
                 title: str = None, attachments: list = None) -> str:
    """发送消息到指定平台
    
    Args:
        platform: cli | telegram | discord | feishu | wecom | slack | email | sms | webhook
        content: 消息内容
        target: 目标 (chat_id, channel, webhook_url, email address...)
        title: 可选标题
        attachments: 附件列表 [{name, url, type}]
    """
    if platform in PLATFORM_HANDLERS:
        return PLATFORM_HANDLERS[platform](content, target, title, attachments)
    
    if platform == "cli":
        print(f"\n{'='*60}\n{title or 'Message'}\n{'='*60}\n{content}\n{'='*60}")
        return "Printed to CLI"
    
    if platform == "webhook":
        if not target:
            return "Error: webhook requires target URL"
        try:
            data = json.dumps({"content": content, "title": title}).encode()
            req = urllib.request.Request(target, data=data, 
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return f"Webhook sent to {target[:50]}..."
        except Exception as e:
            return f"Webhook failed: {e}"
    
    if platform == "telegram":
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = target or os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return "Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required"
        try:
            text = f"*{title}*\n{content}" if title else content
            data = json.dumps({"chat_id": chat_id, "text": text[:4000], 
                               "parse_mode": "Markdown"}).encode()
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            req = urllib.request.Request(url, data=data, 
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return f"Telegram sent to {chat_id}"
        except Exception as e:
            return f"Telegram failed: {e}"
    
    if platform == "discord":
        webhook = target or os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook:
            return "Error: DISCORD_WEBHOOK_URL required"
        try:
            data = json.dumps({"content": f"**{title}**\n{content}" if title else content}).encode()
            req = urllib.request.Request(webhook, data=data,
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return "Discord sent"
        except Exception as e:
            return f"Discord failed: {e}"
    
    if platform == "feishu":
        webhook = target or os.environ.get("FEISHU_WEBHOOK_URL")
        if not webhook:
            return "Error: FEISHU_WEBHOOK_URL required"
        try:
            text = f"{title}\n{content}" if title else content
            data = json.dumps({"msg_type": "text", 
                "content": {"text": text[:20000]}}).encode()
            req = urllib.request.Request(webhook, data=data,
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return "Feishu sent"
        except Exception as e:
            return f"Feishu failed: {e}"
    
    if platform == "email":
        # Use sendmail or SMTP
        recipient = target
        if not recipient:
            return "Error: email target required"
        try:
            subject = title or "meshctx Message"
            body = content
            msg = f"Subject: {subject}\nContent-Type: text/plain; charset=utf-8\n\n{body}"
            p = subprocess.run(["sendmail", recipient], input=msg, 
                             capture_output=True, text=True, timeout=10)
            return f"Email sent to {recipient}" if p.returncode == 0 else f"Email failed: {p.stderr}"
        except FileNotFoundError:
            return "Error: sendmail not available"
        except Exception as e:
            return f"Email failed: {e}"
    
    return f"Unknown platform: {platform}. Available: cli, webhook, telegram, discord, feishu, email"

def message_broadcast(content: str, platforms: list[str], title: str = None,
                      targets: dict = None) -> str:
    """广播消息到多个平台"""
    targets = targets or {}
    results = []
    for p in platforms:
        t = targets.get(p)
        r = message_send(p, content, t, title)
        results.append(f"  {p}: {r}")
    return "Broadcast:\n" + "\n".join(results)
