"""Integration and pipeline tests for Phase 2:
Usage Metering Hookup, BYOK Injection, Atomic Quota Enforcement, and Watchdog.
"""

from __future__ import annotations

import asyncio
import tempfile
import shutil
import pytest
from unittest.mock import AsyncMock, patch

from app.jobs.manager import JobManager
from app.jobs.models import JobInfo, JobState, JobType
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.schemas.workspace import WorkspaceCreate
from app.services.quota_enforcer import QuotaEnforcer
from app.services.secrets_manager import SecretsManager
from app.services.usage_meter import UsageMeter
from app.services.workspace_manager import WorkspaceManager
from app.api.routes_ai import _require_api_key


@pytest.fixture
def temp_env():
    tmp = tempfile.mkdtemp(prefix="crawlbot_phase2_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# ==============================================================================
# 1. ARC-01: Metering Hookup in Discovery & Extraction
# ==============================================================================

@pytest.mark.asyncio
async def test_usage_metering_hookup_in_discovery(temp_env):
    """Discovery execution must record pages_crawled in UsageMeter."""
    meter = UsageMeter(usage_dir=temp_env)
    manager = JobManager()
    tenant_id = "tenant-meter-test"

    job = manager.create_discovery_job("https://example.com", max_pages=2, tenant_id=tenant_id)

    # Mock crawler discovery result
    mock_result = AsyncMock()
    mock_result.crawled = {"https://example.com/1": {}, "https://example.com/2": {}}
    mock_result.failed = {}
    mock_result.discovered = {"https://example.com/1": {}, "https://example.com/2": {}}

    with patch("app.services.crawler.CrawlerService.discover", return_value=mock_result), \
         patch("app.services.usage_meter.get_usage_meter", return_value=meter):
        await manager.run_discovery(job.job_id)

    # Check meter
    usage = meter.get_current_month(tenant_id)
    assert usage.pages_crawled == 2, f"Expected 2 pages crawled, got {usage.pages_crawled}"


@pytest.mark.asyncio
async def test_usage_metering_hookup_in_extraction(temp_env):
    """Extraction execution must record pages_crawled in UsageMeter."""
    meter = UsageMeter(usage_dir=temp_env)
    manager = JobManager()
    tenant_id = "tenant-extract-meter"

    job = manager.create_extraction_job(["https://example.com/p1", "https://example.com/p2"], tenant_id=tenant_id)

    mock_doc = ExtractedDocument(
        url="https://example.com/p1",
        title="Page 1",
        cleaned_content="Valid content with sufficient length for quality pass.",
        raw_html="<html>Valid content with sufficient length for quality pass.</html>",
        status_code=200,
        quality_status=QualityStatus.SUCCESS,
    )

    with patch("app.services.extractor.ContentExtractor.extract", new_callable=AsyncMock, return_value=mock_doc), \
         patch("app.services.usage_meter.get_usage_meter", return_value=meter):
        await manager.run_extraction(job.job_id)

    usage = meter.get_current_month(tenant_id)
    assert usage.pages_crawled == 2, f"Expected 2 pages crawled, got {usage.pages_crawled}"


# ==============================================================================
# 2. ARC-02: BYOK Tenant Secret Injection
# ==============================================================================

def test_byok_tenant_secret_retrieval(temp_env):
    """_require_api_key(tenant_id) must retrieve workspace BYOK key if present."""
    sm = SecretsManager(secrets_dir=temp_env)
    tenant_id = "tenant-byok-test"
    sm.set_secret(tenant_id, "openai_api_key", "sk-tenant-custom-key-999")

    with patch("app.services.secrets_manager.get_secrets_manager", return_value=sm):
        resolved_key = _require_api_key(tenant_id)
        assert resolved_key == "sk-tenant-custom-key-999"


# ==============================================================================
# 3. ARC-03: Atomic Quota Reservation & Job Creation Enforcement
# ==============================================================================

def test_quota_reservation_blocks_over_limit(temp_env):
    """QuotaEnforcer.reserve_pages must fail when requested pages exceed remaining allowance."""
    meter = UsageMeter(usage_dir=temp_env)
    wm = WorkspaceManager(workspace_dir=temp_env)
    info, _ = wm.create_workspace(WorkspaceCreate(name="Quota Test", plan="trial"))  # trial has 100 pages

    enforcer = QuotaEnforcer()
    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter):

        # Pre-record 90 pages
        meter.record(info.workspace_id, "pages_crawled", 90)

        # Reserving 5 pages should succeed
        assert enforcer.reserve_pages(info.workspace_id, 5) is True

        # Reserving 10 more pages should fail (90 + 5 + 10 = 105 > 100)
        assert enforcer.reserve_pages(info.workspace_id, 10) is False

        # Release the 5 pages
        enforcer.release_pages(info.workspace_id, 5)

        # Now reserving 6 pages should succeed (90 + 6 = 96 <= 100)
        assert enforcer.reserve_pages(info.workspace_id, 6) is True
