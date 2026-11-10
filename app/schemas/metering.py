"""Usage metering and event tracking schemas for Phase 5."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class UsageEvent(BaseModel):
    """A single metered usage event recorded for a workspace."""
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    workspace_id: str
    event_type: str  # pages_crawled, files_processed, chunks_created, embeddings_generated, llm_tokens, storage_bytes, job_count
    quantity: float = Field(ge=0)
    job_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str  # ISO 8601


class MonthlyUsageSummary(BaseModel):
    """Aggregated monthly usage per workspace."""
    workspace_id: str
    period: str  # "YYYY-MM"
    pages_crawled: int = 0
    files_processed: int = 0
    chunks_created: int = 0
    embeddings_generated: int = 0
    llm_tokens_used: int = 0
    storage_bytes: int = 0
    job_count: int = 0
    events_count: int = 0

    @property
    def llm_tokens(self) -> int:
        return self.llm_tokens_used


class UsageReport(BaseModel):
    """Full usage report returned to API consumers."""
    workspace_id: str
    current_period: MonthlyUsageSummary
    history: list[MonthlyUsageSummary] = Field(default_factory=list)
