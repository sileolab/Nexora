"""Phase 5 Comprehensive Verification Suite: Anti-Bot Observability, Metrics & Telemetry.

Verifies:
1. JobMetricsSummary model and all 11 required metrics.
2. Bounded cardinality enforcement (no dynamic URLs, queries, or auth tokens as metric labels).
3. Thread-safe metrics aggregation with MetricsCollector.
4. Per-job metric scoping, tenant isolation, and global rollups.
5. AntiBotManager.fetch() metrics instrumentation across success, retryable errors, exhausted retries, and SSRF blocks.
6. Browser fallback tracking and promotions.
7. JobInfo and JobStatus models integration.
8. Admin health endpoint (/api/admin/health) exposing antibot_metrics.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes_admin import router as admin_router
from app.core.config import get_settings
from app.jobs.manager import JobManager
from app.jobs.models import JobInfo, JobState, JobType
from app.main import app
from app.schemas.responses import JobStatus
from app.services.anti_bot import (
    AntiBotManager,
    JobMetricsSummary,
    MetricsCollector,
    RequestScheduler,
    ResponseAnalyzer,
    ResponseClassification,
    RetryPolicy,
    get_antibot_manager,
)
from app.services.extractor import ContentExtractor


@pytest.fixture(autouse=True)
def reset_antibot_metrics():
    """Reset global AntiBotManager metrics before and after each test."""
    manager = get_antibot_manager()
    manager.metrics.reset()
    yield
    manager.metrics.reset()


# ==============================================================================
# 1. JobMetricsSummary Model & Cardinality Tests
# ==============================================================================

def test_job_metrics_summary_defaults_and_all_11_metrics():
    """Verify JobMetricsSummary initializes with all 11 required metrics with sensible defaults."""
    summary = JobMetricsSummary()

    # 1. requests_total
    assert summary.requests_total == 0
    # 2. successful_requests
    assert summary.successful_requests == 0
    # 3. failed_requests
    assert summary.failed_requests == 0
    # 4. blocked_requests
    assert summary.blocked_requests == 0
    # 5. rate_limited_requests
    assert summary.rate_limited_requests == 0
    # 6. retry_attempts
    assert summary.retry_attempts == 0
    # 7. retry_exhausted
    assert summary.retry_exhausted == 0
    # 8. timeout_count
    assert summary.timeout_count == 0
    # 9. average_request_latency
    assert summary.average_request_latency == 0.0
    # 10. browser_fallback_count
    assert summary.browser_fallback_count == 0
    # 11. classification_count
    assert isinstance(summary.classification_count, dict)
    assert len(summary.classification_count) == 12

    # Verify all 12 ResponseClassification enum members are present
    for classification in ResponseClassification:
        assert classification.value in summary.classification_count
        assert summary.classification_count[classification.value] == 0

    # Serialization
    data = summary.to_dict()
    assert "requests_total" in data
    assert "successful_requests" in data
    assert "failed_requests" in data
    assert "blocked_requests" in data
    assert "rate_limited_requests" in data
    assert "retry_attempts" in data
    assert "retry_exhausted" in data
    assert "timeout_count" in data
    assert "average_request_latency" in data
    assert "browser_fallback_count" in data
    assert "classification_count" in data


def test_bounded_cardinality_guarantee():
    """Verify that metric labels remain strictly bounded to the 12 classification states."""
    summary = JobMetricsSummary()

    # Record valid classifications
    summary.record_request(ResponseClassification.SUCCESS, latency_seconds=0.1)
    summary.record_request(ResponseClassification.RATE_LIMITED, latency_seconds=0.2)
    summary.record_request(ResponseClassification.BOT_PROTECTION, latency_seconds=0.3)

    data = summary.to_dict()
    classes = data["classification_count"]

    # Verify no arbitrary keys exist
    expected_keys = {c.value for c in ResponseClassification}
    assert set(classes.keys()) == expected_keys
    assert classes["SUCCESS"] == 1
    assert classes["RATE_LIMITED"] == 1
    assert classes["BOT_PROTECTION"] == 1
    assert classes["TIMEOUT"] == 0


def test_job_metrics_summary_state_transitions():
    """Verify metric counters and invariants under different response classifications."""
    summary = JobMetricsSummary()

    # 1. Success request
    summary.record_request(ResponseClassification.SUCCESS, latency_seconds=0.1)
    assert summary.requests_total == 1
    assert summary.successful_requests == 1
    assert summary.failed_requests == 0
    assert summary.requests_total == summary.successful_requests + summary.failed_requests

    # 2. Blocked request (Bot protection)
    summary.record_request(ResponseClassification.BOT_PROTECTION, latency_seconds=0.2)
    assert summary.requests_total == 2
    assert summary.successful_requests == 1
    assert summary.failed_requests == 1
    assert summary.blocked_requests == 1
    assert summary.requests_total == summary.successful_requests + summary.failed_requests

    # 3. Rate limited request
    summary.record_request(ResponseClassification.RATE_LIMITED, latency_seconds=0.15)
    assert summary.requests_total == 3
    assert summary.rate_limited_requests == 1
    assert summary.failed_requests == 2

    # 4. Timeout request
    summary.record_request(ResponseClassification.TIMEOUT, latency_seconds=5.0)
    assert summary.requests_total == 4
    assert summary.timeout_count == 1
    assert summary.failed_requests == 3

    # 5. Latency calculation: (0.1 + 0.2 + 0.15 + 5.0) / 4 = 5.45 / 4 = 1.3625
    data = summary.to_dict()
    assert round(data["average_request_latency"], 4) == 1.3625


# ==============================================================================
# 2. MetricsCollector & Thread Safety Tests
# ==============================================================================

def test_metrics_collector_per_job_and_global_scoping():
    """Verify that per-job metrics are isolated from each other while globally aggregated."""
    collector = MetricsCollector()

    # Job A records
    collector.record_request("job-A", ResponseClassification.SUCCESS, latency_seconds=0.1)
    collector.record_request("job-A", ResponseClassification.RATE_LIMITED, latency_seconds=0.2, retries=1)
    collector.record_browser_fallback("job-A")

    # Job B records
    collector.record_request("job-B", ResponseClassification.HTTP_FORBIDDEN, latency_seconds=0.05)
    collector.record_request("job-B", ResponseClassification.SUCCESS, latency_seconds=0.15)

    # Job A verification
    metrics_a = collector.get_metrics("job-A")
    assert metrics_a["requests_total"] == 2
    assert metrics_a["successful_requests"] == 1
    assert metrics_a["failed_requests"] == 1
    assert metrics_a["rate_limited_requests"] == 1
    assert metrics_a["retry_attempts"] == 1
    assert metrics_a["browser_fallback_count"] == 1
    assert metrics_a["classification_count"]["SUCCESS"] == 1
    assert metrics_a["classification_count"]["HTTP_FORBIDDEN"] == 0

    # Job B verification
    metrics_b = collector.get_metrics("job-B")
    assert metrics_b["requests_total"] == 2
    assert metrics_b["successful_requests"] == 1
    assert metrics_b["failed_requests"] == 1
    assert metrics_b["blocked_requests"] == 1
    assert metrics_b["rate_limited_requests"] == 0
    assert metrics_b["browser_fallback_count"] == 0
    assert metrics_b["classification_count"]["HTTP_FORBIDDEN"] == 1

    # Global aggregation verification
    global_metrics = collector.get_metrics()
    assert global_metrics["requests_total"] == 4
    assert global_metrics["successful_requests"] == 2
    assert global_metrics["failed_requests"] == 2
    assert global_metrics["blocked_requests"] == 1
    assert global_metrics["rate_limited_requests"] == 1
    assert global_metrics["retry_attempts"] == 1
    assert global_metrics["browser_fallback_count"] == 1

    # Unknown job returns empty template
    empty_job = collector.get_metrics("job-unknown")
    assert empty_job["requests_total"] == 0
    assert empty_job["classification_count"]["SUCCESS"] == 0


def test_metrics_collector_reset():
    """Verify resetting a specific job clears only that job, while resetting all clears everything."""
    collector = MetricsCollector()
    collector.record_request("job-1", ResponseClassification.SUCCESS, latency_seconds=0.1)
    collector.record_request("job-2", ResponseClassification.SUCCESS, latency_seconds=0.1)

    # Reset job-1 only
    collector.reset("job-1")
    assert collector.get_metrics("job-1")["requests_total"] == 0
    assert collector.get_metrics("job-2")["requests_total"] == 1
    assert collector.get_metrics()["requests_total"] == 2  # global retained

    # Full reset
    collector.reset()
    assert collector.get_metrics()["requests_total"] == 0
    assert collector.get_metrics("job-2")["requests_total"] == 0


def test_metrics_collector_thread_safety():
    """Verify that MetricsCollector is safely updated across concurrent threads."""
    collector = MetricsCollector()
    iterations = 200

    def worker(job_id: str):
        for _ in range(iterations):
            collector.record_request(
                job_id=job_id,
                classification=ResponseClassification.SUCCESS,
                latency_seconds=0.01,
            )
            collector.record_browser_fallback(job_id=job_id)

    with ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(worker, "job-thread-1")
        f2 = executor.submit(worker, "job-thread-2")
        f3 = executor.submit(worker, "job-thread-1")
        f4 = executor.submit(worker, "job-thread-2")
        f1.result()
        f2.result()
        f3.result()
        f4.result()

    job1_metrics = collector.get_metrics("job-thread-1")
    job2_metrics = collector.get_metrics("job-thread-2")
    global_metrics = collector.get_metrics()

    assert job1_metrics["requests_total"] == iterations * 2
    assert job1_metrics["browser_fallback_count"] == iterations * 2
    assert job2_metrics["requests_total"] == iterations * 2
    assert global_metrics["requests_total"] == iterations * 4
    assert global_metrics["browser_fallback_count"] == iterations * 4


# ==============================================================================
# 3. AntiBotManager.fetch() Observability Instrumentation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_antibot_manager_fetch_success_telemetry():
    """Verify AntiBotManager.fetch() accurately records success telemetry and latency."""
    mock_transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text="<html><body>OK</body></html>")
    )
    async with httpx.AsyncClient(transport=mock_transport) as client:
        manager = AntiBotManager()
        resp, diag = await manager.fetch(
            "https://example.com/page",
            custom_client=client,
            job_id="job-fetch-1",
        )

        assert resp is not None
        assert diag.classification == ResponseClassification.SUCCESS

        job_metrics = manager.metrics.get_metrics("job-fetch-1")
        assert job_metrics["requests_total"] == 1
        assert job_metrics["successful_requests"] == 1
        assert job_metrics["failed_requests"] == 0
        assert job_metrics["classification_count"]["SUCCESS"] == 1
        assert job_metrics["average_request_latency"] >= 0.0


@pytest.mark.asyncio
async def test_antibot_manager_fetch_retry_and_rate_limit_telemetry():
    """Verify fetch() records rate-limited attempts and retry attempts before eventual success."""
    attempt_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="Too Many Requests")
        return httpx.Response(200, text="<html>Success</html>")

    mock_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        retry_policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05)
        manager = AntiBotManager(retry_policy=retry_policy)

        resp, diag = await manager.fetch(
            "https://example.com/retry-me",
            custom_client=client,
            job_id="job-retry-test",
        )

        assert resp is not None
        assert resp.status_code == 200
        assert diag.classification == ResponseClassification.SUCCESS

        job_metrics = manager.metrics.get_metrics("job-retry-test")
        assert job_metrics["requests_total"] == 1
        assert job_metrics["successful_requests"] == 1
        assert job_metrics["failed_requests"] == 0
        assert job_metrics["retry_attempts"] == 1
        assert job_metrics["retry_exhausted"] == 0
        assert job_metrics["rate_limited_requests"] == 1
        assert job_metrics["classification_count"]["RATE_LIMITED"] == 1
        assert job_metrics["classification_count"]["SUCCESS"] == 1


@pytest.mark.asyncio
async def test_antibot_manager_fetch_retries_exhausted_telemetry():
    """Verify fetch() correctly increments retry_exhausted when all retries fail."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    mock_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        retry_policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.02)
        manager = AntiBotManager(retry_policy=retry_policy)

        resp, diag = await manager.fetch(
            "https://example.com/fail-me",
            custom_client=client,
            job_id="job-exhaust-test",
        )

        assert diag.classification == ResponseClassification.SERVER_ERROR
        job_metrics = manager.metrics.get_metrics("job-exhaust-test")
        assert job_metrics["requests_total"] == 1
        assert job_metrics["successful_requests"] == 0
        assert job_metrics["failed_requests"] == 1
        assert job_metrics["retry_attempts"] == 2
        assert job_metrics["retry_exhausted"] == 1
        assert job_metrics["classification_count"]["SERVER_ERROR"] >= 2


