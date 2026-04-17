"""
Universal retry decorator with exponential back-off.

Usage
-----
from src.podcast_automation.utils.retry import with_retry

@with_retry(max_attempts=3, base_delay=2.0)
def call_some_api(...):
    ...

Or call ad-hoc:
    result = with_retry(max_attempts=3)(my_fn)(arg1, arg2)
"""
import time
import functools
from typing import Callable, Tuple, Type
from loguru import logger


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
):
    """
    Decorator factory.  Wraps *func* so that it retries up to *max_attempts*
    times on any exception in *exceptions*, waiting ``base_delay * 2**attempt``
    seconds between tries (capped at *max_delay*).

    The original exception is re-raised after all attempts are exhausted.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception = RuntimeError("No attempts made")
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"[retry] {func.__qualname__} attempt {attempt + 1}/{max_attempts} "
                            f"failed: {exc}. Retrying in {delay:.1f}s…"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"[retry] {func.__qualname__} failed after "
                            f"{max_attempts} attempts: {exc}"
                        )
            raise last_exc
        return wrapper
    return decorator
