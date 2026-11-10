"""API endpoints for content extraction."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.jobs.manager import JobManager
from app.schemas.requests import CompareRequest, ExtractionRequest, SingleExtractRequest
from app.schemas.responses import ApiResponse, JobStatus

router = APIRouter(prefix="/api/extraction", tags=["extraction"])

job_manager: Optional[JobManager] = None


def set_job_manager(manager: JobManager) -> None:
    """Inject JobManager dependency."""
    global job_manager
    job_manager = manager


def get_manager() -> JobManager:
    """Ensure JobManager is initialized."""
    if job_manager is None:
        raise HTTPException(status_code=500, detail="Job manager not initialized")
    return job_manager


@router.post("/start", response_model=ApiResponse)
async def start_extraction(request: ExtractionRequest, background_tasks: BackgroundTasks, http_request: Request) -> ApiResponse:
    """Start extraction for selected URLs in the background with quota checks."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)

    # Quota check if tenant is set
    if tenant_id:
        from app.services.quota_enforcer import get_quota_enforcer
        enforcer = get_quota_enforcer()
        try:
            enforcer.check_pages(tenant_id, count=len(request.urls))
            active_count = len([j for j in manager.list_jobs(tenant_id=tenant_id) if getattr(j, "state", None) in ("pending", "running")])
            enforcer.check_concurrent_jobs(tenant_id, active_count)
        except ValueError as err:
            raise HTTPException(status_code=429, detail=str(err))

    config = request.model_dump()
    if tenant_id:
        config["tenant_id"] = tenant_id

    try:
        job = manager.create_extraction_job(urls=request.urls, config=config)
    except ValueError as err:
        raise HTTPException(status_code=429, detail=str(err))

    if tenant_id:
        from app.services.usage_meter import get_usage_meter
        get_usage_meter().record(
            tenant_id,
            "job_count",
            1,
            job_id=job.job_id,
            idempotency_key=f"job_count:{job.job_id}",
        )

    background_tasks.add_task(manager.run_extraction, job.job_id)

    return ApiResponse.ok(
        data={"job_id": job.job_id, "total": len(request.urls)},
        message="Content extraction process started successfully.",
    )


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_extraction_status(job_id: str, http_request: Request) -> JobStatus:
    """Get extraction job progress and document summaries."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)
    job = manager.get_job(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Extraction job ID not found.")

    return manager.to_job_status_response(job)


@router.post("/cancel/{job_id}", response_model=ApiResponse)
async def cancel_extraction(job_id: str, http_request: Request) -> ApiResponse:
    """Cancel a running extraction job."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)
    job = manager.get_job(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")

    if job.is_finished:
        return ApiResponse.ok(message="Extraction process is already finished.")

    manager.cancel_job(job_id, tenant_id=tenant_id)
    return ApiResponse.ok(message="Extraction cancellation command issued.")


@router.post("/retry/{job_id}", response_model=ApiResponse)
async def retry_failed(job_id: str, background_tasks: BackgroundTasks) -> ApiResponse:
    """Retry extraction for URLs that failed or were blocked in a previous job."""
    manager = get_manager()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Previous job not found.")

    failed_urls: list[str] = []
    for doc in job.documents:
        if doc.get("status") in {"failed", "blocked"} or doc.get("quality") in {"failed", "blocked"}:
            failed_urls.append(doc.get("url", ""))

    if not failed_urls:
        return ApiResponse.ok(
            data={"job_id": job_id},
            message="No failed or blocked pages found to retry.",
        )

    new_config = dict(job.config)
    new_job = manager.create_extraction_job(urls=failed_urls, config=new_config)
    background_tasks.add_task(manager.run_extraction, new_job.job_id)

    return ApiResponse.ok(
        data={"job_id": new_job.job_id, "retry_count": len(failed_urls)},
        message=f"Retry process started for {len(failed_urls)} pages.",
    )


@router.post("/single", response_model=ApiResponse)
async def extract_single_url(request: SingleExtractRequest) -> ApiResponse:
    """Extract content from a single URL synchronously using specified engine or auto mode."""
    from app.services.extractor import ContentExtractor

    extractor = ContentExtractor(
        strategy=request.extraction_strategy,
        min_quality_score=request.min_quality_score,
        render_mode=request.render_mode,
    )
    doc = await extractor.extract(
        url=request.url,
        timeout=request.timeout,
        crawl_mode=request.crawl_mode,
        loading_delay=request.loading_delay,
        wait_for_selector=request.wait_for_selector,
        visible_only=request.visible_only,
    )
    return ApiResponse.ok(
        data=doc.model_dump(mode="json"),
        message="Page extraction completed successfully.",
    )


@router.post("/compare", response_model=ApiResponse)
async def compare_engines(request: CompareRequest) -> ApiResponse:
    """Benchmark all 3 extraction engines (Trafilatura, BeautifulSoup, Crawl4AI) on a single URL."""
    from app.services.extractor import ContentExtractor

    extractor = ContentExtractor()
    doc = await extractor.extract(
        url=request.url,
        timeout=request.timeout,
        crawl_mode="compare",
        loading_delay=request.loading_delay,
        wait_for_selector=request.wait_for_selector,
    )
    return ApiResponse.ok(
        data=doc.model_dump(mode="json"),
        message="Comparison of all 3 extraction engines completed successfully.",
    )
