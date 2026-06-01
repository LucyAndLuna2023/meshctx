"""
meshctx v3.92 — Email Integration Engine (IMAP/SMTP 邮件集成引擎)

功能:
  1) IMAP 收件 / SMTP 发件
  2) AI 自动分类 + 智能标签
  3) 自动摘要 + 回复草稿生成
  4) 垃圾邮件过滤 (规则+AI双引擎)

设计模式: dataclass + 类 + 单例 (get_email_engine / reset_email_engine)
"""

import imaplib
import logging
import re
import smtplib
import threading
import time
from dataclasses import dataclass, field
from email import message as email_message
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.email_engine")


# ═══════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════

class EmailLabelType(str, Enum):
    """邮件标签类型"""
    PRIMARY = "primary"           # 主要
    SOCIAL = "social"             # 社交
    PROMOTIONS = "promotions"     # 推广/营销
    UPDATES = "updates"           # 通知/更新
    FINANCE = "finance"           # 金融/账单
    TRAVEL = "travel"             # 旅行
    WORK = "work"                 # 工作
    PERSONAL = "personal"         # 个人
    SPAM = "spam"                 # 垃圾
    UNKNOWN = "unknown"           # 未分类


class SpamLevel(str, Enum):
    """垃圾邮件等级"""
    CLEAN = "clean"               # 正常
    SUSPICIOUS = "suspicious"     # 可疑
    LIKELY_SPAM = "likely_spam"   # 很可能垃圾
    SPAM = "spam"                 # 确认垃圾
    PHISHING = "phishing"         # 钓鱼邮件


# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EmailAttachment:
    """邮件附件"""
    filename: str
    content_type: str
    size_bytes: int
    payload: Optional[bytes] = None


@dataclass
class EmailMessage:
    """规范化邮件消息"""
    uid: str = ""
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: List[str] = field(default_factory=list)
    cc: List[str] = field(default_factory=list)
    date: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: List[EmailAttachment] = field(default_factory=list)
    raw_headers: Dict[str, str] = field(default_factory=dict)
    is_read: bool = False
    is_flagged: bool = False
    flags: List[str] = field(default_factory=list)

    @property
    def snippet(self) -> str:
        """正文摘要 (前200字符)"""
        return self.body_text[:200] if self.body_text else "(no body)"


@dataclass
class EmailLabel:
    """AI 分类标签结果"""
    label_type: EmailLabelType = EmailLabelType.UNKNOWN
    confidence: float = 0.0          # 0.0 ~ 1.0
    sub_labels: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    reasoning: str = ""              # 分类理由


@dataclass
class EmailSummary:
    """AI 自动摘要结果"""
    summary_text: str = ""           # 一句话摘要
    key_points: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    sentiment: str = "neutral"      # positive / neutral / negative
    urgency: str = "low"            # low / medium / high
    model_used: str = ""


@dataclass
class DraftReply:
    """AI 生成的回复草稿"""
    subject: str = ""
    body_text: str = ""
    tone: str = "professional"      # professional / casual / formal / friendly
    references: str = ""
    suggested_actions: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class SpamVerdict:
    """垃圾邮件判定结果"""
    level: SpamLevel = SpamLevel.CLEAN
    score: float = 0.0               # 0.0 ~ 1.0 (越高越像垃圾)
    rules_triggered: List[str] = field(default_factory=list)
    ai_verdict: str = ""
    ai_confidence: float = 0.0
    recommended_action: str = ""     # keep / quarantine / reject


@dataclass
class InboxStats:
    """收件箱统计"""
    total: int = 0
    unread: int = 0
    flagged: int = 0
    by_label: Dict[str, int] = field(default_factory=dict)
    spam_count: int = 0
    last_fetch: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# Spam Filter Rules Engine
# ═══════════════════════════════════════════════════════════════════

