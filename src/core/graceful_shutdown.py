"""
meshctx Graceful Shutdown (v3.115.16)
Handles SIGTERM/SIGINT cleanly — prevents RecursionError during shutdown.
"""
import signal
import asyncio
import logging
from typing import Callable, List

logger = logging.getLogger("meshctx.shutdown")

_shutdown_hooks: List[Callable] = []
_shutting_down = False


def register_shutdown_hook(hook: Callable):
    """Register a cleanup function to run during shutdown."""
    _shutdown_hooks.append(hook)


async def shutdown():
    """Execute all shutdown hooks and stop the event loop."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    logger.info("Graceful shutdown initiated...")
    
    for hook in _shutdown_hooks:
        try:
            if asyncio.iscoroutinefunction(hook):
                await hook()
            else:
                hook()
        except Exception as e:
            logger.warning(f"Shutdown hook failed: {e}")
    
    logger.info("Shutdown complete.")


def setup_signal_handlers(loop=None):
    """Install SIGTERM/SIGINT handlers on the event loop."""
    if loop is None:
        loop = asyncio.get_event_loop()
    
    def _handle_signal():
        logger.info("Received shutdown signal")
        asyncio.ensure_future(shutdown())
        # Stop accepting new connections
        loop.call_later(5, lambda: loop.stop() if loop.is_running() else None)
    
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_signal)
        loop.add_signal_handler(signal.SIGINT, _handle_signal)
        logger.debug("Signal handlers installed")
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        signal.signal(signal.SIGTERM, lambda s, f: _handle_signal())
        signal.signal(signal.SIGINT, lambda s, f: _handle_signal())
