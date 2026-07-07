"""meshctx email_engine"""
import uuid, time, re
from dataclasses import dataclass, field
from enum import Enum

class SpamLevel(str, Enum):
    CLEAN = "clean"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    LIKELY_SPAM = "likely_spam"
    SPAM = "spam"
    PHISHING = "phishing"

@dataclass
class SpamVerdict:
    level: SpamLevel = SpamLevel.CLEAN
    score: float = 0.0
    rules_triggered: list = field(default_factory=list)
    recommended_action: str = ""

class EmailLabelType(str, Enum):
    IMPORTANT = "important"
    WORK = "work"
    PERSONAL = "personal"
    NEWSLETTER = "newsletter"
    SPAM = "spam"
    FINANCE = "finance"

@dataclass
class EmailLabel:
    label_type: EmailLabelType = EmailLabelType.IMPORTANT
    confidence: float = 0.5
    reasoning: str = ""

@dataclass
class EmailAttachment:
    filename: str = ""
    size: int = 0
    size_bytes: int = 0
    content_type: str = ""
    payload: bytes = b""

@dataclass
class EmailSummary:
    email_id: str = ""
    subject: str = ""
    sender: str = ""
    summary: str = ""
    summary_text: str = ""
    urgency: str = "low"
    model_used: str = "heuristic"
    labels: list = field(default_factory=list)

@dataclass
class DraftReply:
    reply_id: str = field(default_factory=lambda: f"draft_{uuid.uuid4().hex[:8]}")
    to: str = ""
    subject: str = ""
    body: str = ""
    body_text: str = ""
    tone: str = "professional"
    confidence: float = 0.7

@dataclass
class InboxStats:
    total: int = 0
    unread: int = 0
    spam_count: int = 0
    by_label: dict = field(default_factory=dict)

@dataclass
class EmailMessage:
    uid: str = ""
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: list = field(default_factory=list)
    date: str = ""
    body_text: str = ""
    body_html: str = ""

    @property
    def snippet(self) -> str:
        text = self.body_text or self.body_html or self.subject
        return text[:200]


def _score_spam_rules(msg: EmailMessage) -> SpamVerdict:
    text = (msg.subject + " " + msg.body_text).lower()
    spam_keywords = ["viagra", "lottery", "winner", "click here", "urgent", "free money", "won", "prize", "claim"]
    phishing_keywords = ["verify your password", "verify your account", "verify your bank", "credentials", "account suspended", "compromised"]

    spam_score = 0.0
    rules_triggered = []

    spam_count = sum(1 for kw in spam_keywords if kw in text)
    if spam_count >= 3:
        spam_score = 0.8
        rules_triggered.append("spam_keywords")
    elif spam_count >= 1:
        spam_score = 0.5
        rules_triggered.append("spam_keywords")

    if any(kw in text for kw in phishing_keywords):
        spam_score = max(spam_score, 0.7)
        rules_triggered.append("phishing")

    if not msg.body_text.strip() and msg.body_html.strip():
        spam_score = max(spam_score, 0.35)
        rules_triggered.append("html_only_no_text")

    if spam_score >= 0.8:
        level = SpamLevel.SPAM
        action = "reject"
    elif spam_score >= 0.6:
        level = SpamLevel.LIKELY_SPAM
        action = "quarantine"
    elif spam_score > 0.3:
        level = SpamLevel.LOW
        action = "keep"
    else:
        level = SpamLevel.CLEAN
        action = "keep"

    return SpamVerdict(level=level, score=spam_score, rules_triggered=rules_triggered, recommended_action=action)


def _classify_by_keywords(msg: EmailMessage) -> EmailLabel:
    text = (msg.subject + " " + msg.body_text).lower()
    finance_kw = ["invoice", "payment", "billing", "purchase", "amount", "charged"]
    work_kw = ["meeting", "report", "roadmap", "deadline", "project", "sprint"]
    personal_kw = ["party", "birthday", "weekend", "vacation", "dinner"]
    newsletter_kw = ["newsletter", "unsubscribe", "weekly digest", "subscribe"]

    for kw in finance_kw:
        if kw in text:
            return EmailLabel(label_type=EmailLabelType.FINANCE, confidence=0.5, reasoning=f"keyword: {kw}")
    for kw in work_kw:
        if kw in text:
            return EmailLabel(label_type=EmailLabelType.WORK, confidence=0.4, reasoning=f"keyword: {kw}")
    for kw in personal_kw:
        if kw in text:
            return EmailLabel(label_type=EmailLabelType.PERSONAL, confidence=0.4, reasoning=f"keyword: {kw}")
    for kw in newsletter_kw:
        if kw in text:
            return EmailLabel(label_type=EmailLabelType.NEWSLETTER, confidence=0.4, reasoning=f"keyword: {kw}")
    return EmailLabel(label_type=EmailLabelType.IMPORTANT, confidence=0.2, reasoning="default")


