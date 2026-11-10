"""In-memory job management service for Crawlbot.

Coordinates background execution of discovery and extraction tasks, manages
lifecycle states, supports real-time progress tracking, cancellation events,
and stores in-memory extracted document artifacts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.logging_config import get_logger
from app.core.security import is_safe_identifier, validate_path_containment
from app.jobs.models import JobInfo, JobState, JobType
from app.schemas.documents import ExtractedDocument, QualityStatus
from app.schemas.responses import DiscoveredPage, JobStatus
from app.services.crawler import CrawlerService, DiscoveryResult
from app.services.extractor import ContentExtractor
from app.services.quality_checker import QualityChecker

logger = get_logger(__name__)


class JobManager:
    """Manages creation, execution, cancellation, and retrieval of crawl and extraction jobs."""

    def __init__(self) -> None:
        """Initialize the in-memory JobManager state storage."""
        self._jobs: dict[str, JobInfo] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._documents: dict[str, list[ExtractedDocument]] = {}
        self._chunks: dict[str, list] = {}       # job_id -> list[DocumentChunk]
        self._rag_metadata: dict[str, list] = {}  # job_id -> list[dict]


    def create_discovery_job(self, config: dict[str, Any] | str, **kwargs) -> JobInfo:
        """Create and queue a new website discovery job.

        Args:
            config: Discovery configuration parameters or root URL string.
            **kwargs: Extra parameters (max_pages, tenant_id, auto_start, etc.).

        Returns:
            JobInfo instance for the newly registered discovery job.
        """
        if isinstance(config, str):
            job_config: dict[str, Any] = {"root_url": config}
        else:
            job_config = dict(config)
        job_config.update(kwargs)

        root_url = str(job_config.get("root_url", "")).strip()
        max_pages = int(job_config.get("max_pages", 500))
        tenant_id = job_config.get("tenant_id") or job_config.get("workspace_id")

        if tenant_id:
            try:
                from app.services.quota_enforcer import get_quota_enforcer
                qe = get_quota_enforcer()
                if not qe.reserve_pages(tenant_id, max_pages):
                    raise ValueError(f"Quota exceeded: Workspace '{tenant_id}' cannot crawl {max_pages} pages.")
            except ImportError:
                pass

        job = JobInfo(
            job_type=JobType.DISCOVERY,
            state=JobState.PENDING,
            total=max_pages,
            config=job_config,
            tenant_id=tenant_id,
        )

        self._jobs[job.job_id] = job
        self._cancel_events[job.job_id] = asyncio.Event()
        self._documents[job.job_id] = []

        logger.info("Created discovery job %s for root URL: %s", job.job_id, root_url)

        if tenant_id:
            try:
                from app.services.usage_meter import get_usage_meter
                get_usage_meter().record(
                    tenant_id,
                    "job_count",
                    1,
                    job_id=job.job_id,
                    idempotency_key=f"job_count:{job.job_id}",
                )
            except Exception as u_err:
                logger.warning("Could not record job_count for discovery %s: %s", job.job_id, u_err)
            try:
                from app.services.job_watchdog import get_job_watchdog
                get_job_watchdog().persist_job(tenant_id, job)
            except Exception:
                pass

        # Launch background task if loop running and auto_start requested
        try:
            loop = asyncio.get_running_loop()
            if job_config.get("auto_start", False):
                self._tasks[job.job_id] = loop.create_task(self.run_discovery(job.job_id))
        except RuntimeError:
            pass

        return job

    def create_extraction_job(
        self,
        urls: list[str],
        config: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> JobInfo:
        """Create and queue a new content extraction job.

        Args:
            urls: Target URLs to extract.
            config: Extraction options and configurations.
            **kwargs: Extra parameters (tenant_id, auto_start, etc.).

        Returns:
            JobInfo instance for the newly registered extraction job.
        """
        clean_urls = [str(u).strip() for u in urls if u and isinstance(u, str) and str(u).strip()]
        job_config = dict(config or {})
        job_config.update(kwargs)
        job_config["urls"] = clean_urls
        tenant_id = job_config.get("tenant_id") or job_config.get("workspace_id")

        if tenant_id:
            try:
                from app.services.quota_enforcer import get_quota_enforcer
                qe = get_quota_enforcer()
                if not qe.reserve_pages(tenant_id, len(clean_urls)):
                    raise ValueError(f"Quota exceeded: Workspace '{tenant_id}' cannot extract {len(clean_urls)} pages.")
            except ImportError:
                pass

        job = JobInfo(
            job_type=JobType.EXTRACTION,
            state=JobState.PENDING,
            total=len(clean_urls),
            config=job_config,
            tenant_id=tenant_id,
        )

        self._jobs[job.job_id] = job
        self._cancel_events[job.job_id] = asyncio.Event()
        self._documents[job.job_id] = []

        logger.info("Created extraction job %s for %d URLs", job.job_id, len(clean_urls))

        if tenant_id:
            try:
                from app.services.usage_meter import get_usage_meter
                get_usage_meter().record(
                    tenant_id,
                    "job_count",
                    1,
                    job_id=job.job_id,
                    idempotency_key=f"job_count:{job.job_id}",
                )
            except Exception as u_err:
                logger.warning("Could not record job_count for discovery %s: %s", job.job_id, u_err)
            try:
                from app.services.job_watchdog import get_job_watchdog
                get_job_watchdog().persist_job(tenant_id, job)
            except Exception:
                pass

        # Launch background task if loop running and auto_start requested
        try:
            loop = asyncio.get_running_loop()
            if job_config.get("auto_start", False):
                self._tasks[job.job_id] = loop.create_task(self.run_extraction(job.job_id))
        except RuntimeError:
            pass

        return job

    async def run_discovery(self, job_id: str) -> None:
        """Run discovery job in background.

        Args:
            job_id: ID of the discovery job to execute.
        """
        job = self._jobs.get(job_id)
        if not job:
            logger.error("Discovery job %s not found in manager", job_id)
            return

        cancel_event = self._cancel_events.setdefault(job_id, asyncio.Event())
        if cancel_event.is_set() or job.state == JobState.CANCELLED:
            job.mark_cancelled()
            return

        job.mark_running()
        logger.info("Running discovery job %s", job_id)

        async def on_progress(result: DiscoveryResult) -> None:
            """Update job state as progress updates are emitted by the crawler."""
            job.completed = len(result.crawled)
            job.failed = len(result.failed)
            # Update total to reflect discovered pages count or target ceiling
            job.total = max(len(result.discovered), 1)
            job.pages = [
                {
                    "url": url,
                    "title": meta.get("title"),
                    "status": meta.get("status", 0),
                    "depth": meta.get("depth", 0),
                    "source": meta.get("source", "crawl"),
                    "error": meta.get("error"),
                    "final_url": meta.get("final_url"),
                }
                for url, meta in result.discovered.items()
            ]

        try:
            root_url = str(job.config.get("root_url", "")).strip()
            max_depth = int(job.config.get("max_depth", 3))
            max_pages = int(job.config.get("max_pages", 500))
            request_timeout = float(job.config.get("request_timeout", 30.0))
            max_concurrency = int(job.config.get("max_concurrency", 5))
            delay = float(job.config.get("delay", job.config.get("delay_between_requests", 1.0)))
            allowed_domains = job.config.get("allowed_domains")
            include_patterns = job.config.get("include_patterns")
            exclude_patterns = job.config.get("exclude_patterns")
            allow_subdomains = bool(job.config.get("allow_subdomains", False))
            keep_query_params = bool(job.config.get("keep_query_params", False))
            use_sitemap = bool(job.config.get("use_sitemap", True))
            path_prefix = job.config.get("path_prefix")
            max_response_size = int(job.config.get("max_response_size", 10 * 1024 * 1024))

            crawler = CrawlerService(
                root_url=root_url,
                max_depth=max_depth,
                max_pages=max_pages,
                request_timeout=request_timeout,
                max_concurrency=max_concurrency,
                delay=delay,
                allowed_domains=allowed_domains,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                allow_subdomains=allow_subdomains,
                keep_query_params=keep_query_params,
                use_sitemap=use_sitemap,
                path_prefix=path_prefix,
                max_response_size=max_response_size,
                progress_callback=on_progress,
                cancel_event=cancel_event,
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                headers=job.config.get("headers"),
                enable_browser_fallback=bool(job.config.get("enable_browser_fallback", True)),
            )

            result = await crawler.discover()

            # Record final outcome
            job.completed = len(result.crawled)
            job.failed = len(result.failed)
            job.total = len(result.discovered)
            job.pages = [
                {
                    "url": url,
                    "title": meta.get("title"),
                    "status": meta.get("status", 0),
                    "depth": meta.get("depth", 0),
                    "source": meta.get("source", "crawl"),
                    "error": meta.get("error"),
                }
                for url, meta in result.discovered.items()
            ]

            if cancel_event.is_set():
                job.mark_cancelled()
                logger.info("Discovery job %s cancelled", job_id)
            else:
                job.mark_completed()
                logger.info("Discovery job %s completed successfully", job_id)

        except asyncio.CancelledError:
            logger.info("Discovery job %s cancelled via task cancellation", job_id)
            job.mark_cancelled()
        except Exception as exc:
            logger.error("Discovery job %s failed with exception: %s", job_id, exc, exc_info=True)
            job.mark_failed(str(exc))
        finally:
            if job and job.tenant_id:
                try:
                    from app.services.usage_meter import get_usage_meter
                    from app.services.quota_enforcer import get_quota_enforcer
                    from app.services.job_watchdog import get_job_watchdog
                    get_quota_enforcer().release_pages(job.tenant_id, job.total)
                    if job.completed > 0:
                        get_usage_meter().record(
                            job.tenant_id,
                            "pages_crawled",
                            job.completed,
                            job_id=job.job_id,
                            idempotency_key=f"pages_crawled:{job.job_id}",
                        )
                    get_job_watchdog().persist_job(job.tenant_id, job)
                except Exception as m_err:
                    logger.warning("Error recording discovery usage/persistence: %s", m_err)
            if job:
                try:
                    from app.services.anti_bot import get_antibot_manager
                    job.metrics = get_antibot_manager().metrics.get_metrics(job.job_id)
                except Exception as met_err:
                    logger.debug("Failed saving discovery job metrics: %s", met_err)
            self._cleanup_task(job_id)

    async def run_extraction(self, job_id: str) -> None:
        """Run extraction job in background.

        Args:
            job_id: ID of the extraction job to execute.
        """
        job = self._jobs.get(job_id)
        if not job:
            logger.error("Extraction job %s not found in manager", job_id)
            return

        cancel_event = self._cancel_events.setdefault(job_id, asyncio.Event())
        if cancel_event.is_set() or job.state == JobState.CANCELLED:
            job.mark_cancelled()
            return

        job.mark_running()
        logger.info("Running extraction job %s", job_id)

        urls: list[str] = job.config.get("urls", [])
        strategy = str(job.config.get("extraction_strategy", job.config.get("extractor", "auto")))
        crawl_mode = str(job.config.get("crawl_mode", "single_page"))
        render_mode = str(job.config.get("render_mode", "auto"))
        min_quality_score = int(job.config.get("min_quality_score", 40))
        max_concurrency = int(job.config.get("max_concurrency", 3))
        request_timeout = float(job.config.get("request_timeout", 30.0))
        loading_delay = float(job.config.get("loading_delay", 0.0))
        wait_for_selector = job.config.get("wait_for_selector")
        visible_only = bool(job.config.get("visible_only", False))
        min_word_count = int(job.config.get("min_word_count", 20))
        min_char_count = int(job.config.get("min_char_count", 100))

        job.total = len(urls)
        job.completed = 0
        job.failed = 0

        extractor = ContentExtractor(
            strategy=strategy,
            min_quality_score=min_quality_score,
            render_mode=render_mode,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
        )
        quality_checker = QualityChecker(
            min_word_count=min_word_count,
            min_char_count=min_char_count,
            min_quality_score=min_quality_score,
        )

        semaphore = asyncio.Semaphore(max_concurrency)
        lock = asyncio.Lock()

        async def process_single_url(url: str) -> None:
            if cancel_event.is_set():
                return

            async with semaphore:
                if cancel_event.is_set():
                    return

                try:
                    doc = await extractor.extract(
                        url,
                        timeout=request_timeout,
                        crawl_mode=crawl_mode,
                        loading_delay=loading_delay,
                        wait_for_selector=wait_for_selector,
                        visible_only=visible_only,
                    )
                    doc = quality_checker.check(doc)

                    async with lock:
                        self._documents.setdefault(job_id, []).append(doc)
                        job.documents.append(doc.model_dump(mode="json"))

                        if doc.quality_status in (QualityStatus.FAILED, QualityStatus.BLOCKED):
                            job.failed += 1
                        else:
                            job.completed += 1

                except Exception as exc:
                    logger.warning("Extraction failed for %s: %s", url, exc)
                    failed_doc = ExtractedDocument(
                        url=url,
                        extraction_method=strategy,
                        quality_status=QualityStatus.FAILED,
                        warnings=[f"Extraction error: {str(exc)}"],
                    )
                    async with lock:
                        self._documents.setdefault(job_id, []).append(failed_doc)
                        job.documents.append(failed_doc.model_dump(mode="json"))
                        job.failed += 1
                        job.add_error(f"{url}: {str(exc)}")

        try:
            tasks = [asyncio.create_task(process_single_url(url)) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

            if cancel_event.is_set():
                job.mark_cancelled()
                logger.info("Extraction job %s cancelled", job_id)
            else:
                job.mark_completed()
                logger.info("Extraction job %s completed successfully", job_id)
                # Auto-persist extracted documents to disk artifact for persistence across restarts
                try:
                    from app.services.export_service import ExportService
                    exporter = ExportService()
                    exporter.export_json(job_id, self._documents.get(job_id, []))
                except Exception as save_err:
                    logger.warning("Could not auto-save documents for job %s: %s", job_id, save_err)

        except asyncio.CancelledError:
            logger.info("Extraction job %s cancelled via task cancellation", job_id)
            job.mark_cancelled()
        except Exception as exc:
            logger.error("Extraction job %s failed with exception: %s", job_id, exc, exc_info=True)
            job.mark_failed(str(exc))
        finally:
            if job and job.tenant_id:
                try:
                    from app.services.usage_meter import get_usage_meter
                    from app.services.quota_enforcer import get_quota_enforcer
                    from app.services.job_watchdog import get_job_watchdog
                    get_quota_enforcer().release_pages(job.tenant_id, job.total)
                    if job.completed > 0:
                        get_usage_meter().record(
                            job.tenant_id,
                            "pages_crawled",
                            job.completed,
                            job_id=job.job_id,
                            idempotency_key=f"pages_crawled:{job.job_id}",
                        )
                    get_job_watchdog().persist_job(job.tenant_id, job)
                except Exception as m_err:
                    logger.warning("Error recording discovery usage/persistence: %s", m_err)
            if job:
                try:
                    from app.services.anti_bot import get_antibot_manager
                    job.metrics = get_antibot_manager().metrics.get_metrics(job.job_id)
                except Exception as met_err:
                    logger.debug("Failed saving discovery job metrics: %s", met_err)
            self._cleanup_task(job_id)

    def get_job(self, job_id: str, tenant_id: Optional[str] = None) -> Optional[JobInfo]:
        """Get job status, reconstructing from disk artifact if needed.

        If tenant_id is provided, enforces that the job belongs to that tenant.
        """
        if not is_safe_identifier(job_id):
            return None
        if tenant_id and not is_safe_identifier(tenant_id):
            return None
        job = self._jobs.get(job_id)
        if job:
            if tenant_id and job.tenant_id and job.tenant_id != tenant_id:
                return None
            return job

        # Check watchdog persistence files under data/jobs/
        try:
            from pathlib import Path
            import json
            from app.jobs.models import JobType, JobState
            candidate_files = []
            if tenant_id:
                candidate_files.append(Path("data/jobs") / tenant_id / f"{job_id}.json")
            else:
                candidate_files = list(Path("data/jobs").glob(f"*/{job_id}.json"))

            for c_file in candidate_files:
                if c_file.exists():
                    with open(c_file, "r", encoding="utf-8") as f:
                        jdata = json.load(f)
                    restored_job = JobInfo(
                        job_id=jdata["job_id"],
                        job_type=JobType(jdata["job_type"]),
                        state=JobState(jdata["state"]),
                        total=jdata.get("total", 0),
                        completed=jdata.get("completed", 0),
                        failed=jdata.get("failed", 0),
                        tenant_id=jdata.get("tenant_id"),
                        errors=jdata.get("errors", []),
                    )
                    self._jobs[job_id] = restored_job
                    if tenant_id and restored_job.tenant_id and restored_job.tenant_id != tenant_id:
                        return None
                    return restored_job
        except Exception as err:
            logger.debug("Could not restore job from watchdog disk: %s", err)

        # Check if completed job artifacts exist on disk under output/<job_id>/documents.json
        import json
        from pathlib import Path
        from app.core.config import get_settings
        out_file = Path(get_settings().output_dir) / job_id / "documents.json"
        if out_file.exists():
            try:
                with open(out_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                restored_job = JobInfo(
                    job_id=job_id,
                    job_type=JobType.EXTRACTION,
                    state=JobState.COMPLETED,
                    total=len(data),
                    completed=len(data),
                    documents=data,
                )
                self._jobs[job_id] = restored_job
                if tenant_id and restored_job.tenant_id and restored_job.tenant_id != tenant_id:
                    return None
                return restored_job
            except Exception as load_err:
                logger.warning("Could not restore job info from %s: %s", out_file, load_err)

        return None

    def cancel_job(self, job_id: str, tenant_id: Optional[str] = None) -> bool:
        """Cancel a running or pending job with optional tenant access check.

        Args:
            job_id: ID of the job to cancel.
            tenant_id: Optional tenant / workspace identifier for access verification.

        Returns:
            True if job was cancelled, False if job not found, access denied, or already terminated.
        """
        job = self._jobs.get(job_id)
        if not job:
            return False

        if tenant_id and job.tenant_id and job.tenant_id != tenant_id:
            return False

        event = self._cancel_events.get(job_id)
        if event:
            event.set()

        if job.state in (JobState.PENDING, JobState.RUNNING):
            old_state = job.state
            job.mark_cancelled()
            task = self._tasks.get(job_id)
            if task and not task.done():
                task.cancel()
            elif old_state == JobState.PENDING and job.tenant_id:
                try:
                    from app.services.quota_enforcer import get_quota_enforcer
                    get_quota_enforcer().release_pages(job.tenant_id, job.total)
                except Exception as r_err:
                    logger.warning("Error releasing quota on cancel pending: %s", r_err)
            logger.info("Cancelled job %s", job_id)
            return True

        return False

    def get_documents(self, job_id: str, tenant_id: Optional[str] = None) -> list[ExtractedDocument]:
        """Get extracted documents for a job, reloading from disk artifact if needed.

        Args:
            job_id: Target extraction job ID.
            tenant_id: Optional tenant ID for access verification.

        Returns:
            List of ExtractedDocument instances.
        """
        if tenant_id:
            job = self.get_job(job_id, tenant_id=tenant_id)
            if not job:
                return []

        docs = self._documents.get(job_id)
        if docs:
            return list(docs)

        # Attempt to load from disk if present under output/<job_id>/documents.json
        import json
        from pathlib import Path
        from app.core.config import get_settings
        out_file = Path(get_settings().output_dir) / job_id / "documents.json"
        if out_file.exists():
            try:
                with open(out_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded_docs = [ExtractedDocument.model_validate(d) for d in data]
                self._documents[job_id] = loaded_docs
                return list(loaded_docs)
            except Exception as load_err:
                logger.warning("Could not restore documents from %s: %s", out_file, load_err)

        return []

    def set_documents(self, job_id: str, documents: list[ExtractedDocument]) -> None:
        """Set or update extracted documents for a job.

        Args:
            job_id: Target extraction job ID.
            documents: List of ExtractedDocument instances.
        """
        self._documents[job_id] = list(documents)

    def list_jobs(self, tenant_id: Optional[str] = None) -> list[JobInfo]:
        """List all tracked jobs, optionally filtered by tenant_id.

        Returns:
            List of JobInfo instances.
        """
        jobs = list(self._jobs.values())
        if tenant_id:
            return [j for j in jobs if getattr(j, "tenant_id", None) == tenant_id]
        return jobs

    def delete_job(self, job_id: str, tenant_id: Optional[str] = None) -> bool:
        """Permanently delete a job and its associated in-memory and disk records.

        Args:
            job_id: Target job ID to remove.
            tenant_id: Optional tenant ID for access verification.

        Returns:
            True if job was found and removed, False otherwise.
        """
        if not is_safe_identifier(job_id):
            return False
        if tenant_id and not is_safe_identifier(tenant_id):
            return False
        job = self.get_job(job_id, tenant_id=tenant_id)
        if not job:
            return False

        self._jobs.pop(job_id, None)
        self._cancel_events.pop(job_id, None)
        self._documents.pop(job_id, None)
        self._chunks.pop(job_id, None)
        self._rag_metadata.pop(job_id, None)
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()

        import shutil
        from pathlib import Path
        from app.core.config import get_settings
        base_out = Path(get_settings().output_dir).resolve()
        out_dir = (base_out / job_id).resolve()
        if validate_path_containment(base_out, out_dir) and out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)

        # Remove persisted watchdog job state and chunks from disk
        for base_dir in ["data/jobs", "data/chunks"]:
            p = Path(base_dir).resolve()
            if p.exists():
                for f in p.glob(f"**/{job_id}.json"):
                    if validate_path_containment(p, f.resolve()):
                        f.unlink(missing_ok=True)

        return True

    def to_job_status_response(self, job: JobInfo) -> JobStatus:
        """Convert internal JobInfo to API JobStatus response model."""
        parsed_pages: list[DiscoveredPage] = []
        for p in job.pages:
            raw_status = p.get("status", "discovered")
            if isinstance(raw_status, int):
                if 200 <= raw_status < 300:
                    status_str = "crawled"
                elif raw_status in (401, 403):
                    status_str = "blocked"
                elif raw_status == 311:
                    status_str = "redirect_loop"
                elif raw_status == 310:
                    status_str = "too_many_redirects"
                else:
                    status_str = "failed"
            else:
                status_str = str(raw_status) if raw_status else "discovered"

            parsed_pages.append(
                DiscoveredPage(
                    url=str(p.get("url", "")),
                    final_url=p.get("final_url"),
                    title=p.get("title"),
                    status=status_str,
                    depth=int(p.get("depth", 0)),
                    source=str(p.get("source", "crawl")),
                    error=p.get("error"),
                )
            )

        status_val = job.state.value if hasattr(job.state, "value") else str(job.state)
        type_val = job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type)

        job_metrics = job.metrics
        if not job_metrics:
            try:
                from app.services.anti_bot import get_antibot_manager
                job_metrics = get_antibot_manager().metrics.get_metrics(job.job_id)
            except Exception:
                job_metrics = {}

        return JobStatus(
            job_id=job.job_id,
            status=status_val,
            job_type=type_val,
            total=job.total,
            completed=job.completed,
            failed=job.failed,
            pages=parsed_pages,
            documents=job.documents,
            errors=job.errors,
            started_at=job.started_at,
            finished_at=job.finished_at,
            progress_percent=job.progress_percent,
            metrics=job_metrics,
        )

    def _cleanup_task(self, job_id: str) -> None:
        """Clean up background task reference on completion."""
        self._tasks.pop(job_id, None)

    # ------------------------------------------------------------------
    # AI Feature: Chunk storage
    # ------------------------------------------------------------------

    def store_chunks(self, job_id: str, chunks: list, tenant_id: Optional[str] = None) -> None:
        """Store document chunks for a job (replaces any previously stored chunks).

        Args:
            job_id: Job identifier.
            chunks: List of DocumentChunk objects.
            tenant_id: Optional tenant identifier.
        """
        self._chunks[job_id] = list(chunks)
        logger.debug("Stored %d chunks for job %s.", len(chunks), job_id)
        # Disk persistence for restart recovery
        try:
            from pathlib import Path
            import json
            chunks_dir = Path("data/chunks")
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_file = chunks_dir / f"{job_id}.json"
            serialized = [
                c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                for c in chunks
            ]
            with open(chunk_file, "w", encoding="utf-8") as f:
                json.dump(serialized, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Could not persist chunks to disk for job %s: %s", job_id, e)

    def get_chunks(self, job_id: str, tenant_id: Optional[str] = None) -> list:
        """Retrieve stored chunks for a job.

        Args:
            job_id: Job identifier.
            tenant_id: Optional tenant identifier for isolation verification.

        Returns:
            List of DocumentChunk objects, or empty list if none stored.
        """
        if not is_safe_identifier(job_id):
            return []
        if tenant_id and not self.get_job(job_id, tenant_id=tenant_id):
            return []
        if job_id in self._chunks:
            return self._chunks[job_id]
        # Disk fallback
        try:
            from pathlib import Path
            import json
            from app.schemas.chunks import DocumentChunk
            chunk_file = Path("data/chunks") / f"{job_id}.json"
            if chunk_file.exists():
                with open(chunk_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                restored = [DocumentChunk.model_validate(c) for c in raw]
                self._chunks[job_id] = restored
                return restored
        except Exception:
            pass
        return []

    def get_job_chunks(self, job_id: str, tenant_id: Optional[str] = None) -> list:
        """Alias for get_chunks to ensure API compatibility."""
        return self.get_chunks(job_id, tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # AI Feature: RAG metadata storage
    # ------------------------------------------------------------------

    def store_rag_metadata(self, job_id: str, metadata: list) -> None:
        """Store RAG enhancement metadata for a job.

        Args:
            job_id: Job identifier.
            metadata: List of enrichment dicts from RAGEnhancer.
        """
        self._rag_metadata[job_id] = list(metadata)
        logger.debug("Stored RAG metadata for %d docs in job %s.", len(metadata), job_id)

    def get_rag_metadata(self, job_id: str, tenant_id: Optional[str] = None) -> list:
        """Retrieve stored RAG metadata for a job.

        Args:
            job_id: Job identifier.
            tenant_id: Optional tenant identifier for isolation verification.

        Returns:
            List of enrichment dicts, or empty list if none stored.
        """
        if not is_safe_identifier(job_id):
            return []
        if tenant_id and not self.get_job(job_id, tenant_id=tenant_id):
            return []
        return self._rag_metadata.get(job_id, [])



# Global singleton instance
_global_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    """Retrieve or create the global JobManager singleton instance.

    Returns:
        JobManager instance.
    """
    global _global_job_manager
    if _global_job_manager is None:
        _global_job_manager = JobManager()
    return _global_job_manager
