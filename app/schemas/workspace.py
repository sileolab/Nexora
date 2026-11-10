"""Workspace and SaaS-related Pydantic schemas for Phase 5."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Workspace Schemas
# ---------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    """Request body for creating a new workspace."""
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable workspace name.")
    plan: str = Field(default="trial", description="Plan identifier (trial / developer / professional).")
    description: Optional[str] = Field(default=None, max_length=512)


class WorkspaceInfo(BaseModel):
    """Workspace metadata returned by the API (never includes raw secrets)."""
    workspace_id: str
    name: str
    plan: str
    description: Optional[str]
    api_key_prefix: str = Field(description="First 8 chars of the workspace API key (for display).")
    created_at: str
    updated_at: str
    quota: dict[str, Any] = Field(default_factory=dict, description="Effective quota from plan.")
    usage_this_month: dict[str, Any] = Field(default_factory=dict)


class WorkspaceKeyRotateResponse(BaseModel):
    """Returned after key rotation — the new key shown only once."""
    workspace_id: str
    new_api_key: str = Field(description="New full API key. Store it securely; it will not be shown again.")
    rotated_at: str


# ---------------------------------------------------------------------------
# Plan Schemas
# ---------------------------------------------------------------------------

class PlanConfig(BaseModel):
    """Configuration of a service plan loaded from plans.json."""
    name: str
    display_name: str
    max_pages_per_month: int
    max_file_mb: float
    max_concurrent_jobs: int
    max_chunks_per_month: int
    max_embeddings_per_month: int
    max_workspaces: int = 1
    max_history_days: int = 30
    allow_byok: bool = True
    description: str = ""


# ---------------------------------------------------------------------------
# Quota Enforcement Schemas
# ---------------------------------------------------------------------------

class QuotaStatus(BaseModel):
    """Current quota usage and remaining allowance for a workspace."""
    workspace_id: str
    plan: str
    period: str  # "YYYY-MM"
    metrics: dict[str, dict[str, Any]] = Field(
        description="Per-metric: {used, limit, remaining, pct_used}"
    )
    over_limit: list[str] = Field(default_factory=list, description="Metrics that exceed their limit.")
    near_limit: list[str] = Field(default_factory=list, description="Metrics above 80% of limit.")
