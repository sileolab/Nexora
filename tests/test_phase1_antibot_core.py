"""Phase 1 Unit and Integration Tests:
Retry Engine, Scheduling, Exponential Backoff, Jitter, Retry-After, and Concurrency.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.anti_bot import (
    AntiBotManager,
    DomainPolicy,
    DomainPolicyManager,
    RequestDiagnostics,
    RequestScheduler,
    ResponseClassification,
    RetryPolicy,
    SessionManager,
    get_antibot_manager,
)


# ==============================================================================
# 1. RetryPolicy Unit Tests
# ==============================================================================

def test_retry_policy_exponential_backoff_and_cap():
    """Verify exponential backoff calculation and max_delay cap."""
    policy = RetryPolicy(max_retries=5, base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter=False)

    assert policy.compute_delay(0) == 1.0   # 1 * 2^0 = 1
    assert policy.compute_delay(1) == 2.0   # 1 * 2^1 = 2
    assert policy.compute_delay(2) == 4.0   # 1 * 2^2 = 4
    assert policy.compute_delay(3) == 8.0   # 1 * 2^3 = 8
    assert policy.compute_delay(4) == 10.0  # 1 * 2^4 = 16 -> capped at 10.0


def test_retry_policy_jitter_bounds():
    """Verify jitter produces delays within [0.5 * delay, delay]."""
    policy = RetryPolicy(max_retries=3, base_delay=4.0, max_delay=20.0, jitter=True)

    delays = [policy.compute_delay(0) for _ in range(50)]
    for d in delays:
        # raw delay = 4.0, with equal jitter: [2.0, 4.0]
        assert 2.0 <= d <= 4.0


def test_retry_policy_parse_retry_after_seconds():
    """Verify parsing of integer/float seconds in Retry-After header."""
    policy = RetryPolicy(max_delay=60.0)

    assert policy.parse_retry_after("5") == 5.0
    assert policy.parse_retry_after("12.5") == 12.5
    assert policy.parse_retry_after("120") == 60.0  # capped at max_delay
    assert policy.parse_retry_after("-10") == 0.0
    assert policy.parse_retry_after("") is None
    assert policy.parse_retry_after(None) is None


def test_retry_policy_parse_retry_after_http_date():
    """Verify parsing of HTTP-date formatted Retry-After header."""
    policy = RetryPolicy(max_delay=120.0)

    # Future date in GMT (10 seconds from now)
    future_dt = datetime.now(timezone.utc) + timedelta(seconds=10)
    future_str = future_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = policy.parse_retry_after(future_str)
    assert parsed is not None
    assert 8.0 <= parsed <= 12.0

    # Past date
    past_dt = datetime.now(timezone.utc) - timedelta(seconds=60)
    past_str = past_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed_past = policy.parse_retry_after(past_str)
    assert parsed_past == 0.0


def test_retry_policy_should_retry_status_codes_and_attempts():
    """Verify retry decisions on retryable vs non-retryable HTTP status codes."""
    policy = RetryPolicy(max_retries=3)

    # Retryable status codes on attempt 0 and 1
    assert policy.should_retry(0, status_code=429) is True
    assert policy.should_retry(1, status_code=500) is True
    assert policy.should_retry(2, status_code=503) is True

    # Exceeding max retries
    assert policy.should_retry(3, status_code=429) is False

    # Permanent non-retryable 4xx
    assert policy.should_retry(0, status_code=400) is False
    assert policy.should_retry(0, status_code=401) is False
    assert policy.should_retry(0, status_code=403) is False
    assert policy.should_retry(0, status_code=404) is False
    assert policy.should_retry(0, status_code=200) is False


def test_retry_policy_should_retry_exceptions():
    """Verify retry decisions on network exceptions vs fatal errors."""
    policy = RetryPolicy(max_retries=2)

    assert policy.should_retry(0, exception=httpx.ConnectTimeout("timeout")) is True
    assert policy.should_retry(0, exception=httpx.ConnectError("refused")) is True
    assert policy.should_retry(0, exception=ConnectionResetError("reset")) is True

    # CancelledError must NEVER be retried
    assert policy.should_retry(0, exception=asyncio.CancelledError()) is False


# ==============================================================================
# 2. RequestScheduler Unit Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_scheduler_global_concurrency():
    """Global semaphore must restrict total in-flight requests across all domains."""
    scheduler = RequestScheduler(max_global_concurrency=2, default_min_delay=0.0)

    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def worker(domain: str):
        nonlocal active_count, max_active
        async with scheduler.schedule(domain, min_delay=0.0):
            async with lock:
                active_count += 1
                if active_count > max_active:
                    max_active = active_count
            await asyncio.sleep(0.05)
            async with lock:
                active_count -= 1

    tasks = [
        asyncio.create_task(worker(f"https://domain{i}.com/page"))
        for i in range(5)
    ]
    await asyncio.gather(*tasks)

    assert max_active == 2


@pytest.mark.asyncio
async def test_scheduler_per_domain_concurrency():
    """Domain semaphore must restrict concurrent requests to the same domain."""
    scheduler = RequestScheduler(
        max_global_concurrency=10,
        default_domain_concurrency=1,
        default_min_delay=0.0,
    )

    active_same_domain = 0
    max_active_domain = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal active_same_domain, max_active_domain
        async with scheduler.schedule("https://example.com/test", min_delay=0.0):
            async with lock:
                active_same_domain += 1
                if active_same_domain > max_active_domain:
                    max_active_domain = active_same_domain
            await asyncio.sleep(0.05)
            async with lock:
                active_same_domain -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(4)]
    await asyncio.gather(*tasks)

    assert max_active_domain == 1


@pytest.mark.asyncio
async def test_scheduler_independent_domains_concurrency():
    """Requests to different domains must proceed in parallel up to global concurrency."""
    scheduler = RequestScheduler(
        max_global_concurrency=4,
        default_domain_concurrency=1,
        default_min_delay=0.0,
    )

    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def worker(domain: str):
        nonlocal active_count, max_active
        async with scheduler.schedule(f"https://{domain}/page", min_delay=0.0):
            async with lock:
                active_count += 1
                if active_count > max_active:
                    max_active = active_count
            await asyncio.sleep(0.05)
            async with lock:
                active_count -= 1

    tasks = [
        asyncio.create_task(worker("site-a.com")),
        asyncio.create_task(worker("site-b.com")),
        asyncio.create_task(worker("site-c.com")),
    ]
    await asyncio.gather(*tasks)

    # 3 distinct domains should execute concurrently
    assert max_active == 3


@pytest.mark.asyncio
async def test_scheduler_min_delay_rate_limiting():
    """Requests to the same domain must respect the minimum spacing interval."""
    scheduler = RequestScheduler(default_domain_concurrency=1, default_min_delay=0.1)

    timestamps = []

    async def fetch_item():
        async with scheduler.schedule("https://slowsite.org/api", min_delay=0.1):
            timestamps.append(time.monotonic())

    await fetch_item()
    await fetch_item()

    assert len(timestamps) == 2
    diff = timestamps[1] - timestamps[0]
    assert diff >= 0.09, f"Expected at least 0.09s spacing, got {diff:.3f}s"


@pytest.mark.asyncio
async def test_scheduler_releases_semaphore_for_cancellation():
    """Cancelled task must release global and domain semaphores immediately."""
    scheduler = RequestScheduler(max_global_concurrency=1, default_domain_concurrency=1)

    cancel_evt = asyncio.Event()
    cancel_evt.set()

    with pytest.raises(asyncio.CancelledError):
        async with scheduler.schedule("https://cancel-test.com", cancel_event=cancel_evt):
            pass

    # Ensure semaphores are not leaked (slots remain 1)
    state = await scheduler.get_or_create_domain_state("cancel-test.com")
    assert state.semaphore._value == 1
    assert scheduler._global_semaphore._value == 1


# ==============================================================================
# 3. AntiBotManager End-to-End Resilience Tests
# ==============================================================================

class MockTransport(httpx.AsyncBaseTransport):
    """Custom async transport to simulate rate limits, retries, and errors."""

    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if self.responses:
            resp = self.responses.pop(0)
            resp.request = request
            return resp
        return httpx.Response(200, request=request, text="OK")


@pytest.mark.asyncio
async def test_antibot_manager_retries_429_with_retry_after():
    """AntiBotManager must retry 429 response using Retry-After header and succeed."""
    retry_policy = RetryPolicy(max_retries=2, base_delay=0.05, jitter=False)
    scheduler = RequestScheduler(default_min_delay=0.0)
    manager = AntiBotManager(scheduler=scheduler, retry_policy=retry_policy)

    mock_429 = httpx.Response(429, headers={"Retry-After": "0.05"}, text="Rate Limited")
    mock_200 = httpx.Response(200, text="Success")
    transport = MockTransport([mock_429, mock_200])

    resp, diag = await manager.fetch("https://example.com/data", custom_transport=transport)

    assert resp is not None
    assert resp.status_code == 200
    assert diag.classification == ResponseClassification.SUCCESS
    assert diag.attempt_count == 2
    assert transport.call_count == 2


@pytest.mark.asyncio
async def test_antibot_manager_does_not_retry_403():
    """AntiBotManager must not retry HTTP 403 Forbidden."""
    retry_policy = RetryPolicy(max_retries=3, base_delay=0.01)
    scheduler = RequestScheduler(default_min_delay=0.0)
    manager = AntiBotManager(scheduler=scheduler, retry_policy=retry_policy)

    mock_403 = httpx.Response(403, text="Forbidden")
    transport = MockTransport([mock_403])

    resp, diag = await manager.fetch("https://example.com/secret", custom_transport=transport)

    assert resp is not None
    assert resp.status_code == 403
    assert diag.classification == ResponseClassification.HTTP_FORBIDDEN
    assert diag.attempt_count == 1
    assert transport.call_count == 1


@pytest.mark.asyncio
async def test_antibot_manager_blocks_ssrf_without_network_call():
    """AntiBotManager must block loopback/private IPs before attempting network fetch."""
    manager = get_antibot_manager()

    resp, diag = await manager.fetch("http://127.0.0.1:8080/admin")

    assert resp is None
    assert diag.http_status == 403
    assert diag.classification == ResponseClassification.HTTP_FORBIDDEN
    assert "SSRF" in diag.reason
