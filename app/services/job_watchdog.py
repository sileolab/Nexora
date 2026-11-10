"""Job Watchdog — detects and remediates stuck or stale jobs.

A stuck job is one that has been in RUNNING state for longer than the configured
`max_job_runtime_minutes` without making progress. The watchdog auto-cancels
such jobs and records the reason.

Job state persistence:
  Jobs are also serialized to data/jobs/{workspace_id}/{job_id}.json so that
  state survives server restarts for tenant-scoped jobs.

Artifact cleanup:
  Old output directories beyond the plan's max_history_days are removed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from app.core.security import is_safe_identifier, validate_path_containment

logger = logging.getLogger(__name__)

_JOBS_DIR = Path("data/jobs")
_OUTPUT_DIR = Path("output")


class JobWatchdog:
    """
    Monitors in-memory jobs for stuck/stale conditions.

    Designed to be called periodically (e.g. every 60 seconds) from a background
    asyncio task attached to the JobManager.

    Does NOT require a new external dependency — uses the existing JobManager.
    """

    def __init__(self, max_runtime_minutes: int = 60) -> None:
        self.max_runtime_minutes = max_runtime_minutes
        self._jobs_dir = _JOBS_DIR
        self._jobs_dir.mkdir(parents=True, exist_ok=True)

    def check_stuck_jobs(self, manager: Any) -> list[str]:
        """
        Identify and cancel jobs that have been running for too long.

        Args:
            manager: JobManager instance.

        Returns:
            List of job_ids that were cancelled as stuck.
        """
        from app.jobs.models import JobState

        cancelled: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.max_runtime_minutes)

        for job in manager.list_jobs():
            state = getattr(job, "state", None)
            if hasattr(state, "value"):
                state_val = state.value
            else:
                state_val = str(state) if state else ""

            if state_val != "running":
                continue

            started_at = getattr(job, "started_at", None)
            if started_at is None:
                continue

            # Normalize timezone
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)

            if started_at < cutoff:
                job_id = getattr(job, "job_id", None)
                if job_id:
                    try:
                        manager.cancel_job(job_id)
                        job.add_error(
                            f"Auto-cancelled by watchdog: job ran for >"
                            f"{self.max_runtime_minutes} minutes without completing."
                        )
                        cancelled.append(job_id)
                        logger.warning("Watchdog cancelled stuck job %s", job_id)
                    except Exception as e:
                        logger.error("Watchdog failed to cancel job %s: %s", job_id, e)

        return cancelled

    def cleanup_old_artifacts(self, max_history_days: int = 30) -> int:
        """
        Remove output artifact directories older than max_history_days.

        Returns count of directories removed.
        """
        removed = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_history_days)

        if not _OUTPUT_DIR.exists():
            return 0

        for tenant_dir in _OUTPUT_DIR.iterdir():
            if not tenant_dir.is_dir():
                continue
            for job_dir in tenant_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                # Check directory modification time
                try:
                    mtime = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        import shutil
                        shutil.rmtree(job_dir, ignore_errors=True)
                        removed += 1
                        logger.info("Watchdog removed stale artifact dir %s", job_dir)
                except Exception as e:
                    logger.warning("Error checking artifact dir %s: %s", job_dir, e)

        return removed

    # ------------------------------------------------------------------
    # Job State Persistence
    # ------------------------------------------------------------------

    def persist_job(self, workspace_id: str, job: Any) -> None:
        """
        Serialize and write a job's state to disk for crash recovery.

        Called after significant state transitions (created, completed, failed).
        """
        if not workspace_id or not is_safe_identifier(workspace_id) or not job:
            return
        job_id = getattr(job, "job_id", None)
        if not job_id or not is_safe_identifier(str(job_id)):
            return
        tenant_jobs_dir = (self._jobs_dir / workspace_id).resolve()
        if not validate_path_containment(self._jobs_dir, tenant_jobs_dir):
            return
        tenant_jobs_dir.mkdir(parents=True, exist_ok=True)
        path = tenant_jobs_dir / f"{job_id}.json"
        try:
            data = job.model_dump(mode="json")
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            tmp.replace(path)
        except Exception as e:
            logger.error("Failed to persist job %s: %s", job_id, e)

    def restore_jobs(self, workspace_id: str) -> list[dict]:
        """
        Load persisted job states from disk for a workspace.

        Returns list of raw job dicts for reinstatement into JobManager.
        """
        if not is_safe_identifier(workspace_id):
            return []
        tenant_dir = (self._jobs_dir / workspace_id).resolve()
        if not validate_path_containment(self._jobs_dir, tenant_dir):
            return []
        if not tenant_dir.exists():
            return []
        restored = []
        for p in tenant_dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    restored.append(json.load(f))
            except Exception as e:
                logger.warning("Could not restore job from %s: %s", p, e)
        return restored


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: JobWatchdog | None = None


def get_job_watchdog() -> JobWatchdog:
    global _instance
    if _instance is None:
        _instance = JobWatchdog()
    return _instance
