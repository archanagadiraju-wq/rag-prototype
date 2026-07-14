"""Retry-with-backoff helper — unit tests.

The helper wraps Anthropic + OpenAI calls so transient 429s, 5xx, network
errors, and timeouts retry with exponential backoff. Permanent errors (4xx
that aren't 429) propagate immediately so we don't waste time retrying a
malformed request.
"""
from __future__ import annotations

import time

import pytest
from services.api_retry import with_retry_sync, with_retry_async, _is_transient

pytestmark = pytest.mark.unit


# ── Custom error classes matching SDK shape ──────────────────────────────────


class FakeRateLimitError(Exception):
    pass

FakeRateLimitError.__name__ = "RateLimitError"  # matches Anthropic/OpenAI


class FakeBadRequestError(Exception):
    status_code = 400


class FakeServerError(Exception):
    status_code = 503


# ── _is_transient classifier ─────────────────────────────────────────────────


def test_transient_detected_by_class_name():
    """Errors named like the SDK rate-limit classes should be transient."""
    assert _is_transient(FakeRateLimitError("hit rate limit"))


def test_transient_detected_by_status_code():
    """5xx and 429 status codes should be transient."""
    assert _is_transient(FakeServerError("upstream failed"))


def test_permanent_4xx_not_retried():
    """400 should NOT be classified as transient."""
    assert not _is_transient(FakeBadRequestError("bad json"))


def test_generic_value_error_not_transient():
    """ValueError should not be retried — it's a programming error."""
    assert not _is_transient(ValueError("bug"))


# ── Sync wrapper ─────────────────────────────────────────────────────────────


def test_sync_returns_immediately_on_success():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return "ok"
    assert with_retry_sync(fn, max_attempts=3) == "ok"
    assert calls["n"] == 1


def test_sync_retries_transient_then_succeeds():
    """Transient error twice, then success → should return successfully on third attempt."""
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeRateLimitError("transient")
        return "finally"
    out = with_retry_sync(fn, max_attempts=3, base_delay=0.01)
    assert out == "finally"
    assert calls["n"] == 3


def test_sync_does_not_retry_permanent_errors():
    """Permanent errors must propagate on first attempt."""
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        raise FakeBadRequestError("malformed input")
    with pytest.raises(FakeBadRequestError):
        with_retry_sync(fn, max_attempts=3)
    assert calls["n"] == 1, "Permanent errors must not be retried"


def test_sync_gives_up_after_max_attempts():
    """After max_attempts transient errors, the last one propagates."""
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        raise FakeRateLimitError("persistent")
    with pytest.raises(FakeRateLimitError):
        with_retry_sync(fn, max_attempts=3, base_delay=0.01)
    assert calls["n"] == 3


def test_sync_backoff_grows():
    """Backoff between attempts should grow exponentially (loosely measured)."""
    calls = {"n": 0, "timestamps": []}
    def fn():
        calls["n"] += 1
        calls["timestamps"].append(time.perf_counter())
        if calls["n"] < 3:
            raise FakeRateLimitError("retry")
        return "done"
    t0 = time.perf_counter()
    with_retry_sync(fn, max_attempts=4, base_delay=0.05, max_delay=2.0)
    dt = time.perf_counter() - t0
    # 2 retries with base 0.05 → expect at least 0.05 + 0.10 = 0.15s
    assert dt >= 0.13, f"Backoff too fast: {dt:.3f}s"


# ── Async wrapper ────────────────────────────────────────────────────────────


async def test_async_returns_immediately_on_success():
    calls = {"n": 0}
    async def fn():
        calls["n"] += 1
        return "ok"
    out = await with_retry_async(fn, max_attempts=3)
    assert out == "ok"
    assert calls["n"] == 1


async def test_async_retries_transient_then_succeeds():
    calls = {"n": 0}
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeServerError("503")
        return "finally"
    out = await with_retry_async(fn, max_attempts=3, base_delay=0.01)
    assert out == "finally"
    assert calls["n"] == 3


async def test_async_does_not_retry_permanent_errors():
    calls = {"n": 0}
    async def fn():
        calls["n"] += 1
        raise FakeBadRequestError("bad")
    with pytest.raises(FakeBadRequestError):
        await with_retry_async(fn, max_attempts=3)
    assert calls["n"] == 1