def _generate_summary_heuristic(msg: EmailMessage) -> EmailSummary:
    text = msg.body_text or msg.subject
    summary_text = text[:200] if text else ""
    return EmailSummary(
        email_id=msg.uid,
        subject=msg.subject,
        sender=msg.sender,
        summary=summary_text,
        summary_text=summary_text,
        urgency="low",
        model_used="heuristic",
    )


def _draft_reply_heuristic(msg: EmailMessage) -> DraftReply:
    return DraftReply(
        subject=f"Re: {msg.subject}",
        body=f"Thank you for your email regarding '{msg.subject}'. I will review and respond shortly.",
        body_text=f"Thank you for your email regarding '{msg.subject}'. I will review and respond shortly.",
        tone="professional",
        confidence=0.7,
    )


class EmailEngine:
    def __init__(self, imap_host: str = "", smtp_host: str = "", classifier_fn=None, summarizer_fn=None, reply_fn=None, username: str = "", password: str = "", **kw):
        self.imap_host = imap_host
        self.smtp_host = smtp_host
        self.username = username
        self._password = password
        self.imap_connected = False
        self.smtp_connected = False
        self._classifier_fn = classifier_fn
        self._summarizer_fn = summarizer_fn
        self._reply_fn = reply_fn
        self._emails = {}
        self._labels = {}
        self._stats = InboxStats()
        self._counters = {"classifications_done": 0, "spam_detected": 0, "summaries_done": 0, "replies_drafted": 0}

    def classify_email(self, msg: EmailMessage) -> EmailLabel:
        self._counters["classifications_done"] += 1
        if self._classifier_fn:
            return self._classifier_fn(msg)
        return _classify_by_keywords(msg)

    classify = classify_email

    def summarize_email(self, msg: EmailMessage) -> EmailSummary:
        self._counters["summaries_done"] += 1
        if self._summarizer_fn:
            return self._summarizer_fn(msg)
        return _generate_summary_heuristic(msg)

    summarize = summarize_email

    def summarize(self, email_id, subject="", body="", sender="", **kw):
        return EmailSummary(email_id=email_id, subject=subject, sender=sender, summary=body[:100] if body else "")

    def draft_reply(self, msg: EmailMessage) -> DraftReply:
        self._counters["replies_drafted"] += 1
        if self._reply_fn:
            return self._reply_fn(msg)
        return _draft_reply_heuristic(msg)

    def check_spam(self, msg) -> SpamVerdict:
        verdict = _score_spam_rules(msg)
        if verdict.level in (SpamLevel.LIKELY_SPAM, SpamLevel.SPAM, SpamLevel.PHISHING):
            self._counters["spam_detected"] += 1
        return verdict

    def is_spam(self, msg: EmailMessage) -> bool:
        verdict = self.check_spam(msg)
        return verdict.level in (SpamLevel.LIKELY_SPAM, SpamLevel.SPAM, SpamLevel.PHISHING)

    def stats(self) -> dict:
        return dict(self._counters)

    def reset_stats(self):
        self._counters = {"classifications_done": 0, "spam_detected": 0, "summaries_done": 0, "replies_drafted": 0}

    def fetch_emails(self) -> list:
        return []

    def send_email(self, to: str = "", subject: str = "", body: str = "") -> bool:
        return False

    def inbox_stats(self) -> InboxStats:
        return self._stats

    def get_inbox_stats(self, **kw):
        return self._stats


_engine = None
def get_email_engine(imap_host: str = None, **kwargs):
    global _engine
    if _engine is None:
        _engine = EmailEngine(imap_host=imap_host or "", **kwargs)
    return _engine

def reset_email_engine():
    global _engine
    _engine = None
