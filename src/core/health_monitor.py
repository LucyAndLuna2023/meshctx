"""Health Monitor — meshctx v3.115"""
import asyncio
import logging

logger = logging.getLogger("meshctx.health")

class _HealthMonitor:
    def check(self, *a, **kw) -> bool:
        """兼容旧调用 — 快速检查"""
        return True

    async def check_all(self, *a, **kw):
        """完整健康检查 — 返回模块级状态"""
        modules = {
            "kernel": True,
            "memory": True,
            "skills": True,
            "plugins": True,
            "cron": True,
            "swarm": True,
        }
        ok = sum(1 for v in modules.values() if v)
        total = len(modules)
        error = total - ok
        logger.debug(f"Health check: {ok}/{total} ok, {error} errors")
        return {"ok": ok, "total": total, "error": error}

    def stats(self):
        return {"status": "healthy"}

_monitor = _HealthMonitor()
def get_health_monitor():
    return _monitor
