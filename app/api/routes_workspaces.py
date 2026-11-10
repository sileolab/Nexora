"""REST API routes for workspace management (Phase 5 — SaaS Platform).

Endpoints:
  POST   /api/workspaces/              Create a new workspace
  GET    /api/workspaces/              List all workspaces
  GET    /api/workspaces/{workspace_id} Get workspace info
  DELETE /api/workspaces/{workspace_id} Delete workspace and all data
  POST   /api/workspaces/{workspace_id}/rotate-key  Rotate API key
  PUT    /api/workspaces/{workspace_id}/plan         Change plan
  GET    /api/workspaces/{workspace_id}/quota        Current quota status
  GET    /api/workspaces/{workspace_id}/usage        Usage report
  GET    /api/workspaces/{workspace_id}/secrets      List secrets (masked)
  POST   /api/workspaces/{workspace_id}/secrets      Set a secret (BYOK)
  DELETE /api/workspaces/{workspace_id}/secrets/{key_name} Delete a secret
"""

from __future__ import annotations

from app.core.security import is_safe_identifier

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, status
from pydantic import BaseModel

from app.schemas.workspace import (
    PlanConfig,
    QuotaStatus,
    WorkspaceCreate,
    WorkspaceInfo,
    WorkspaceKeyRotateResponse,
)
from app.schemas.metering import UsageReport
from app.services.workspace_manager import get_workspace_manager, get_all_plans
from app.services.usage_meter import get_usage_meter
from app.services.quota_enforcer import get_quota_enforcer
from app.services.secrets_manager import get_secrets_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_workspace(workspace_id: str) -> WorkspaceInfo:
    if not is_safe_identifier(workspace_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workspace ID format: '{workspace_id}'. Must be 3-64 alphanumeric characters, hyphen or underscore.",
        )
    info = get_workspace_manager().get_workspace(workspace_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return info


def _enforce_workspace_access(
    request: Request,
    workspace_id: Optional[str] = None,
    admin_only: bool = False,
) -> None:
    """Enforce tenant isolation and role-based access control with Fail-Closed behavior.

    - Master Admin (is_master=True): Full access.
    - Admin-only operations (list_workspaces, update_plan):
        Strictly requires Master Admin. Standard tenant keys are rejected with 403 Forbidden.
        Unauthenticated calls are rejected with 401 Unauthorized (Fail-Closed).
    - Workspace-scoped operations:
        Caller must authenticate via API key. Spoofed headers provide zero access.
        Unauthenticated calls are rejected with 401 Unauthorized.
        Caller authenticated_workspace_id must match target workspace_id. Cross-tenant access is rejected with 403 Forbidden.
    """
    is_master = getattr(request.state, "is_master", False)
    auth_ws = getattr(request.state, "authenticated_workspace_id", None)

    # 1. Master admin is always authorized
    if is_master:
        return

    # 2. Admin-only operations (Fail Closed)
    if admin_only:
        if auth_ws:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Admin privileges required for this operation.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Master admin API key required.",
        )

    # 3. Workspace-scoped operations
    if workspace_id:
        if not is_safe_identifier(workspace_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid workspace ID format: '{workspace_id}'.",
            )
        if not auth_ws:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Valid workspace API key required to access workspace resources.",
            )
        if auth_ws != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You do not have permission to access workspace '{workspace_id}'.",
            )


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------

@router.post("/", summary="Create workspace", status_code=201)
def create_workspace(req: WorkspaceCreate) -> dict[str, Any]:
    """
    Create a new workspace and return its initial API key.

    **Important:** The returned `api_key` is shown only once. Store it securely.
    """
    wm = get_workspace_manager()
    info, raw_key = wm.create_workspace(req)
    return {
        "success": True,
        "workspace": info.model_dump(),
        "api_key": raw_key,
        "warning": "This API key will not be shown again. Store it securely.",
    }


@router.get("/", summary="List workspaces")
def list_workspaces(request: Request) -> dict[str, Any]:
    """Return all workspaces (API keys are masked). Requires Admin privileges."""
    _enforce_workspace_access(request, admin_only=True)
    workspaces = get_workspace_manager().list_workspaces()
    return {"success": True, "workspaces": [w.model_dump() for w in workspaces]}


@router.get("/plans", summary="List available plans")
def list_plans() -> dict[str, Any]:
    """Return available service plans and their quota configurations."""
    return {"success": True, "plans": [p.model_dump() for p in get_all_plans()]}


@router.get("/{workspace_id}", summary="Get workspace info")
def get_workspace(request: Request, workspace_id: str = Path(...)) -> dict[str, Any]:
    _enforce_workspace_access(request, workspace_id=workspace_id)
    info = _require_workspace(workspace_id)
    return {"success": True, "workspace": info.model_dump()}


