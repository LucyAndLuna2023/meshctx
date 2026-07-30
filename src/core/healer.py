"""Healer — 开源版 (stub)"""
class HealthStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"

from .autonomous_health import CircuitBreaker  # was stub

class HealerPlugin:
    info = type('Info', (), {'name': 'healer', 'version': '0.1', 'dependencies': [], 'category': 'health', 'description': 'Healer stub'})()
    state = "active"
    async def on_load(self, kernel): return True
    def generate_report(self): return {"status": "stub"}