@pytest.mark.asyncio
async def test_antibot_manager_fetch_ssrf_blocked_telemetry():
    """Verify fetch() records blocked_requests when SSRF policy intercepts a forbidden URL."""
    manager = AntiBotManager()
    resp, diag = await manager.fetch(
        "http://127.0.0.1:8000/internal",
        job_id="job-ssrf-test",
    )

    assert resp is None
    assert diag.classification == ResponseClassification.HTTP_FORBIDDEN
    job_metrics = manager.metrics.get_metrics("job-ssrf-test")
    assert job_metrics["requests_total"] == 1
    assert job_metrics["blocked_requests"] == 1
    assert job_metrics["failed_requests"] == 1
    assert job_metrics["classification_count"]["HTTP_FORBIDDEN"] == 1


# ==============================================================================
# 4. Browser Fallback Telemetry Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_browser_fallback_recording():
    """Verify browser fallback promotions increment browser_fallback_count."""
    manager = get_antibot_manager()
    manager.record_browser_fallback("job-browser-1")
    manager.record_browser_fallback("job-browser-1")

    metrics = manager.metrics.get_metrics("job-browser-1")
    assert metrics["browser_fallback_count"] == 2

    # Check global rollup
    assert manager.metrics.get_metrics()["browser_fallback_count"] == 2


