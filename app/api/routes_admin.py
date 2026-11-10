"""Admin API routes — internal monitoring, operations, and maintenance.

These endpoints are for system administrators / devops only.
In production, protect with NEXORA_API_KEY or firewall rules.

Endpoints:
  GET  /api/admin/health           Comprehensive system health check
  GET  /api/admin/usage-summary    Aggregate usage across all workspaces
  POST /api/admin/cleanup          Remove expired artifacts
  GET  /api/admin/watchdog/status  Stuck job detection status
  POST /api/admin/watchdog/run     Manually trigger watchdog scan
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from app.core.security import require_admin

from app.services.workspace_manager import get_workspace_manager
from app.services.usage_meter import get_usage_meter
from app.services.job_watchdog import get_job_watchdog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Injected from main.py (same pattern as other routes)
_manager: Any = None


def set_job_manager(mgr: Any) -> None:
    global _manager
    _manager = mgr


@router.get("/health", summary="Admin system health")
def admin_health() -> dict[str, Any]:
    """Extended system health with operational metrics."""
    from app.core.config import get_settings
    settings = get_settings()

    workspaces = get_workspace_manager().list_workspaces()
    active_jobs = 0
    total_jobs = 0
    if _manager:
        all_jobs = _manager.list_jobs()
        total_jobs = len(all_jobs)
        active_jobs = sum(
            1 for j in all_jobs
            if str(getattr(getattr(j, "state", None), "value", "")).lower() in ("pending", "running")
        )

    # Disk usage metrics
    def _dir_size(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    output_bytes = _dir_size(Path("output"))
    data_bytes = _dir_size(Path("data"))

    from app.services.anti_bot import get_antibot_manager
    antibot_metrics = get_antibot_manager().metrics.get_metrics()

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "5.0.0",
        "env": settings.app_env,
        "workspaces_count": len(workspaces),
        "jobs": {
            "total": total_jobs,
            "active": active_jobs,
        },
        "disk_usage": {
            "output_bytes": output_bytes,
            "data_bytes": data_bytes,
            "output_mb": round(output_bytes / 1024 / 1024, 2),
            "data_mb": round(data_bytes / 1024 / 1024, 2),
        },
        "antibot_metrics": antibot_metrics,
    }


@router.get("/usage-summary", summary="Aggregate usage across all workspaces")
def usage_summary() -> dict[str, Any]:
    """Return per-workspace current-month usage aggregated in a table."""
    workspaces = get_workspace_manager().list_workspaces()
    meter = get_usage_meter()
    rows = []
    for w in workspaces:
        usage = meter.get_current_month(w.workspace_id)
        rows.append({
            "workspace_id": w.workspace_id,
            "workspace_name": w.name,
            "plan": w.plan,
            "pages_crawled": usage.pages_crawled,
            "files_processed": usage.files_processed,
            "chunks_created": usage.chunks_created,
            "embeddings_generated": usage.embeddings_generated,
            "llm_tokens_used": usage.llm_tokens_used,
            "storage_bytes": usage.storage_bytes,
            "job_count": usage.job_count,
        })
    return {
        "success": True,
        "period": datetime.now(timezone.utc).strftime("%Y-%m"),
        "workspaces": rows,
    }


@router.post("/cleanup", summary="Remove expired artifact directories")
def cleanup_artifacts(
    max_history_days: int = Query(default=30, ge=1, le=365)
) -> dict[str, Any]:
    """
    Remove output artifact directories older than max_history_days.

    Safe to call multiple times (idempotent).
    """
    watchdog = get_job_watchdog()
    removed = watchdog.cleanup_old_artifacts(max_history_days=max_history_days)
    return {
        "success": True,
        "directories_removed": removed,
        "max_history_days": max_history_days,
    }


@router.get("/watchdog/status", summary="Watchdog status")
def watchdog_status() -> dict[str, Any]:
    """Return information about the job watchdog configuration."""
    watchdog = get_job_watchdog()
    return {
        "success": True,
        "max_runtime_minutes": watchdog.max_runtime_minutes,
        "jobs_dir": str(watchdog._jobs_dir),
    }


@router.post("/watchdog/run", summary="Manually trigger watchdog scan")
def watchdog_run() -> dict[str, Any]:
    """Scan for stuck jobs and cancel them. Idempotent."""
    if _manager is None:
        return {"success": False, "message": "Job manager not initialized."}
    watchdog = get_job_watchdog()
    cancelled = watchdog.check_stuck_jobs(_manager)
    return {
        "success": True,
        "stuck_jobs_cancelled": len(cancelled),
        "cancelled_job_ids": cancelled,
    }
