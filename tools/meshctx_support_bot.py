#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MeshCtx 产品支持 Telegram Bot — meshctx.com 联系方式 / 社群与产品支持
部署: cloudcone (003, 66.154.101.18)
依赖: 仅 requests (003 已有)
用法: python3 meshctx_support_bot.py
"""
import json
import logging
import os
import time
from datetime import datetime

import requests

# ===== 配置 =====
TOKEN = os.environ.get("MESHCTX_BOT_TOKEN", "REDACTED_TELEGRAM_BOT_TOKEN9YLz7fPQ5thpU")
SUPPORT_CHAT_ID = int(os.environ.get("MESHCTX_SUPPORT_CHAT", "7554956188"))  # 支持人员通知
API = f"https://api.telegram.org/bot{TOKEN}"
TIMEOUT = 50  # 长轮询

LOG_DIR = "/opt/meshctx_bot"
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=f"{LOG_DIR}/bot.log", level=logging.INFO,
    format="%(asctime)s %(message)s", datefmt="%m-%d %H:%M:%S")


def log(msg):
    print(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)
    logging.info(msg)


# ===== 产品信息 (FAQ 数据源) =====
VERSION = "v3.121.7"
PRODUCT = {
    "name": "MeshCtx",
    "tagline": "世界第一全脑仿真自进化 AI Agent 平台",
    "version": VERSION,
    "website": "https://meshctx.com",
    "github": "https://github.com/LucyAndLuna2023/meshctx",
    "open_core": "AGPLv3 框架永久开源, 个人永久免费",
}

FAQ = {
    "install": {
        "keywords": ["安装", "install", "下载", "download", "怎么用", "getting started", "桌面", "desktop"],
        "answer": (
            "📥 安装 MeshCtx:\n"
            "• Linux/WSL: curl -fsSL https://meshctx.com/install.sh | bash\n"
            "• macOS: curl -fsSL https://meshctx.com/install-mac.sh | bash\n"
            "• 桌面版: https://github.com/LucyAndLuna2023/meshctx/releases/latest\n"
            "三平台原生包 (Windows/macOS/Linux), 10 语言 UI。"
        ),
    },
    "version": {
        "keywords": ["版本", "version", "更新", "update", "最新"],
        "answer": (
            f"📦 当前版本: {VERSION}\n"
            "• GitHub: https://github.com/LucyAndLuna2023/meshctx/releases\n"
            "• 最新功能: 无轮次限制 + 推理流 + 工具审批 + 全厂商模型 (37 供应商 123+ 模型)"
        ),
    },
    "memory": {
        "keywords": ["记忆", "memory", "mem0", "FSRS", "脑区", "brain"],
        "answer": (
            "🧠 记忆系统: 17 脑区架构 + 四层记忆 (L0-L4)\n"
            "• FSRS 间隔重复 + 图式化三层收敛 + ARCHIVAL 修剪\n"
            "• LongMemEval: EM 64.6% (3采样 best-of-3) / judge 同口径 60.4%\n"
            "• 同预算 16KB: 脑区精选 41.7% vs 暴力截断 25% (+16.7pp)"
        ),
    },
    "models": {
        "keywords": ["模型", "model", "deepseek", "openai", "claude", "gpt", "ollama", "api key", "token"],
        "answer": (
            "🤖 模型支持: 37 供应商 123+ 模型 (DeepSeek/OpenAI/Anthropic/Google/xAI/Ollama/智谱等)\n"
            "• Setup 向导全厂商配置, 自带 API Key 即用\n"
            "• Swarm 群审 (Team 版): 5 模型并行共识投票"
        ),
    },
    "open_source": {
        "keywords": ["开源", "open source", "免费", "free", "license", "AGPL", "收费", "价格", "price"],
        "answer": (
            "🔓 开源与定价:\n"
            "• Open Core: AGPLv3 框架永久开源 (GitHub: LucyAndLuna2023/meshctx)\n"
            "• 个人永久免费\n"
            "• Team ($9/人/月) / Enterprise ($29/人/月) 开发中 → 敬请期待"
        ),
    },
    "features": {
        "keywords": ["功能", "feature", "能做什么", "what can", "能力", "多智能体", "agent", "群审", "swarm", "审批"],
        "answer": (
            "⚡ 核心能力:\n"
            "• 17 脑区全脑仿真 (海马体记忆/杏仁核情感/默认模式网络主动思考)\n"
            "• SDM 稀疏分布式记忆 (O(2^1000) 地址空间)\n"
            "• 多 Agent 协作 + 5 模型群审\n"
            "• 工具审批: 删除/改动文件前征求你意见 (允许/拒绝/自定义)\n"
            "• GenomicOptimizer 基因进化引擎, 越用越聪明"
        ),
    },
    "contact": {
        "keywords": ["联系", "contact", "support", "帮助", "help", "问题", "bug", "反馈", "群", "社群", "community"],
        "answer": (
            "📬 联系我们:\n"
            "• 邮箱: support@meshctx.com\n"
            "• GitHub Issues: https://github.com/LucyAndLuna2023/meshctx/issues\n"
            "• 官网: https://meshctx.com\n"
            "此 bot 也会把你的问题转给支持团队, 我们会尽快回复。"
        ),
    },
}


# ===== Telegram API =====
def api(method, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        log(f"API 错误 {method}: {e}")
        return {}


def send(chat_id, text):
    api("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)


def match_faq(text):
    """关键词匹配 FAQ, 返回最相关答案。"""
    t = (text or "").lower()
    best, best_score = None, 0
    for key, faq in FAQ.items():
        score = sum(1 for kw in faq["keywords"] if kw in t)
        if score > best_score:
            best, best_score = faq, score
    return best["answer"] if best and best_score > 0 else None


def handle_command(text, chat_id):
    cmd = (text or "").strip().split()[0].lower()
    if cmd in ("/start", "/help"):
        send(chat_id, (
            "👋 你好! 我是 MeshCtx 官方支持 bot。\n\n"
            "📌 MeshCtx — 世界第一全脑仿真自进化 AI Agent 平台\n"
            "• 个人永久免费 · Open Core AGPLv3\n"
            "• 官网: https://meshctx.com\n\n"
            "可用命令:\n"
            "/start — 欢迎\n"
            "/faq — 常见问题\n"
            "/version — 版本信息\n"
            "/contact — 联系方式\n\n"
            "也可以直接输入问题 (如: 怎么安装? / 支持哪些模型?)"
        ))
    elif cmd == "/faq":
        send(chat_id, "📖 常见问题:\n\n" + "\n".join(
            f"/{key} — {list(faq['keywords'])[:2]}" for key, faq in FAQ.items()))
    elif cmd == "/version":
        send(chat_id, f"📦 当前版本: {VERSION}\n\n安装: https://meshctx.com")
    elif cmd == "/contact":
        send(chat_id, FAQ["contact"]["answer"])
    else:
        send(chat_id, "未知命令。输入 /help 查看可用命令。")
    return True


def handle_text(text, chat_id, user):
    """自由文本: FAQ 匹配 → 自动回复; 否则转人工。"""
    ans = match_faq(text)
    if ans:
        send(chat_id, ans)
        return
    # 未匹配 → 提示 + 通知支持人员
    send(chat_id, (
        "🤔 这个问题需要人工支持, 已转给 MeshCtx 支持团队。\n"
        "也可发邮件 support@meshctx.com 或到 GitHub Issues 提问: "
        "https://github.com/LucyAndLuna2023/meshctx/issues"
    ))
    name = user.get("first_name", "")
    username = user.get("username", "")
    api("sendMessage", chat_id=SUPPORT_CHAT_ID, text=(
        f"🔔 新支持请求 from {name} (@{username}):\n{text[:500]}"))


# ===== 主循环 =====
def main():
    log(f"MeshCtx 支持 bot 启动 (token={TOKEN[:10]}...)")
    me = api("getMe")
    if me.get("ok"):
        log(f"Bot: @{me['result']['username']}")
    else:
        log("⚠ getMe 失败, 检查 token")
        return
    offset = 0
    while True:
        try:
            r = requests.post(f"{API}/getUpdates",
                              json={"offset": offset, "timeout": TIMEOUT},
                              timeout=TIMEOUT + 15)
            if r.status_code != 200:
                log(f"getUpdates HTTP {r.status_code}")
                time.sleep(3)
                continue
            data = r.json()
            if not data.get("ok"):
                log(f"getUpdates 错误: {data.get('description')}")
                time.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")
                user = msg.get("from", {})
                log(f"← {user.get('username', user.get('first_name','?'))}: {text[:50]}")
                if text.startswith("/"):
                    handle_command(text, chat_id)
                else:
                    handle_text(text, chat_id, user)
        except Exception as e:
            log(f"主循环错误: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