@pytest.mark.asyncio
async def test_content_extractor_browser_promotion_increments_fallback_metric():
    """Verify ContentExtractor increments browser_fallback_count when falling back to headless browser."""
    manager = get_antibot_manager()
    manager.metrics.reset()

    extractor = ContentExtractor(
        strategy="auto",
        render_mode="auto",
        job_id="job-extractor-pw",
    )

    # Mock _safe_fetch_html to return JS_RENDER_REQUIRED
    mock_diag = MagicMock()
    mock_diag.classification = ResponseClassification.JS_RENDER_REQUIRED
    mock_diag.reason = "Client-rendered React application"

    with patch.object(
        extractor,
        "_safe_fetch_html",
        new_callable=AsyncMock,
        return_value={
            "failed": False,
            "html": "<div id='root'></div>",
            "diagnostics": mock_diag,
            "status_code": 200,
        },
    ), patch.object(
        extractor,
        "_extract_via_crawl4ai_direct",
        new_callable=AsyncMock,
        return_value=MagicMock(quality_status="passed"),
    ):
        await extractor.extract("https://example.com/spa-app")

    job_metrics = manager.metrics.get_metrics("job-extractor-pw")
    assert job_metrics["browser_fallback_count"] >= 1


# ==============================================================================
# 5. Job Models & Serialization Tests
# ==============================================================================