# 已知垃圾邮件关键词/模式
SPAM_KEYWORDS = [
    r"\b(viagra|cialis|levitra)\b",
    r"\b(you.?won|prize|lottery|jackpot)\b",
    r"\b(click.?(here|now)|act.?(now|fast))\b",
    r"\b(nigerian.?(prince|royalty))\b",
    r"\b(cryptocurrency.?(investment|millionaire|guaranteed))\b",
    r"\b(work.?(from|at).?home.*\$\d+)",
    r"\b(free.?(money|cash|gift|offer|sample))\b",
    r"\b(limited.?(time|offer).*!)\b",
    r"\b(100%.?(free|satisfaction|guaranteed))\b",
    r"\b(urgent.?(reply|action).*required)\b",
    r"\b(account.?(suspended|locked|verify|update).*click)\b",
]

SPAM_SENDER_PATTERNS = [
    r"@(?:mailinator|tempmail|guerrillamail|10minutemail)\.com",
    r"\.(?:xyz|top|click|win|loan|work|gq|cf|ga|ml|tk)$",
]

PHISHING_PATTERNS = [
    r"(?:paypal|bank|apple|google|microsoft|amazon).*(?:verify|confirm|update|security).*(?:click|link|login)",
    r"(?:urgent|immediate).*(?:password|credential|account).*(?:expired|compromised|suspended)",
]


def _score_spam_rules(message: EmailMessage) -> SpamVerdict:
    """基于规则引擎的垃圾评分"""
    score = 0.0
    rules = []

    combined = (
        message.subject.lower() + " " +
        message.body_text.lower()[:2000] + " " +
        message.sender.lower()
    )

    # 关键词检测
    for pattern in SPAM_KEYWORDS:
        if re.search(pattern, combined, re.IGNORECASE):
            score += 0.12
            rules.append(f"spam_kw:{pattern[:30]}")

    # 发件人域名检测
    sender_domain = message.sender.split("@")[-1] if "@" in message.sender else ""
    for pattern in SPAM_SENDER_PATTERNS:
        if re.search(pattern, sender_domain, re.IGNORECASE):
            score += 0.20
            rules.append(f"spam_sender:{pattern}")

    # 钓鱼检测
    for pattern in PHISHING_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            score += 0.25
            rules.append(f"phishing:{pattern[:40]}")

    # 空正文 + 纯HTML = 可疑
    if not message.body_text.strip() and message.body_html:
        score += 0.10
        rules.append("html_only_no_text")

    # 过多链接
    link_count = len(re.findall(r"https?://", combined))
    if link_count > 5:
        score += 0.10
        rules.append(f"excessive_links:{link_count}")

    # 全大写主题
    if message.subject and message.subject == message.subject.upper() and len(message.subject) > 10:
        score += 0.05
        rules.append("all_caps_subject")

    # 无Message-ID头
    if not message.message_id:
        score += 0.08
        rules.append("missing_message_id")

    score = min(score, 1.0)

    if score >= 0.80:
        level = SpamLevel.SPAM
        action = "reject"
    elif score >= 0.60:
        level = SpamLevel.LIKELY_SPAM
        action = "quarantine"
    elif score >= 0.30:
        level = SpamLevel.SUSPICIOUS
        action = "keep_with_warning"
    else:
        level = SpamLevel.CLEAN
        action = "keep"

    return SpamVerdict(
        level=level,
        score=score,
        rules_triggered=rules,
        ai_verdict="",
        ai_confidence=0.0,
        recommended_action=action,
    )


# ═══════════════════════════════════════════════════════════════════
# AI Classification (keyword heuristic fallback)
# ═══════════════════════════════════════════════════════════════════

