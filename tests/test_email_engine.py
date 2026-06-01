"""v3.92 Email Engine tests"""
import time
import pytest
from src.core.email_engine import (
    EmailEngine,
    EmailMessage,
    EmailLabel,
    EmailLabelType,
    EmailSummary,
    DraftReply,
    SpamVerdict,
    SpamLevel,
    InboxStats,
    EmailAttachment,
    get_email_engine,
    reset_email_engine,
    _score_spam_rules,
    _classify_by_keywords,
    _generate_summary_heuristic,
    _draft_reply_heuristic,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def clean_email():
    """正常邮件 fixture"""
    return EmailMessage(
        uid="1001",
        message_id="<abc123@example.com>",
        subject="Meeting tomorrow at 10am",
        sender="boss@company.com",
        sender_name="John Boss",
        recipients=["me@company.com"],
        date="Mon, 01 Jun 2026 10:00:00 +0000",
        body_text="Hi team, let's meet tomorrow at 10am to discuss the Q3 roadmap. Please bring your reports.",
        body_html="<p>Hi team, let's meet tomorrow at 10am to discuss the Q3 roadmap.</p>",
    )


@pytest.fixture
def spam_email():
    """垃圾邮件 fixture"""
    return EmailMessage(
        uid="2001",
        subject="YOU WON $1,000,000!!! Click here NOW",
        sender="lottery@win-prizes.xyz",
        sender_name="Lottery Winner",
        recipients=["me@company.com"],
        body_text="CONGRATULATIONS! You have won $1,000,000 in our lottery. Click the link to claim your prize now! Free money guaranteed!",
    )


@pytest.fixture
def phishing_email():
    """钓鱼邮件 fixture"""
    return EmailMessage(
        uid="3001",
        subject="URGENT: Verify your bank account",
        sender="security@bank-verify-login.tk",
        sender_name="Bank Security",
        recipients=["me@company.com"],
        body_text="Your account has been compromised. Click here immediately to verify your password and credentials before your account is suspended.",
    )


@pytest.fixture
def finance_email():
    """金融账单邮件"""
    return EmailMessage(
        uid="4001",
        message_id="<inv456@shop.com>",
        subject="Your invoice #2026-0042 from Amazon",
        sender="billing@amazon.com",
        sender_name="Amazon Billing",
        recipients=["me@personal.com"],
        body_text="Thank you for your purchase. Your invoice #2026-0042 is attached. Payment processed: $49.99.",
    )


@pytest.fixture
def empty_email():
    """空正文邮件"""
    return EmailMessage(
        uid="5001",
        subject="(no subject)",
        sender="unknown@example.com",
        recipients=["me@company.com"],
        body_text="",
        body_html="<html><body></body></html>",
    )


@pytest.fixture
def engine():
    """不带连接的 EmailEngine"""
    return EmailEngine(
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        username="user@example.com",
        password="secret123",
    )


# ═══════════════════════════════════════════════════════════════════
# Test: Spam Filter (4 test cases)
# ═══════════════════════════════════════════════════════════════════

class TestSpamFilter:
    """垃圾邮件过滤测试"""

    def test_clean_email_passes(self, clean_email):
        """TC1: 正常邮件应判定为 CLEAN"""
        verdict = _score_spam_rules(clean_email)
        assert verdict.level == SpamLevel.CLEAN
        assert verdict.score < 0.30
        assert verdict.recommended_action == "keep"

    def test_spam_keywords_detected(self, spam_email):
        """TC2: 含垃圾关键词的邮件应判定为非CLEAN"""
        verdict = _score_spam_rules(spam_email)
        assert verdict.level in (SpamLevel.LIKELY_SPAM, SpamLevel.SPAM)
        assert verdict.score >= 0.60
        assert verdict.recommended_action in ("reject", "quarantine")

    def test_phishing_detected(self, phishing_email):
        """TC3: 钓鱼邮件应被检测"""
        verdict = _score_spam_rules(phishing_email)
        assert verdict.level in (SpamLevel.LIKELY_SPAM, SpamLevel.SPAM)
        assert any("phishing" in r for r in verdict.rules_triggered)

    def test_html_only_no_text_suspicious(self, empty_email):
        """TC4: 纯HTML无文本正文应触发html_only_no_text规则"""
        verdict = _score_spam_rules(empty_email)
        assert "html_only_no_text" in verdict.rules_triggered
        assert verdict.score > 0


# ═══════════════════════════════════════════════════════════════════
# Test: AI Classification (2 test cases)
# ═══════════════════════════════════════════════════════════════════

class TestClassification:
    """AI 分类测试"""

    def test_finance_email_classified(self, finance_email):
        """TC5: 金融邮件应分类为 FINANCE"""
        label = _classify_by_keywords(finance_email)
        assert label.label_type == EmailLabelType.FINANCE
        assert label.confidence > 0.3

    def test_default_to_primary_when_unknown(self, clean_email):
        """TC6: 含工作关键词的邮件应分类为WORK (正确检测到report)"""
        label = _classify_by_keywords(clean_email)
        # "meeting" and "report" are WORK keywords
        assert label.label_type == EmailLabelType.WORK
        assert label.confidence >= 0.2


# ═══════════════════════════════════════════════════════════════════
# Test: Summary & Reply (2 test cases)
# ═══════════════════════════════════════════════════════════════════

class TestSummarization:
    """自动摘要测试"""

    def test_summary_generates_text(self, clean_email):
        """TC7: 摘要应生成非空文本"""
        summary = _generate_summary_heuristic(clean_email)
        assert len(summary.summary_text) > 0
        assert summary.urgency == "low"

    def test_draft_reply_generates_body(self, clean_email):
        """TC8: 回复草稿应包含主题和正文"""
        draft = _draft_reply_heuristic(clean_email)
        assert draft.subject.startswith("Re:")
        assert len(draft.body_text) > 0
        assert draft.tone == "professional"


# ═══════════════════════════════════════════════════════════════════
# Test: EmailEngine core methods (3 test cases)
# ═══════════════════════════════════════════════════════════════════

class TestEmailEngine:
    """EmailEngine 核心测试"""

    def test_engine_initialization(self, engine):
        """TC9: 引擎初始化状态正确"""
        assert engine.imap_host == "imap.example.com"
        assert engine.smtp_host == "smtp.example.com"
        assert engine.username == "user@example.com"
        assert not engine.imap_connected
        assert not engine.smtp_connected

    def test_check_spam_delegates(self, engine, spam_email):
        """TC10: engine.check_spam 正确处理垃圾邮件"""
        verdict = engine.check_spam(spam_email)
        assert verdict.level in (SpamLevel.LIKELY_SPAM, SpamLevel.SPAM)
        assert engine.is_spam(spam_email)

    def test_classify_delegates_to_heuristic(self, engine, finance_email):
        """TC11: engine.classify_email 使用启发式分类"""
        label = engine.classify_email(finance_email)
        assert label.label_type == EmailLabelType.FINANCE

    def test_summarize_delegates_to_heuristic(self, engine, clean_email):
        """TC12: engine.summarize_email 使用启发式摘要"""
        summary = engine.summarize_email(clean_email)
        assert len(summary.summary_text) > 0

    def test_draft_reply_delegates_to_heuristic(self, engine, clean_email):
        """TC13: engine.draft_reply 使用模板草稿"""
        draft = engine.draft_reply(clean_email)
        assert draft.subject.startswith("Re:")
        assert len(draft.body_text) > 0

    def test_engine_stats(self, engine, finance_email, spam_email):
        """TC14: 统计信息正确累积"""
        engine.reset_stats()
        engine.classify_email(finance_email)
        engine.check_spam(spam_email)
        engine.summarize_email(finance_email)
        engine.draft_reply(finance_email)

        stats = engine.stats()
        assert stats["classifications_done"] == 1
        assert stats["spam_detected"] == 1
        assert stats["summaries_done"] == 1
        assert stats["replies_drafted"] == 1


# ═══════════════════════════════════════════════════════════════════
# Test: Custom AI injection
# ═══════════════════════════════════════════════════════════════════

class TestCustomAI:
    """自定义 AI 函数注入测试"""

    def test_custom_classifier_used(self):
        """TC15: 注入的自定义分类器应被调用"""
        called = []

        def custom_cls(msg: EmailMessage) -> EmailLabel:
            called.append(True)
            return EmailLabel(
                label_type=EmailLabelType.WORK,
                confidence=0.99,
                reasoning="custom classifier",
            )

        engine = EmailEngine(classifier_fn=custom_cls)
        msg = EmailMessage(uid="1", subject="test", sender="x@y.com", recipients=["a@b.com"])
        label = engine.classify_email(msg)
        assert len(called) == 1
        assert label.label_type == EmailLabelType.WORK
        assert label.confidence == 0.99

    def test_custom_summarizer_used(self):
        """TC16: 注入的自定义摘要器应被调用"""
        called = []

        def custom_summ(msg: EmailMessage) -> EmailSummary:
            called.append(True)
            return EmailSummary(summary_text="Custom summary", model_used="gpt-4")

        engine = EmailEngine(summarizer_fn=custom_summ)
        msg = EmailMessage(uid="1", subject="test", sender="x@y.com", recipients=["a@b.com"])
        summary = engine.summarize_email(msg)
        assert len(called) == 1
        assert summary.summary_text == "Custom summary"
        assert summary.model_used == "gpt-4"

    def test_custom_reply_fn_used(self):
        """TC17: 注入的自定义回复函数应被调用"""
        called = []

        def custom_reply(msg: EmailMessage) -> DraftReply:
            called.append(True)
            return DraftReply(subject="Re: custom", body_text="Custom reply", confidence=0.95)

        engine = EmailEngine(reply_fn=custom_reply)
        msg = EmailMessage(uid="1", subject="test", sender="x@y.com", recipients=["a@b.com"])
        draft = engine.draft_reply(msg)
        assert len(called) == 1
        assert draft.body_text == "Custom reply"
        assert draft.confidence == 0.95


# ═══════════════════════════════════════════════════════════════════
# Test: Singleton
# ═══════════════════════════════════════════════════════════════════

class TestSingleton:
    """单例模式测试"""

    def test_get_email_engine_returns_singleton(self):
        """TC18: get_email_engine 返回单例"""
        reset_email_engine()
        e1 = get_email_engine(imap_host="h1", smtp_host="s1")
        e2 = get_email_engine()
        assert e1 is e2
        assert e2.imap_host == "h1"

    def test_reset_email_engine_creates_new(self):
        """TC19: reset 后创建新实例"""
        reset_email_engine()
        e1 = get_email_engine(imap_host="h1", smtp_host="s1")
        reset_email_engine()
        e2 = get_email_engine(imap_host="h2", smtp_host="s2")
        assert e1 is not e2
        assert e2.imap_host == "h2"


# ═══════════════════════════════════════════════════════════════════
# Test: Dataclass properties
# ═══════════════════════════════════════════════════════════════════

class TestDataclassProperties:
    """Dataclass 属性测试"""

    def test_email_message_snippet(self):
        """TC20: snippet 属性返回前200字符"""
        msg = EmailMessage(
            uid="1", subject="Test", sender="x@y.com",
            recipients=["a@b.com"],
            body_text="Hello " * 100,
        )
        assert len(msg.snippet) == 200
        assert msg.snippet.startswith("Hello ")

    def test_spam_verdict_levels(self):
        """TC21: SpamVerdict 不同分数对应不同level"""
        v1 = SpamVerdict(level=SpamLevel.CLEAN, score=0.1)
        assert v1.level == SpamLevel.CLEAN
        v2 = SpamVerdict(level=SpamLevel.PHISHING, score=0.95)
        assert v2.recommended_action == ""
        assert v2.level == SpamLevel.PHISHING

    def test_email_attachment_fields(self):
        """TC22: EmailAttachment 字段正确"""
        att = EmailAttachment(
            filename="report.pdf",
            content_type="application/pdf",
            size_bytes=12345,
            payload=b"fake pdf content",
        )
        assert att.filename == "report.pdf"
        assert att.content_type == "application/pdf"
        assert att.size_bytes == 12345

    def test_inbox_stats_defaults(self):
        """TC23: InboxStats 默认值为零"""
        stats = InboxStats()
        assert stats.total == 0
        assert stats.unread == 0
        assert stats.by_label == {}


# ═══════════════════════════════════════════════════════════════════
# Test: Connection state
# ═══════════════════════════════════════════════════════════════════

class TestConnectionState:
    """连接状态测试"""

    def test_not_connected_by_default(self, engine):
        """TC24: 默认未连接"""
        assert not engine.imap_connected
        assert not engine.smtp_connected

    def test_fetch_returns_empty_when_not_connected(self, engine):
        """TC25: 未连接时 fetch_emails 返回空列表"""
        emails = engine.fetch_emails()
        assert emails == []

    def test_send_returns_false_when_not_connected(self, engine):
        """TC26: 未连接时 send_email 返回 False"""
        result = engine.send_email(to="a@b.com", subject="test", body="hello")
        assert result is False

    def test_inbox_stats_no_connection(self, engine):
        """TC27: 未连接时 inbox_stats 返回默认值"""
        stats = engine.inbox_stats()
        assert stats.total == 0
