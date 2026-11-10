"""API endpoints for downloading exported crawl data."""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.jobs.manager import JobManager
from app.schemas.requests import ExportRequest
from app.schemas.responses import ApiResponse
from app.services.export_service import ExportService

router = APIRouter(prefix="/api/export", tags=["export"])

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


@router.post("/download")
async def export_documents(request: ExportRequest, http_request: Request):
    """Export extracted documents in requested format (json, jsonl, markdown, text)."""
    manager = get_manager()
    tenant_id = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
    job = manager.get_job(request.job_id, tenant_id=tenant_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID for export not found.")

    documents = manager.get_documents(request.job_id, tenant_id=tenant_id)
    if not documents:
        raise HTTPException(status_code=400, detail="No documents registered in this job to export.")

    export_service = ExportService()
    fmt = request.format.lower().strip()
    category = request.category

    dedup = getattr(request, "deduplicate", False)

    try:
        if fmt == "json":
            file_path = export_service.export_json(documents, request.job_id, category, deduplicate=dedup)
            return FileResponse(
                path=file_path,
                filename=f"nexora_export_{request.job_id[:8]}.json",
                media_type="application/json",
            )

        elif fmt == "jsonl":
            file_path = export_service.export_jsonl(documents, request.job_id, category, deduplicate=dedup)
            return FileResponse(
                path=file_path,
                filename=f"nexora_export_{request.job_id[:8]}.jsonl",
                media_type="application/x-ndjson",
            )

        elif fmt in {"markdown", "md"}:
            folder_path = export_service.export_markdown(documents, request.job_id, category, deduplicate=dedup)
            # Create a zip archive of the markdown folder
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_p in folder_path.glob("*.md"):
                    zf.write(file_p, arcname=file_p.name)
            zip_buffer.seek(0)
            return Response(
                content=zip_buffer.getvalue(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename=nexora_markdown_{request.job_id[:8]}.zip"
                },
            )

        elif fmt in {"text", "txt"}:
            folder_path = export_service.export_text(documents, request.job_id, category, deduplicate=dedup)
            # Create a zip archive of the text folder
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_p in folder_path.glob("*.txt"):
                    zf.write(file_p, arcname=file_p.name)
            zip_buffer.seek(0)
            return Response(
                content=zip_buffer.getvalue(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename=nexora_text_{request.job_id[:8]}.zip"
                },
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid format: {fmt}. Allowed formats: json, jsonl, markdown, text",
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error creating export: {str(exc)}")


@router.get("/formats", response_model=ApiResponse)
async def get_export_formats() -> ApiResponse:
    """Return available export formats."""
    return ApiResponse.ok(
        data={
            "formats": [
                {"id": "json", "name": "JSON", "extension": ".json", "description": "Complete document with full metadata"},
                {"id": "jsonl", "name": "JSON Lines", "extension": ".jsonl", "description": "One JSON document per line"},
                {"id": "markdown", "name": "Markdown", "extension": ".zip", "description": "Individual Markdown files with YAML Frontmatter"},
                {"id": "text", "name": "Plain Text", "extension": ".zip", "description": "Cleaned plain text"},
            ]
        }
    )
