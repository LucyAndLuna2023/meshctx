"""Tests for Usage Insights — v2.38"""
import pytest
import tempfile
import time
from pathlib import Path
from src.core.usage_insights import (
    UsageInsights, DailyStats, ProviderStat, ModelStat,
    get_insights, reset_insights,
)
from dataclasses import asdict


class TestUsageInsightsBasics:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.insights = UsageInsights(data_dir=self.tmp)

    def test_init_empty(self):
        today = self.insights.get_today()
        assert today["sessions"] == 0
        assert today["messages"] == 0

    def test_record_session(self):
        self.insights.record_session_start()
        today = self.insights.get_today()
        assert today["sessions"] == 1

    def test_record_multiple_sessions(self):
        for _ in range(5):
            self.insights.record_session_start()
        today = self.insights.get_today()
        assert today["sessions"] == 5

    def test_record_message(self):
        self.insights.record_message()
        self.insights.record_message()
        today = self.insights.get_today()
        assert today["messages"] == 2

    def test_persistence_across_restart(self):
        self.insights.record_session_start()
        self.insights.record_message()

        # Create new instance with same data dir
        i2 = UsageInsights(data_dir=self.tmp)
        today = i2.get_today()
        assert today["sessions"] == 1
        assert today["messages"] == 1

    def test_peak_hour_tracking(self):
        # Record messages at specific hours
        now = time.time()
        hour = time.localtime(now).tm_hour
        for _ in range(10):
            self.insights.record_message()
        today = self.insights.get_today()
        assert today["peak_hour"] == hour
        assert today["hourly_activity"].get(hour, 0) >= 10


class TestLLMCallRecording:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.insights = UsageInsights(data_dir=self.tmp)

    def test_record_llm_call_basic(self):
        self.insights.record_llm_call("deepseek-chat", "deepseek", tokens=500, latency_ms=200)
        today = self.insights.get_today()
        assert today["total_tokens"] == 500
        assert today["models_used"].get("deepseek-chat") == 1

    def test_record_llm_call_error(self):
        self.insights.record_llm_call("gpt-4", "openai", error=True)
        today = self.insights.get_today()
        assert today["errors"] == 1
        assert today["error_rate_pct"] == 100.0

    def test_avg_latency(self):
        self.insights.record_message()
        self.insights.record_llm_call("m1", "p1", latency_ms=100)
        self.insights.record_message()
        self.insights.record_llm_call("m1", "p1", latency_ms=300)
        today = self.insights.get_today()
        assert today["avg_latency_ms"] == 200.0

    def test_multiple_models(self):
        self.insights.record_llm_call("deepseek-chat", "deepseek", tokens=100)
        self.insights.record_llm_call("deepseek-chat", "deepseek", tokens=200)
        self.insights.record_llm_call("gpt-4", "openai", tokens=50)
        today = self.insights.get_today()
        assert today["models_used"]["deepseek-chat"] == 2
        assert today["models_used"]["gpt-4"] == 1


class TestProviderStats:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.insights = UsageInsights(data_dir=self.tmp)

    def test_provider_stats_basic(self):
        self.insights.record_llm_call("m1", "openai", tokens=100, latency_ms=200)
        self.insights.record_llm_call("m2", "deepseek", tokens=200, latency_ms=100)
        stats = self.insights.get_provider_stats()
        providers = {p["provider"]: p for p in stats["providers"]}
        assert providers["openai"]["calls"] == 1
        assert providers["deepseek"]["calls"] == 1

    def test_provider_error_rate(self):
        self.insights.record_llm_call("m1", "test", error=True)
        self.insights.record_llm_call("m1", "test", error=False)
        stats = self.insights.get_provider_stats()
        p = stats["providers"][0]
        assert p["calls"] == 2
        assert p["errors"] == 1
        assert p["error_rate_pct"] == 50.0

    def test_model_stats(self):
        self.insights.record_llm_call("gpt-4", "openai", latency_ms=500)
        self.insights.record_llm_call("gpt-3.5", "openai", latency_ms=100)
        stats = self.insights.get_model_stats()
        assert len(stats["models"]) == 2


class TestAggregation:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.insights = UsageInsights(data_dir=self.tmp)

    def test_weekly_aggregation(self):
        self.insights.record_session_start()
        self.insights.record_message()
        self.insights.record_llm_call("m1", "p1", tokens=500)
        weekly = self.insights.get_weekly()
        assert weekly["total_sessions"] >= 1
        assert weekly["total_messages"] >= 1

    def test_monthly_aggregation(self):
        self.insights.record_session_start()
        monthly = self.insights.get_monthly()
        assert "total_sessions" in monthly
        assert "daily_breakdown" in monthly

    def test_full_summary(self):
        self.insights.record_session_start()
        self.insights.record_llm_call("m1", "p1", tokens=100)
        summary = self.insights.get_summary()
        assert "today" in summary
        assert "weekly" in summary
        assert "monthly" in summary
        assert "providers" in summary
        assert "models" in summary


class TestSingleton:
    def test_singleton_same_instance(self):
        reset_insights()
        i1 = get_insights()
        i2 = get_insights()
        assert i1 is i2

    def test_reset_creates_new(self):
        reset_insights()
        i1 = get_insights()
        reset_insights()
        i2 = get_insights()
        assert i1 is not i2


class TestDataClasses:
    def test_daily_stats(self):
        ds = DailyStats(date="2026-05-20", sessions=10, messages=100)
        assert ds.date == "2026-05-20"
        assert ds.sessions == 10

    def test_provider_stat(self):
        ps = ProviderStat(provider="deepseek", calls=50, errors=2)
        d = asdict(ps)
        assert d["provider"] == "deepseek"
        assert d["calls"] == 50

    def test_model_stat(self):
        ms = ModelStat(model="gpt-4", provider="openai", calls=100)
        assert ms.model == "gpt-4"
        assert ms.provider == "openai"
