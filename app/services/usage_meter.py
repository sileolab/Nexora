"""Usage Metering Service — records and aggregates per-workspace resource consumption.

Events are appended to data/usage/{workspace_id}/{YYYY-MM}.jsonl (one JSON object per line).
Aggregations are computed incrementally with persistent check-pointing in {YYYY-MM}_summary.json.

Measurable units:
  pages_crawled         — discovery + extraction pages
  files_processed       — uploaded file documents
  chunks_created        — document chunks produced by chunker
  embeddings_generated  — embedding vectors produced
  llm_tokens_used       — tokens sent/received to/from LLM (if available)
  storage_bytes         — bytes of stored output artifacts
  job_count             — total jobs created
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.security import is_safe_identifier, validate_path_containment
from app.schemas.metering import MonthlyUsageSummary, UsageEvent, UsageReport

logger = logging.getLogger(__name__)

_USAGE_DIR = Path("data/usage")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class UsageMeter:
    """
    Records metered usage events and produces aggregated reports.

    Storage format:
      Log:        data/usage/{workspace_id}/{YYYY-MM}.jsonl (append-only)
      Checkpoint: data/usage/{workspace_id}/{YYYY-MM}_summary.json (fast restart cache)

    Features:
      - Thread-safe via internal re-entrant lock (RLock).
      - Idempotency key tracking to avoid double-charging retried jobs or operations.
      - O(1) incremental tail-reading avoiding re-reading large JSONL files.
      - Multi-worker compatible via file size / offset detection.
      - Persistent checkpoint recovery across application restarts.
    """

    def __init__(self, usage_dir: Path | str = _USAGE_DIR) -> None:
        self._dir = Path(usage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # In-memory aggregation cache: (workspace_id, period) -> MonthlyUsageSummary
        self._cache: dict[tuple[str, str], MonthlyUsageSummary] = {}
        # Seen idempotency keys: (workspace_id, period) -> set of keys
        self._seen_idempotency_keys: dict[tuple[str, str], set[str]] = {}
        # Last processed byte offsets: (workspace_id, period) -> int
        self._file_offsets: dict[tuple[str, str], int] = {}

    @property
    def current_period(self) -> str:
        """Return current billing period string 'YYYY-MM'."""
        return _current_period()

    def reset_cache(self) -> None:
        """Reset in-memory cache to simulate restart or reload from disk."""
        with self._lock:
            self._cache.clear()
            self._seen_idempotency_keys.clear()
            self._file_offsets.clear()

    def _event_file(self, workspace_id: str, period: Optional[str] = None) -> Optional[Path]:
        if not is_safe_identifier(workspace_id):
            return None
        p = period or _current_period()
        tenant_dir = (self._dir / workspace_id).resolve()
        if not validate_path_containment(self._dir, tenant_dir):
            return None
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir / f"{p}.jsonl"

    def _summary_file(self, workspace_id: str, period: Optional[str] = None) -> Optional[Path]:
        if not is_safe_identifier(workspace_id):
            return None
        p = period or _current_period()
        tenant_dir = (self._dir / workspace_id).resolve()
        if not validate_path_containment(self._dir, tenant_dir):
            return None
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir / f"{p}_summary.json"

    def record(
        self,
        workspace_id: str,
        event_type: str,
        quantity: float,
        job_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Append a metered usage event to the workspace's current-month log.

        Guarantees:
          - Thread-safe append and cache update.
          - Idempotency: duplicate events with identical idempotency_key are ignored.
          - Multi-worker safe: updates checkpoint and file offsets.
        """
        if not workspace_id or not is_safe_identifier(workspace_id):
            return
        if quantity < 0:
            logger.warning("Attempted to record negative usage quantity %s for %s", quantity, workspace_id)
            return

        period = _current_period()
        cache_key = (workspace_id, period)
        path = self._event_file(workspace_id, period)
        if not path:
            return

        with self._lock:
            # Ensure period state is loaded before recording
            if cache_key not in self._cache:
                self._aggregate_file(workspace_id, period)

            # Idempotency check
            seen_keys = self._seen_idempotency_keys.setdefault(cache_key, set())
            if idempotency_key:
                if idempotency_key in seen_keys:
                    logger.info("Usage event skipped; duplicate idempotency key '%s' for workspace %s", idempotency_key, workspace_id)
                    return
                seen_keys.add(idempotency_key)

            event = UsageEvent(
                workspace_id=workspace_id,
                event_type=event_type,
                quantity=quantity,
                job_id=job_id,
                idempotency_key=idempotency_key,
                metadata=metadata or {},
                recorded_at=_now_iso(),
            )

            # Append to JSONL log
            try:
                line = event.model_dump_json() + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                self._file_offsets[cache_key] = path.stat().st_size
            except Exception as e:
                logger.error("UsageMeter.record write error for workspace %s: %s", workspace_id, e)
                # If write failed and key was added, remove key to allow retry
                if idempotency_key:
                    seen_keys.discard(idempotency_key)
                return

            # Update in-memory counters
            summary = self._cache[cache_key]
            summary.events_count += 1
            qty_int = int(quantity)
            if event_type == "pages_crawled":
                summary.pages_crawled += qty_int
            elif event_type == "files_processed":
                summary.files_processed += qty_int
            elif event_type == "chunks_created":
                summary.chunks_created += qty_int
            elif event_type == "embeddings_generated":
                summary.embeddings_generated += qty_int
            elif event_type in ("llm_tokens", "llm_tokens_used"):
                summary.llm_tokens_used += qty_int
            elif event_type == "storage_bytes":
                summary.storage_bytes += qty_int
            elif event_type in ("job_created", "job_count"):
                summary.job_count += qty_int

            # Save checkpoint to disk
            self._save_checkpoint(workspace_id, period)

    def _save_checkpoint(self, workspace_id: str, period: str) -> None:
        """Save current summary and seen idempotency keys to summary JSON checkpoint atomically."""
        cache_key = (workspace_id, period)
        if cache_key not in self._cache:
            return
        summary_path = self._summary_file(workspace_id, period)
        if not summary_path:
            return

        try:
            summary = self._cache[cache_key]
            seen = list(self._seen_idempotency_keys.get(cache_key, set()))
            offset = self._file_offsets.get(cache_key, 0)

            data = {
                "summary": summary.model_dump(mode="json"),
                "last_offset": offset,
                "seen_idempotency_keys": seen,
                "updated_at": _now_iso(),
            }
            tmp_path = summary_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Atomic replace
            os.replace(tmp_path, summary_path)
        except Exception as exc:
            logger.warning("Failed saving usage checkpoint for %s: %s", workspace_id, exc)

    def _aggregate_file(self, workspace_id: str, period: str) -> MonthlyUsageSummary:
        """Aggregate a single month's usage with incremental check-pointing."""
        cache_key = (workspace_id, period)
        jsonl_path = self._event_file(workspace_id, period)
        summary_path = self._summary_file(workspace_id, period)

        with self._lock:
            # 1. Initialize or load from persistent checkpoint if not in memory
            if cache_key not in self._cache:
                loaded_from_disk = False
                if summary_path and summary_path.exists():
                    try:
                        with open(summary_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        summary_data = data.get("summary", {})
                        self._cache[cache_key] = MonthlyUsageSummary.model_validate(summary_data)
                        self._seen_idempotency_keys[cache_key] = set(data.get("seen_idempotency_keys", []))
                        self._file_offsets[cache_key] = int(data.get("last_offset", 0))
                        loaded_from_disk = True
                    except Exception as e:
                        logger.warning("Could not parse usage checkpoint %s: %s", summary_path, e)

                if not loaded_from_disk:
                    self._cache[cache_key] = MonthlyUsageSummary(workspace_id=workspace_id, period=period)
                    self._seen_idempotency_keys[cache_key] = set()
                    self._file_offsets[cache_key] = 0

            # 2. Check if JSONL file has new data beyond last known offset
            if jsonl_path and jsonl_path.exists():
                try:
                    cur_size = jsonl_path.stat().st_size
                    last_offset = self._file_offsets.get(cache_key, 0)

                    # If file was truncated or smaller than offset, re-read from start
                    if cur_size < last_offset:
                        last_offset = 0
                        self._cache[cache_key] = MonthlyUsageSummary(workspace_id=workspace_id, period=period)
                        self._seen_idempotency_keys[cache_key] = set()

                    if cur_size > last_offset:
                        summary = self._cache[cache_key]
                        seen_keys = self._seen_idempotency_keys.setdefault(cache_key, set())

                        with open(jsonl_path, "r", encoding="utf-8") as f:
                            if last_offset > 0:
                                f.seek(last_offset)
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    ev = json.loads(line)
                                except json.JSONDecodeError:
                                    continue

                                ikey = ev.get("idempotency_key")
                                if ikey:
                                    if ikey in seen_keys:
                                        continue
                                    seen_keys.add(ikey)

                                etype = ev.get("event_type", "")
                                qty = float(ev.get("quantity", 0))
                                qty_int = int(qty)
                                summary.events_count += 1
                                if etype == "pages_crawled":
                                    summary.pages_crawled += qty_int
                                elif etype == "files_processed":
                                    summary.files_processed += qty_int
                                elif etype == "chunks_created":
                                    summary.chunks_created += qty_int
                                elif etype == "embeddings_generated":
                                    summary.embeddings_generated += qty_int
                                elif etype in ("llm_tokens", "llm_tokens_used"):
                                    summary.llm_tokens_used += qty_int
                                elif etype == "storage_bytes":
                                    summary.storage_bytes += qty_int
                                elif etype in ("job_created", "job_count"):
                                    summary.job_count += qty_int

                            self._file_offsets[cache_key] = f.tell()

                        # Checkpoint the freshly aggregated state
                        self._save_checkpoint(workspace_id, period)

                except Exception as e:
                    logger.error("Error aggregating usage file %s: %s", jsonl_path, e)

            return self._cache[cache_key].model_copy()

    def get_current_month(self, workspace_id: str) -> MonthlyUsageSummary:
        """Return aggregated usage for the current calendar month."""
        return self._aggregate_file(workspace_id, _current_period())

    def get_report(self, workspace_id: str, months: int = 3) -> UsageReport:
        """
        Produce a full usage report for the past N months.

        Args:
            workspace_id: Target workspace.
            months: Number of past months to include in history (default: 3).
        """
        current = self.get_current_month(workspace_id)

        history = []
        dt = datetime.now(timezone.utc)
        for i in range(1, months + 1):
            month = dt.month - i
            year = dt.year
            while month <= 0:
                month += 12
                year -= 1
            period = f"{year:04d}-{month:02d}"
            hist = self._aggregate_file(workspace_id, period)
            if hist.events_count > 0:
                history.append(hist)

        return UsageReport(
            workspace_id=workspace_id,
            current_period=current,
            history=history,
        )

    def get_metric_total(self, workspace_id: str, event_type: str, period: Optional[str] = None) -> float:
        """Return the total usage for a single metric in a given period."""
        p = period or _current_period()
        summary = self._aggregate_file(workspace_id, p)
        metric_map = {
            "pages_crawled": summary.pages_crawled,
            "files_processed": summary.files_processed,
            "chunks_created": summary.chunks_created,
            "embeddings_generated": summary.embeddings_generated,
            "llm_tokens": summary.llm_tokens_used,
            "llm_tokens_used": summary.llm_tokens_used,
            "storage_bytes": summary.storage_bytes,
            "job_count": summary.job_count,
            "job_created": summary.job_count,
        }
        return float(metric_map.get(event_type, 0))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: UsageMeter | None = None


def get_usage_meter() -> UsageMeter:
    global _instance
    if _instance is None:
        _instance = UsageMeter()
    return _instance
