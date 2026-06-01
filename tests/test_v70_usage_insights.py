"""v3.70 Usage Insights — tests"""
import pytest
from src.core.usage_insights import UsageInsights, get_usage_insights

class TestInsights:
    def test_record(self):
        u = UsageInsights()
        u.record("test", tokens=100, cost=0.01)
        assert len(u._records) == 1

    def test_insights(self):
        u = UsageInsights()
        u.record("code", tokens=500, cost=0.05, success=True)
        u.record("debug", tokens=200, cost=0.02, success=False)
        insights = u.insights()
        assert "total_tokens" in insights

    def test_empty(self):
        u = UsageInsights()
        assert u.insights()["status"] == "no_data"

    def test_singleton(self):
        assert get_usage_insights() is get_usage_insights()
