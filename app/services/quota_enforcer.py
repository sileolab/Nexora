"""Quota Enforcer — validates resource consumption against workspace plan limits.

Checks current-month usage against plan maximums before allowing expensive operations.
Hard limits: block the operation and return HTTP 429.
Soft limits: allow but warn (near_limit flag in response).

Usage metering is done separately via UsageMeter; this service reads the totals and manages in-flight reservations.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.schemas.workspace import PlanConfig, QuotaStatus
from app.services.usage_meter import get_usage_meter
from app.services.workspace_manager import get_plan, get_workspace_manager

logger = logging.getLogger(__name__)

_WARN_THRESHOLD = 0.80  # 80% -> near_limit warning


class QuotaEnforcer:
    """
    Checks and enforces resource quotas for a workspace.

    Provides atomic reservation of in-flight quota to prevent race conditions.
    Methods raise ValueError when a hard limit is exceeded.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._reserved_pages: dict[str, int] = {}
        self._reserved_chunks: dict[str, int] = {}
        self._reserved_embeddings: dict[str, int] = {}

    def reset(self) -> None:
        """Clear all in-flight quota reservations (for tests and clean teardown)."""
        with self._lock:
            self._reserved_pages.clear()
            self._reserved_chunks.clear()
            self._reserved_embeddings.clear()

    def _get_plan(self, workspace_id: str) -> Optional[PlanConfig]:
        wm = get_workspace_manager()
        info = wm.get_workspace(workspace_id)
        if info is None:
            return None
        return get_plan(info.plan)

    # ------------------------------------------------------------------
    # Atomic Page Reservation & Checking
    # ------------------------------------------------------------------

    def reserve_pages(self, workspace_id: str, count: int) -> bool:
        """Atomically check and reserve pages quota for an in-flight job."""
        if count <= 0:
            return True
        plan = self._get_plan(workspace_id)
        if plan is None:
            return True
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "pages_crawled")
            reserved = self._reserved_pages.get(workspace_id, 0)
            if current + reserved + count > plan.max_pages_per_month:
                return False
            self._reserved_pages[workspace_id] = reserved + count
            return True

    def release_pages(self, workspace_id: str, count: int) -> None:
        """Release previously reserved in-flight pages quota."""
        if count <= 0:
            return
        with self._lock:
            current_reserved = self._reserved_pages.get(workspace_id, 0)
            self._reserved_pages[workspace_id] = max(0, current_reserved - count)

    def check_pages(self, workspace_id: str, count: int = 1) -> None:
        """
        Raise ValueError if adding `count` pages would exceed the monthly page quota.
        Call before starting a crawl/extraction job.
        """
        plan = self._get_plan(workspace_id)
        if plan is None:
            return  # No workspace — let auth layer handle it
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "pages_crawled")
            reserved = self._reserved_pages.get(workspace_id, 0)
            if current + reserved + count > plan.max_pages_per_month:
                raise ValueError(
                    f"Page quota exceeded for workspace {workspace_id}: "
                    f"{int(current + reserved)} used/reserved / {plan.max_pages_per_month} allowed this month."
                )

    # ------------------------------------------------------------------
    # Atomic Chunk Reservation & Checking
    # ------------------------------------------------------------------

    def reserve_chunks(self, workspace_id: str, count: int) -> bool:
        """Atomically check and reserve chunk creation quota."""
        if count <= 0:
            return True
        plan = self._get_plan(workspace_id)
        if plan is None:
            return True
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "chunks_created")
            reserved = self._reserved_chunks.get(workspace_id, 0)
            if current + reserved + count > plan.max_chunks_per_month:
                return False
            self._reserved_chunks[workspace_id] = reserved + count
            return True

    def release_chunks(self, workspace_id: str, count: int) -> None:
        """Release previously reserved in-flight chunk quota."""
        if count <= 0:
            return
        with self._lock:
            current_reserved = self._reserved_chunks.get(workspace_id, 0)
            self._reserved_chunks[workspace_id] = max(0, current_reserved - count)

    def check_chunks(self, workspace_id: str, count: int) -> None:
        """Raise ValueError if creating `count` chunks would exceed monthly limit."""
        plan = self._get_plan(workspace_id)
        if plan is None:
            return
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "chunks_created")
            reserved = self._reserved_chunks.get(workspace_id, 0)
            if current + reserved + count > plan.max_chunks_per_month:
                raise ValueError(
                    f"Chunk quota exceeded for workspace {workspace_id}: "
                    f"{int(current + reserved)} used/reserved / {plan.max_chunks_per_month} allowed this month."
                )

    # ------------------------------------------------------------------
    # Atomic Embedding Reservation & Checking
    # ------------------------------------------------------------------

    def reserve_embeddings(self, workspace_id: str, count: int) -> bool:
        """Atomically check and reserve embedding generation quota."""
        if count <= 0:
            return True
        plan = self._get_plan(workspace_id)
        if plan is None:
            return True
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "embeddings_generated")
            reserved = self._reserved_embeddings.get(workspace_id, 0)
            if current + reserved + count > plan.max_embeddings_per_month:
                return False
            self._reserved_embeddings[workspace_id] = reserved + count
            return True

    def release_embeddings(self, workspace_id: str, count: int) -> None:
        """Release previously reserved in-flight embedding quota."""
        if count <= 0:
            return
        with self._lock:
            current_reserved = self._reserved_embeddings.get(workspace_id, 0)
            self._reserved_embeddings[workspace_id] = max(0, current_reserved - count)

    def check_embeddings(self, workspace_id: str, count: int) -> None:
        """Raise ValueError if creating `count` embeddings would exceed monthly limit."""
        plan = self._get_plan(workspace_id)
        if plan is None:
            return
        with self._lock:
            meter = get_usage_meter()
            current = meter.get_metric_total(workspace_id, "embeddings_generated")
            reserved = self._reserved_embeddings.get(workspace_id, 0)
            if current + reserved + count > plan.max_embeddings_per_month:
                raise ValueError(
                    f"Embedding quota exceeded for workspace {workspace_id}: "
                    f"{int(current + reserved)} used/reserved / {plan.max_embeddings_per_month} allowed this month."
                )

    # ------------------------------------------------------------------
    # File Size & Concurrency Checking
    # ------------------------------------------------------------------

    def check_file_size(self, workspace_id: str, file_bytes: int) -> None:
        """Raise ValueError if file size exceeds the plan's max_file_mb."""
        plan = self._get_plan(workspace_id)
        if plan is None:
            return
        max_bytes = int(plan.max_file_mb * 1024 * 1024)
        if file_bytes > max_bytes:
            raise ValueError(
                f"File size {file_bytes / 1024 / 1024:.1f} MB exceeds plan limit "
                f"of {plan.max_file_mb} MB for workspace {workspace_id}."
            )

    def check_concurrent_jobs(self, workspace_id: str, active_count: int) -> None:
        """Raise ValueError if active job count is at or above plan limit."""
        plan = self._get_plan(workspace_id)
        if plan is None:
            return
        if active_count >= plan.max_concurrent_jobs:
            raise ValueError(
                f"Concurrent job limit reached for workspace {workspace_id}: "
                f"{active_count} active / {plan.max_concurrent_jobs} allowed."
            )

    # ------------------------------------------------------------------
    # Status & Reporting
    # ------------------------------------------------------------------

    def get_quota_status(self, workspace_id: str) -> QuotaStatus:
        """Return current quota status for a workspace."""
        plan = self._get_plan(workspace_id)
        meter = get_usage_meter()
        usage = meter.get_current_month(workspace_id)
        from app.services.usage_meter import _current_period
        period = _current_period()

        if plan is None:
            return QuotaStatus(workspace_id=workspace_id, plan="unknown", period=period, metrics={})

        def _metric(used: int, limit: int, key: str) -> dict:
            remaining = max(0, limit - used)
            pct = (used / limit) if limit > 0 else 0.0
            return {
                "used": used,
                "limit": limit,
                "remaining": remaining,
                "pct_used": round(pct * 100, 1),
            }

        metrics = {
            "pages_crawled": _metric(usage.pages_crawled, plan.max_pages_per_month, "pages_crawled"),
            "files_processed": _metric(usage.files_processed, plan.max_pages_per_month, "files_processed"),
            "chunks_created": _metric(usage.chunks_created, plan.max_chunks_per_month, "chunks_created"),
            "embeddings_generated": _metric(usage.embeddings_generated, plan.max_embeddings_per_month, "embeddings_generated"),
        }

        over_limit = [k for k, v in metrics.items() if v["remaining"] == 0 and v["limit"] > 0]
        near_limit = [k for k, v in metrics.items() if _WARN_THRESHOLD <= v["pct_used"] / 100 < 1.0]

        return QuotaStatus(
            workspace_id=workspace_id,
            plan=plan.name,
            period=period,
            metrics=metrics,
            over_limit=over_limit,
            near_limit=near_limit,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: QuotaEnforcer | None = None


def get_quota_enforcer() -> QuotaEnforcer:
    global _instance
    if _instance is None:
        _instance = QuotaEnforcer()
    return _instance
