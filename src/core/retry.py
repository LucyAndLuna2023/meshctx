"""
meshctx Retry Module (v3.115.16)
Exponential backoff retry decorator for async functions.
"""
import asyncio
import logging
from functools import wraps
from typing import Type, Tuple, Optional

logger = logging.getLogger("meshctx.retry")


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[callable] = None,
):
    """Async retry decorator with exponential backoff.
    
    Args:
        max_attempts: Max retry attempts (including initial call)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        backoff: Multiplier for each retry
        exceptions: Exception types to catch and retry
        on_retry: Callback(attempt, exception) called before each retry
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt >= max_attempts:
                        raise
                    
                    delay = min(base_delay * (backoff ** (attempt - 1)), max_delay)
                    logger.debug(f"Retry {attempt}/{max_attempts} for {func.__name__}: {e} — waiting {delay:.1f}s")
                    
                    if on_retry:
                        on_retry(attempt, e)
                    
                    await asyncio.sleep(delay)
            
            raise last_exc  # Should never reach here
        return wrapper
    return decorator


def sync_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Synchronous retry decorator. For use with non-async functions."""
    import time
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt >= max_attempts:
                        raise
                    delay = min(base_delay * (backoff ** (attempt - 1)), 30.0)
                    time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