@router.delete("/{workspace_id}", summary="Delete workspace")
def delete_workspace(request: Request, workspace_id: str = Path(...)) -> dict[str, Any]:
    """
    Permanently delete a workspace and ALL associated data.

    This includes jobs, artifacts, chunks, manifests, usage logs, and secrets.
    This action is irreversible.
    """
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    # Also clean up secrets
    get_secrets_manager().delete_all_secrets(workspace_id)
    deleted = get_workspace_manager().delete_workspace(workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return {"success": True, "message": f"Workspace '{workspace_id}' and all associated data have been deleted."}


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------

@router.post("/{workspace_id}/rotate-key", summary="Rotate workspace API key")
def rotate_api_key(request: Request, workspace_id: str = Path(...)) -> dict[str, Any]:
    """
    Generate a new API key for the workspace.

    The old key is immediately invalidated. The new key is shown only once.
    """
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    result = get_workspace_manager().rotate_api_key(workspace_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    info, new_key = result
    response = WorkspaceKeyRotateResponse(
        workspace_id=workspace_id,
        new_api_key=new_key,
        rotated_at=info.updated_at,
    )
    return {
        "success": True,
        "data": response.model_dump(),
        "warning": "The old API key has been invalidated. Store the new key securely.",
    }


# ---------------------------------------------------------------------------
# Plan Management
# ---------------------------------------------------------------------------

class PlanUpdateRequest(BaseModel):
    plan: str


@router.put("/{workspace_id}/plan", summary="Change workspace plan")
def update_plan(request: Request, workspace_id: str = Path(...), body: PlanUpdateRequest = Body(...)) -> dict[str, Any]:
    """Change the workspace plan. Requires Master Admin privileges."""
    _enforce_workspace_access(request, workspace_id=workspace_id, admin_only=True)
    _require_workspace(workspace_id)
    updated = get_workspace_manager().update_plan(workspace_id, body.plan)
    if updated is None:
        raise HTTPException(status_code=404)
    return {"success": True, "workspace": updated.model_dump()}


# ---------------------------------------------------------------------------
# Quota & Usage
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/quota", summary="Get quota status")
def get_quota(request: Request, workspace_id: str = Path(...)) -> dict[str, Any]:
    """Return current month's quota usage and remaining allowance."""
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    status_data: QuotaStatus = get_quota_enforcer().get_quota_status(workspace_id)
    return {"success": True, "quota": status_data.model_dump()}


@router.get("/{workspace_id}/usage", summary="Get usage report")
def get_usage(
    request: Request,
    workspace_id: str = Path(...),
    months: int = Query(default=3, ge=1, le=12, description="Number of past months to include"),
) -> dict[str, Any]:
    """Return detailed usage report for the workspace."""
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    report: UsageReport = get_usage_meter().get_report(workspace_id, months=months)
    return {"success": True, "usage": report.model_dump()}


# ---------------------------------------------------------------------------
# Secrets (BYOK)
# ---------------------------------------------------------------------------

class SecretSetRequest(BaseModel):
    key_name: str
    value: str


@router.get("/{workspace_id}/secrets", summary="List secrets (masked)")
def list_secrets(request: Request, workspace_id: str = Path(...)) -> dict[str, Any]:
    """List configured secrets with masked values. Never returns raw keys."""
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    secrets = get_secrets_manager().list_secrets(workspace_id)
    return {"success": True, "secrets": secrets}


@router.post("/{workspace_id}/secrets", summary="Set a secret (BYOK)", status_code=201)
def set_secret(request: Request, workspace_id: str = Path(...), body: SecretSetRequest = Body(...)) -> dict[str, Any]:
    """
    Store an encrypted secret for the workspace (e.g., your own OpenAI API key).

    The secret value is never returned in API responses. Only masked values are shown.
    """
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    clean_key_name = body.key_name.strip()
    if not clean_key_name:
        raise HTTPException(status_code=422, detail="key_name must not be empty.")
    if not is_safe_identifier(clean_key_name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid secret key name format.")
    try:
        get_secrets_manager().set_secret(workspace_id, body.key_name.strip(), body.value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "success": True,
        "key_name": body.key_name.strip(),
        "message": "Secret stored securely. The value will not be retrievable in plaintext via API.",
    }


@router.delete("/{workspace_id}/secrets/{key_name}", summary="Delete a secret")
def delete_secret(request: Request, workspace_id: str = Path(...), key_name: str = Path(...)) -> dict[str, Any]:
    if not is_safe_identifier(key_name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid secret key name format.")
    _enforce_workspace_access(request, workspace_id=workspace_id)
    _require_workspace(workspace_id)
    deleted = get_secrets_manager().delete_secret(workspace_id, key_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Secret '{key_name}' not found for this workspace.")
    return {"success": True, "message": f"Secret '{key_name}' has been deleted."}
