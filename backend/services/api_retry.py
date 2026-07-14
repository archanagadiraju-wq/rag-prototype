"""Retry helpers for transient LLM-API failures.

Wraps Anthropic and OpenAI calls so 429s, 5xx, connection drops, and timeouts
are retried with exponential backoff instead of killing the stage. Permanent
errors (4xx that aren't 429) re-raise immediately so we don't waste time
retrying a malformed request.

Usage:
    from services.api_retry import with_retry_sync, with_retry_async

    msg = with_retry_sync(client.messages.create, model=..., system=..., messages=...)
    resp = await with_retry_async(async_client.embeddings.create, model=..., input=...)
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

# Default policy — overridable per-call via kwargs
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY   = 1.0   # seconds
DEFAULT_MAX_DELAY    = 30.0  # cap each backoff at 30s


def _is_transient(exc: BaseException) -> bool:
    """Return True for errors worth retrying (429, 5xx, network, timeout)."""
    # Match by class name so we don't need hard imports on every error class
    name = type(exc).__name__
    transient_names = {
        "RateLimitError",         # anthropic + openai
        "APIStatusError",         # anthropic 5xx wrapper
        "APIConnectionError",     # both
        "APITimeoutError",        # both
        "InternalServerError",    # openai
        "ServiceUnavailableError",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
    }
    if name in transient_names:
        return True
    # Some SDKs set a `.status_code` we can check
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    return False


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random(0, base)."""
    raw = base * (2 ** attempt) + random.uniform(0, base)
    return min(cap, raw)


def with_retry_sync(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    label: str | None = None,
    **kwargs: Any,
) -> Any:
    """Synchronous retry wrapper. Use inside `asyncio.to_thread` from async code."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == max_attempts - 1:
                raise
            delay = _backoff_delay(attempt, base_delay, max_delay)
            log.warning(
                "api_retry[%s] attempt %d/%d failed with %s: %s — sleeping %.2fs",
                label or fn.__name__, attempt + 1, max_attempts,
                type(exc).__name__, exc, delay,
            )
            time.sleep(delay)
    # Should be unreachable, but keeps type-checkers happy
    assert last_exc is not None
    raise last_exc


async def with_retry_async(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    label: str | None = None,
    **kwargs: Any,
) -> Any:
    """Async retry wrapper for awaitable API methods (AsyncOpenAI, AsyncAnthropic)."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await fn(*args, **kwargs)
        except BaseException as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == max_attempts - 1:
                raise
            delay = _backoff_delay(attempt, base_delay, max_delay)
            log.warning(
                "api_retry[%s] attempt %d/%d failed with %s: %s — sleeping %.2fs",
                label or fn.__name__, attempt + 1, max_attempts,
                type(exc).__name__, exc, delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


__all__: Iterable[str] = ("with_retry_sync", "with_retry_async")