# 关键词 → 标签 映射表
LABEL_KEYWORD_MAP: Dict[EmailLabelType, List[str]] = {
    EmailLabelType.FINANCE: [
        "invoice", "receipt", "payment", "transaction", "bank", "credit",
        "billing", "subscription", "order #", "purchase", "statement",
        "余额", "账单", "发票", "付款", "银行", "退款",
    ],
    EmailLabelType.SOCIAL: [
        "friend request", "like", "comment", "follow", "tweet", "post",
        "mentioned", "shared", "tagged", "connection request",
    ],
    EmailLabelType.PROMOTIONS: [
        "discount", "sale", "offer", "deal", "coupon", "promo", "clearance",
        "save", "off", "limited time", "shop now", "buy now",
        "促销", "折扣", "优惠", "限时",
    ],
    EmailLabelType.UPDATES: [
        "confirmation", "notification", "alert", "reminder", "status",
        "update", "password reset", "verify", "welcome", "registered",
    ],
    EmailLabelType.TRAVEL: [
        "flight", "hotel", "booking", "itinerary", "reservation",
        "check-in", "boarding", "trip", "destination",
    ],
    EmailLabelType.WORK: [
        "meeting", "agenda", "deadline", "project", "report", "presentation",
        "task", "assign", "sprint", "standup", "quarterly",
        "会议", "项目", "报告", "任务",
    ],
    EmailLabelType.PERSONAL: [
        "mom", "dad", "family", "birthday", "congratulations", "wedding",
        "dinner", "lunch", "party", "invitation",
    ],
}


def _classify_by_keywords(message: EmailMessage) -> EmailLabel:
    """基于关键词的启发式邮件分类 (无LLM时的fallback)"""
    combined = (message.subject + " " + message.body_text[:1000]).lower()
    scores: Dict[EmailLabelType, float] = {}
    matched_keywords: Dict[EmailLabelType, List[str]] = {}

    for label_type, keywords in LABEL_KEYWORD_MAP.items():
        hits = [kw for kw in keywords if kw.lower() in combined]
        if hits:
            # 每命中一个关键词加 0.2，上限 1.0
            raw = min(len(hits) * 0.2, 1.0)
            scores[label_type] = raw
            matched_keywords[label_type] = hits

    if not scores:
        return EmailLabel(
            label_type=EmailLabelType.PRIMARY,
            confidence=0.3,
            reasoning="No strong signals; defaulting to primary",
        )

    best = max(scores, key=lambda k: scores[k])
    return EmailLabel(
        label_type=best,
        confidence=scores[best],
        keywords=matched_keywords[best],
        sub_labels=[],
        reasoning=f"Matched {len(matched_keywords[best])} keywords: {', '.join(matched_keywords[best][:5])}",
    )


def _generate_summary_heuristic(message: EmailMessage) -> EmailSummary:
    """基于启发式的邮件摘要 (无LLM时的fallback)"""
    text = message.body_text or message.body_html or ""
    if not text.strip():
        return EmailSummary(
            summary_text=f"Email from {message.sender_name or message.sender}: {message.subject}",
            key_points=[],
            action_items=[],
        )

    # 提取首段作为摘要
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    first_para = paragraphs[0][:300] if paragraphs else text[:300]
    summary = first_para if len(first_para) <= 300 else first_para[:297] + "..."

    # 提取行动项 (包含以下关键词的句子)
    action_patterns = [
        r"(?:please|pls|kindly|should|must|need to|don't forget).*?[.!?]",
        r"(?:click|visit|download|attach|reply|confirm|review|approve).*?[.!?]",
    ]
    action_items = []
    for pattern in action_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        action_items.extend(matches[:3])

    # 紧迫度
    urgent_kws = ["urgent", "asap", "immediately", "deadline", "紧急"]
    urgency = "high" if any(kw in text.lower() for kw in urgent_kws) else "low"

    return EmailSummary(
        summary_text=summary,
        key_points=[p[:200] for p in paragraphs[1:4]],
        action_items=list(set(action_items))[:5],
        sentiment="neutral",
        urgency=urgency,
        model_used="heuristic",
    )


