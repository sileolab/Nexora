"""API Endpoints for File & Data Processing Studio.

Supports uploading, processing, transforming, chunking, and downloading
Markdown, Text, JSON, JSONL, and CSV files in Crawlbot.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.schemas.responses import ApiResponse
from app.services.file_processor import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    FileProcessorService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

_file_service = FileProcessorService()


@router.get("/supported-formats", response_model=ApiResponse)
async def supported_formats() -> ApiResponse:
    """Return supported file extensions and max limits."""
    return ApiResponse.ok(
        data={
            "supported_formats": sorted([ext.lstrip(".") for ext in ALLOWED_EXTENSIONS]),
            "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
            "max_file_size_mb": MAX_FILE_SIZE_BYTES // (1024 * 1024),
        },
        message="Supported file formats",
    )


@router.post("/upload", response_model=ApiResponse)
async def upload_file(http_request: Request, file: UploadFile = File(...)) -> ApiResponse:
    """Upload a file (.md, .txt, .json, .jsonl, .csv, .pdf, .docx) for processing with quota check."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file name is empty.")

    try:
        content_bytes = await file.read()
        tenant_id = getattr(http_request.state, "tenant_id", None)
        if tenant_id:
            from app.services.quota_enforcer import get_quota_enforcer
            try:
                get_quota_enforcer().check_file_size(tenant_id, len(content_bytes))
            except ValueError as err:
                raise HTTPException(status_code=429, detail=str(err))

        effective_tenant = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
        record = _file_service.upload_file(file.filename, content_bytes, tenant_id=effective_tenant)
        logger.info("Uploaded file %s (ID: %s, %d bytes)", record["filename"], record["file_id"], record["size_bytes"])
        return ApiResponse.ok(
            data=record,
            message=f"File '{record['filename']}' uploaded successfully.",
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Upload failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Error saving file: {str(exc)}")


@router.post("/process", response_model=ApiResponse)
async def process_file(request: dict[str, Any], http_request: Request) -> ApiResponse:
    """Execute selected processing pipeline on an uploaded file.

    Body parameters:
        file_id (str): Unique file identifier from upload.
        operations (list[str]): List of operations to apply.
        options (dict, optional): Configuration options.
    """
    file_id = request.get("file_id", "").strip()
    if not file_id:
        raise HTTPException(status_code=400, detail="File ID (file_id) is required.")

    operations = request.get("operations", [])
    if not operations or not isinstance(operations, list):
        raise HTTPException(status_code=400, detail="At least one processing operation must be selected.")

    options = request.get("options", {})
    tenant_id = getattr(http_request.state, "tenant_id", None)

    try:
        effective_tenant = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
        result = await _file_service.process(file_id, operations, options, tenant_id=effective_tenant)
        if tenant_id:
            from app.services.usage_meter import get_usage_meter
            meter = get_usage_meter()
            meter.record(tenant_id, "files_processed", 1, job_id=file_id)

        logger.info("Processed file %s with operations %s", file_id, operations)
        return ApiResponse.ok(
            data=result,
            message="File processing completed successfully.",
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe))
    except Exception as exc:
        logger.exception("Processing failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(exc)}")


@router.get("/preview/{artifact_id}", response_model=ApiResponse)
async def preview_artifact(artifact_id: str, http_request: Request) -> ApiResponse:
    """Retrieve metadata and preview for a processed artifact."""
    tenant_id = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
    artifact = _file_service.get_artifact(artifact_id, tenant_id=tenant_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Processing artifact not found.")

    path = Path(artifact["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Physical output file not found.")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content_preview = f.read(3000)

    return ApiResponse.ok(
        data={**artifact, "content_preview": content_preview},
        message="Output preview retrieved successfully.",
    )


@router.get("/download/{artifact_id}")
async def download_artifact(artifact_id: str, http_request: Request):
    """Download the processed output file."""
    tenant_id = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
    artifact = _file_service.get_artifact(artifact_id, tenant_id=tenant_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Processing artifact for download not found.")

    path = Path(artifact["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Physical output file does not exist.")

    content_type, _ = mimetypes.guess_type(artifact["filename"])
    content_type = content_type or "application/octet-stream"

    return FileResponse(
        path=str(path),
        filename=artifact["filename"],
        media_type=content_type,
    )


@router.get("/info/{file_id}", response_model=ApiResponse)
async def file_info(file_id: str, http_request: Request) -> ApiResponse:
    """Retrieve metadata for an uploaded file."""
    tenant_id = getattr(http_request.state, "authenticated_workspace_id", None) or getattr(http_request.state, "tenant_id", None) or getattr(http_request.state, "workspace_id", None)
    info = _file_service.get_file(file_id, tenant_id=tenant_id)
    if not info:
        raise HTTPException(status_code=404, detail="Requested file not found.")
    return ApiResponse.ok(data=info, message="File information retrieved successfully.")
