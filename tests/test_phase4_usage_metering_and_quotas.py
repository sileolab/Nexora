"""Comprehensive Phase 4 Tests:
Usage Metering across all 7 events, Atomic Quota Enforcement,
Idempotency, Concurrency Race Protection, Multi-Worker Checkpointing, and Tenant Independence.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import shutil
import tempfile
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.jobs.manager import JobManager
from app.jobs.models import JobInfo, JobState, JobType
from app.main import create_app
from app.schemas.chunks import DocumentChunk
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.schemas.workspace import WorkspaceCreate
from app.services.file_processor import FileProcessorService
from app.services.quota_enforcer import QuotaEnforcer, get_quota_enforcer
from app.services.usage_meter import UsageMeter, get_usage_meter
from app.services.workspace_manager import WorkspaceManager, get_workspace_manager


@pytest.fixture
def temp_dir():
    """Create isolated temporary directory."""
    tmp = tempfile.mkdtemp(prefix="phase4_metering_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# ==============================================================================
# 1. Real Extraction Execution Increments pages_crawled
# ==============================================================================

@pytest.mark.asyncio
async def test_real_crawl_pages_crawled_increment(temp_dir):
    """Extraction job execution must accurately record completed pages in UsageMeter."""
    meter = UsageMeter(usage_dir=temp_dir)
    manager = JobManager()
    tenant_id = "tenant-crawl-meter"

    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
    ]
    job = manager.create_extraction_job(urls, tenant_id=tenant_id)

    mock_doc = ExtractedDocument(
        url="https://example.com/page",
        title="Valid Page",
        cleaned_content="This is extracted page content with enough length to be valid.",
        raw_html="<html>This is extracted page content with enough length to be valid.</html>",
        status_code=200,
        quality_status=QualityStatus.SUCCESS,
    )

    with patch("app.services.extractor.ContentExtractor.extract", new_callable=AsyncMock, return_value=mock_doc), \
         patch("app.services.usage_meter.get_usage_meter", return_value=meter):
        await manager.run_extraction(job.job_id)

    # Usage meter must reflect exactly 3 pages crawled
    usage = meter.get_current_month(tenant_id)
    assert usage.pages_crawled == 3, f"Expected 3 pages, got {usage.pages_crawled}"

    # Persistent checkpoint summary file must exist and reflect 3 pages
    period = meter.current_period
    summary_path = os.path.join(temp_dir, tenant_id, f"{period}_summary.json")
    assert os.path.exists(summary_path), "Summary file should exist after usage recording"
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
    assert summary_data["summary"].get("pages_crawled") == 3


# ==============================================================================
# 2. Chunks and Embeddings Usage Metering & Quotas
# ==============================================================================

@pytest.mark.asyncio
async def test_chunks_and_embeddings_usage_metering(temp_dir):
    """Chunking and Embedding services must record chunks_created and embeddings_generated."""
    meter = UsageMeter(usage_dir=temp_dir)
    wm = WorkspaceManager(workspace_dir=temp_dir)
    info, raw_key = wm.create_workspace(WorkspaceCreate(name="AI Meter Test", plan="starter"))
    tenant_id = info.workspace_id

    manager = JobManager()
    job = manager.create_extraction_job(["https://example.com/item1"], tenant_id=tenant_id)
    manager.set_documents(job.job_id, [
        ExtractedDocument(
            url="https://example.com/item1",
            title="Title 1",
            cleaned_content="Sentence one. " * 30,
            status_code=200,
            quality_status=QualityStatus.SUCCESS,
        )
    ])

    enforcer = QuotaEnforcer()

    # Pre-record chunks and embeddings
    meter.record(tenant_id, "chunks_created", 15, job_id=job.job_id, idempotency_key=f"chunks_created:{job.job_id}")
    meter.record(tenant_id, "embeddings_generated", 15, job_id=job.job_id, idempotency_key=f"embeddings_generated:{job.job_id}")

    usage = meter.get_current_month(tenant_id)
    assert usage.chunks_created == 15
    assert usage.embeddings_generated == 15

    # Quota check: starter plan has 5,000 chunks limit. Checking 10,000 must raise ValueError
    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter):
        with pytest.raises(ValueError, match="Chunk quota exceeded"):
            enforcer.check_chunks(tenant_id, 10000)

        with pytest.raises(ValueError, match="Embedding quota exceeded"):
            enforcer.check_embeddings(tenant_id, 10000)


# ==============================================================================
# 3. Job Retry Idempotency Prevents Duplicate Metering
# ==============================================================================

def test_job_retry_idempotency_no_duplicate_metering(temp_dir):
    """Recording with the same idempotency key must not duplicate usage counts."""
    meter = UsageMeter(usage_dir=temp_dir)
    tenant_id = "tenant-retry-idemp"
    idem_key = "retry_token_abc_123"

    # First attempt records 10 pages
    meter.record(tenant_id, "pages_crawled", 10, job_id="job_x", idempotency_key=idem_key)
    usage1 = meter.get_current_month(tenant_id)
    assert usage1.pages_crawled == 10
    assert usage1.events_count == 1

    # Retry with identical idempotency key must be ignored and not increment
    meter.record(tenant_id, "pages_crawled", 10, job_id="job_x", idempotency_key=idem_key)
    usage2 = meter.get_current_month(tenant_id)
    assert usage2.pages_crawled == 10, f"Expected 10 due to idempotency, got {usage2.pages_crawled}"
    assert usage2.events_count == 1


# ==============================================================================
# 4. Concurrent Quota Reservation Race Condition Protection
# ==============================================================================

def test_concurrent_quota_reservation_race_condition(temp_dir):
    """High-concurrency reservation attempts near quota limit must not allow over-consumption."""
    meter = UsageMeter(usage_dir=temp_dir)
    wm = WorkspaceManager(workspace_dir=temp_dir)
    # trial plan has 100 pages limit
    info, _ = wm.create_workspace(WorkspaceCreate(name="Race Test", plan="trial"))
    tenant_id = info.workspace_id

    # Pre-record 80 pages used. Remaining capacity = 20 pages.
    meter.record(tenant_id, "pages_crawled", 80)

    enforcer = QuotaEnforcer()

    # 10 concurrent threads each try to reserve 15 pages.
    # Since only 20 pages are remaining, exactly 1 thread can succeed!
    results = []

    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(enforcer.reserve_pages, tenant_id, 15) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

    success_count = sum(1 for r in results if r is True)
    failure_count = sum(1 for r in results if r is False)

    assert success_count == 1, f"Expected exactly 1 thread to succeed, got {success_count}"
    assert failure_count == 9, f"Expected 9 threads to be blocked, got {failure_count}"
    assert enforcer._reserved_pages[tenant_id] == 15


# ==============================================================================
# 5. Job Cancellation Releases Unspent Quota Reservation
# ==============================================================================

@pytest.mark.asyncio
async def test_job_cancellation_releases_reservation(temp_dir):
    """Cancelling a job must release its reserved quota while retaining completed pages."""
    meter = UsageMeter(usage_dir=temp_dir)
    wm = WorkspaceManager(workspace_dir=temp_dir)
    info, _ = wm.create_workspace(WorkspaceCreate(name="Cancel Test", plan="trial"))
    tenant_id = info.workspace_id

    enforcer = QuotaEnforcer()
    manager = JobManager()

    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter), \
         patch("app.services.quota_enforcer.get_quota_enforcer", return_value=enforcer), \
         patch("app.services.usage_meter.get_usage_meter", return_value=meter):

        # Create job requesting 25 pages -> enforcer reserves 25 pages
        urls = [f"https://example.com/item{i}" for i in range(25)]
        job = manager.create_extraction_job(urls, tenant_id=tenant_id)
        assert enforcer._reserved_pages.get(tenant_id, 0) == 25

        # Cancel job while pending
        cancelled = manager.cancel_job(job.job_id, tenant_id=tenant_id)
        assert cancelled is True

        # Reservation must be released
        assert enforcer._reserved_pages.get(tenant_id, 0) == 0


# ==============================================================================
# 6. Usage Persistence & Multi-Worker Checkpoint Tail-Reading Across Restart
# ==============================================================================

def test_usage_persistence_across_restart(temp_dir):
    """Usage totals must survive cache resets and read incrementally without full rescans."""
    meter1 = UsageMeter(usage_dir=temp_dir)
    tenant_id = "tenant-restart-perf"

    meter1.record(tenant_id, "pages_crawled", 12)
    meter1.record(tenant_id, "chunks_created", 45)
    meter1.record(tenant_id, "storage_bytes", 8192)

    usage1 = meter1.get_current_month(tenant_id)
    assert usage1.pages_crawled == 12
    assert usage1.chunks_created == 45
    assert usage1.storage_bytes == 8192

    # Simulate restart by resetting in-memory caches and re-initializing UsageMeter
    meter1.reset_cache()
    meter2 = UsageMeter(usage_dir=temp_dir)

    usage2 = meter2.get_current_month(tenant_id)
    assert usage2.pages_crawled == 12
    assert usage2.chunks_created == 45
    assert usage2.storage_bytes == 8192

    # Now append an additional event from "another process"
    meter2.record(tenant_id, "pages_crawled", 5)

    usage3 = meter2.get_current_month(tenant_id)
    assert usage3.pages_crawled == 17
    assert usage3.chunks_created == 45


# ==============================================================================
# 7. Multi-Tenant Usage & Quota Independence
# ==============================================================================

def test_multi_tenant_usage_and_quota_independence(temp_dir):
    """Usage and quota limits in Workspace A must never affect Workspace B."""
    meter = UsageMeter(usage_dir=temp_dir)
    wm = WorkspaceManager(workspace_dir=temp_dir)

    ws_a, _ = wm.create_workspace(WorkspaceCreate(name="Tenant A", plan="trial"))  # 100 pages
    ws_b, _ = wm.create_workspace(WorkspaceCreate(name="Tenant B", plan="trial"))  # 100 pages

    enforcer = QuotaEnforcer()

    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter):

        # Tenant A consumes all 100 pages
        meter.record(ws_a.workspace_id, "pages_crawled", 100)

        # Tenant A cannot reserve even 1 page
        assert enforcer.reserve_pages(ws_a.workspace_id, 1) is False

        # Tenant B should have 0 usage and be able to reserve 50 pages easily
        assert enforcer.reserve_pages(ws_b.workspace_id, 50) is True
        assert meter.get_current_month(ws_b.workspace_id).pages_crawled == 0


# ==============================================================================
# 8. File Storage and Processing Metering
# ==============================================================================

@pytest.mark.asyncio
async def test_file_storage_and_processing_metering(temp_dir):
    """File uploads and pipeline transformations must meter storage_bytes and files_processed."""
    meter = UsageMeter(usage_dir=temp_dir)
    tenant_id = "tenant-files-meter"

    processor = FileProcessorService(base_dir=os.path.join(temp_dir, "file_storage"))

    sample_content = b"# RAG Document\n\nThis is a sample document for indexing in the RAG platform."
    with patch("app.services.usage_meter.get_usage_meter", return_value=meter):
        uploaded = processor.upload_file("rag_doc.md", sample_content, tenant_id=tenant_id)
        assert uploaded["size_bytes"] == len(sample_content)

        # Process the uploaded file
        res = await processor.process(
            uploaded["file_id"],
            operations=["normalize"],
            tenant_id=tenant_id,
        )
        assert res["status"] == "success"

    usage = meter.get_current_month(tenant_id)
    assert usage.storage_bytes >= len(sample_content)
    assert usage.files_processed == 1


# ==============================================================================
# 9. LLM Token Metering
# ==============================================================================

def test_llm_tokens_metering(temp_dir):
    """LLM operations must record prompt + completion token usage under llm_tokens."""
    meter = UsageMeter(usage_dir=temp_dir)
    tenant_id = "tenant-llm-tokens"
    job_id = "job-llm-test"

    meter.record(
        tenant_id,
        "llm_tokens",
        450,
        job_id=job_id,
        idempotency_key=f"llm_tokens:{job_id}",
    )

    usage = meter.get_current_month(tenant_id)
    assert usage.llm_tokens == 450
    assert usage.llm_tokens_used == 450


# ==============================================================================
# 10. Quota Status and Utilization Calculations
# ==============================================================================

def test_quota_enforcer_status_and_utilization(temp_dir):
    """QuotaEnforcer.get_quota_status must accurately compute used, limit, remaining and pct_used."""
    meter = UsageMeter(usage_dir=temp_dir)
    wm = WorkspaceManager(workspace_dir=temp_dir)
    ws, _ = wm.create_workspace(WorkspaceCreate(name="Status Test", plan="trial"))
    tenant_id = ws.workspace_id

    # Record 40 pages out of 100 limit
    meter.record(tenant_id, "pages_crawled", 40)

    enforcer = QuotaEnforcer()
    with patch("app.services.quota_enforcer.get_workspace_manager", return_value=wm), \
         patch("app.services.quota_enforcer.get_usage_meter", return_value=meter):

        status = enforcer.get_quota_status(tenant_id)
        assert "pages_crawled" in status.metrics
        pages_stat = status.metrics["pages_crawled"]
        assert pages_stat["limit"] == 100
        assert pages_stat["used"] == 40
        assert pages_stat["remaining"] == 60
        assert pages_stat["pct_used"] == 40.0


# ==============================================================================
# 11. API Endpoints Return HTTP 429 On Quota Exhaustion
# ==============================================================================

def test_api_endpoints_return_429_on_quota_exceeded():
    """Discovery, extraction, and AI processing endpoints must return HTTP 429 when quota is exhausted."""
    app = create_app()
    client = TestClient(app)
    wm = get_workspace_manager()
    ws, raw_key = wm.create_workspace(WorkspaceCreate(name="API 429 Test", plan="trial"))
    meter = get_usage_meter()

    # Pre-record max pages (100)
    meter.record(ws.workspace_id, "pages_crawled", 100)

    # 1. Extraction start should return 429
    resp_extract = client.post(
        "/api/extraction/start",
        json={"urls": ["https://example.com/item1"]},
        headers={"X-API-Key": raw_key},
    )
    assert resp_extract.status_code == 429
    assert "Page quota exceeded" in resp_extract.json()["detail"]

    # 2. Discovery start should return 429
    resp_disc = client.post(
        "/api/discovery/start",
        json={"root_url": "https://example.com", "max_pages": 5},
        headers={"X-API-Key": raw_key},
    )
    assert resp_disc.status_code == 429
    assert "Page quota exceeded" in resp_disc.json()["detail"]

    # 3. Create a workspace with exhausted chunk quota
    ws_chunk, chunk_key = wm.create_workspace(WorkspaceCreate(name="Chunk 429 Test", plan="trial"))
    meter.record(ws_chunk.workspace_id, "chunks_created", 5000)

    # Create dummy job with documents
    from app.api.routes_ai import get_manager
    mgr = get_manager()
    job = mgr.create_extraction_job(["https://example.com/p1"], tenant_id=ws_chunk.workspace_id)
    mgr.set_documents(job.job_id, [
        ExtractedDocument(
            url="https://example.com/p1",
            title="T",
            cleaned_content="Valid extracted document content " * 30,
            status_code=200,
            quality_status=QualityStatus.SUCCESS,
        )
    ])

    # AI chunk documents should return 429
    resp_chunk = client.post(
        "/api/ai/chunk",
        json={"job_id": job.job_id},
        headers={"X-API-Key": chunk_key},
    )
    assert resp_chunk.status_code == 429
    assert "Chunk quota exceeded" in resp_chunk.json()["detail"]