def _draft_reply_heuristic(message: EmailMessage) -> DraftReply:
    """基于模板的回复草稿 (无LLM时的fallback)"""
    sender = message.sender_name or message.sender.split("@")[0] if "@" in message.sender else "there"

    # 检测是否需要行动
    needs_action = any(
        kw in (message.subject + message.body_text).lower()
        for kw in ["confirm", "approve", "review", "urgent", "meeting", "deadline"]
    )

    if needs_action:
        body = (
            f"Hi {sender},\n\n"
            f"Thank you for your email regarding \"{message.subject}\". "
            f"I've received it and will take appropriate action.\n\n"
            f"Best regards"
        )
    else:
        body = (
            f"Hi {sender},\n\n"
            f"Thanks for your message about \"{message.subject}\". "
            f"I'll check it out and get back to you shortly.\n\n"
            f"Best regards"
        )

    return DraftReply(
        subject=f"Re: {message.subject}",
        body_text=body,
        tone="professional",
        references=message.message_id or "",
        suggested_actions=["review_and_respond"] if needs_action else ["acknowledge"],
        confidence=0.6,
    )


# ═══════════════════════════════════════════════════════════════════
# EmailEngine
# ═══════════════════════════════════════════════════════════════════

class EmailEngine:
    """
    v3.92 Email Integration Engine — IMAP/SMTP + AI 分类/摘要/回复 + 垃圾过滤

    支持:
      - IMAP 收件: connect_imap / fetch_emails / disconnect_imap
      - SMTP 发件: connect_smtp / send_email / disconnect_smtp
      - AI 分类: classify_email (标签)
      - AI 摘要: summarize_email
      - AI 回复: draft_reply
      - 垃圾过滤: check_spam
      - 全流程: process_inbox (批量处理)
      - 统计: stats / inbox_stats
    """

    def __init__(
        self,
        imap_host: str = "",
        imap_port: int = 993,
        smtp_host: str = "",
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        classifier_fn: Optional[Callable[[EmailMessage], EmailLabel]] = None,
        summarizer_fn: Optional[Callable[[EmailMessage], EmailSummary]] = None,
        reply_fn: Optional[Callable[[EmailMessage], DraftReply]] = None,
    ):
        """
        Args:
            imap_host: IMAP 服务器地址
            imap_port: IMAP 端口 (默认 993 SSL)
            smtp_host: SMTP 服务器地址
            smtp_port: SMTP 端口 (默认 587 STARTTLS)
            username: 邮箱账号
            password: 邮箱密码/App密码
            classifier_fn: 自定义AI分类函数 (email → label)
            summarizer_fn: 自定义摘要函数 (email → summary)
            reply_fn: 自定义回复草稿函数 (email → draft)
        """
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password

        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._smtp: Optional[smtplib.SMTP] = None
        self._lock = threading.RLock()

        # 可插拔的AI函数
        self._classifier_fn = classifier_fn
        self._summarizer_fn = summarizer_fn
        self._reply_fn = reply_fn

        # 统计
        self._emails_fetched = 0
        self._emails_sent = 0
        self._spam_detected = 0
        self._classifications_done = 0
        self._summaries_done = 0
        self._replies_drafted = 0
        self._start_time = time.monotonic()
        self._last_fetch_time: float = 0.0
        self._label_counts: Dict[str, int] = {}

        # 已处理消息缓存
        self._processed_uids: Dict[str, dict] = {}

    # ── Connection Management ──────────────────────────────────────

    def connect_imap(self) -> bool:
        """连接IMAP服务器"""
        with self._lock:
            try:
                if self._imap is not None:
                    try:
                        self._imap.logout()
                    except Exception:
                        pass
                self._imap = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
                self._imap.login(self.username, self.password)
                logger.info(f"IMAP connected: {self.imap_host}:{self.imap_port}")
                return True
            except imaplib.IMAP4.error as e:
                logger.error(f"IMAP login failed: {e}")
                self._imap = None
                return False
            except Exception as e:
                logger.error(f"IMAP connection error: {e}")
                self._imap = None
                return False

    def disconnect_imap(self) -> None:
        """断开IMAP连接"""
        with self._lock:
            if self._imap is not None:
                try:
                    self._imap.close()
                    self._imap.logout()
                except Exception:
                    pass
                self._imap = None

    def connect_smtp(self) -> bool:
        """连接SMTP服务器"""
        with self._lock:
            try:
                if self._smtp is not None:
                    try:
                        self._smtp.quit()
                    except Exception:
                        pass
                self._smtp = smtplib.SMTP(self.smtp_host, self.smtp_port)
                self._smtp.starttls()
                self._smtp.login(self.username, self.password)
                logger.info(f"SMTP connected: {self.smtp_host}:{self.smtp_port}")
                return True
            except smtplib.SMTPException as e:
                logger.error(f"SMTP login failed: {e}")
                self._smtp = None
                return False
            except Exception as e:
                logger.error(f"SMTP connection error: {e}")
                self._smtp = None
                return False

    def disconnect_smtp(self) -> None:
        """断开SMTP连接"""
        with self._lock:
            if self._smtp is not None:
                try:
                    self._smtp.quit()
                except Exception:
                    pass
                self._smtp = None

    def disconnect_all(self) -> None:
        """断开所有连接"""
        self.disconnect_imap()
        self.disconnect_smtp()

    @property
    def imap_connected(self) -> bool:
        """IMAP是否已连接"""
        return self._imap is not None

    @property
    def smtp_connected(self) -> bool:
        """SMTP是否已连接"""
        return self._smtp is not None

    # ── IMAP: Fetch ────────────────────────────────────────────────

    def fetch_emails(
        self,
        folder: str = "INBOX",
        limit: int = 50,
        unread_only: bool = False,
        mark_seen: bool = False,
    ) -> List[EmailMessage]:
        """
        从IMAP抓取邮件。

        Args:
            folder: 邮箱文件夹 (默认 INBOX)
            limit: 最大抓取数量
            unread_only: 仅抓取未读
            mark_seen: 是否标记为已读

        Returns:
            解析后的 EmailMessage 列表
        """
        if not self._imap:
            logger.warning("IMAP not connected, returning empty list")
            return []

        with self._lock:
            try:
                status, _ = self._imap.select(folder)
                if status != "OK":
                    logger.error(f"Failed to select folder: {folder}")
                    return []

                search_criteria = "UNSEEN" if unread_only else "ALL"
                status, uids = self._imap.uid("SEARCH", "UTF-8", search_criteria)
                if status != "OK":
                    return []

                uid_list = uids[0].split() if uids[0] else []
                uid_list = uid_list[-limit:]  # 取最近的

                messages = []
                for uid in uid_list:
                    uid_str = uid.decode() if isinstance(uid, bytes) else uid
                    status, data = self._imap.uid(
                        "FETCH", uid_str, "(BODY.PEEK[] FLAGS)"
                    )
                    if status != "OK" or not data or data[0] is None:
                        continue

                    raw_email = data[0][1] if isinstance(data[0], tuple) else data[0]
                    msg = self._parse_raw_email(raw_email, uid_str)

                    # 解析标志
                    flags_raw = ""
                    if isinstance(data[0], tuple) and len(data[0]) > 1:
                        flags_raw = data[0][0].decode(errors="ignore") if isinstance(data[0][0], bytes) else str(data[0][0])
                    msg.is_read = b"\\Seen" in (data[0][0] if isinstance(data[0], tuple) and len(data[0]) > 0 and isinstance(data[0][0], bytes) else b"")
                    msg.flags = re.findall(r"\\([A-Za-z]+)", flags_raw)
                    msg.is_flagged = "Flagged" in msg.flags

                    if mark_seen:
                        self._imap.uid("STORE", uid_str, "+FLAGS", "\\Seen")

                    messages.append(msg)

                self._emails_fetched += len(messages)
                self._last_fetch_time = time.monotonic()
                logger.info(f"Fetched {len(messages)} emails from {folder}")
                return messages

            except imaplib.IMAP4.error as e:
                logger.error(f"IMAP fetch error: {e}")
                return []
            except Exception as e:
                logger.error(f"Unexpected fetch error: {e}")
                return []

    def _parse_raw_email(self, raw: bytes, uid: str) -> EmailMessage:
        """解析原始邮件为 EmailMessage"""
        msg = email_message.message_from_bytes(raw)

        # 解码主题
        subject_parts = decode_header(msg.get("Subject", ""))
        subject = ""
        for part, charset in subject_parts:
            if isinstance(part, bytes):
                try:
                    subject += part.decode(charset or "utf-8", errors="replace")
                except Exception:
                    subject += part.decode("utf-8", errors="replace")
            else:
                subject += str(part)

        # 解析发件人
        from_header = msg.get("From", "")
        sender_name, sender_addr = self._parse_address(from_header)

        # 解析收件人
        to_header = msg.get("To", "")
        recipients = [addr for _, addr in self._parse_addresses(to_header)]

        cc_header = msg.get("Cc", "")
        cc_list = [addr for _, addr in self._parse_addresses(cc_header)]

        # 解析正文
        body_text, body_html, attachments = self._extract_body(msg)

        return EmailMessage(
            uid=uid,
            message_id=msg.get("Message-ID", "").strip("<>"),
            subject=subject,
            sender=sender_addr,
            sender_name=sender_name,
            recipients=recipients,
            cc=cc_list,
            date=msg.get("Date", ""),
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            raw_headers=dict(msg.items()),
        )

    @staticmethod
    def _parse_address(header: str) -> Tuple[str, str]:
        """解析单个地址头，返回 (name, addr)"""
        parts = decode_header(header)
        decoded = ""
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    decoded += part.decode(charset or "utf-8", errors="replace")
                except Exception:
                    decoded += part.decode("utf-8", errors="replace")
            else:
                decoded += str(part)

        # 提取 name <addr> 或 addr
        match = re.match(r'(?:["\']?([^"\']+)["\']?\s*)?<?([^>]+)>?', decoded.strip())
        if match:
            name = match.group(1).strip() if match.group(1) else ""
            addr = match.group(2).strip()
            return name, addr
        return "", decoded.strip()

    @staticmethod
    def _parse_addresses(header: str) -> List[Tuple[str, str]]:
        """解析多个地址，返回 [(name, addr), ...]"""
        results = []
        for part in header.split(","):
            part = part.strip()
            if part:
                results.append(EmailEngine._parse_address(part))
        return results

    @staticmethod
    def _extract_body(
        msg: "email_message.Message",
    ) -> Tuple[str, str, List[EmailAttachment]]:
        """提取邮件正文和附件"""
        body_text = ""
        body_html = ""
        attachments: List[EmailAttachment] = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    payload = part.get_payload(decode=True)
                    attachments.append(EmailAttachment(
                        filename=part.get_filename() or "attachment",
                        content_type=content_type,
                        size_bytes=len(payload) if payload else 0,
                        payload=payload,
                    ))
                elif content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body_text += payload.decode(charset, errors="replace")
                        except Exception:
                            body_text += payload.decode("utf-8", errors="replace")
                elif content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body_html += payload.decode(charset, errors="replace")
                        except Exception:
                            body_html += payload.decode("utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                ct = msg.get_content_type()
                try:
                    text = payload.decode(charset, errors="replace")
                except Exception:
                    text = payload.decode("utf-8", errors="replace")
                if ct == "text/html":
                    body_html = text
                else:
                    body_text = text

        return body_text.strip(), body_html.strip(), attachments

    # ── SMTP: Send ─────────────────────────────────────────────────

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        html: bool = False,
    ) -> bool:
        """
        发送邮件。

        Args:
            to: 收件人地址 (多个用逗号分隔)
            subject: 主题
            body: 正文
            cc: 抄送
            bcc: 密送
            html: body是否为HTML

        Returns:
            是否发送成功
        """
        if not self._smtp:
            logger.warning("SMTP not connected")
            return False

        with self._lock:
            try:
                msg = MIMEMultipart()
                msg["From"] = self.username
                msg["To"] = to
                msg["Subject"] = subject
                if cc:
                    msg["Cc"] = cc

                subtype = "html" if html else "plain"
                msg.attach(MIMEText(body, subtype))

                recipients = [a.strip() for a in to.split(",")]
                if cc:
                    recipients += [a.strip() for a in cc.split(",")]
                if bcc:
                    recipients += [a.strip() for a in bcc.split(",")]

                self._smtp.sendmail(self.username, recipients, msg.as_string())
                self._emails_sent += 1
                logger.info(f"Email sent to {to}: {subject}")
                return True
            except smtplib.SMTPException as e:
                logger.error(f"SMTP send error: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected send error: {e}")
                return False

    # ── AI Classification ──────────────────────────────────────────

    def classify_email(self, message: EmailMessage) -> EmailLabel:
        """
        AI自动分类邮件并分配标签。

        优先使用注入的 classifier_fn，fallback 到关键词启发式分类。
        """
        if self._classifier_fn:
            try:
                label = self._classifier_fn(message)
            except Exception as e:
                logger.warning(f"Classifier function failed: {e}, falling back to heuristic")
                label = _classify_by_keywords(message)
        else:
            label = _classify_by_keywords(message)

        self._classifications_done += 1
        lt = label.label_type.value
        self._label_counts[lt] = self._label_counts.get(lt, 0) + 1
        return label

    def set_classifier(self, fn: Callable[[EmailMessage], EmailLabel]) -> None:
        """注入自定义AI分类函数"""
        self._classifier_fn = fn

    # ── AI Summarization ───────────────────────────────────────────

    def summarize_email(self, message: EmailMessage) -> EmailSummary:
        """
        自动生成邮件摘要。

        优先使用注入的 summarizer_fn，fallback 到启发式摘要。
        """
        if self._summarizer_fn:
            try:
                summary = self._summarizer_fn(message)
            except Exception as e:
                logger.warning(f"Summarizer function failed: {e}, falling back to heuristic")
                summary = _generate_summary_heuristic(message)
        else:
            summary = _generate_summary_heuristic(message)

        self._summaries_done += 1
        return summary

    def set_summarizer(self, fn: Callable[[EmailMessage], EmailSummary]) -> None:
        """注入自定义摘要函数"""
        self._summarizer_fn = fn

    # ── AI Reply Draft ─────────────────────────────────────────────

    def draft_reply(self, message: EmailMessage) -> DraftReply:
        """
        自动生成回复草稿。

        优先使用注入的 reply_fn，fallback 到模板草稿。
        """
        if self._reply_fn:
            try:
                draft = self._reply_fn(message)
            except Exception as e:
                logger.warning(f"Reply function failed: {e}, falling back to template")
                draft = _draft_reply_heuristic(message)
        else:
            draft = _draft_reply_heuristic(message)

        self._replies_drafted += 1
        return draft

    def set_reply_fn(self, fn: Callable[[EmailMessage], DraftReply]) -> None:
        """注入自定义回复草稿函数"""
        self._reply_fn = fn

    # ── Spam Filtering ─────────────────────────────────────────────

    def check_spam(self, message: EmailMessage) -> SpamVerdict:
        """
        垃圾邮件过滤。

        规则引擎评分 + 可选的AI判定。返回详细判定结果。
        """
        verdict = _score_spam_rules(message)
        if verdict.level != SpamLevel.CLEAN:
            self._spam_detected += 1
        return verdict

    def is_spam(self, message: EmailMessage) -> bool:
        """快速判断是否为垃圾邮件"""
        return self.check_spam(message).recommended_action in ("reject", "quarantine")

    # ── Pipeline: Full Inbox Processing ────────────────────────────

    def process_inbox(
        self, folder: str = "INBOX", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        全流程处理收件箱: 抓取 → 垃圾过滤 → 分类 → 摘要 → 回复草稿

        Returns:
            每封邮件的处理结果列表：
            [{message, spam_verdict, label, summary, draft_reply, ...}, ...]
        """
        messages = self.fetch_emails(folder=folder, limit=limit)
        results = []

        for msg in messages:
            spam = self.check_spam(msg)

            # 垃圾邮件跳过后续AI处理
            if spam.recommended_action in ("reject", "quarantine"):
                results.append({
                    "message": msg,
                    "spam_verdict": spam,
                    "label": EmailLabel(label_type=EmailLabelType.SPAM, confidence=spam.score),
                    "summary": None,
                    "draft_reply": None,
                })
                self._processed_uids[msg.uid] = {"spam": True, "processed_at": time.time()}
                continue

            label = self.classify_email(msg)
            summary = self.summarize_email(msg)
            draft = self.draft_reply(msg)

            results.append({
                "message": msg,
                "spam_verdict": spam,
                "label": label,
                "summary": summary,
                "draft_reply": draft,
            })
            self._processed_uids[msg.uid] = {
                "spam": False,
                "label": label.label_type.value,
                "processed_at": time.time(),
            }

        return results

    # ── Statistics ──────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """获取引擎运行统计"""
        uptime = time.monotonic() - self._start_time
        return {
            "uptime_seconds": round(uptime, 1),
            "imap_connected": self.imap_connected,
            "smtp_connected": self.smtp_connected,
            "emails_fetched": self._emails_fetched,
            "emails_sent": self._emails_sent,
            "spam_detected": self._spam_detected,
            "classifications_done": self._classifications_done,
            "summaries_done": self._summaries_done,
            "replies_drafted": self._replies_drafted,
            "label_distribution": dict(self._label_counts),
            "processed_emails_cached": len(self._processed_uids),
        }

    def inbox_stats(self, folder: str = "INBOX") -> InboxStats:
        """获取IMAP收件箱统计 (需连接)"""
        if not self._imap:
            return InboxStats(last_fetch=self._last_fetch_time)

        with self._lock:
            try:
                status, _ = self._imap.select(folder)
                if status != "OK":
                    return InboxStats(last_fetch=self._last_fetch_time)

                status, data = self._imap.search(None, "ALL")
                total = len(data[0].split()) if data[0] else 0

                status, data = self._imap.search(None, "UNSEEN")
                unread = len(data[0].split()) if data[0] else 0

                status, data = self._imap.search(None, "FLAGGED")
                flagged = len(data[0].split()) if data[0] else 0

                return InboxStats(
                    total=total,
                    unread=unread,
                    flagged=flagged,
                    by_label=dict(self._label_counts),
                    spam_count=self._spam_detected,
                    last_fetch=self._last_fetch_time,
                )
            except Exception as e:
                logger.error(f"Inbox stats error: {e}")
                return InboxStats(last_fetch=self._last_fetch_time)

    def reset_stats(self) -> None:
        """重置统计计数器"""
        with self._lock:
            self._emails_fetched = 0
            self._emails_sent = 0
            self._spam_detected = 0
            self._classifications_done = 0
            self._summaries_done = 0
            self._replies_drafted = 0
            self._start_time = time.monotonic()
            self._last_fetch_time = 0.0
            self._label_counts.clear()
            self._processed_uids.clear()


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_email_engine: Optional[EmailEngine] = None
_lock_singleton = threading.Lock()


def get_email_engine(
    imap_host: str = "",
    imap_port: int = 993,
    smtp_host: str = "",
    smtp_port: int = 587,
    username: str = "",
    password: str = "",
    classifier_fn: Optional[Callable[[EmailMessage], EmailLabel]] = None,
    summarizer_fn: Optional[Callable[[EmailMessage], EmailSummary]] = None,
    reply_fn: Optional[Callable[[EmailMessage], DraftReply]] = None,
) -> EmailEngine:
    """获取或创建全局 EmailEngine 单例"""
    global _email_engine
    if _email_engine is None:
        with _lock_singleton:
            if _email_engine is None:
                _email_engine = EmailEngine(
                    imap_host=imap_host,
                    imap_port=imap_port,
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    username=username,
                    password=password,
                    classifier_fn=classifier_fn,
                    summarizer_fn=summarizer_fn,
                    reply_fn=reply_fn,
                )
    return _email_engine


def reset_email_engine() -> None:
    """重置全局 EmailEngine 单例"""
    global _email_engine
    with _lock_singleton:
        _email_engine = None
