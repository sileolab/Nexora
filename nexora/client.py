"""Official Python SDK Client for Nexora Studio & Developer Platform.

Consumes the Nexora HTTP REST API for seamless pipeline automation in Python scripts,
notebooks, and external RAG workflows.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Generator, Optional, Union
import httpx

from nexora.exceptions import (
    NexoraAPIError,
    NexoraAuthenticationError,
    NexoraError,
    NexoraNotFoundError,
    NexoraTimeoutError,
    CrawlbotAPIError,
    CrawlbotAuthenticationError,
    CrawlbotError,
    CrawlbotNotFoundError,
    CrawlbotTimeoutError,
)
from nexora.models import (
    ChunkInfo,
    DiscoveredDynamicFieldInfo,
    DynamicFieldDetectionResult,
    ExtractionResult,
    JobInfo,
    LiveChangeEvent,
    LiveWatcherInfo,
    QualityReport,
    SearchResult,
    SyncReport,
)

logger = logging.getLogger(__name__)


class NexoraClient:
    """Synchronous client to interact with Nexora Studio API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ):
        raw_url = base_url or os.getenv("NEXORA_BASE_URL") or os.getenv("CRAWLBOT_BASE_URL") or "http://127.0.0.1:8000"
        self.base_url = raw_url.rstrip("/")
        self.api_key = api_key or os.getenv("NEXORA_API_KEY") or os.getenv("CRAWLBOT_API_KEY")
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        headers = {
            "User-Agent": "Nexora-Python-SDK/4.0.0",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        self.live = LiveExtractionNamespace(self)

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._client.close()

    def __enter__(self) -> NexoraClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[Any] = None,
        files: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Execute HTTP request with uniform error handling and response normalization."""
        try:
            resp = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
                files=files,
            )
        except httpx.TimeoutException as exc:
            raise NexoraTimeoutError(f"Request to {path} timed out after {self.timeout}s: {exc}") from exc
        except httpx.RequestError as exc:
            raise NexoraError(f"HTTP connection error while reaching {self.base_url}: {exc}") from exc

        if resp.status_code == 401:
            raise NexoraAuthenticationError(
                message="Unauthorized: Invalid or missing Nexora API key.",
                data=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None,
            )
        elif resp.status_code == 404:
            raise NexoraNotFoundError(
                message=f"Endpoint or resource at {path} was not found.",
                data=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None,
            )
        elif resp.status_code >= 400:
            err_msg = f"HTTP {resp.status_code} Error"
            try:
                body = resp.json()
                err_msg = body.get("detail") or body.get("message") or str(body)
            except Exception:
                err_msg = resp.text
            raise NexoraAPIError(message=err_msg, status_code=resp.status_code)

        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            res = resp.json()
            # If wrapped in standard ApiResponse envelope
            if isinstance(res, dict) and "success" in res and "data" in res:
                return res["data"]
            return res
        return resp.content

    # --- System & Operational Endpoints ---

    def health(self) -> dict[str, Any]:
        """Check server operational status, version, and vector store readiness."""
        return self._request("GET", "/api/v1/health")

    def ping(self) -> bool:
        """Quick boolean connection test."""
        try:
            res = self.health()
            return res.get("status") in ("ok", "healthy")
        except Exception:
            return False

    # --- Single Extraction ---

    def extract_url(
        self,
        url: str,
        strategy: str = "auto",
        loading_delay: float = 0.0,
        render_mode: str = "auto",
        wait_for_selector: Optional[str] = None,
        visible_only: bool = False,
    ) -> ExtractionResult:
        """Extract clean text, markdown, and metadata from a single web page."""
        payload = {
            "url": url,
            "extraction_strategy": strategy,
            "render_mode": render_mode,
            "loading_delay": loading_delay,
            "wait_for_selector": wait_for_selector,
            "visible_only": visible_only,
        }
        data = self._request("POST", "/api/v1/extraction/single", json_data=payload)
        return ExtractionResult.model_validate(data)

    # --- Crawl Discovery & Extraction Jobs ---

    def start_crawl(
        self,
        url: str,
        max_depth: int = 2,
        max_pages: int = 50,
        strategy: str = "auto",
        wait: bool = False,
        wait_timeout: float = 300.0,
    ) -> Union[str, JobInfo]:
        """Initiate background website discovery and extraction.

        If wait=True, blocks until completion and returns the finished JobInfo.
        Otherwise returns the job_id string immediately.
        """
        payload = {
            "start_url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "strategy": strategy,
        }
        res = self._request("POST", "/api/v1/extraction/start", json_data=payload)
        job_id = res.get("job_id") if isinstance(res, dict) else str(res)

        if wait:
            return self.wait_for_job(job_id, timeout=wait_timeout)
        return job_id

    # --- Website Discovery Jobs ---

    def start_discovery(
        self,
        root_url: str,
        max_depth: int = 2,
        max_pages: int = 50,
        enable_browser_fallback: bool = True,
        use_sitemap: bool = True,
        delay: float = 1.0,
        timeout: float = 30.0,
        wait: bool = False,
        wait_timeout: float = 300.0,
    ) -> Union[str, JobInfo]:
        """Initiate website URL discovery across pages (mirrors UI discovery tab).

        If wait=True, blocks until completion and returns the finished JobInfo.
        Otherwise returns the job_id string immediately.
        """
        payload = {
            "root_url": root_url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "enable_browser_fallback": enable_browser_fallback,
            "use_sitemap": use_sitemap,
            "delay_between_requests": delay,
            "request_timeout": timeout,
        }
        res = self._request("POST", "/api/v1/discovery/start", json_data=payload)
        job_id = res.get("job_id") if isinstance(res, dict) else str(res)

        if wait:
            return self.wait_for_discovery(job_id, timeout=wait_timeout)
        return job_id

    def get_discovery_status(self, job_id: str) -> JobInfo:
        """Retrieve live status and discovered URLs for a discovery job."""
        data = self._request("GET", f"/api/v1/discovery/status/{job_id}")
        return JobInfo.model_validate(data)

    def cancel_discovery(self, job_id: str) -> bool:
        """Cancel a running discovery job."""
        try:
            self._request("POST", f"/api/v1/discovery/cancel/{job_id}")
            return True
        except Exception:
            return False

    def wait_for_discovery(
        self,
        job_id: str,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> JobInfo:
        """Poll discovery job until it reaches completed, failed, or cancelled state."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            job = self.get_discovery_status(job_id)
            if job.state in ("completed", "failed", "cancelled"):
                return job
            time.sleep(poll_interval)
        raise NexoraTimeoutError(f"Discovery job {job_id} did not finish within {timeout} seconds.", job_id=job_id)

    # --- Job Management ---

    def get_job(self, job_id: str) -> JobInfo:
        """Retrieve current status, progress counters, and error states for a job."""
        data = self._request("GET", f"/api/v1/jobs/{job_id}")
        return JobInfo.model_validate(data)

    def list_jobs(self, limit: int = 50, offset: int = 0) -> list[JobInfo]:
        """List background jobs with pagination."""
        data = self._request("GET", "/api/v1/jobs/list", params={"limit": limit, "offset": offset})
        if isinstance(data, list):
            return [JobInfo.model_validate(j) for j in data]
        return []

    def cancel_job(self, job_id: str) -> bool:
        """Cancel an ongoing discovery or extraction job."""
        try:
            self._request("POST", f"/api/v1/extraction/cancel/{job_id}")
            return True
        except Exception:
            return False

    def wait_for_job(
        self,
        job_id: str,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> JobInfo:
        """Poll job status until it reaches 'completed', 'failed', or 'cancelled' state."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            job = self.get_job(job_id)
            if job.state in ("completed", "failed", "cancelled"):
                return job
            time.sleep(poll_interval)
        raise NexoraTimeoutError(f"Job {job_id} did not finish within {timeout} seconds.", job_id=job_id)

    # --- AI & RAG Pipeline Operations ---

    def chunk_job(
        self,
        job_id: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        strategy: str = "token",
    ) -> dict[str, Any]:
        """Segment extracted documents into semantic chunks for RAG."""
        payload = {
            "job_id": job_id,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "strategy": strategy,
        }
        return self._request("POST", "/api/v1/ai/chunk", json_data=payload)

    def repair_chunks(self, job_id: str) -> dict[str, Any]:
        """Perform semantic boundary repair and grammar smoothing on chunks."""
        return self._request("POST", "/api/v1/ai/repair", json_data={"job_id": job_id})

    def embed_chunks(
        self,
        job_id: str,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate vector embeddings for all document chunks in a job."""
        payload: dict[str, Any] = {"job_id": job_id}
        if model:
            payload["model"] = model
        return self._request("POST", "/api/v1/ai/embed", json_data=payload)

    def search(
        self,
        job_id: str,
        query: str,
        top_k: int = 5,
        method: str = "hybrid",
        alpha: float = 0.7,
        min_score: float = 0.0,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        expand_neighbors: bool = False,
    ) -> list[SearchResult]:
        """Execute dense, lexical (BM25), or hybrid retrieval on job chunks."""
        payload = {
            "job_id": job_id,
            "query": query,
            "top_k": top_k,
            "method": method,
            "alpha": alpha,
            "min_score": min_score,
            "category": category,
            "source_url": source_url,
            "expand_neighbors": expand_neighbors,
        }
        data = self._request("POST", "/api/v1/ai/eval/playground", json_data=payload)
        hits = data.get("results", []) if isinstance(data, dict) else []
        return [SearchResult.model_validate(h) for h in hits]

    # --- Exports & Files ---

    def export_job(
        self,
        job_id: str,
        export_format: str = "jsonl",
        output_file: Optional[str] = None,
    ) -> Union[bytes, str]:
        """Download extracted documents in JSONL, JSON, CSV, or Markdown format."""
        payload = {"job_id": job_id, "format": export_format}
        content = self._request("POST", "/api/v1/export/download", json_data=payload)
        if isinstance(content, dict):
            import json
            content = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
        elif isinstance(content, str):
            content = content.encode("utf-8")

        if output_file:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            with open(output_file, "wb") as f:
                f.write(content)
            return output_file
        return content

    def process_file(
        self,
        file_path: str,
        strategy: str = "balanced",
    ) -> dict[str, Any]:
        """Upload and process a local document (PDF, DOCX, TXT, HTML)."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/octet-stream")}
            data = self._request("POST", "/api/v1/files/upload", files=files)

        file_id = data.get("file_id") if isinstance(data, dict) else None
        if not file_id:
            return data

        proc_payload = {"file_id": file_id, "strategy": strategy}
        return self._request("POST", "/api/v1/files/process", json_data=proc_payload)

    def get_quality_report(self, job_id: str) -> QualityReport:
        """Obtain RAG readiness and quality report for a job dataset."""
        data = self._request("GET", f"/api/v1/ai/dataset/{job_id}/quality-report")
        return QualityReport.model_validate(data)

    # --- Incremental Synchronization ---

    def sync_incremental(
        self,
        project_id: str,
        candidate_urls: list[str],
        raw_documents: Optional[list[dict[str, Any]]] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        force_reprocess: bool = False,
    ) -> SyncReport:
        """Perform incremental sync: detects new, modified, unchanged, and deleted documents."""
        payload = {
            "project_id": project_id,
            "candidate_urls": candidate_urls,
            "raw_documents": raw_documents,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "force_reprocess": force_reprocess,
        }
        data = self._request("POST", "/api/v1/ai/incremental/sync", json_data=payload)
        return SyncReport.model_validate(data)

    # --- Vector Database Integrations ---

    def export_to_qdrant(
        self,
        job_id: str,
        collection_name: str = "nexora_chunks",
        qdrant_url: Optional[str] = None,
        api_key: Optional[str] = None,
        batch_size: int = 64,
    ) -> dict[str, Any]:
        """Sync chunks with vector embeddings directly into a Qdrant collection."""
        payload = {
            "job_id": job_id,
            "collection_name": collection_name,
            "qdrant_url": qdrant_url,
            "api_key": api_key,
            "batch_size": batch_size,
        }
        return self._request("POST", "/api/v1/ai/vector-export/qdrant", json_data=payload)

    def export_to_chroma(self, job_id: str) -> dict[str, Any]:
        """Generate ChromaDB batch add structure (ids, embeddings, documents, metadatas)."""
        return self._request("GET", f"/api/v1/ai/vector-export/chroma/{job_id}")

    def export_to_pinecone(self, job_id: str, namespace: Optional[str] = None) -> dict[str, Any]:
        """Generate Pinecone vectors upsert structure."""
        params = {"namespace": namespace} if namespace else None
        return self._request("GET", f"/api/v1/ai/vector-export/pinecone/{job_id}", params=params)


class LiveExtractionNamespace:
    """Namespace for managing real-time live watchers and streaming changes."""

    def __init__(self, client: NexoraClient):
        self._c = client

    def auto_detect(
        self,
        url: str,
        observation_seconds: float = 3.0,
        engine: str = "auto",
        headers: Optional[dict[str, str]] = None,
    ) -> DynamicFieldDetectionResult:
        """Autonomously scan a target webpage for mutating dynamic fields (prices, stock, tickers)."""
        payload = {
            "url": url,
            "observation_seconds": observation_seconds,
            "engine": engine,
            "headers": headers or {},
        }
        data = self._c._request("POST", "/api/v1/live/auto-detect", json_data=payload)
        return DynamicFieldDetectionResult.model_validate(data)

    def create(
        self,
        url: str,
        name: Optional[str] = None,
        selectors: Optional[dict[str, str]] = None,
        interval_seconds: float = 5.0,
        engine: str = "auto",
        single_trigger: bool = False,
        turn_on: bool = True,
        mode: str = "manual",
        auto_detect: bool = False,
        observation_seconds: float = 3.0,
        webhook_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> LiveWatcherInfo:
        """Create a new live watcher for a dynamic webpage or API feed."""
        effective_mode = "auto" if auto_detect or mode == "auto" or (selectors is None) else "manual"
        payload = {
            "url": url,
            "name": name,
            "selectors": selectors or {},
            "interval_seconds": interval_seconds,
            "engine": engine,
            "single_trigger": single_trigger,
            "turn_on": turn_on,
            "mode": effective_mode,
            "observation_seconds": observation_seconds,
            "webhook_url": webhook_url,
            "headers": headers or {},
        }
        data = self._c._request("POST", "/api/v1/live/watchers", json_data=payload)
        return LiveWatcherInfo.model_validate(data)

    def list(self) -> list[LiveWatcherInfo]:
        """List all registered live watchers."""
        data = self._c._request("GET", "/api/v1/live/watchers")
        watchers = data.get("watchers", []) if isinstance(data, dict) else []
        return [LiveWatcherInfo.model_validate(w) for w in watchers]

    def get(self, watcher_id: str) -> LiveWatcherInfo:
        """Fetch watcher metadata, operational status, and latest snapshot."""
        data = self._c._request("GET", f"/api/v1/live/watchers/{watcher_id}")
        return LiveWatcherInfo.model_validate(data)

    def turn_on(self, watcher_id: str) -> dict[str, Any]:
        """Turn ON watcher to begin real-time monitoring."""
        return self._c._request("POST", f"/api/v1/live/watchers/{watcher_id}/turn-on")

    def turn_off(self, watcher_id: str) -> dict[str, Any]:
        """Turn OFF watcher to halt monitoring."""
        return self._c._request("POST", f"/api/v1/live/watchers/{watcher_id}/turn-off")

    def get_latest(self, watcher_id: str) -> dict[str, Any]:
        """Get the latest live data snapshot (previous stale data has been replaced)."""
        return self._c._request("GET", f"/api/v1/live/watchers/{watcher_id}/latest")

    def extract_now(self, watcher_id: str) -> dict[str, Any]:
        """Force an immediate extraction pass and return latest data."""
        return self._c._request("POST", f"/api/v1/live/watchers/{watcher_id}/extract-now")

    def delete(self, watcher_id: str) -> bool:
        """Delete live watcher."""
        try:
            self._c._request("DELETE", f"/api/v1/live/watchers/{watcher_id}")
            return True
        except Exception:
            return False

    def stream(self, watcher_id: str) -> Generator[LiveChangeEvent, None, None]:
        """Yield live ChangeEvents in real-time as Server-Sent Events (SSE)."""
        url = f"{self._c.base_url}/api/v1/live/watchers/{watcher_id}/stream"
        headers = dict(self._c._client.headers)
        with httpx.stream("GET", url, headers=headers, timeout=None) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    raw_data = line[6:].strip()
                    try:
                        parsed = json.loads(raw_data)
                        if "event" in parsed and parsed.get("event") == "connected":
                            continue
                        yield LiveChangeEvent.model_validate(parsed)
                    except Exception:
                        pass

    def watch(
        self,
        url: str,
        selectors: Optional[dict[str, str]] = None,
        interval_seconds: float = 3.0,
        engine: str = "auto",
        mode: str = "manual",
        auto_detect: bool = False,
        observation_seconds: float = 3.0,
        on_change: Optional[Callable[[LiveChangeEvent], None]] = None,
        max_changes: Optional[int] = None,
        single_trigger: bool = False,
    ) -> Generator[LiveChangeEvent, None, None]:
        """High-level one-liner to watch a URL live, automatically creating and streaming."""
        effective_mode = "auto" if auto_detect or mode == "auto" or (selectors is None) else "manual"
        watcher = self.create(
            url=url,
            selectors=selectors,
            interval_seconds=interval_seconds,
            engine=engine,
            single_trigger=single_trigger,
            mode=effective_mode,
            observation_seconds=observation_seconds,
            turn_on=True,
        )
        try:
            count = 0
            for event in self.stream(watcher.id):
                if on_change:
                    on_change(event)
                yield event
                count += 1
                if max_changes and count >= max_changes:
                    break
                if single_trigger:
                    break
        finally:
            self.turn_off(watcher.id)
            self.delete(watcher.id)



# Backward compatibility alias
CrawlbotClient = NexoraClient
