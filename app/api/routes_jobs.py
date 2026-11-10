"""API endpoints for managing and inspecting background jobs."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from app.jobs.manager import JobManager
from app.schemas.responses import JobStatus

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

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


@router.get("/list", response_model=list[JobStatus])
async def list_jobs(request: Request, limit: int = 100, offset: int = 0) -> list[JobStatus]:
    """List all registered jobs with optional pagination and tenant filtering."""
    manager = get_manager()
    tenant_id = getattr(request.state, "tenant_id", None)
    jobs = manager.list_jobs(tenant_id=tenant_id)
    paginated = jobs[offset : offset + limit] if offset > 0 or limit < len(jobs) else jobs
    return [manager.to_job_status_response(j) for j in paginated]


@router.get("/{job_id}", response_model=JobStatus)
async def get_job(request: Request, job_id: str) -> JobStatus:
    """Get status and details of a specific job, with tenant isolation check."""
    manager = get_manager()
    tenant_id = getattr(request.state, "tenant_id", None)
    job = manager.get_job(job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Requested job not found.")

    return manager.to_job_status_response(job)


@router.delete("/{job_id}")
async def delete_job(request: Request, job_id: str) -> dict[str, Any]:
    """Permanently delete a job and its artifacts."""
    manager = get_manager()
    tenant_id = getattr(request.state, "tenant_id", None)
    deleted = manager.delete_job(job_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Requested job to delete was not found.")
    return {"success": True, "message": f"Job {job_id} deleted successfully."}
