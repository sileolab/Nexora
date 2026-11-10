"""API endpoints for website discovery."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.jobs.manager import JobManager
from app.schemas.requests import DiscoveryRequest
from app.schemas.responses import ApiResponse, JobStatus

router = APIRouter(prefix="/api/discovery", tags=["discovery"])

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
async def start_discovery(request: DiscoveryRequest, background_tasks: BackgroundTasks, http_request: Request) -> ApiResponse:
    """Start a new discovery job in the background with quota enforcement and tenant tagging."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)

    # Quota check if workspace/tenant is set
    if tenant_id:
        from app.services.quota_enforcer import get_quota_enforcer
        enforcer = get_quota_enforcer()
        try:
            enforcer.check_pages(tenant_id, count=request.max_pages)
            active_count = len([j for j in manager.list_jobs(tenant_id=tenant_id) if getattr(j, "state", None) in ("pending", "running")])
            enforcer.check_concurrent_jobs(tenant_id, active_count)
        except ValueError as err:
            raise HTTPException(status_code=429, detail=str(err))

    config = request.model_dump()
    if tenant_id:
        config["tenant_id"] = tenant_id

    try:
        job = manager.create_discovery_job(config)
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

    # Launch background task
    background_tasks.add_task(manager.run_discovery, job.job_id)

    return ApiResponse.ok(
        data={"job_id": job.job_id},
        message="Website discovery process started successfully.",
    )


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_discovery_status(job_id: str, http_request: Request) -> JobStatus:
    """Get the live status and discovered pages of a discovery job."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)
    job = manager.get_job(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")

    return manager.to_job_status_response(job)


@router.post("/cancel/{job_id}", response_model=ApiResponse)
async def cancel_discovery(job_id: str, http_request: Request) -> ApiResponse:
    """Cancel a running discovery job."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "tenant_id", None)
    job = manager.get_job(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")

    if job.is_finished:
        return ApiResponse.ok(message="Discovery process is already finished.")

    manager.cancel_job(job_id, tenant_id=tenant_id)
    return ApiResponse.ok(message="Discovery cancellation command issued.")
