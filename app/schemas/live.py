"""Pydantic schemas for Nexora Live Real-Time Extraction and Change Tracking."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class DiscoveredDynamicField(BaseModel):
    """An automatically discovered dynamic or mutating field on a target webpage."""
    name: str = Field(..., description="Human-friendly inferred field name (e.g. 'bitcoin_price', 'change_24h').")
    selector: str = Field(..., description="Stable CSS selector identified for this dynamic element.")
    sample_value: str = Field(..., description="Observed text or numeric value during inspection.")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Detection confidence score.")
    field_type: str = Field(default="price", description="Inferred category: 'price', 'percentage', 'crypto', 'number', 'text'.")
    mutation_detected: bool = Field(default=False, description="Whether an active DOM text mutation was observed during observation window.")


class LiveWatcherCreateRequest(BaseModel):
    """Request payload to create a new live data watcher."""
    url: str = Field(..., description="Target webpage or API endpoint URL to monitor in real-time.")
    name: Optional[str] = Field(None, description="Human-friendly label for this watcher.")
    selectors: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Dictionary mapping field names to CSS selectors. If empty in auto mode, selectors are auto-discovered."
    )
    interval_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=3600.0,
        description="Polling frequency in seconds (minimum 0.1s)."
    )
    engine: Literal["auto", "fast_http", "playwright"] = Field(
        default="auto",
        description="Extraction engine strategy: 'auto', 'fast_http', 'playwright'."
    )
    single_trigger: bool = Field(
        default=False,
        description="If True, automatically turns OFF the watcher after the first detected change and data replacement."
    )
    turn_on: bool = Field(
        default=True,
        description="Whether to immediately turn ON the watcher upon creation."
    )
    mode: Literal["manual", "auto"] = Field(
        default="manual",
        description="Watcher configuration mode: 'manual' (explicit selectors) or 'auto' (autonomous dynamic field discovery)."
    )
    observation_seconds: float = Field(
        default=3.0,
        ge=0.5,
        le=60.0,
        description="Observation window in seconds for autonomous dynamic field detection."
    )
    webhook_url: Optional[str] = Field(
        None,
        description="Optional HTTP webhook URL to POST change events to in real-time."
    )
    headers: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Optional custom HTTP request headers."
    )


class ChangeEvent(BaseModel):
    """Event payload emitted when a live data change is detected."""
    watcher_id: str
    timestamp: str
    previous_data: Optional[Dict[str, Any]] = None
    latest_data: Dict[str, Any]
    diff: Dict[str, Any]
    change_count: int


class LiveWatcherResponse(BaseModel):
    """Detailed live watcher state and latest snapshot."""
    id: str
    name: str
    url: str
    status: Literal["active", "paused", "stopped", "triggered", "error"]
    selectors: Dict[str, str] = Field(default_factory=dict)
    interval_seconds: float
    engine: str
    single_trigger: bool
    mode: str = "manual"
    discovered_fields: List[DiscoveredDynamicField] = Field(default_factory=list)
    last_checked_at: Optional[str] = None
    last_changed_at: Optional[str] = None
    change_count: int = 0
    latest_data: Optional[Dict[str, Any]] = None
    created_at: str
    error_message: Optional[str] = None


class LiveWatcherListResponse(BaseModel):
    """List of all registered live watchers."""
    watchers: List[LiveWatcherResponse]
    total_active: int
    total_watchers: int


class LiveActionResponse(BaseModel):
    """Response returned upon lifecycle action (turn-on, turn-off, pause)."""
    watcher_id: str
    status: str
    message: str
    latest_data: Optional[Dict[str, Any]] = None


class DynamicFieldDetectionRequest(BaseModel):
    """Request payload to scan a target webpage and auto-detect mutating/dynamic fields."""
    url: str = Field(..., description="Target webpage URL to inspect for dynamic content.")
    observation_seconds: float = Field(default=3.0, ge=0.5, le=60.0, description="Observation time window in seconds.")
    engine: Literal["auto", "fast_http", "playwright"] = Field(default="auto", description="Inspection engine strategy.")
    headers: Optional[Dict[str, str]] = Field(default_factory=dict, description="Custom headers.")


class DynamicFieldDetectionResponse(BaseModel):
    """Result of autonomous dynamic field discovery."""
    url: str
    observation_seconds: float
    detected_fields: List[DiscoveredDynamicField]
    recommended_selectors: Dict[str, str]
    summary: str
