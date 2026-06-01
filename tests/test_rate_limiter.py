"""v3.90 Rate Limiter tests"""
import time
import pytest
from src.core.rate_limiter import (
    RateLimiter,
    RateLimitTier,
    TokenBucket,
    RateLimitResult,
    get_rate_limiter,
    reset_rate_limiter,
)


class TestTokenBucket:
    def test_initial_tokens_at_capacity(self):
        bucket = TokenBucket(capacity=100, refill_rate=10)
        assert bucket.tokens == 100

    def test_consume_reduces_tokens(self):
        bucket = TokenBucket(capacity=100, refill_rate=10)
        allowed, retry = bucket.consume(5)
        assert allowed is True
        assert retry == 0.0
        assert bucket.tokens == 95

    def test_consume_denied_when_empty(self):
        bucket = TokenBucket(capacity=1, refill_rate=0.1)
        bucket.tokens = 0
        allowed, retry = bucket.consume(1)
        assert allowed is False
        assert retry > 0

    def test_refill_over_time(self):
        bucket = TokenBucket(capacity=10, refill_rate=10)
        bucket.tokens = 0
        bucket.last_refill = time.monotonic() - 0.5
        bucket.refill()
        assert 4.5 <= bucket.tokens <= 5.5

    def test_tokens_never_exceed_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=100)
        bucket.tokens = 9.5
        bucket.last_refill = time.monotonic() - 10
        bucket.refill()
        assert bucket.tokens == 10


class TestRateLimiter:
    def test_basic_rate_limit_allows(self):
        rl = RateLimiter()
        result = rl.check("192.168.1.1")
        assert result.allowed is True
        assert result.status_code == 200

    def test_rate_limit_blocks_after_exhaustion(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=3, refill_rate=0.01)
        for _ in range(3):
            assert rl.check("10.0.0.1").allowed
        result = rl.check("10.0.0.1")
        assert result.allowed is False
        assert result.status_code == 429
        assert "Retry-After" in result.headers
        assert int(result.headers["Retry-After"]) > 0

    def test_tiered_rate_limits(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=1, refill_rate=0.01)
        rl.set_tier_config(RateLimitTier.PREMIUM, capacity=100, refill_rate=100)
        rl.check("1.1.1.1")
        result_free = rl.check("1.1.1.1")
        assert result_free.allowed is False
        rl.register_api_key("premium-key-123", RateLimitTier.PREMIUM)
        result_prem = rl.check("2.2.2.2", api_key="premium-key-123")
        assert result_prem.allowed is True

    def test_api_key_gets_correct_tier(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.ADMIN, capacity=5, refill_rate=100)
        rl.set_tier_config(RateLimitTier.FREE, capacity=1, refill_rate=0.01)
        rl.register_api_key("admin-key", RateLimitTier.ADMIN)
        for _ in range(5):
            assert rl.check("10.0.0.1", api_key="admin-key").allowed
        assert not rl.check("10.0.0.1", api_key="admin-key").allowed

    def test_is_allowed_shortcut(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=1, refill_rate=0.01)
        assert rl.is_allowed("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")

    def test_different_ips_independent(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=1, refill_rate=0.01)
        rl.check("10.0.0.1")
        assert not rl.is_allowed("10.0.0.1")
        assert rl.is_allowed("10.0.0.2")

    def test_dashboard_contains_stats(self):
        rl = RateLimiter()
        rl.check("192.168.1.1")
        dash = rl.dashboard()
        assert "overview" in dash
        assert "clients" in dash
        assert "tiers" in dash
        assert dash["overview"]["total_requests"] > 0

    def test_stats_increments(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=2, refill_rate=0.01)
        rl.check("1.1.1.1")
        rl.check("1.1.1.1")
        rl.check("1.1.1.1")
        stats = rl.stats()
        assert stats["total_allowed"] == 2
        assert stats["total_denied"] == 1

    def test_reset_clears_all(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.FREE, capacity=5, refill_rate=1)
        rl.check("1.1.1.1")
        rl.reset()
        stats = rl.stats()
        assert stats["total_requests"] == 0
        assert stats["active_clients"] == 0

    def test_cleanup_stale_buckets(self):
        rl = RateLimiter()
        rl.check("10.0.0.1")
        rl._buckets["ip:10.0.0.1"].last_refill = time.monotonic() - 7200
        removed = rl.cleanup_stale(max_age_seconds=3600)
        assert removed == 1
        assert "ip:10.0.0.1" not in rl._buckets

    def test_singleton(self):
        reset_rate_limiter()
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        assert rl1 is rl2
        reset_rate_limiter()

    def test_rate_limit_result_properties(self):
        result = RateLimitResult(allowed=False, retry_after=5.0, status_code=429)
        assert result.is_limited is True
        result2 = RateLimitResult(allowed=True, retry_after=0.0)
        assert result2.is_limited is False

    def test_set_ip_tier(self):
        rl = RateLimiter()
        rl.set_tier_config(RateLimitTier.PREMIUM, capacity=10, refill_rate=10)
        rl.set_tier_config(RateLimitTier.FREE, capacity=1, refill_rate=0.01)
        rl.set_ip_tier("10.0.0.99", RateLimitTier.PREMIUM)
        for _ in range(10):
            assert rl.check("10.0.0.99").allowed
        assert not rl.check("10.0.0.99").allowed

    def test_client_stats_filtered(self):
        rl = RateLimiter()
        rl.check("1.1.1.1")
        rl.check("2.2.2.2")
        cs = rl.client_stats("ip:1.1.1.1")
        assert "ip:1.1.1.1" in cs
        assert "ip:2.2.2.2" not in cs
