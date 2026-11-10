"""Nexora Live Real-Time Extraction & Change Tracking API Routes.

Exposes REST and SSE streaming endpoints for managing live watchers,
toggling Turn ON / Turn OFF states, retrieving the latest data, streaming real-time diffs,
and autonomously discovering dynamic/mutating fields (Auto-Detect).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.schemas.live import (
    ChangeEvent,
    DynamicFieldDetectionRequest,
    DynamicFieldDetectionResponse,
    LiveActionResponse,
    LiveWatcherCreateRequest,
    LiveWatcherListResponse,
    LiveWatcherResponse,
)
from app.services.live_extractor import DynamicFieldDetector, get_live_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live-extraction"])


@router.post(
    "/auto-detect",
    response_model=DynamicFieldDetectionResponse,
    summary="Auto-Detect Dynamic & Mutating Fields",
    description="Inspects target webpage for mutating, financial, crypto, or dynamic elements over an observation window and infers stable CSS selectors automatically.",
)
async def auto_detect_dynamic_fields(
    payload: DynamicFieldDetectionRequest,
) -> DynamicFieldDetectionResponse:
    detector = DynamicFieldDetector()
    try:
        return await detector.detect(
            url=payload.url,
            observation_seconds=payload.observation_seconds,
            engine=payload.engine,
            headers=payload.headers,
        )
    except Exception as e:
        logger.error(f"Auto-detection failed for {payload.url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-detection failed: {str(e)}",
        )


@router.post(
    "/watchers",
    response_model=LiveWatcherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Live Data Watcher",
    description="Registers a new real-time watcher on a target URL with field selectors, polling frequency, and engine strategy.",
)
async def create_live_watcher(spec: LiveWatcherCreateRequest, request: Request) -> LiveWatcherResponse:
    workspace_id = getattr(request.state, "workspace_id", None)
    manager = get_live_manager()
    watcher = manager.create_watcher(spec=spec, workspace_id=workspace_id)
    return watcher.to_response()


@router.get(
    "/watchers",
    response_model=LiveWatcherListResponse,
    summary="List All Live Watchers",
    description="Returns all registered live watchers, active counts, and current states.",
)
async def list_live_watchers(request: Request) -> LiveWatcherListResponse:
    workspace_id = getattr(request.state, "workspace_id", None)
    manager = get_live_manager()
    watchers = manager.list_watchers(workspace_id=workspace_id)
    responses = [w.to_response() for w in watchers]
    active_count = sum(1 for w in responses if w.status == "active")
    return LiveWatcherListResponse(
        watchers=responses,
        total_active=active_count,
        total_watchers=len(responses),
    )


@router.get(
    "/watchers/{watcher_id}",
    response_model=LiveWatcherResponse,
    summary="Get Live Watcher Details",
    description="Fetches configuration, operational status, change metrics, and the latest extracted snapshot.",
)
async def get_live_watcher(watcher_id: str) -> LiveWatcherResponse:
    manager = get_live_manager()
    watcher = manager.get_watcher(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    return watcher.to_response()


@router.post(
    "/watchers/{watcher_id}/turn-on",
    response_model=LiveActionResponse,
    summary="Turn ON Live Watcher",
    description="Activates real-time monitoring and change detection for the target watcher.",
)
async def turn_on_live_watcher(watcher_id: str) -> LiveActionResponse:
    manager = get_live_manager()
    watcher = manager.turn_on(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    return LiveActionResponse(
        watcher_id=watcher.id,
        status=watcher.status,
        message="Live watcher turned ON successfully.",
        latest_data=watcher.latest_data,
    )


@router.post(
    "/watchers/{watcher_id}/turn-off",
    response_model=LiveActionResponse,
    summary="Turn OFF Live Watcher",
    description="Deactivates live monitoring and halts background extraction for this watcher.",
)
async def turn_off_live_watcher(watcher_id: str) -> LiveActionResponse:
    manager = get_live_manager()
    watcher = manager.turn_off(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    return LiveActionResponse(
        watcher_id=watcher.id,
        status=watcher.status,
        message="Live watcher turned OFF successfully.",
        latest_data=watcher.latest_data,
    )


@router.get(
    "/watchers/{watcher_id}/latest",
    summary="Get Latest Live Data Snapshot",
    description="Returns only the most current live data extracted from the site (previous stale data has been replaced).",
)
async def get_latest_live_data(watcher_id: str) -> Dict[str, Any]:
    manager = get_live_manager()
    watcher = manager.get_watcher(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    return {
        "watcher_id": watcher.id,
        "status": watcher.status,
        "last_checked_at": watcher.last_checked_at,
        "last_changed_at": watcher.last_changed_at,
        "change_count": watcher.change_count,
        "latest_data": watcher.latest_data or {},
    }


@router.post(
    "/watchers/{watcher_id}/extract-now",
    summary="Trigger Immediate Extraction",
    description="Forces an instant extraction pass right now, updates latest data, and returns the result.",
)
async def extract_now(watcher_id: str) -> Dict[str, Any]:
    manager = get_live_manager()
    watcher = manager.get_watcher(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    data = await watcher.extract_current_snapshot()
    watcher.latest_data = data
    watcher.last_checked_at = watcher.to_response().last_checked_at
    return {
        "watcher_id": watcher.id,
        "extracted_data": data,
    }


@router.delete(
    "/watchers/{watcher_id}",
    summary="Delete Live Watcher",
    description="Permanently deletes the live watcher and terminates all associated monitoring tasks.",
)
async def delete_live_watcher(watcher_id: str) -> Dict[str, Any]:
    manager = get_live_manager()
    deleted = manager.delete_watcher(watcher_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")
    return {"success": True, "message": f"Live watcher '{watcher_id}' deleted."}


@router.get(
    "/watchers/{watcher_id}/stream",
    summary="Stream Live Change Events (SSE)",
    description="Server-Sent Events (SSE) stream yielding real-time change events as they occur on the target page.",
)
async def stream_live_changes(watcher_id: str, request: Request) -> StreamingResponse:
    manager = get_live_manager()
    watcher = manager.get_watcher(watcher_id)
    if not watcher:
        raise HTTPException(status_code=404, detail=f"Live watcher '{watcher_id}' not found.")

    queue = watcher.subscribe()

    async def event_generator():
        try:
            initial_payload = {
                "event": "connected",
                "watcher_id": watcher.id,
                "status": watcher.status,
                "latest_data": watcher.latest_data,
            }
            yield f"data: {json.dumps(initial_payload, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event: ChangeEvent = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            watcher.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