def test_job_info_metrics_field_and_serialization():
    """Verify JobInfo model supports metrics dictionary and serializes cleanly."""
    job = JobInfo(
        job_type=JobType.DISCOVERY,
        metrics={
            "requests_total": 10,
            "successful_requests": 9,
            "failed_requests": 1,
            "retry_attempts": 2,
        },
    )

    status_dict = job.to_status_dict()
    assert "metrics" in status_dict
    assert status_dict["metrics"]["requests_total"] == 10
    assert status_dict["metrics"]["successful_requests"] == 9


def test_job_manager_to_job_status_response_includes_metrics():
    """Verify JobManager.to_job_status_response() attaches metrics to JobStatus schema."""
    mgr = JobManager()
    job = JobInfo(
        job_id="job-status-test",
        job_type=JobType.DISCOVERY,
        metrics={
            "requests_total": 42,
            "successful_requests": 40,
            "failed_requests": 2,
            "browser_fallback_count": 3,
        },
    )

    status_resp = mgr.to_job_status_response(job)
    assert isinstance(status_resp, JobStatus)
    assert status_resp.metrics is not None
    assert status_resp.metrics["requests_total"] == 42
    assert status_resp.metrics["browser_fallback_count"] == 3


# ==============================================================================
# 6. Admin API Health Endpoint Telemetry Exposure
# ==============================================================================

def test_admin_health_endpoint_exposes_antibot_metrics(monkeypatch):
    """Verify /api/admin/health exposes antibot_metrics with all required fields."""
    manager = get_antibot_manager()
    manager.metrics.record_request(
        job_id=None,
        classification=ResponseClassification.SUCCESS,
        latency_seconds=0.12,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "api_key", "test-master-admin-key-32chars-long")

    client = TestClient(app)
    headers = {"X-API-Key": "test-master-admin-key-32chars-long"}
    response = client.get("/api/admin/health", headers=headers)

    assert response.status_code == 200
    data = response.json()

    assert "antibot_metrics" in data
    ab_metrics = data["antibot_metrics"]
    assert "requests_total" in ab_metrics
    assert ab_metrics["requests_total"] >= 1
    assert "classification_count" in ab_metrics
    assert "average_request_latency" in ab_metrics
    assert "browser_fallback_count" in ab_metrics
